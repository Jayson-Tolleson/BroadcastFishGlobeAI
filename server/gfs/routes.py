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


def _route_debug_start(route: str, vp, raw_query: str) -> float:
    started = time.time()
    log.info("[gfs/route] start route=%s query=%s viewport=%s", route, raw_query, vp.as_dict() if hasattr(vp, "as_dict") else vp)
    return started


def _route_debug_done(route: str, started: float, payload: dict[str, Any], status_code: int = 200) -> None:
    log.info(
        "[gfs/route] done route=%s status=%s latency_ms=%.2f ok=%s source=%s stale=%s payload_state=%s count=%s",
        route,
        status_code,
        (time.time() - started) * 1000,
        payload.get("ok") if isinstance(payload, dict) else None,
        payload.get("source") if isinstance(payload, dict) else None,
        payload.get("stale") if isinstance(payload, dict) else None,
        payload.get("payload_state") if isinstance(payload, dict) else None,
        payload.get("count") if isinstance(payload, dict) else None,
    )


async def handle_gfs_ws(engine_getter, ws_obj) -> None:
    log.info("/ws/gfs route entry")
    engine = None
    try:
        engine = engine_getter()
        mark_open = getattr(engine, "mark_gfs_ws_open", None)
        if callable(mark_open):
            mark_open()
    except Exception:
        log.exception("/ws/gfs failed to resolve engine before handshake")
    log.info("/ws/gfs handshake open")
    try:
        await ws_obj.send_json({"type": "hello", "channel": "gfs", "ws": "connected"})
        log.info("/ws/gfs first hello sent")
    except Exception as exc:
        log.exception("/ws/gfs hello send failed")
        if engine is not None:
            mark_exc = getattr(engine, "mark_gfs_ws_exception", None)
            if callable(mark_exc):
                mark_exc(exc)
        if engine is not None:
            mark_close = getattr(engine, "mark_gfs_ws_close", None)
            if callable(mark_close):
                mark_close()
        return
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
                status_payload = (engine or engine_getter()).websocket_status_payload()
                await ws_obj.send_json(status_payload)
                log.info("/ws/gfs status served")
            elif msg_type in {"refresh", "refresh_nudge"}:
                await ws_obj.send_json({"type": "refresh_nudge", "layer": "ocean"})
            else:
                await ws_obj.send_json({"type": "ack", "detail": msg_type})
        except Exception as exc:
            log.exception("/ws/gfs exception")
            if engine is not None:
                mark_exc = getattr(engine, "mark_gfs_ws_exception", None)
                if callable(mark_exc):
                    mark_exc(exc)
            break
    if engine is not None:
        mark_close = getattr(engine, "mark_gfs_ws_close", None)
        if callable(mark_close):
            mark_close()
    log.info("/ws/gfs closed")


def _normalize_location_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = item.get("id") or item.get("location_key") or "loc"
    location_key = item.get("location_key") or item.get("id") or "loc"
    return {
        "id": item_id,
        "location_key": location_key,
        "name": item.get("name") or "Fishing location",
        "lat": item.get("lat"),
        "lon": item.get("lon"),
        "fish_index": item.get("fish_index"),
        "probability": item.get("probability"),
        "confidence": item.get("confidence"),
        "meta": {"reason": item.get("reason"), "reasons": item.get("reasons") or []},
        "score": item.get("score"),
        "marker_class": item.get("marker_class") or "coastal",
        "bait_applicable": bool(item.get("bait_applicable")),
        "species_profile_seed": item.get("species_profile_seed"),
        "quick_weather": item.get("quick_weather") if isinstance(item.get("quick_weather"), dict) else {},
        "quick_ocean": item.get("quick_ocean") if isinstance(item.get("quick_ocean"), dict) else {},
        "quick_snapshot": item.get("quick_snapshot") if isinstance(item.get("quick_snapshot"), dict) else {},
    }


def _locations_response(payload: dict[str, Any], locations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "count": len(locations),
        "locations": locations,
        "source": payload.get("source"),
        "entity_type": payload.get("entity_type", "location"),
        "derived": bool(payload.get("derived", False)),
        "degraded": payload.get("degraded"),
        "warm": payload.get("warm"),
        "stale": payload.get("stale"),
        "fallback_reason": payload.get("fallback_reason"),
        "timestamp": payload.get("timestamp", int(time.time() * 1000)),
        "ts": payload.get("ts"),
    }


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
        started = _route_debug_start("/gfs/api/weather", vp, request.query_string.decode("utf-8", errors="ignore"))
        payload = gfs().generate_weather_payload(vp.as_dict())
        payload_state = str(payload.get("payload_state") or "").lower()
        source_status = "live" if payload_state == "live" else "stale_last_good" if payload_state == "cached" else "unavailable"
        if payload_state == "synthetic":
            out = {
                "ok": False,
                "source": str(payload.get("source") or "ncss_weather"),
                "payload_state": "unavailable",
                "error_code": "weather_unavailable",
                "error_message": "NCSS weather unavailable and no stale last-good payload",
                "latency_ms": round((time.time() - started) * 1000, 2),
                "stale": False,
                "source_status": source_status,
                "request_url": request.full_path,
            }
            _route_debug_done("/gfs/api/weather", started, out, status_code=503)
            return jsonify(out), 503
        out = {
            **payload,
            "analysis_time": payload.get("cycle"),
            "forecast_hour": payload.get("forecast_hour"),
            "valid_time": payload.get("valid_time"),
            "source_status": source_status,
            "stale": source_status == "stale_last_good",
            "ok": bool(payload.get("ok", True)),
        }
        _route_debug_done("/gfs/api/weather", started, out)
        return jsonify(out)

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
        started = time.time()
        vp = parse_viewport_args(request.args)
        payload = gfs().frame_payload(vp.as_dict())
        payload.setdefault("latency_ms", round((time.time() - started) * 1000, 2))
        log.info("/gfs/api/frame latency_ms=%s viewport=%s", payload.get("latency_ms"), vp.as_dict())
        return jsonify(payload)

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
        payload = gfs().fish_from_ocean(vp.as_dict())
        payload.setdefault("entity_type", "fish")
        payload.setdefault("derived", True)
        return jsonify(payload)

    @bp.route("/api/locations")
    async def api_locations():
        vp = parse_viewport_args(request.args)
        payload = gfs().locations_fast(vp.as_dict(), budget_ms=1800)
        log.info(
            "/gfs/api/locations viewport=%s source=%s warm=%s stale=%s count=%s latency_ms=%s",
            vp.as_dict(),
            payload.get("source"),
            payload.get("warm"),
            payload.get("stale"),
            payload.get("count"),
            payload.get("latency_ms"),
        )
        items = payload.get("items") if isinstance(payload, dict) else []
        locations = [_normalize_location_item(item) for item in (items or []) if isinstance(item, dict)]
        safe_payload = payload if isinstance(payload, dict) else {}
        return jsonify(_locations_response(safe_payload, locations))

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
        normalized = _normalize_location_item(item)
        return {
            "ok": True,
            "id": normalized.get("id") or location_key,
            "location_key": normalized.get("location_key") or location_key,
            "name": normalized.get("name") or media_payload.get("label") or location_key,
            "lat": normalized.get("lat"),
            "lon": normalized.get("lon"),
            "fish_index": normalized.get("fish_index"),
            "probability": normalized.get("probability"),
            "confidence": normalized.get("confidence"),
            "meta": normalized.get("meta"),
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
            normalized = _normalize_location_item(fish)
            return jsonify({
                "ok": True,
                "id": normalized.get("id") or location_key,
                "location_key": normalized.get("location_key") or location_key,
                "name": normalized.get("name") or payload.get("label") or location_key,
                "lat": normalized.get("lat"),
                "lon": normalized.get("lon"),
                "active": bool(live.get("active")),
                "stream_url": live.get("stream_url") or "",
                "updated_at": live.get("updated_at"),
                "live": live,
                "ts": payload.get("ts") or int(time.time() * 1000),
            })
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
