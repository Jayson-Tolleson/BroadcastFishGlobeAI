"""
GFS Routes module.
Registers endpoints expected by the GFS frontend and installer health checks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import time

from quart import Blueprint, current_app, request, jsonify, send_file, websocket

from server.gfs.polygon_builder import build_bait_ocean_field_v1


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

    @bp.route("/api/weather")
    async def api_weather():
        bbox = _parse_bbox(request.args)
        payload = gfs().generate_weather_payload(bbox)
        payload.setdefault("polygon_field_v1", _build_polygon_field_v1(payload, bbox))
        return jsonify(payload)

    @bp.route("/api/clouds")
    async def api_clouds():
        bbox = _parse_bbox(request.args)
        return jsonify(gfs().cloud_tiles_payload(bbox))

    @bp.route("/api/bait")
    async def api_bait():
        bbox = _parse_bbox(request.args)
        return jsonify(_build_bait_payload(gfs(), bbox, include_advanced=False))

    @bp.route("/api/bait-advanced")
    @bp.route("/api/bait/advanced")
    async def api_bait_advanced():
        bbox = _parse_bbox(request.args)
        return jsonify(_build_bait_payload(gfs(), bbox, include_advanced=True))

    @bp.route("/api/frame")
    async def api_frame():
        bbox = _parse_bbox(request.args)
        weather = gfs().generate_weather_payload(bbox)
        clouds = gfs().cloud_tiles_payload(bbox)
        bait_base = _build_bait_payload(gfs(), bbox, include_advanced=False)
        bait_advanced = _build_bait_payload(gfs(), bbox, include_advanced=True)
        boats = {"boats": []}
        payload = {
            "ok": True,
            "weather": weather,
            "clouds": clouds,
            "baitBase": bait_base,
            "baitAdvanced": bait_advanced,
            "boats": boats,
            "recursiveGrid": None,
            "sigmaClouds": clouds.get("items") or [],
        }
        return jsonify(payload)

    @bp.route("/api/tiles/<layer>/<int:z>/<int:x>/<int:y>")
    async def api_tiles(layer, z, x, y):
        return jsonify(gfs().layer_tile_payload(layer, z, x, y))

    @bp.route("/api/scene")
    async def api_scene():
        bbox = _parse_bbox(request.args)
        return jsonify(gfs().get_scene_payload(bbox))

    @bp.route("/api/hazards")
    async def api_hazards():
        return jsonify(gfs().hazards_payload())

    @bp.route("/api/diagnostics")
    async def api_diagnostics():
        return jsonify(gfs().diagnostics_payload())

    @bp.route("/api/fish")
    async def api_fish():
        return jsonify(gfs().fish_payload())

    @bp.route("/api/locations")
    async def api_locations():
        payload = gfs().fish_payload()
        items = payload.get("items") if isinstance(payload, dict) else []
        locations = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            locations.append({
                "id": item.get("id") or item.get("location_key") or item.get("name") or "loc",
                "location_key": item.get("location_key") or item.get("id") or item.get("name") or "loc",
                "name": item.get("name") or item.get("location_key") or "Fishing location",
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "probability": item.get("probability") if item.get("probability") is not None else item.get("confidence"),
                "confidence": item.get("confidence") if item.get("confidence") is not None else item.get("probability"),
                "meta": item.get("meta") or {},
                "environment": item.get("environment") or {},
                "species": item.get("species") or [],
                "score": item.get("score"),
            })
        return jsonify({
            "ok": payload.get("ok", True) if isinstance(payload, dict) else True,
            "count": len(locations),
            "locations": locations,
            "source": "fish_payload",
            "ts": payload.get("ts") if isinstance(payload, dict) else None,
            "error": payload.get("error") if isinstance(payload, dict) else None,
        })

    @bp.route("/api/live/session", methods=["POST"])
    async def create_live_session():
        data = await request.get_json() or {}
        location_id = data.get("location_id") or "default"
        return jsonify(gfs().create_live_session(location_id))

    def _coerce_key(value: str) -> str:
        return str(value or "").strip()

    def _find_fish_item(location_key: str) -> dict[str, Any] | None:
        key = _coerce_key(location_key)
        payload = gfs().fish_payload()
        items = payload.get("items") if isinstance(payload, dict) else []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            candidates = {
                _coerce_key(item.get("id")),
                _coerce_key(item.get("location_key")),
                _coerce_key(item.get("name")),
            }
            if key in candidates:
                return item
        return None

    def _location_detail_payload(location_key: str) -> dict[str, Any]:
        item = _find_fish_item(location_key) or {}
        media_payload = media().location_media(location_key)
        reports = []
        report_text = media_payload.get("report_text") or ""
        if report_text:
            reports.append(report_text)
        uploads = media_payload.get("uploads") or []
        videos = []
        for up in uploads:
            if not isinstance(up, dict):
                continue
            videos.append({
                "url": up.get("url") or up.get("media_url") or up.get("path") or "",
                "filename": up.get("filename") or up.get("name") or "video",
                "uploaded_at": up.get("uploaded_at") or up.get("ts"),
            })
        return {
            "ok": True,
            "id": item.get("id") or item.get("location_key") or location_key,
            "location_key": item.get("location_key") or location_key,
            "name": item.get("name") or media_payload.get("label") or location_key,
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "probability": item.get("probability") if item.get("probability") is not None else item.get("confidence"),
            "confidence": item.get("confidence") if item.get("confidence") is not None else item.get("probability"),
            "species": item.get("species") or [],
            "meta": item.get("meta") or {},
            "environment": item.get("environment") or media_payload.get("environment") or {},
            "reports": reports,
            "report_text": report_text,
            "report_updated_at": media_payload.get("report_updated_at"),
            "uploads": uploads,
            "videos": videos,
            "live": media_payload.get("live") or {"active": False, "stream_url": "", "updated_at": None},
            "ts": media_payload.get("ts") or int(time.time() * 1000),
        }

    @bp.route("/api/location/<location_key>")
    async def location_detail(location_key):
        payload = _location_detail_payload(location_key)
        return jsonify(payload)

    @bp.route("/api/location/<location_key>/media")
    async def location_media(location_key):
        payload = media().location_media(location_key)
        payload.setdefault("videos", [
            {
                "url": up.get("url") or up.get("media_url") or up.get("path") or "",
                "filename": up.get("filename") or up.get("name") or "video",
                "uploaded_at": up.get("uploaded_at") or up.get("ts"),
            }
            for up in (payload.get("uploads") or []) if isinstance(up, dict)
        ])
        return jsonify(payload)

    @bp.route("/api/location/<location_key>/videos")
    async def location_videos(location_key):
        payload = media().location_media(location_key)
        videos = [
            {
                "url": up.get("url") or up.get("media_url") or up.get("path") or "",
                "filename": up.get("filename") or up.get("name") or "video",
                "uploaded_at": up.get("uploaded_at") or up.get("ts"),
            }
            for up in (payload.get("uploads") or []) if isinstance(up, dict)
        ]
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
            return jsonify({
                "ok": True,
                "id": fish.get("id") or fish.get("location_key") or location_key,
                "location_key": fish.get("location_key") or location_key,
                "name": fish.get("name") or payload.get("label") or location_key,
                "lat": fish.get("lat"),
                "lon": fish.get("lon"),
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
        if "video" not in files:
            return jsonify({"ok": False, "error": "no video file"}), 400
        video = files["video"]
        raw = video.read()
        return jsonify(media().save_upload_video(location_key, video.filename, raw))

    @bp.websocket("/ws")
    async def ws_gfs():
        while True:
            msg = await websocket.receive()
            if msg is None:
                break
            await websocket.send_json({"type": "pong" if msg == "ping" else "ack", "detail": msg})

    return bp


def _parse_bbox(args: dict) -> dict[str, float] | None:
    raw = args.get("bbox") if hasattr(args, "get") else None
    if isinstance(raw, str) and raw.strip():
        try:
            west, south, east, north = [float(part.strip()) for part in raw.split(",")]
            return {"west": west, "south": south, "east": east, "north": north}
        except (ValueError, TypeError):
            pass
    try:
        if "west" in args and "south" in args:
            return {
                "west": float(args["west"]),
                "south": float(args["south"]),
                "east": float(args["east"]),
                "north": float(args["north"]),
            }
    except (ValueError, TypeError):
        pass
    return None


def _get_field(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload.get(name)
        fields = payload.get("fields") or {}
        if name in fields:
            return fields.get(name)
    return None


def _normalize_grid(grid: Any) -> list[list[float]]:
    if not isinstance(grid, list) or not grid:
        return []
    if isinstance(grid[0], list) and grid and grid[0] and isinstance(grid[0][0], list):
        return grid[0]
    return grid


def _build_polygon_field_v1(weather: dict[str, Any], bbox: dict[str, float] | None) -> dict[str, Any]:
    bbox = bbox or weather.get("bbox_used") or {"west": -180.0, "south": -80.0, "east": 180.0, "north": 80.0}
    wind_u = _normalize_grid(_get_field(weather, "wind_u", "ugrd", "u10", "u"))
    wind_v = _normalize_grid(_get_field(weather, "wind_v", "vgrd", "v10", "v"))
    temp = _normalize_grid(_get_field(weather, "air_temp", "temp2m", "temperature_k"))
    rh = _normalize_grid(_get_field(weather, "rel_humidity", "rh2m", "relative_humidity"))
    dew = _normalize_grid(_get_field(weather, "dewpoint", "dewpoint2m"))
    pmsl = _normalize_grid(_get_field(weather, "pressure_msl", "mslp"))
    rows = max(len(grid) for grid in [wind_u, wind_v, temp, rh, dew, pmsl] if isinstance(grid, list)) if any(isinstance(grid, list) and grid for grid in [wind_u, wind_v, temp, rh, dew, pmsl]) else 0
    cols = max(len(row) for grid in [wind_u, wind_v, temp, rh, dew, pmsl] if grid for row in grid if isinstance(row, list)) if rows else 0
    lat, lon, altitude_m = [], [], []
    fields = {"wind_u": [], "wind_v": [], "air_temp": [], "rel_humidity": [], "dewpoint": [], "pressure_msl": []}
    for iy in range(rows):
        for ix in range(cols):
            lat.append(round(float(bbox["south"]) + ((iy + 0.5) / max(1, rows)) * (float(bbox["north"]) - float(bbox["south"])), 6))
            lon.append(round(float(bbox["west"]) + ((ix + 0.5) / max(1, cols)) * (float(bbox["east"]) - float(bbox["west"])), 6))
            altitude_m.append(10.0)
            for out_name, grid in [("wind_u", wind_u), ("wind_v", wind_v), ("air_temp", temp), ("rel_humidity", rh), ("dewpoint", dew), ("pressure_msl", pmsl)]:
                try:
                    val = grid[iy][ix]
                except Exception:
                    val = 0.0
                try:
                    val = float(val)
                except Exception:
                    val = 0.0
                fields[out_name].append(val)
    return {"schema": "gfs_polygon_field_v1", "count": len(lat), "fields": {"lat": lat, "lon": lon, "altitude_m": altitude_m, **fields}}


def _build_bait_payload(engine: Any, bbox: dict[str, float] | None, include_advanced: bool) -> dict[str, Any]:
    weather = engine.generate_weather_payload(bbox)
    polygon_field_v1 = _build_polygon_field_v1(weather, bbox)
    fields = polygon_field_v1.get("fields") or {}
    bait_base_field_v1 = {
        "schema": "gfs_bait_field_v1",
        "count": polygon_field_v1.get("count", 0),
        "fields": {
            "lat": fields.get("lat", []),
            "lon": fields.get("lon", []),
            "wind_u": fields.get("wind_u", []),
            "wind_v": fields.get("wind_v", []),
            "air_temp": fields.get("air_temp", []),
            "rel_humidity": fields.get("rel_humidity", []),
            "dewpoint": fields.get("dewpoint", []),
            "pressure_msl": fields.get("pressure_msl", []),
            "precip_rate": [0.0 for _ in fields.get("lat", [])],
            "cloud_total": [0.0 for _ in fields.get("lat", [])],
        },
    }
    bait_advanced_field_v1 = None
    if include_advanced:
        bait_advanced_field_v1 = build_bait_ocean_field_v1(
            bbox=[float((bbox or {}).get("west", -180.0)), float((bbox or {}).get("south", -80.0)), float((bbox or {}).get("east", 180.0)), float((bbox or {}).get("north", 80.0))],
            cell_size_deg=0.25,
            source_time=weather.get("valid_time"),
            quality=str(request.args.get("quality") or "coarse"),
            ocean={
                "sst": [[0.0]],
                "chlorophyll": [[0.0]],
                "current_u": [[0.0]],
                "current_v": [[0.0]],
                "optional_ssh_anomaly": [[0.0]],
            },
            max_count=1,
        )
    return {
        "ok": True,
        "bbox": [float((bbox or {}).get("west", -180.0)), float((bbox or {}).get("south", -80.0)), float((bbox or {}).get("east", 180.0)), float((bbox or {}).get("north", 80.0))],
        "valid_time": weather.get("valid_time"),
        "polygon_field_v1": polygon_field_v1,
        "bait_base_field_v1": bait_base_field_v1,
        "bait_advanced_field_v1": bait_advanced_field_v1 or {},
        "bait": {"status": "ok" if include_advanced else "incomplete", "source": "wrapper", "polygons": [], "outer_polygons": [], "inner_polygons": [], "core_polygons": []},
    }
