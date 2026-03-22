"""GFS routes with canonical shared-ocean architecture."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import logging
import time

from quart import Blueprint, current_app, request, jsonify, send_file, websocket

from server.gfs.viewport import parse_viewport_args

log = logging.getLogger("server.gfs.routes")


async def handle_gfs_ws(engine_getter, ws_obj) -> None:
    log.info("/ws/gfs connect")
    await ws_obj.send_json({"type": "hello", "channel": "gfs", "ws": "connected"})
    while True:
        try:
            msg = await ws_obj.receive()
            if msg is None:
                log.info("/ws/gfs disconnect: empty")
                break
            parsed = msg
            if isinstance(msg, str):
                try:
                    parsed = json.loads(msg)
                except Exception:
                    parsed = {"type": msg}
            msg_type = str((parsed or {}).get("type") or msg).lower()
            if msg_type == "ping":
                await ws_obj.send_json({"type": "pong", "detail": "ping"})
            elif msg_type == "status":
                status_payload = engine_getter().websocket_status_payload()
                await ws_obj.send_json(status_payload)
                log.info("/ws/gfs status served")
            elif msg_type in {"refresh", "refresh_nudge"}:
                await ws_obj.send_json({"type": "refresh_nudge", "layer": "ocean"})
            else:
                await ws_obj.send_json({"type": "ack", "detail": msg_type})
        except Exception as exc:
            log.warning("/ws/gfs exception: %s", exc)
            break
    log.info("/ws/gfs closed")


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
        payload = gfs().health_payload()
        payload["warm"] = gfs().warm_status()
        return jsonify(payload)

    @bp.route("/api/config")
    async def api_config():
        return jsonify(gfs().config_payload())

    @bp.route("/api/status")
    async def api_status():
        return jsonify(gfs().status_payload())

    @bp.route("/api/ocean")
    async def api_ocean():
        started = time.time()
        vp = parse_viewport_args(request.args)
        log.info("/gfs/api/ocean viewport=%s", vp.as_dict())
        payload = gfs().shared_ocean_payload(vp.as_dict())
        payload.setdefault("latency_ms", round((time.time() - started) * 1000, 2))
        log.info("/gfs/api/ocean latency_ms=%s", payload.get("latency_ms"))
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
        payload = gfs().bait_from_ocean(vp.as_dict())
        log.info("/gfs/api/bait polygons=%s", len((payload.get("bait") or {}).get("polygons") or []))
        return jsonify(payload)

    @bp.route("/api/bait-advanced")
    @bp.route("/api/bait/advanced")
    async def api_bait_advanced():
        vp = parse_viewport_args(request.args)
        return jsonify(gfs().bait_from_ocean(vp.as_dict()))

    @bp.route("/api/boats")
    async def api_boats():
        started = time.time()
        vp = parse_viewport_args(request.args)
        log.info("/gfs/api/boats viewport=%s", vp.as_dict())
        payload = gfs().boats_from_ocean(vp.as_dict())
        payload["latency_ms"] = round((time.time() - started) * 1000, 2)
        log.info("/gfs/api/boats count=%s latency_ms=%s", payload.get("count"), payload.get("latency_ms"))
        return jsonify(payload)

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
        started = time.time()
        payload = gfs().locations_fast(vp.as_dict(), budget_ms=1800)
        log.info("/gfs/api/locations viewport=%s source=%s warm=%s stale=%s count=%s latency_ms=%s", vp.as_dict(), payload.get("source"), payload.get("warm"), payload.get("stale"), payload.get("count"), payload.get("latency_ms"))
        items = payload.get("items") if isinstance(payload, dict) else []
        locations = [{
            "id": item.get("id") or item.get("location_key") or "loc",
            "location_key": item.get("location_key") or item.get("id") or "loc",
            "name": item.get("name") or "Fishing location",
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "fish_index": item.get("fish_index"),
            "probability": item.get("probability"),
            "confidence": item.get("confidence"),
            "meta": {"reason": item.get("reason"), "reasons": item.get("reasons") or []},
            "score": item.get("score"),
        } for item in (items or []) if isinstance(item, dict)]
        return jsonify({"ok": True, "count": len(locations), "locations": locations, "source": payload.get("source") if isinstance(payload, dict) else "unknown", "degraded": payload.get("degraded") if isinstance(payload, dict) else True, "warm": payload.get("warm") if isinstance(payload, dict) else False, "stale": payload.get("stale") if isinstance(payload, dict) else False, "fallback_reason": payload.get("fallback_reason") if isinstance(payload, dict) else "none", "timestamp": payload.get("timestamp") if isinstance(payload, dict) else int(time.time()*1000), "ts": payload.get("ts") if isinstance(payload, dict) else None})

    @bp.route("/api/live/session", methods=["POST"])
    async def create_live_session():
        data = await request.get_json() or {}
        location_id = data.get("location_id") or "default"
        return jsonify(gfs().create_live_session(location_id))

    def _coerce_key(value: str) -> str:
        return str(value or "").strip()

    def _find_fish_item(location_key: str) -> dict[str, Any] | None:
        payload = gfs().locations_fast(None, budget_ms=1800)
        for item in payload.get("items") or []:
            item_keys = {_coerce_key(item.get("id")), _coerce_key(item.get("location_key"))}
            if _coerce_key(location_key) in item_keys:
                return item
        return None

    def _location_detail_payload(location_key: str) -> dict[str, Any]:
        item = _find_fish_item(location_key) or {}
        media_payload = media().location_media(location_key)
        return {
            "ok": True,
            "id": item.get("id") or item.get("location_key") or location_key,
            "location_key": item.get("location_key") or item.get("id") or location_key,
            "name": item.get("name") or media_payload.get("label") or location_key,
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "fish_index": item.get("fish_index"),
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
            return jsonify({"ok": True, "id": fish.get("id") or fish.get("location_key") or location_key, "location_key": fish.get("location_key") or fish.get("id") or location_key, "name": fish.get("name") or payload.get("label") or location_key, "lat": fish.get("lat"), "lon": fish.get("lon"), "active": bool(live.get("active")), "stream_url": live.get("stream_url") or "", "updated_at": live.get("updated_at"), "live": live, "ts": payload.get("ts") or int(time.time() * 1000)})
        data = await request.get_json() or {}
        active = bool(data.get("active"))
        url = data.get("stream_url", "")
        return jsonify(media().upsert_live(location_key, active, url))

    @bp.route("/api/location/<location_key>/upload", methods=["POST"])
    async def upload_video(location_key):
        files = await request.files
        video = files.get("video") or files.get("file")
        if video is None:
            return jsonify({"ok": False, "error": "no video/file field"}), 400
        return jsonify(media().save_upload_video(location_key, video.filename, video.read()))

    @bp.websocket("/ws")
    async def ws_gfs_legacy():
        # compatibility websocket path under /gfs/ws; /ws/gfs remains authoritative.
        await handle_gfs_ws(gfs, websocket)

    return bp
