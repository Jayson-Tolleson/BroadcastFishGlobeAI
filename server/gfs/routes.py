"""GFS routes with canonical shared-ocean architecture."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import logging
import time

from quart import Blueprint, current_app, request, jsonify, send_file, websocket

from server.gfs.viewport import parse_viewport_args

log = logging.getLogger("server.gfs.routes")


def create_gfs_blueprint(static_dir: Path) -> Blueprint:
    bp = Blueprint("gfs", __name__, url_prefix="/gfs")

    def gfs():
        return current_app.extensions["gfs_engine"]

    def media():
        return current_app.extensions.get("gfs_media_store") or gfs()

    @bp.route("")
    @bp.route("/")
    async def index():
        return await send_file(str(static_dir / "indexgfs.html"))

    @bp.route("/api/health")
    async def api_health():
        return jsonify(gfs().health_payload())

    @bp.route("/api/config")
    async def api_config():
        return jsonify(gfs().config_payload())

    @bp.route("/api/status")
    async def api_status():
        return jsonify(gfs().status_payload())

    @bp.route("/api/ocean")
    async def api_ocean():
        vp = parse_viewport_args(request.args)
        payload = gfs().shared_ocean_payload(vp.as_dict())
        return jsonify(payload)

    @bp.route("/api/weather")
    async def api_weather():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().generate_weather_payload(vp.as_dict()))

    @bp.route("/api/clouds")
    async def api_clouds():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().cloud_tiles_payload(vp.as_dict()))

    @bp.route("/api/bait")
    async def api_bait():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().bait_from_ocean(vp.as_dict()))

    @bp.route("/api/bait-advanced")
    @bp.route("/api/bait/advanced")
    async def api_bait_advanced():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().bait_from_ocean(vp.as_dict()))

    @bp.route("/api/frame")
    async def api_frame():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().frame_payload(vp.as_dict()))

    @bp.route("/api/tiles/<layer>/<int:z>/<int:x>/<int:y>")
    async def api_tiles(layer, z, x, y):
        return jsonify(gfs().layer_tile_payload(layer, z, x, y))

    @bp.route("/api/scene")
    async def api_scene():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().get_scene_payload(vp.as_dict()))

    @bp.route("/api/hazards")
    async def api_hazards():
        return jsonify(gfs().hazards_payload())

    @bp.route("/api/diagnostics")
    async def api_diagnostics():
        return jsonify(gfs().diagnostics_payload())

    @bp.route("/api/fish")
    async def api_fish():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().fish_from_ocean(vp.as_dict()))

    @bp.route("/api/locations")
    async def api_locations():
        vp = parse_viewport_args(request.args)
        payload = gfs().fish_from_ocean(vp.as_dict())
        items = payload.get("items") if isinstance(payload, dict) else []
        locations = [{
            "id": item.get("id") or "loc",
            "location_key": item.get("id") or "loc",
            "name": item.get("name") or "Fishing location",
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "probability": item.get("probability"),
            "confidence": item.get("confidence"),
            "meta": {"reason": item.get("reason"), "reasons": item.get("reasons") or []},
            "score": item.get("score"),
        } for item in (items or []) if isinstance(item, dict)]
        return jsonify({"ok": True, "count": len(locations), "locations": locations, "source": "fish_from_ocean", "ts": payload.get("ts") if isinstance(payload, dict) else None})

    @bp.route("/api/live/session", methods=["POST"])
    async def create_live_session():
        data = await request.get_json() or {}
        location_id = data.get("location_id") or "default"
        return jsonify(gfs().create_live_session(location_id))

    def _coerce_key(value: str) -> str:
        return str(value or "").strip()

    def _find_fish_item(location_key: str) -> dict[str, Any] | None:
        payload = gfs().fish_from_ocean(None)
        for item in payload.get("items") or []:
            if _coerce_key(item.get("id")) == _coerce_key(location_key):
                return item
        return None

    def _location_detail_payload(location_key: str) -> dict[str, Any]:
        item = _find_fish_item(location_key) or {}
        media_payload = media().location_media(location_key)
        return {
            "ok": True,
            "id": item.get("id") or location_key,
            "location_key": item.get("id") or location_key,
            "name": item.get("name") or media_payload.get("label") or location_key,
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "probability": item.get("probability"),
            "confidence": item.get("confidence"),
            "meta": {"reason": item.get("reason"), "reasons": item.get("reasons") or []},
            "reports": [media_payload.get("report_text")] if media_payload.get("report_text") else [],
            "report_text": media_payload.get("report_text") or "",
            "uploads": media_payload.get("uploads") or [],
            "live": media_payload.get("live") or {"active": False, "stream_url": "", "updated_at": None},
            "ts": media_payload.get("ts") or int(time.time() * 1000),
        }

    @bp.route("/api/location/<location_key>")
    async def location_detail(location_key):
        return jsonify(_location_detail_payload(location_key))

    @bp.route("/api/location/<location_key>/media")
    async def location_media(location_key):
        return jsonify(media().location_media(location_key))

    @bp.route("/api/location/<location_key>/videos")
    async def location_videos(location_key):
        payload = media().location_media(location_key)
        videos = [{"url": up.get("url") or up.get("media_url") or up.get("path") or "", "filename": up.get("filename") or up.get("name") or "video", "uploaded_at": up.get("uploaded_at") or up.get("ts")} for up in (payload.get("uploads") or []) if isinstance(up, dict)]
        return jsonify({"ok": True, "location_key": location_key, "videos": videos, "ts": payload.get("ts")})

    @bp.route("/api/location/<location_key>/report", methods=["POST"])
    @bp.route("/api/location/<location_key>/reports", methods=["POST"])
    async def update_report(location_key):
        data = await request.get_json() or {}
        text = data.get("text") or data.get("report") or ""
        return jsonify(media().upsert_report(location_key, text))

    @bp.route("/api/location/<location_key>/live", methods=["GET", "POST"])
    async def update_live(location_key):
        if request.method == "GET":
            payload = media().location_media(location_key)
            live = payload.get("live") or {"active": False, "stream_url": "", "updated_at": None}
            fish = _find_fish_item(location_key) or {}
            return jsonify({"ok": True, "id": fish.get("id") or location_key, "location_key": fish.get("id") or location_key, "name": fish.get("name") or payload.get("label") or location_key, "lat": fish.get("lat"), "lon": fish.get("lon"), "active": bool(live.get("active")), "stream_url": live.get("stream_url") or "", "updated_at": live.get("updated_at"), "live": live, "ts": payload.get("ts") or int(time.time() * 1000)})
        data = await request.get_json() or {}
        active = bool(data.get("active"))
        url = data.get("stream_url", "")
        return jsonify(media().upsert_live(location_key, active, url))

    @bp.route("/api/location/<location_key>/upload", methods=["POST"])
    async def upload_video(location_key):
        files = await request.files
        if "video" not in files:
            return jsonify({"ok": False, "error": "no video file"}), 400
        video = files["video"]
        return jsonify(media().save_upload_video(location_key, video.filename, video.read()))

    @bp.websocket("/ws")
    async def ws_gfs():
        await websocket.send_json({"type": "hello", "detail": "gfs websocket optional"})
        while True:
            msg = await websocket.receive()
            if msg is None:
                break
            if str(msg).lower() in {"ping", '{"type":"ping"}'}:
                await websocket.send_json({"type": "status", "detail": "ok"})
            elif "refresh" in str(msg).lower():
                await websocket.send_json({"type": "refresh_nudge", "detail": "frame"})
            else:
                await websocket.send_json({"type": "ack", "detail": msg})

    return bp
