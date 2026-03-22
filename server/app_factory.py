from __future__ import annotations

import logging
import threading
from pathlib import Path

from quart import Quart

from server.ai.core import AICore
from server.ai.memory import AIMemory
from server.ai.queue import shared_ai_queue
from server.ai.worker import AIWorker
from server.config import load_settings
from server.gfs.config import load_gfs_config
from server.gfs.engine import GfsEngine
from server.gfs.media import LocationMediaStore
from server.routes import register_routes
from server.rtc import RTCManager
from server.state import AppState


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = STATIC_DIR


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")


def _validate_layout() -> None:
    if not STATIC_DIR.exists():
        raise RuntimeError(f"static directory missing at startup: {STATIC_DIR}")
    if not STATIC_DIR.is_dir():
        raise RuntimeError(f"static path is not a directory at startup: {STATIC_DIR}")
    if not TEMPLATES_DIR.exists() or not TEMPLATES_DIR.is_dir():
        raise RuntimeError(f"templates directory missing at startup: {TEMPLATES_DIR}")


def create_quart_app() -> Quart:
    settings = load_settings()
    _configure_logging(settings.debug)
    _validate_layout()

    app = Quart(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    state = AppState(default_room=settings.default_room)
    rtc = RTCManager(state)
    app.extensions["ai_core"] = AICore()
    app.extensions["ai_memory"] = AIMemory()
    app.extensions["ai_queue"] = shared_ai_queue
    app.extensions["ai_worker"] = AIWorker(app.extensions["ai_core"], app.extensions["ai_queue"])
    app.extensions["gfs_engine"] = GfsEngine(load_gfs_config(debug_enabled=settings.debug), static_dir=str(STATIC_DIR))
    app.extensions["gfs_media_store"] = app.extensions["gfs_engine"]

    register_routes(app, state, settings, rtc)

    @app.before_serving
    async def _start_ai_worker() -> None:
        task = app.extensions.get("ai_worker_task")
        if task and not task.done():
            return
        app.extensions["ai_worker_task"] = app.add_background_task(app.extensions["ai_worker"].run_forever)

    @app.after_serving
    async def _stop_ai_worker() -> None:
        worker = app.extensions.get("ai_worker")
        if worker:
            worker.stop()
        task = app.extensions.get("ai_worker_task")
        if task and not task.done():
            task.cancel()

    try:
        threading.Thread(target=app.extensions["gfs_engine"].prewarm_startup, daemon=True).start()
    except Exception as exc:
        logging.getLogger("server.startup").warning("gfs prewarm thread start failed: %s", exc)

    app.settings_obj = settings
    app.state_obj = state
    app.rtc_manager = rtc

    logging.getLogger("server.startup").info(
        "startup ready framework=quart static=%s templates=%s routes=/,/broadcast,/watch,/gfs ws=/ws/watch,/ws/broadcast,/ws/chat,/ws/gfs",
        STATIC_DIR,
        TEMPLATES_DIR,
    )
    return app


def create_asgi_app() -> Quart:
    return create_quart_app()


def create_app() -> Quart:
    return create_quart_app()
