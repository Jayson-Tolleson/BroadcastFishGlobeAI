"""GFS routes with canonical shared-ocean architecture."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import logging
import math
import time
import os
import uuid
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from quart import Blueprint, current_app, request, jsonify, send_file, websocket

from server.gfs.viewport import parse_viewport_args, canonicalize_viewport

log = logging.getLogger("server.gfs.routes")

GFS_WORKERS = int(os.getenv("GFS_WORKERS", "2"))
GFS_TIMEOUT_SECONDS = float(os.getenv("GFS_TIMEOUT_SECONDS", "25"))
GFS_MAX_CONCURRENT_BUILDS = int(os.getenv("GFS_MAX_CONCURRENT_BUILDS", "1"))
GFS_CACHE_MAX_ENTRIES = int(os.getenv("GFS_CACHE_MAX_ENTRIES", "32"))
GFS_WEATHER_TTL_SECONDS = float(os.getenv("GFS_WEATHER_TTL_SECONDS", "15"))
GFS_OCEAN_TTL_SECONDS = float(os.getenv("GFS_OCEAN_TTL_SECONDS", "60"))
GFS_STALE_SECONDS = float(os.getenv("GFS_STALE_SECONDS", "180"))

_GFS_EXECUTOR = ThreadPoolExecutor(max_workers=GFS_WORKERS, thread_name_prefix="gfs-worker")
_GFS_BUILD_SEMAPHORE = asyncio.Semaphore(GFS_MAX_CONCURRENT_BUILDS)
_inflight: dict[str, asyncio.Task] = {}
_inflight_lock = asyncio.Lock()
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
cache_hits = 0
cache_misses = 0
timeout_count = 0


def _cache_get(key: str):
    global cache_hits, cache_misses
    entry = _cache.get(key)
    if not entry:
        cache_misses += 1
        log.info("[gfs/cache] miss key=%s", key)
        return None
    age = time.time() - entry["ts"]
    ttl = entry.get("ttl", GFS_OCEAN_TTL_SECONDS)
    if age <= ttl:
        cache_hits += 1
        log.info("[gfs/cache] hit key=%s age=%.2f", key, age)
        return {**entry["payload"], "cache_status": "fresh", "generated_at": entry["generated_at"]}
    if age <= (ttl + GFS_STALE_SECONDS):
        log.info("[gfs/cache] stale key=%s age=%.2f", key, age)
        return {**entry["payload"], "cache_status": "stale", "generated_at": entry["generated_at"]}
    _cache.pop(key, None)
    cache_misses += 1
    log.info("[gfs/cache] miss key=%s", key)
    return None


def _cache_put(key: str, payload: dict[str, Any], ttl: float):
    _cache[key] = {"ts": time.time(), "payload": payload, "ttl": ttl, "generated_at": int(time.time() * 1000)}
    _cache.move_to_end(key)
    while len(_cache) > GFS_CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


async def _run_gfs_blocking(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    log.info("[gfs/worker] offloaded blocking task=%s", getattr(fn, "__name__", "callable"))
    return await loop.run_in_executor(_GFS_EXECUTOR, lambda: fn(*args, **kwargs))


async def _singleflight(key: str, coro_factory):
    async with _inflight_lock:
        task = _inflight.get(key)
        if task and not task.done():
            log.info("[gfs/dedupe] joined in-flight key=%s", key)
            return await task
        task = asyncio.create_task(coro_factory())
        _inflight[key] = task
        log.info("[gfs/dedupe] new task key=%s", key)
    try:
        out = await task
        log.info("[gfs/dedupe] complete key=%s", key)
        return out
    finally:
        async with _inflight_lock:
            if _inflight.get(key) is task:
                _inflight.pop(key, None)


def _norm_key(route: str, vp, extra: str = "") -> str:
    d = vp.as_dict() if hasattr(vp, "as_dict") else dict(vp or {})
    rounded = {k: round(float(v), 2) if isinstance(v, (int, float)) else v for k, v in d.items()}
    return f"{route}|{json.dumps(rounded, sort_keys=True)}|{extra}"


async def _heavy_json(route: str, vp, ttl: float, builder, *, extra_key: str = ""):
    global timeout_count
    request_id = uuid.uuid4().hex[:8]
    bbox = vp.as_bbox() if hasattr(vp, "as_bbox") else "na"
    log.info("[gfs/request] start route=%s bbox=%s request_id=%s", route, bbox, request_id)
    started = time.time()
    key = _norm_key(route, vp, extra_key)
    cached = _cache_get(key)
    if cached and cached.get("cache_status") == "fresh":
        return jsonify(_json_safe(cached))

    async def _build_once():
        acquired = False
        try:
            log.info("[gfs/backpressure] waiting route=%s request_id=%s", route, request_id)
            await asyncio.wait_for(_GFS_BUILD_SEMAPHORE.acquire(), timeout=2.0)
            acquired = True
            log.info("[gfs/backpressure] acquired route=%s request_id=%s", route, request_id)
        except asyncio.TimeoutError:
            log.warning("[gfs/backpressure] timeout route=%s request_id=%s", route, request_id)
            stale = _cache_get(key)
            if stale:
                return stale, 200
            return {"ok": False, "status": "busy", "message": "GFS busy"}, 429
        try:
            payload = await asyncio.wait_for(_run_gfs_blocking(builder), timeout=GFS_TIMEOUT_SECONDS)
            payload = payload if isinstance(payload, dict) else {"ok": True, "data": payload}
            payload.setdefault("cache_status", "miss")
            payload.setdefault("generated_at", int(time.time() * 1000))
            _cache_put(key, payload, ttl)
            return payload, 200
        except asyncio.TimeoutError:
            timeout_count += 1
            return {"ok": False, "status": "timeout", "message": "GFS payload timed out"}, 504
        finally:
            if acquired:
                _GFS_BUILD_SEMAPHORE.release()

    payload, status = await _singleflight(key, _build_once)
    ms = (time.time() - started) * 1000
    if status >= 400:
        log.warning("[gfs/request] error route=%s ms=%.2f request_id=%s", route, ms, request_id)
    else:
        log.info("[gfs/request] done route=%s ms=%.2f request_id=%s", route, ms, request_id)
    return jsonify(_json_safe(payload)), status



def _json_safe(value: Any):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    return value


def _ocean_stride_for_viewport(vp, args) -> int:
    span = max(abs(float(vp.east) - float(vp.west)), abs(float(vp.north) - float(vp.south)))
    range_hint = None
    raw_viewport = args.get("viewport") if hasattr(args, "get") else None
    if isinstance(raw_viewport, str) and raw_viewport.strip():
        try:
            obj = json.loads(raw_viewport)
            range_hint = float(((obj.get("camera") or {}).get("range")))
        except Exception:
            range_hint = None
    if span <= 8 and (range_hint is None or range_hint <= 900000):
        return 1
    if span <= 20 and (range_hint is None or range_hint <= 2200000):
        return 2
    if span <= 45:
        return 3
    return 4


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
    location_key = item.get("location_key") or item.get("id") or "loc"
    item_id = location_key
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
        "marker_environment": item.get("marker_environment") if isinstance(item.get("marker_environment"), dict) else {},
        "intel_tier": item.get("intel_tier"),
        "intel_sources": item.get("intel_sources") if isinstance(item.get("intel_sources"), list) else [],
        "missing_inputs": item.get("missing_inputs") if isinstance(item.get("missing_inputs"), list) else [],
        "intel_confidence": item.get("intel_confidence"),
        "wavewatch_available": bool(item.get("wavewatch_available")),
    }


def _locations_response(payload: dict[str, Any], locations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "count": len(locations),
        "locations": locations,
        "source": payload.get("source"),
        "entity_type": payload.get("entity_type", "location_markers"),
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
        payload["concurrency"] = {"executor_workers": GFS_WORKERS, "max_concurrent_builds": GFS_MAX_CONCURRENT_BUILDS, "inflight": len(_inflight), "semaphore_available": getattr(_GFS_BUILD_SEMAPHORE, "_value", None)}
        payload["cache"] = {"entries": len(_cache), "max_entries": GFS_CACHE_MAX_ENTRIES, "hits": cache_hits, "misses": cache_misses}
        payload["timeouts"] = timeout_count
        payload["ttl"] = {"weather": GFS_WEATHER_TTL_SECONDS, "ocean": GFS_OCEAN_TTL_SECONDS, "stale": GFS_STALE_SECONDS}
        return jsonify(_json_safe(payload))

    @bp.route("/api/config")
    async def api_config():
        return jsonify(gfs().config_payload())

    @bp.route("/api/status")
    async def api_status():
        return jsonify(gfs().status_payload())

    @bp.route("/api/ocean")
    async def api_ocean():
        vp = parse_viewport_args(request.args)
        ocean_stride = _ocean_stride_for_viewport(vp, request.args)
        ocean_vp = canonicalize_viewport({**vp.as_dict(), "stride": ocean_stride})
        return await _heavy_json(
            "/gfs/api/ocean",
            ocean_vp,
            GFS_OCEAN_TTL_SECONDS,
            lambda: {**gfs().shared_ocean_payload(ocean_vp.as_dict()), "ocean_stride": ocean_stride},
            extra_key=f"ocean_stride={ocean_stride}",
        )

    @bp.route("/api/weather")
    async def api_weather():
        vp = parse_viewport_args(request.args)
        started = _route_debug_start("/gfs/api/weather", vp, request.query_string.decode("utf-8", errors="ignore"))
        weather_resp, weather_status = await _heavy_json(
            "/gfs/api/weather",
            vp,
            GFS_WEATHER_TTL_SECONDS,
            lambda: gfs().generate_weather_payload(vp.as_dict()),
            extra_key=request.query_string.decode("utf-8", errors="ignore"),
        )
        if weather_status != 200:
            return weather_resp, weather_status
        payload = await weather_resp.get_json()
        payload_state = str(payload.get("payload_state") or "").lower()
        source_status = "live" if payload_state == "live" else "stale_last_good" if payload_state == "cached" else "unavailable"
        if payload_state not in {"live", "cached"}:
            out = {
                "ok": False,
                "source": str(payload.get("source") or "ncss_weather"),
                "payload_state": "unavailable",
                "error_code": "weather_unavailable",
                "error_message": str(payload.get("error_message") or "NCSS weather unavailable and no stale last-good payload"),
                "latency_ms": round((time.time() - started) * 1000, 2),
                "stale": False,
                "source_status": source_status,
                "request_url": request.full_path,
                "fallback_reason": payload.get("fallback_reason"),
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
        return await _heavy_json("/gfs/api/clouds", vp, GFS_WEATHER_TTL_SECONDS, lambda: gfs().compact_cloud_payload(vp.as_dict()))

    @bp.route("/api/bait")
    async def api_bait():
        vp = parse_viewport_args(request.args)
        return await _heavy_json("/gfs/api/bait", vp, GFS_OCEAN_TTL_SECONDS, lambda: gfs().bait_from_ocean(vp.as_dict()))

    @bp.route("/api/bait-advanced")
    @bp.route("/api/bait/advanced")
    async def api_bait_advanced():
        vp = parse_viewport_args(request.args)
        return await _heavy_json("/gfs/api/bait-advanced", vp, GFS_OCEAN_TTL_SECONDS, lambda: gfs().bait_from_ocean(vp.as_dict()))

    @bp.route("/api/boats")
    async def api_boats():
        vp = parse_viewport_args(request.args)
        return await _heavy_json("/gfs/api/boats", vp, GFS_OCEAN_TTL_SECONDS, lambda: gfs().boats_from_ocean(vp.as_dict()))

    @bp.route("/api/frame")
    async def api_frame():
        vp = parse_viewport_args(request.args)
        extra_key = f"query={request.query_string.decode('utf-8', errors='ignore')}"
        return await _heavy_json("/gfs/api/frame", vp, GFS_WEATHER_TTL_SECONDS, lambda: gfs().frame_payload(vp.as_dict()), extra_key=extra_key)

    @bp.route("/api/tiles/<layer>/<int:z>/<int:x>/<int:y>")
    async def api_tiles(layer, z, x, y):
        vp = parse_viewport_args(request.args)
        return await _heavy_json("/gfs/api/tiles", vp, GFS_OCEAN_TTL_SECONDS, lambda: gfs().layer_tile_payload(layer, z, x, y), extra_key=f"{layer}:{z}:{x}:{y}")

    @bp.route("/api/scene")
    async def api_scene():
        vp = parse_viewport_args(request.args)
        return await _heavy_json("/gfs/api/scene", vp, GFS_OCEAN_TTL_SECONDS, lambda: gfs().get_scene_payload(vp.as_dict()))

    @bp.route("/api/hazards")
    async def api_hazards():
        return jsonify(gfs().hazards_payload())

    @bp.route("/api/diagnostics")
    async def api_diagnostics():
        return jsonify(gfs().diagnostics_payload())

    @bp.route("/api/fish")
    async def api_fish():
        vp = parse_viewport_args(request.args)
        return await _heavy_json("/gfs/api/fish", vp, GFS_OCEAN_TTL_SECONDS, lambda: gfs().fish_from_ocean(vp.as_dict()))

    @bp.route("/api/locations")
    async def api_locations():
        vp = parse_viewport_args(request.args)
        payload = await _run_gfs_blocking(lambda: gfs().locations_fast(vp.as_dict(), budget_ms=1800))
        log.info(
            "/gfs/api/locations route=/gfs/api/locations query=%s viewport=%s source_policy=csv_only source=%s warm=%s stale=%s count=%s latency_ms=%s entity_type=%s intel_tier=%s",
            request.query_string.decode("utf-8", errors="ignore"),
            vp.as_dict(),
            payload.get("source"),
            payload.get("warm"),
            payload.get("stale"),
            payload.get("count"),
            payload.get("latency_ms"),
            payload.get("entity_type"),
            payload.get("intel_tier"),
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

    async def _find_fish_item(location_key: str) -> dict[str, Any] | None:
        payload = await _run_gfs_blocking(lambda: gfs().locations_fast(None, budget_ms=1800))
        for item in payload.get("items") or []:
            item_keys = {_coerce_key(item.get("id")), _coerce_key(item.get("location_key"))}
            if _coerce_key(location_key) in item_keys:
                return item
        return None

    async def _location_detail_payload(location_key: str) -> dict[str, Any]:
        item = (await _find_fish_item(location_key)) or {}
        media_payload = await _run_gfs_blocking(lambda: media().location_media(location_key))
        normalized = _normalize_location_item(item)
        canonical_id = _coerce_key(normalized.get("location_key") or normalized.get("id") or location_key)
        return {
            "ok": True,
            "id": canonical_id,
            "location_key": canonical_id,
            "canonical_id": canonical_id,
            "name": normalized.get("name") or media_payload.get("label") or canonical_id,
            "lat": normalized.get("lat"),
            "lon": normalized.get("lon"),
            "fish_index": normalized.get("fish_index"),
            "probability": normalized.get("probability"),
            "confidence": normalized.get("confidence"),
            "meta": normalized.get("meta"),
            "marker_class": normalized.get("marker_class"),
            "bait_applicable": bool(normalized.get("bait_applicable")),
            "intel_tier": normalized.get("intel_tier"),
            "intel_sources": normalized.get("intel_sources") or [],
            "missing_inputs": normalized.get("missing_inputs") or [],
            "quick_weather": normalized.get("quick_weather") or {},
            "quick_ocean": normalized.get("quick_ocean") or {},
            "quick_snapshot": normalized.get("quick_snapshot") or {},
            "marker_environment": normalized.get("marker_environment") or {},
            "profile": {
                "node_id": canonical_id,
                "canonical_id": canonical_id,
                "marker_class": normalized.get("marker_class"),
                "bait_applicable": bool(normalized.get("bait_applicable")),
                "intel_tier": normalized.get("intel_tier"),
                "intel_sources": normalized.get("intel_sources") or [],
                "missing_inputs": normalized.get("missing_inputs") or [],
            },
            "reports": [media_payload.get("report_text")] if media_payload.get("report_text") else [],
            "report_text": media_payload.get("report_text") or "",
            "uploads": media_payload.get("uploads") or [],
            "live": media_payload.get("live") or {"active": False, "stream_url": "", "updated_at": None},
            "ts": media_payload.get("ts") or int(time.time() * 1000),
        }

    @bp.route("/api/location/<location_key>")
    async def location_detail(location_key):
        return jsonify(await _location_detail_payload(location_key))

    @bp.route("/api/intelligence/node/<location_key>")
    async def intelligence_node(location_key):
        return jsonify(await _location_detail_payload(location_key))

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
            normalized = await _location_detail_payload(location_key)
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
