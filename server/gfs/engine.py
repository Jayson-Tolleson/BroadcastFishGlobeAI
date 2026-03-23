from __future__ import annotations

import logging
import math
import threading
import time
import csv
from dataclasses import dataclass
from typing import Any

from server.gfs.cache import TinyTTLCache
from server.gfs.models import BBox
from server.gfs.viewport import canonicalize_viewport
from server.gfs.services.ocean_service import OceanService
from server.gfs.services.fish_service import FishService
from server.gfs.services.bait_service import BaitService
from server.gfs.services.boat_service import BoatService
from server.gfs_service import GFSService

log = logging.getLogger("server.gfs.engine")


@dataclass(frozen=True)
class ParsedIntent:
    bbox: BBox


class GfsEngine(GFSService):
    def __init__(self, config: Any | None = None, static_dir: str | None = None) -> None:
        super().__init__(static_dir or "static")
        self.config_obj = config
        self.ocean_service = OceanService()
        self.fish_service = FishService()
        self.bait_service = BaitService()
        self.boat_service = BoatService()
        self._cache = TinyTTLCache(ttl_seconds=75.0, max_entries=128)
        self._warm_lock = threading.Lock()
        self._warm_started = False
        self._warm_ready = False
        self._warm_error: str | None = None
        self._warm_at: int | None = None
        self._gfs_ws_registered = False
        self._gfs_ws_active_clients = 0
        self._gfs_ws_last_exception: str | None = None
        self._gfs_ws_last_open_ts: int | None = None
        self._weather_refresh_inflight = False
        self._weather_refresh_last_ts = 0.0
        self._prewarm_duration_ms: float | None = None
        self._last_ocean_latency_ms: float | None = None
        self._last_frame_latency_ms: float | None = None
        self._last_ocean_cache_state: str | None = None
        self._last_frame_cache_state: str | None = None

    def parse_intent(self, args: Any) -> ParsedIntent:
        vp = canonicalize_viewport({
            "west": args.get("west") if hasattr(args, "get") else None,
            "south": args.get("south") if hasattr(args, "get") else None,
            "east": args.get("east") if hasattr(args, "get") else None,
            "north": args.get("north") if hasattr(args, "get") else None,
            "quality": args.get("quality") if hasattr(args, "get") else None,
            "stride": args.get("stride") if hasattr(args, "get") else None,
        })
        return ParsedIntent(BBox(vp.west, vp.south, vp.east, vp.north))

    async def weather_payload(self, intent: ParsedIntent) -> dict[str, Any]:
        return self.generate_weather_payload({"west": intent.bbox.west, "south": intent.bbox.south, "east": intent.bbox.east, "north": intent.bbox.north})

    def _cache_key(self, kind: str, vp) -> str:
        return f"{kind}:{vp.west:.3f}:{vp.south:.3f}:{vp.east:.3f}:{vp.north:.3f}:{vp.quality}:{vp.stride}"

    def _default_warm_viewport(self):
        return canonicalize_viewport({"west": -121.5, "south": 32.5, "east": -117.5, "north": 35.8, "quality": "full", "stride": 1})

    def _safe_weather_payload(self, vp) -> dict[str, Any]:
        started = time.time()
        payload = self.generate_weather_payload_fast(vp.as_dict())
        if str(payload.get("payload_state") or "").lower() != "live":
            self._maybe_refresh_weather_async()
        log.info(
            "[gfs-perf] weather fast_path payload_state=%s source=%s latency_ms=%.2f",
            payload.get("payload_state"),
            payload.get("source"),
            (time.time() - started) * 1000,
        )
        return payload

    def _maybe_refresh_weather_async(self) -> None:
        now = time.time()
        if self._weather_refresh_inflight:
            return
        if (now - float(self._weather_refresh_last_ts or 0.0)) < 30.0:
            return
        self._weather_refresh_inflight = True
        self._weather_refresh_last_ts = now

        def _refresh() -> None:
            started = time.time()
            try:
                payload = self.generate_weather_payload(self._default_warm_viewport().as_dict())
                log.info(
                    "[gfs-perf] weather async refresh complete payload_state=%s source=%s latency_ms=%.2f",
                    payload.get("payload_state"),
                    payload.get("source"),
                    (time.time() - started) * 1000,
                )
            except Exception as exc:
                log.warning("[gfs-perf] weather async refresh failed err=%s", exc)
            finally:
                self._weather_refresh_inflight = False

        try:
            threading.Thread(target=_refresh, daemon=True).start()
        except Exception as exc:
            self._weather_refresh_inflight = False
            log.warning("[gfs-perf] failed to start weather async refresh thread: %s", exc)

    def _build_shared_products(self, vp):
        weather = self._safe_weather_payload(vp)
        ocean = self.ocean_service.build_shared_state(vp, weather)
        fish = self.fish_service.score_markers(ocean, vp)
        bait = self.bait_service.score(ocean, vp)
        boats = self.boat_service.agents(ocean, vp, count=12)
        return weather, ocean, fish, bait, boats

    def prewarm_startup(self) -> None:
        with self._warm_lock:
            if self._warm_started:
                return
            self._warm_started = True
        log.info("gfs prewarm start")
        started = time.time()
        try:
            vp = self._default_warm_viewport()
            weather, ocean, fish, bait, boats = self._build_shared_products(vp)
            csv_locations = self._csv_locations(vp.as_dict())
            self._cache.set(self._cache_key("ocean", vp), ocean)
            self._cache.set(
                self._cache_key("locations", vp),
                {"items": csv_locations.get("items") or [], "count": int(csv_locations.get("count") or 0), "ts": csv_locations.get("ts")},
            )
            self._cache.set(self._cache_key("fish", vp), {"items": fish, "count": len(fish), "ts": ocean.get("ts")})
            self._cache.set(self._cache_key("bait", vp), bait)
            self._cache.set(self._cache_key("boats", vp), {"boats": boats, "count": len(boats)})
            self._warm_ready = True
            self._warm_error = None
            self._warm_at = int(time.time() * 1000)
            self._prewarm_duration_ms = (time.time() - started) * 1000
            log.info("gfs prewarm complete latency_ms=%.2f", self._prewarm_duration_ms)
        except Exception as exc:
            self._warm_error = str(exc)
            log.warning("gfs prewarm failed: %s", exc)

    def shared_ocean_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        started = time.time()
        vp = canonicalize_viewport(bbox)
        key = self._cache_key("ocean", vp)
        cached = self._cache.get(key)
        if cached:
            out = {**cached, "warm": self._warm_ready, "stale": False, "cache": "fresh"}
            self._last_ocean_latency_ms = (time.time() - started) * 1000
            self._last_ocean_cache_state = "hit"
            log.info("[gfs-perf] ocean cache=hit viewport=%s latency_ms=%.2f", vp.as_bbox(), (time.time() - started) * 1000)
            return out
        weather_started = time.time()
        weather = self._safe_weather_payload(vp)
        weather_ms = (time.time() - weather_started) * 1000
        ocean_started = time.time()
        ocean = self.ocean_service.build_shared_state(vp, weather)
        ocean_ms = (time.time() - ocean_started) * 1000
        ocean.update({"warm": self._warm_ready, "stale": False, "cache": "miss"})
        self._cache.set(key, ocean)
        self._last_ocean_latency_ms = (time.time() - started) * 1000
        self._last_ocean_cache_state = "miss"
        log.info(
            "[gfs-perf] ocean cache=miss viewport=%s weather_ms=%.2f ocean_build_ms=%.2f latency_ms=%.2f",
            vp.as_bbox(),
            weather_ms,
            ocean_ms,
            (time.time() - started) * 1000,
        )
        return ocean

    def fish_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        cached = self._cache.get(self._cache_key("fish", vp))
        if cached:
            return {
                "ok": True,
                "source": "shared_ocean_cache",
                "degraded": False,
                "items": cached.get("items") or [],
                "count": len(cached.get("items") or []),
                "timestamp": int(time.time() * 1000),
                "ts": cached.get("ts") or int(time.time() * 1000),
                "sources": (self._cache.get(self._cache_key("ocean", vp)) or {}).get("sources"),
                "warm": self._warm_ready,
                "stale": False,
                "entity_type": "fish_intelligence",
                "derived": True,
                "cache": "hit",
            }
        ocean = self.shared_ocean_payload(vp.as_dict())
        items = self.fish_service.score_markers(ocean, vp)
        log.info("fish derived count=%s viewport=%s", len(items), vp.as_bbox())
        payload = {
            "ok": True,
            "source": "shared_ocean",
            "degraded": bool(ocean.get("degraded")),
            "items": items,
            "count": len(items),
            "timestamp": ocean.get("timestamp"),
            "ts": ocean.get("ts"),
            "sources": ocean.get("sources"),
            "warm": self._warm_ready,
            "stale": False,
            "entity_type": "fish_intelligence",
            "derived": True,
            "cache": "miss",
        }
        self._cache.set(self._cache_key("fish", vp), {"items": items, "count": len(items), "ts": payload["ts"]})
        return payload

    @staticmethod
    def _lon_in_viewport(lon: float, west: float, east: float) -> bool:
        # Handle anti-meridian viewports as wrapped ranges.
        if west <= east:
            return west <= lon <= east
        return lon >= west or lon <= east

    @staticmethod
    def _marker_class(item: dict[str, Any], lat: float, lon: float) -> str:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        text = " ".join(str(meta.get(k) or "") for k in meta.keys()).lower()
        text += " " + str(item.get("name") or "").lower()
        inland_tokens = ("lake", "river", "reservoir", "creek", "dam", "trout", "catfish", "bass")
        estuary_tokens = ("estuary", "bay", "delta", "lagoon", "brackish")
        offshore_tokens = ("offshore", "tuna", "yellowtail", "dorado", "pelagic")
        if any(tok in text for tok in inland_tokens):
            return "inland_freshwater"
        if any(tok in text for tok in estuary_tokens):
            return "estuary"
        if any(tok in text for tok in offshore_tokens):
            return "offshore"
        # Longitude/latitude heuristic fallback for US-centric CSV.
        if lat > 35.0 and lon < -118.3:
            return "inland_freshwater"
        return "coastal"

    def _csv_locations(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        points, err = self._read_csv_markers()
        items: list[dict[str, Any]] = []
        for item in points:
            if not isinstance(item, dict):
                continue
            lat = item.get("lat")
            lon = item.get("lon")
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                continue
            if not math.isfinite(lat_f) or not math.isfinite(lon_f):
                continue
            if lat_f < vp.south or lat_f > vp.north:
                continue
            if not self._lon_in_viewport(lon_f, vp.west, vp.east):
                continue
            confidence = item.get("confidence")
            probability = item.get("probability")
            normalized_confidence = confidence if confidence is not None else probability if probability is not None else 0.5
            normalized_probability = probability if probability is not None else confidence if confidence is not None else 0.5
            loc_id = item.get("id") or item.get("location_key") or item.get("name") or "loc"
            marker_class = self._marker_class(item, lat_f, lon_f)
            env = item.get("environment") if isinstance(item.get("environment"), dict) else {}
            bait = item.get("bait") if isinstance(item.get("bait"), dict) else {}
            env_meta = item.get("environment_meta") if isinstance(item.get("environment_meta"), dict) else {}
            bait_applicable = marker_class in {"coastal", "offshore", "estuary"}
            wavewatch_available = any(
                isinstance(env.get(k), (int, float)) and math.isfinite(float(env.get(k)))
                for k in ("wave_feet", "swell_height_ft", "swell_period_s", "swell_direction_deg")
            )
            intel_tier = "enhanced" if wavewatch_available else "basic"
            intel_sources = ["gfs", "hycom"]
            missing_inputs: list[str] = []
            if isinstance(env.get("chlorophyll_mg_m3"), (int, float)) and math.isfinite(float(env.get("chlorophyll_mg_m3"))):
                intel_sources.append("coastwatch")
            else:
                missing_inputs.append("coastwatch")
            if isinstance(env.get("depth_m"), (int, float)) and math.isfinite(float(env.get("depth_m"))):
                intel_sources.append("bathymetry")
            else:
                missing_inputs.append("bathymetry")
            if wavewatch_available:
                intel_sources.append("wavewatch")
            else:
                missing_inputs.append("wavewatch")
            items.append({
                "id": loc_id,
                "location_key": item.get("location_key") or loc_id,
                "name": item.get("name") or "Fishing location",
                "lat": lat_f,
                "lon": lon_f,
                "fish_index": item.get("fish_index") if item.get("fish_index") is not None else normalized_confidence,
                "confidence": normalized_confidence,
                "probability": normalized_probability,
                "score": item.get("score"),
                "reason": "fish_csv",
                "reasons": ["fishloclist.csv"],
                "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
                "marker_class": marker_class,
                "bait_applicable": bait_applicable,
                "species_profile_seed": f"{marker_class}:{str(item.get('location_key') or loc_id)}",
                "quick_weather": {
                    "air_temp_c": env.get("air_temp_c"),
                    "wind_speed_kt": env.get("wind_speed_kt"),
                    "wind_direction_deg": env.get("wind_direction_deg"),
                    "wind_gust_kt": env.get("wind_gust_kt"),
                    "cloud_cover_pct": env.get("cloud_cover_pct"),
                    "precipitation_factor": env.get("precipitation_factor"),
                    "pressure_mb": env.get("pressure_mb"),
                    "source_tier": env_meta.get("source_tier"),
                },
                "quick_ocean": {
                    "sst_c": env.get("water_temp_c"),
                    "current_speed_kt": env.get("current_speed_kt"),
                    "current_direction_deg": env.get("current_direction_deg"),
                    "wave_height_ft": env.get("wave_feet"),
                    "swell_height_ft": env.get("swell_height_ft"),
                    "swell_period_s": env.get("swell_period_s"),
                    "swell_direction_deg": env.get("swell_direction_deg"),
                    "chlorophyll_mg_m3": env.get("chlorophyll_mg_m3"),
                    "depth_m": env.get("depth_m"),
                    "source_tier": env_meta.get("source_tier"),
                    "degraded": env_meta.get("source_tier") not in {"station_enriched_us", "global_model_gfs"},
                } if bait_applicable else {},
                "marker_environment": {
                    "marker_id": loc_id,
                    "marker_class": marker_class,
                    "source_status": {
                        "weather": "available" if bool(env) else "unavailable",
                        "ocean_currents": "available" if isinstance(env.get("current_speed_kt"), (int, float)) else "unavailable",
                        "chlorophyll": "available" if "coastwatch" in intel_sources else "unavailable",
                        "waves": "available" if wavewatch_available else "unavailable",
                        "bathymetry": "available" if "bathymetry" in intel_sources else ("not_applicable" if marker_class == "inland_freshwater" else "unavailable"),
                    },
                    "weather": {
                        "air_temp_c": env.get("air_temp_c"),
                        "wind_speed_kt": env.get("wind_speed_kt"),
                        "wind_direction_deg": env.get("wind_direction_deg"),
                        "cloud_cover_pct": env.get("cloud_cover_pct"),
                        "pressure_mb": env.get("pressure_mb"),
                    },
                    "ocean": {
                        "sst_c": env.get("water_temp_c"),
                        "current_speed_kt": env.get("current_speed_kt"),
                        "current_direction_deg": env.get("current_direction_deg"),
                        "chlorophyll_mg_m3": env.get("chlorophyll_mg_m3"),
                    } if bait_applicable else {},
                    "waves": {
                        "wave_height_ft": env.get("wave_feet"),
                        "swell_height_ft": env.get("swell_height_ft"),
                        "swell_period_s": env.get("swell_period_s"),
                        "swell_direction_deg": env.get("swell_direction_deg"),
                    } if bait_applicable else {},
                    "bathymetry": {
                        "depth_m": env.get("depth_m"),
                    } if marker_class != "inland_freshwater" else {"depth_m": None, "status": "not_applicable"},
                    "derived": True,
                    "intel_tier": intel_tier,
                    "intel_sources": intel_sources,
                    "missing_inputs": missing_inputs,
                },
                "quick_snapshot": {
                    "marker_class": marker_class,
                    "bait_applicable": bait_applicable,
                    "intel_tier": intel_tier,
                    "intel_sources": intel_sources,
                    "missing_inputs": missing_inputs,
                    "intel_confidence": "high" if intel_tier == "enhanced" else "medium",
                    "wavewatch_available": wavewatch_available,
                    "bait_score": bait.get("bait_score"),
                    "bait_intensity": bait.get("intensity"),
                    "weather": {
                        "air_temp_c": env.get("air_temp_c"),
                        "wind_speed_kt": env.get("wind_speed_kt"),
                        "cloud_cover_pct": env.get("cloud_cover_pct"),
                        "pressure_mb": env.get("pressure_mb"),
                        "source_tier": env_meta.get("source_tier"),
                    },
                    "ocean": {
                        "sst_c": env.get("water_temp_c"),
                        "current_speed_kt": env.get("current_speed_kt"),
                        "wave_height_ft": env.get("wave_feet"),
                        "swell_height_ft": env.get("swell_height_ft"),
                        "swell_period_s": env.get("swell_period_s"),
                        "chlorophyll_mg_m3": env.get("chlorophyll_mg_m3"),
                        "depth_m": env.get("depth_m"),
                    } if bait_applicable else {},
                },
                "intel_tier": intel_tier,
                "intel_sources": intel_sources,
                "missing_inputs": missing_inputs,
                "intel_confidence": "high" if intel_tier == "enhanced" else "medium",
                "wavewatch_available": wavewatch_available,
            })
        return {
            "ok": err is None,
            "source": "fish_csv",
            "degraded": bool(err),
            "warm": self._warm_ready,
            "stale": False,
            "fallback_reason": "csv_error" if err else None,
            "items": items,
            "count": len(items),
            "timestamp": int(time.time() * 1000),
            "ts": int(time.time() * 1000),
            "error": err,
            "entity_type": "location_markers",
            "derived": False,
        }

    def _read_csv_markers(self) -> tuple[list[dict[str, Any]], str | None]:
        csv_path = self._fish_csv_path()
        if not csv_path.exists():
            return [], f"missing fish CSV: {csv_path}"
        points: list[dict[str, Any]] = []
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for i, row in enumerate(reader):
                    if not row:
                        continue
                    lat_raw = row.get("lat") or row.get("latitude") or row.get("Lat") or row.get("Latitude")
                    lon_raw = row.get("lon") or row.get("lng") or row.get("longitude") or row.get("Lon") or row.get("Longitude")
                    if lat_raw is None or lon_raw is None:
                        continue
                    try:
                        lat = float(str(lat_raw).strip())
                        lon = float(str(lon_raw).strip())
                    except Exception:
                        continue
                    name = (row.get("name") or row.get("location") or row.get("label") or f"Location {i + 1}").strip()
                    location_key = self._normalize_location_key((row.get("location_key") or name or str(i + 1)))
                    point = {
                        "id": (row.get("id") or row.get("locationId") or str(i + 1)).strip(),
                        "location_key": location_key or f"loc-{i+1}",
                        "name": name,
                        "lat": lat,
                        "lon": lon,
                        "meta": {
                            k: v
                            for k, v in row.items()
                            if k
                            not in {
                                "lat", "latitude", "Lat", "Latitude",
                                "lon", "lng", "longitude", "Lon", "Longitude",
                                "name", "location", "label", "id", "locationId", "location_key",
                            }
                        },
                    }
                    # Attach sampled environment from locked real-source stack.
                    point.update(self._build_bait_intel(point, self._now_ms()))
                    points.append(point)
            return points, None
        except Exception as exc:
            return [], f"failed to parse fish CSV: {exc}"

    def locations_fast(self, bbox: dict[str, float] | None, budget_ms: int = 1800) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        started = time.time()
        key = self._cache_key("locations", vp)
        cached = self._cache.get(key)
        if cached:
            return {"ok": True, "source": "fish_csv_cache", "degraded": False, "warm": self._warm_ready, "stale": False, "fallback_reason": None, "items": cached.get("items") or [], "count": len(cached.get("items") or []), "timestamp": int(time.time() * 1000), "ts": cached.get("ts") or int(time.time() * 1000), "latency_ms": round((time.time() - started) * 1000, 2), "entity_type": "location_markers", "derived": False}

        payload = self._csv_locations(vp.as_dict())
        self._cache.set(key, {"items": payload.get("items") or [], "count": payload.get("count") or 0, "ts": payload.get("ts")})
        payload.update({"latency_ms": round((time.time() - started) * 1000, 2)})
        return payload

    def bait_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        cached = self._cache.get(self._cache_key("bait", vp))
        if isinstance(cached, dict) and (cached.get("polygons") is not None or cached.get("bait_score") is not None):
            return {
                "ok": True,
                "source": cached.get("source", "shared_ocean_cache"),
                "degraded": bool(cached.get("degraded")),
                "bbox": vp.as_bbox(),
                "count": cached.get("count", 0),
                "bait": {"status": "ready", "source": cached.get("source", "shared_ocean_cache"), "polygons": cached.get("polygons") or []},
                "bait_score": cached.get("bait_score") or [],
                "timestamp": int(time.time() * 1000),
                "ts": cached.get("ts") or int(time.time() * 1000),
                "sources": (self._cache.get(self._cache_key("ocean", vp)) or {}).get("sources"),
                "warm": self._warm_ready,
                "stale": False,
                "entity_type": "bait",
                "derived": True,
                "cache": "hit",
            }
        ocean = self.shared_ocean_payload(vp.as_dict())
        scored = self.bait_service.score(ocean, vp)
        log.info("bait derived polygons=%s viewport=%s", len(scored.get("polygons") or []), vp.as_bbox())
        payload = {
            "ok": True,
            "source": scored.get("source", "shared_ocean"),
            "degraded": bool(scored.get("degraded")) or bool(ocean.get("degraded", {}).get("chlorophyll")),
            "bbox": vp.as_bbox(),
            "count": scored.get("count", 0),
            "bait": {"status": "ready", "source": scored.get("source", "shared_ocean"), "polygons": scored.get("polygons") or []},
            "bait_score": scored.get("bait_score") or [],
            "timestamp": ocean.get("timestamp"),
            "ts": ocean.get("ts"),
            "sources": ocean.get("sources"),
            "warm": self._warm_ready,
            "stale": False,
            "entity_type": "bait",
            "derived": True,
            "cache": "miss",
        }
        self._cache.set(self._cache_key("bait", vp), scored)
        return payload

    def boats_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        cached = self._cache.get(self._cache_key("boats", vp))
        if isinstance(cached, dict) and isinstance(cached.get("boats"), list):
            return {
                "ok": True,
                "source": "shared_ocean_cache",
                "degraded": False,
                "boats": cached.get("boats") or [],
                "count": len(cached.get("boats") or []),
                "timestamp": int(time.time() * 1000),
                "ts": cached.get("ts") or int(time.time() * 1000),
                "sources": (self._cache.get(self._cache_key("ocean", vp)) or {}).get("sources"),
                "warm": self._warm_ready,
                "stale": False,
                "entity_type": "boat",
                "derived": True,
                "cache": "hit",
            }
        ocean = self.shared_ocean_payload(vp.as_dict())
        boats = self.boat_service.agents(ocean, vp, count=12)
        log.info("boats derived count=%s viewport=%s", len(boats), vp.as_bbox())
        payload = {
            "ok": True,
            "source": "shared_ocean",
            "degraded": bool(ocean.get("degraded")),
            "boats": boats,
            "count": len(boats),
            "timestamp": ocean.get("timestamp"),
            "ts": ocean.get("ts"),
            "sources": ocean.get("sources"),
            "warm": self._warm_ready,
            "stale": False,
            "entity_type": "boat",
            "derived": True,
            "cache": "miss",
        }
        self._cache.set(self._cache_key("boats", vp), payload)
        return payload

    def frame_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        started = time.time()
        vp = canonicalize_viewport(bbox)
        weather_started = time.time()
        weather = self._safe_weather_payload(vp)
        weather_ms = (time.time() - weather_started) * 1000
        clouds_started = time.time()
        payload_state = str(weather.get("payload_state") or "").lower()
        if payload_state in {"unavailable", "degraded"}:
            clouds = {"cloud_layers": [], "convective": {}, "stale": True, "source": "fast_degraded"}
        else:
            clouds = self.cloud_tiles_payload(vp.as_dict())
        clouds_ms = (time.time() - clouds_started) * 1000
        ocean_started = time.time()
        ocean = self.shared_ocean_payload(vp.as_dict())
        ocean_ms = (time.time() - ocean_started) * 1000
        fish_started = time.time()
        fish_payload = self.fish_from_ocean(vp.as_dict())
        fish_items = fish_payload.get("items") or []
        fish_ms = (time.time() - fish_started) * 1000
        bait_started = time.time()
        bait = self.bait_from_ocean(vp.as_dict())
        bait_ms = (time.time() - bait_started) * 1000
        boats_started = time.time()
        boats_payload = self.boats_from_ocean(vp.as_dict())
        boats = boats_payload.get("boats") or []
        boats_ms = (time.time() - boats_started) * 1000
        log.info("frame refresh viewport=%s fish=%s bait=%s boats=%s", vp.as_bbox(), len(fish_items), len(bait.get("polygons") or []), len(boats))
        log.info(
            "[gfs-perf] frame viewport=%s weather_ms=%.2f clouds_ms=%.2f ocean_ms=%.2f fish_ms=%.2f bait_ms=%.2f boats_ms=%.2f total_ms=%.2f",
            vp.as_bbox(),
            weather_ms,
            clouds_ms,
            ocean_ms,
            fish_ms,
            bait_ms,
            boats_ms,
            (time.time() - started) * 1000,
        )
        self._last_frame_latency_ms = (time.time() - started) * 1000
        self._last_frame_cache_state = f"ocean:{self._last_ocean_cache_state}|fish:{fish_payload.get('cache')}|bait:{bait.get('cache')}|boats:{boats_payload.get('cache')}"
        return {
            "ok": True,
            "bbox": vp.as_bbox(),
            "weather": weather,
            "clouds": clouds,
            "ocean": ocean,
            "fish": {"items": fish_items, "count": len(fish_items), "source": fish_payload.get("source", "shared_ocean"), "cache": fish_payload.get("cache")},
            "baitBase": {"ok": True, "source": bait.get("source", "shared_ocean"), "degraded": bait.get("degraded", False), "bait_score": bait.get("bait_score") or [], "bait": {"status": "ready", "source": bait.get("source", "shared_ocean"), "polygons": (bait.get("bait") or {}).get("polygons") or bait.get("polygons") or []}, "cache": bait.get("cache")},
            "baitAdvanced": {"ok": True, "source": bait.get("source", "shared_ocean"), "degraded": bait.get("degraded", False), "bait_score": bait.get("bait_score") or [], "bait": {"status": "ready", "source": bait.get("source", "shared_ocean"), "polygons": (bait.get("bait") or {}).get("polygons") or bait.get("polygons") or []}, "cache": bait.get("cache")},
            "boats": {"boats": boats, "count": len(boats), "source": "shared_ocean"},
            "recursiveGrid": {"bbox": vp.as_bbox(), "polygons": {"boater": [{"coordinates": poly["coordinates"]} for poly in (bait.get("polygons") or [])]}},
            "debug": {
                "cycle": ocean.get("cycle"),
                "sources": ocean.get("sources"),
                "degraded": ocean.get("degraded"),
                "counts": {"fish": len(fish_items), "bait": len(bait.get("polygons") or []), "boats": len(boats)},
                "warm": self._warm_ready,
            },
        }

    def warm_status(self) -> dict[str, Any]:
        return {
            "ready": self._warm_ready,
            "started": self._warm_started,
            "error": self._warm_error,
            "warmed_at": self._warm_at,
            "cache": self._cache.stats(),
        }

    def websocket_status_payload(self) -> dict[str, Any]:
        ocean = self.shared_ocean_payload(None)
        degraded_details = ocean.get("degraded") or {}
        degraded_flag = any(bool(v) for v in degraded_details.values()) if isinstance(degraded_details, dict) else bool(degraded_details)
        return {
            "type": "status",
            "degraded": degraded_flag,
            "degraded_details": degraded_details,
            "sources": ocean.get("sources"),
            "cycle": ocean.get("cycle"),
            "warm": self.warm_status(),
        }

    def mark_gfs_ws_registered(self, registered: bool = True) -> None:
        self._gfs_ws_registered = bool(registered)

    def mark_gfs_ws_open(self) -> None:
        self._gfs_ws_active_clients = max(0, int(self._gfs_ws_active_clients) + 1)
        self._gfs_ws_last_open_ts = int(time.time() * 1000)

    def mark_gfs_ws_close(self) -> None:
        self._gfs_ws_active_clients = max(0, int(self._gfs_ws_active_clients) - 1)

    def mark_gfs_ws_exception(self, exc: Exception | str) -> None:
        self._gfs_ws_last_exception = str(exc)

    def health_payload(self) -> dict[str, Any]:
        payload = super().health_payload()
        csv, csv_err = self.load_fish()
        payload["websocket"] = {
            "gfs_route_registered": bool(self._gfs_ws_registered),
            "gfs_active_clients": int(self._gfs_ws_active_clients),
            "gfs_last_exception": self._gfs_ws_last_exception,
            "gfs_last_open_ts": self._gfs_ws_last_open_ts,
        }
        try:
            ocean = self.shared_ocean_payload(None)
        except Exception as exc:
            payload["ocean"] = {
                "currents": {
                    "selected_source": "unknown",
                    "degraded": True,
                    "primary": {
                        "name": "hycom",
                        "attempted": True,
                        "ok": False,
                        "reason": "ocean_health_failed",
                        "detail": str(exc),
                    },
                }
            }
            return payload
        currents_diag = (ocean.get("diagnostics") or {}).get("currents") or {}
        payload["ocean"] = {
            "currents": {
                "selected_source": (ocean.get("sources") or {}).get("currents"),
                "degraded": bool((ocean.get("degraded") or {}).get("currents")),
                "primary": currents_diag,
            }
        }
        payload["entities"] = {
            "locations": {
                "entity_type": "location_markers",
                "source": "fishloclist.csv",
                "derived": False,
                "ok": csv_err is None,
                "count": int(len(csv) if isinstance(csv, list) else 0),
                "error": csv_err,
            },
            "fish_intelligence": {
                "entity_type": "fish_intelligence",
                "source": "shared_ocean",
                "derived": True,
                "ok": bool((ocean.get("fields") or {}).get("current_u")),
                "currents_source": (ocean.get("sources") or {}).get("currents"),
                "degraded": bool((ocean.get("degraded") or {}).get("currents")),
            },
        }
        payload["performance"] = {
            "prewarm_duration_ms": self._prewarm_duration_ms,
            "last_ocean_latency_ms": self._last_ocean_latency_ms,
            "last_ocean_cache_state": self._last_ocean_cache_state,
            "last_frame_latency_ms": self._last_frame_latency_ms,
            "last_frame_cache_state": self._last_frame_cache_state,
            "cache_stats": self._cache.stats(),
        }
        return payload

    def diagnostics_payload(self) -> dict[str, Any]:
        out = super().diagnostics_payload()
        out["contract"] = {
            "locations_endpoint": {"path": "/gfs/api/locations", "entity_type": "location_markers", "derived": False, "source": "fishloclist.csv"},
            "fish_endpoint": {"path": "/gfs/api/fish", "entity_type": "fish_intelligence", "derived": True, "source": "shared_ocean"},
        }
        return out
