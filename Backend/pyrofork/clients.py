from asyncio import gather, create_task
from pyrogram import Client
from Backend.logger import LOGGER
from Backend.config import Telegram
from Backend.pyrofork.bot import multi_clients, work_loads, StreamBot, client_dc_map
from Backend.helper.settings_manager import SettingsManager
from Backend.fastapi.routes.stream_routes import _streamer_by_client

# Maps client_id -> bot token; used to detect added/removed/changed tokens on reload.
client_tokens: dict[int, str] = {}


# ── Token Parsing ─────────────────────────────────────────────────────────────
class TokenParser:
    @staticmethod
    def parse_from_settings() -> dict[int, str]:
        # client_id starts at 1 (0 is reserved for the main StreamBot)
        tokens = SettingsManager.current().multi_tokens
        return {i + 1: t.strip() for i, t in enumerate(tokens) if t and t.strip()}


# ── DC Helper ─────────────────────────────────────────────────────────────────
async def _resolve_dc(client, client_id: int, label: str) -> None:
    """Record the client's data-center id, or None if it can't be resolved."""
    try:
        client_dc_map[client_id] = await client.storage.dc_id()
        LOGGER.info(f"{label} connected to DC {client_dc_map[client_id]}")
    except Exception as e:
        LOGGER.warning(f"Could not get DC for {label}: {e}")
        client_dc_map[client_id] = None


# ── Client Lifecycle ──────────────────────────────────────────────────────────
async def start_client(client_id: int, token: str):
    try:
        LOGGER.info(f"Starting - Bot Client {client_id}")
        client = await Client(
            name=str(client_id),
            api_id=Telegram.API_ID,
            api_hash=Telegram.API_HASH,
            bot_token=token,
            sleep_threshold=100,
            no_updates=True,
            in_memory=True,
        ).start()
        await _resolve_dc(client, client_id, f"Client {client_id}")
        work_loads[client_id] = 0
        return client_id, client
    except Exception as e:
        LOGGER.error(f"Failed to start Client - {client_id} Error: {e}", exc_info=True)
        return None


async def stop_client(client_id: int) -> None:
    client = multi_clients.pop(client_id, None)
    # Also drop the cached ByteStreamer so a dead connection's FileId cache isn't reused.
    for registry in (work_loads, client_dc_map, client_tokens, _streamer_by_client):
        registry.pop(client_id, None)

    if client:
        try:
            await client.stop()
            LOGGER.info(f"Stopped Bot Client {client_id}")
        except Exception as e:
            LOGGER.warning(f"Error stopping Client {client_id}: {e}")


# ── Batch start + register the successful clients ─────────────────────────────
async def _start_and_register(tokens: dict[int, str]) -> dict:
    results = await gather(*(create_task(start_client(c, t)) for c, t in tokens.items()))
    started = {cid: client for cid, client in results if client}
    multi_clients.update(started)
    client_tokens.update({cid: tokens[cid] for cid in started})
    return started


# ── Initialization & Reload ───────────────────────────────────────────────────
async def initialize_clients() -> None:
    multi_clients[0], work_loads[0] = StreamBot, 0
    await _resolve_dc(StreamBot, 0, "Main StreamBot")

    all_tokens = TokenParser.parse_from_settings()
    if not all_tokens:
        LOGGER.info("No additional Bot Clients found, Using default client")
        return

    await _start_and_register(all_tokens)

    if len(multi_clients) != 1:
        LOGGER.info(f"Multi-Client Mode Enabled with {len(multi_clients)} clients")
    else:
        LOGGER.info("No additional clients were initialized, using default client")


async def reload_multi_token_clients() -> dict:
    new_tokens = TokenParser.parse_from_settings()
    old_ids = set(client_tokens)

    to_stop = [cid for cid in old_ids if client_tokens.get(cid) != new_tokens.get(cid)]
    for cid in to_stop:
        await stop_client(cid)

    to_start = {c: t for c, t in new_tokens.items() if client_tokens.get(c) != t}
    if to_start:
        await _start_and_register(to_start)

    LOGGER.info(
        f"Multi-token reload complete — {len(to_stop)} stopped, "
        f"{len(to_start)} (re)started, {len(multi_clients)} total clients active."
    )
    return {"stopped": len(to_stop), "started": len(to_start), "total_clients": len(multi_clients)}
