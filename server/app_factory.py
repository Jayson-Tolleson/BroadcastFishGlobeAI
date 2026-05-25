from __future__ import annotations

import logging
import os
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
    startup_log = logging.getLogger("server.startup")
    prewarm_mode = str(os.getenv("GFS_PREWARM_MODE", "lightweight")).strip().lower()
    ai_worker_autostart = str(os.getenv("AI_WORKER_AUTOSTART", "1")).strip().lower() not in {"0", "false", "no", "off"}

    @app.before_serving
    async def _start_ai_worker() -> None:
        if not ai_worker_autostart:
            startup_log.info("startup ai_worker autostart disabled")
            return
        task = app.extensions.get("ai_worker_task")
        if task and not task.done():
            return
        startup_log.info("startup ai_worker autostart enabled")
        app.extensions["ai_worker_task"] = app.add_background_task(app.extensions["ai_worker"].run_forever)

    @app.after_serving
    async def _stop_ai_worker() -> None:
        worker = app.extensions.get("ai_worker")
        if worker:
            worker.stop()
        task = app.extensions.get("ai_worker_task")
        if task and not task.done():
            task.cancel()

    @app.before_serving
    async def _startup_gfs_prewarm() -> None:
        engine = app.extensions.get("gfs_engine")
        if not engine:
            startup_log.warning("startup gfs_engine missing; prewarm skipped")
            return
        if prewarm_mode in {"disabled", "off", "none"}:
            startup_log.info("startup warmup mode=disabled")
            return
        if prewarm_mode in {"light", "lightweight", "route_check"}:
            try:
                engine.lightweight_startup_check()
                startup_log.info("startup warmup mode=lightweight complete")
            except Exception as exc:
                startup_log.warning("startup warmup mode=lightweight failed: %s", exc)
            return
        if prewarm_mode in {"heavy", "full"}:
            startup_log.info("startup warmup mode=heavy background begin")
            try:
                threading.Thread(target=engine.prewarm_startup, daemon=True).start()
            except Exception as exc:
                startup_log.warning("gfs prewarm thread start failed: %s", exc)
            return
        startup_log.warning("startup warmup mode=%s unknown; defaulting to lightweight", prewarm_mode)
        try:
            engine.lightweight_startup_check()
        except Exception as exc:
            startup_log.warning("startup warmup lightweight fallback failed: %s", exc)

    app.settings_obj = settings
    app.state_obj = state
    app.rtc_manager = rtc
    registered_rules = {str(r.rule) for r in app.url_map.iter_rules()}
    ws_gfs_registered = "/ws/gfs" in registered_rules
    ws_gfs_legacy_registered = "/gfs/ws" in registered_rules

    startup_log.info("[startup] route registration complete")
    startup_log.info(
        "startup ready framework=quart static=%s templates=%s routes=/,/broadcast,/watch,/gfs ws=/ws/watch,/ws/broadcast,/ws/chat,/ws/gfs ws_gfs_registered=%s ws_gfs_legacy_registered=%s",
        STATIC_DIR,
        TEMPLATES_DIR,
        ws_gfs_registered,
        ws_gfs_legacy_registered,
    )
    return app


def create_asgi_app() -> Quart:
    return create_quart_app()


def create_app() -> Quart:
    return create_quart_app()
