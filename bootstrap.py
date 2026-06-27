import os
import sys
import logging
import threading
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] - %(message)s")
LOG = logging.getLogger("bootstrap")

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.env"
TEMPLATES_DIR = str(ROOT / "Backend" / "fastapi" / "templates")


def _db_uris(raw: str) -> list:
    return [u.strip() for u in (raw or "").split(",") if u.strip()]


def is_configured() -> bool:
    load_dotenv(CONFIG_PATH)
    api_id = (os.getenv("API_ID") or "").strip()
    api_hash = (os.getenv("API_HASH") or "").strip()
    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    owner_id = (os.getenv("OWNER_ID") or "").strip()
    database = _db_uris(os.getenv("DATABASE", ""))
    return all([
        api_id.isdigit() and int(api_id) > 0,
        api_hash,
        ":" in bot_token,
        owner_id.isdigit() and int(owner_id) > 0,
        len(database) >= 2,
    ])


def _validate(form: dict):
    errors = []
    api_id = (form.get("api_id") or "").strip()
    api_hash = (form.get("api_hash") or "").strip()
    bot_token = (form.get("bot_token") or "").strip()
    owner_id = (form.get("owner_id") or "").strip()
    database = (form.get("database") or "").strip()
    port = (form.get("port") or "8000").strip()
    user_session_string = (form.get("user_session_string") or "").strip()

    if not api_id.isdigit():
        errors.append("API_ID must be a number (from my.telegram.org).")
    if not api_hash:
        errors.append("API_HASH is required.")
    if ":" not in bot_token:
        errors.append("BOT_TOKEN looks invalid (get it from @BotFather).")
    if not owner_id.isdigit():
        errors.append("OWNER_ID must be your numeric Telegram ID.")
    if len(_db_uris(database)) < 2:
        errors.append("DATABASE needs at least 2 MongoDB URIs (1 tracking + 1 storage), comma-separated.")
    if not port.isdigit():
        errors.append("PORT must be a number.")

    values = {
        "api_id": api_id, "api_hash": api_hash, "bot_token": bot_token,
        "owner_id": owner_id, "database": database, "port": port or "8000",
        "user_session_string": user_session_string,
    }
    return values, errors


def _write_config(values: dict) -> None:
    lines = [
        f'API_ID="{values["api_id"]}"',
        f'API_HASH="{values["api_hash"]}"',
        f'BOT_TOKEN="{values["bot_token"]}"',
        f'USER_SESSION_STRING="{values["user_session_string"]}"',
        f'OWNER_ID="{values["owner_id"]}"',
        f'DATABASE="{values["database"]}"',
        f'PORT="{values["port"]}"',
    ]
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass


def _launch_backend() -> None:
    LOG.info("Configuration present — launching Telegram-Stremio.")
    os.execv(sys.executable, [sys.executable, "-m", "Backend"])


def _restart_into_backend() -> None:
    LOG.info("Setup saved — starting Telegram-Stremio...")
    try:
        os.execv(sys.executable, [sys.executable, "-m", "Backend"])
    except Exception as e:
        LOG.error(f"Re-exec failed ({e}); exiting for container restart.")
        os._exit(0)


def run_setup_server() -> None:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    app = FastAPI(title="Telegram-Stremio Setup")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("setup.html", {"request": request, "errors": [], "values": {}})

    @app.post("/save", response_class=HTMLResponse)
    async def save(request: Request):
        form = dict(await request.form())
        values, errors = _validate(form)
        if errors:
            return templates.TemplateResponse(
                "setup.html", {"request": request, "errors": errors, "values": values}, status_code=400
            )
        _write_config(values)
        threading.Timer(2.0, _restart_into_backend).start()
        return templates.TemplateResponse(
            "setup.html", {"request": request, "errors": [], "values": values, "saved": True}
        )

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def catch_all(full_path: str):
        return RedirectResponse(url="/", status_code=302)

    port = int((os.getenv("PORT") or "8000").strip() or "8000")
    LOG.info(f"No configuration detected — starting first-run Setup Wizard on http://0.0.0.0:{port}")
    uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")).run()


def main() -> None:
    if is_configured():
        _launch_backend()
    else:
        run_setup_server()


if __name__ == "__main__":
    main()
