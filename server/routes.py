from __future__ import annotations

from pathlib import Path

from quart import Quart, current_app, websocket

from server.api import api_bp
from server.ai.blueprints import (
    create_ai_blueprint,
    create_broadcast_ai_blueprint,
    create_gfs_ai_blueprint,
    create_lftr_ai_blueprint,
)
from server.broadcast.routes import register_broadcast_routes
from server.config import Settings
from server.gfs import create_gfs_blueprint
from server.gfs.routes import handle_gfs_ws
from server.routes_core import register_core_routes, _static_file as _core_static_file, build_ice_servers
from server.rtc import RTCManager
from server.state import AppState


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _static_file(path_name: str):
    return _core_static_file(path_name, STATIC_DIR)


def register_routes(app: Quart, state: AppState, settings: Settings, rtc: RTCManager) -> None:
    register_core_routes(app, settings, STATIC_DIR)
    register_broadcast_routes(app, state, rtc)
    app.register_blueprint(create_gfs_blueprint(STATIC_DIR))
    app.register_blueprint(create_ai_blueprint())
    app.register_blueprint(create_gfs_ai_blueprint())
    app.register_blueprint(create_broadcast_ai_blueprint())
    app.register_blueprint(create_lftr_ai_blueprint())
    app.register_blueprint(api_bp)
    try:
        current_app_engine = app.extensions.get("gfs_engine")
        mark_registered = getattr(current_app_engine, "mark_gfs_ws_registered", None)
        if callable(mark_registered):
            mark_registered(True)
    except Exception:
        pass

    @app.websocket("/ws/gfs")
    async def ws_gfs():
        await handle_gfs_ws(lambda: current_app.extensions["gfs_engine"], websocket)


__all__ = ["register_routes", "_static_file", "build_ice_servers", "STATIC_DIR"]
