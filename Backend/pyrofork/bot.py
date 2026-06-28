from pyrogram import Client
from Backend.config import Telegram

# ── Main Bot Client ──────────────────────────────────────────────────────────
StreamBot = Client(
    name='bot',
    api_id=Telegram.API_ID,
    api_hash=Telegram.API_HASH,
    bot_token=Telegram.BOT_TOKEN,
    plugins={"root": "Backend/pyrofork/plugins"},
    sleep_threshold=20,
    workers=6,
    max_concurrent_transmissions=10
)

# ── Userbot Client (optional) ─────────────────────────────────────────────────
# Worker clients use indices 0, 1, 2…; the userbot gets the reserved slot -1.
USERBOT_CLIENT_INDEX = -1

# Created only when USER_SESSION_STRING is set. no_updates=True → fetch-only.
Userbot = None
if Telegram.USER_SESSION_STRING:
    Userbot = Client(
        name='userbot',
        api_id=Telegram.API_ID,
        api_hash=Telegram.API_HASH,
        session_string=Telegram.USER_SESSION_STRING,
        sleep_threshold=20,
        workers=6,
        max_concurrent_transmissions=10,
        no_updates=True,
    )

# ── Multi-Client Registries ───────────────────────────────────────────────────
# Populated by clients.initialize_clients(). Keyed by client index.
multi_clients   = {}   # index -> Client instance
work_loads      = {}   # index -> active transmission count (load balancing)
client_dc_map   = {}   # index -> Telegram data-center id
client_failures = {}   # index -> consecutive failure counter
client_avg_mbps = {}   # index -> rolling average throughput (Mbps)


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_streambot_url() -> str:
    """Return the bot's public t.me URL."""
    return f"https://t.me/{StreamBot.username}"


# ── Userbot Registry Seeding ──────────────────────────────────────────────────
if Userbot is not None:
    work_loads[USERBOT_CLIENT_INDEX] = 0
    client_failures[USERBOT_CLIENT_INDEX] = 0
    client_avg_mbps[USERBOT_CLIENT_INDEX] = 0.0
