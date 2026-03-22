from __future__ import annotations

import logging
import math
import threading
import time
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
        return canonicalize_viewport({"west": -121.5, "south": 32.5, "east": -117.5, "north": 35.8, "quality": "coarse", "stride": 2})

    def _fallback_weather(self, vp) -> dict[str, Any]:
        rows = max(1, int(round((vp.north - vp.south) / (0.25 * vp.stride))))
        cols = max(1, int(round((vp.east - vp.west) / (0.25 * vp.stride))))
        wind_u = [[0.6 + (ix / max(1, cols - 1)) * 0.2 for ix in range(cols)] for _ in range(rows)]
        wind_v = [[0.3 + (iy / max(1, rows - 1)) * 0.2 for ix in range(cols)] for iy in range(rows)]
        cloud = [[0.35 for _ in range(cols)] for _ in range(rows)]
        return {
            "ok": True,
            "bbox": vp.as_bbox(),
            "valid_time": None,
            "source_time": None,
            "source": "weather_fallback",
            "fields": {
                "wind_u": wind_u,
                "wind_v": wind_v,
                "air_temp": [[289.0 for _ in range(cols)] for _ in range(rows)],
                "cloud_total": cloud,
            },
        }

    def _safe_weather_payload(self, vp) -> dict[str, Any]:
        try:
            return self.generate_weather_payload(vp.as_dict())
        except Exception as exc:
            log.warning("weather payload fallback activated: %s", exc)
            return self._fallback_weather(vp)

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
            self._cache.set(self._cache_key("ocean", vp), ocean)
            self._cache.set(self._cache_key("locations", vp), {"items": fish, "count": len(fish)})
            self._cache.set(self._cache_key("bait", vp), bait)
            self._cache.set(self._cache_key("boats", vp), {"boats": boats, "count": len(boats)})
            self._warm_ready = True
            self._warm_error = None
            self._warm_at = int(time.time() * 1000)
            log.info("gfs prewarm complete latency_ms=%.2f", (time.time() - started) * 1000)
        except Exception as exc:
            self._warm_error = str(exc)
            log.warning("gfs prewarm failed: %s", exc)

    def shared_ocean_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        key = self._cache_key("ocean", vp)
        cached = self._cache.get(key)
        if cached:
            out = {**cached, "warm": self._warm_ready, "stale": False, "cache": "fresh"}
            return out
        weather = self._safe_weather_payload(vp)
        ocean = self.ocean_service.build_shared_state(vp, weather)
        ocean.update({"warm": self._warm_ready, "stale": False, "cache": "miss"})
        self._cache.set(key, ocean)
        return ocean

    def fish_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
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
        }
        self._cache.set(self._cache_key("locations", vp), {"items": items, "count": len(items), "ts": payload["ts"]})
        return payload

    @staticmethod
    def _lon_in_viewport(lon: float, west: float, east: float) -> bool:
        # Handle anti-meridian viewports as wrapped ranges.
        if west <= east:
            return west <= lon <= east
        return lon >= west or lon <= east

    def _csv_locations(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        raw = self.fish_payload()
        items: list[dict[str, Any]] = []
        for item in (raw.get("items") or []):
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
            })
        return {
            "ok": bool(raw.get("ok", True)),
            "source": "fish_csv",
            "degraded": bool(raw.get("error")),
            "warm": self._warm_ready,
            "stale": False,
            "fallback_reason": "csv_error" if raw.get("error") else None,
            "items": items,
            "count": len(items),
            "timestamp": int(time.time() * 1000),
            "ts": raw.get("ts") or int(time.time() * 1000),
            "error": raw.get("error"),
        }

    def locations_fast(self, bbox: dict[str, float] | None, budget_ms: int = 1800) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        started = time.time()
        key = self._cache_key("locations", vp)
        cached = self._cache.get(key)
        if cached:
            return {"ok": True, "source": "fish_csv_cache", "degraded": False, "warm": self._warm_ready, "stale": False, "fallback_reason": None, "items": cached.get("items") or [], "count": len(cached.get("items") or []), "timestamp": int(time.time() * 1000), "ts": cached.get("ts") or int(time.time() * 1000), "latency_ms": round((time.time() - started) * 1000, 2)}

        payload = self._csv_locations(vp.as_dict())
        self._cache.set(key, {"items": payload.get("items") or [], "count": payload.get("count") or 0, "ts": payload.get("ts")})
        payload.update({"latency_ms": round((time.time() - started) * 1000, 2)})
        return payload

    def bait_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
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
        }
        self._cache.set(self._cache_key("bait", vp), scored)
        return payload

    def boats_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
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
        }
        self._cache.set(self._cache_key("boats", vp), payload)
        return payload

    def frame_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        weather = self._safe_weather_payload(vp)
        clouds = self.cloud_tiles_payload(vp.as_dict())
        ocean = self.shared_ocean_payload(vp.as_dict())
        fish_items = self.fish_service.score_markers(ocean, vp)
        bait = self.bait_service.score(ocean, vp)
        boats = self.boat_service.agents(ocean, vp, count=12)
        log.info("frame refresh viewport=%s fish=%s bait=%s boats=%s", vp.as_bbox(), len(fish_items), len(bait.get("polygons") or []), len(boats))
        return {
            "ok": True,
            "bbox": vp.as_bbox(),
            "weather": weather,
            "clouds": clouds,
            "ocean": ocean,
            "fish": {"items": fish_items, "count": len(fish_items), "source": "shared_ocean"},
            "baitBase": {"ok": True, "source": bait.get("source", "shared_ocean"), "degraded": bait.get("degraded", False), "bait_score": bait.get("bait_score") or [], "bait": {"status": "ready", "source": bait.get("source", "shared_ocean"), "polygons": bait.get("polygons") or []}},
            "baitAdvanced": {"ok": True, "source": bait.get("source", "shared_ocean"), "degraded": bait.get("degraded", False), "bait_score": bait.get("bait_score") or [], "bait": {"status": "ready", "source": bait.get("source", "shared_ocean"), "polygons": bait.get("polygons") or []}},
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

    def health_payload(self) -> dict[str, Any]:
        payload = super().health_payload()
        try:
            ocean = self.shared_ocean_payload(None)
        except Exception as exc:
            payload["ocean"] = {
                "currents": {
                    "selected_source": "unknown",
                    "degraded": True,
                    "primary": {
                        "name": "rtofs",
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
        return payload
