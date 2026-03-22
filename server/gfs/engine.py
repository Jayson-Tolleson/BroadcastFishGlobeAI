from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

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

    def shared_ocean_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        weather = self._safe_weather_payload(vp)
        return self.ocean_service.build_shared_state(vp, weather)

    def fish_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        ocean = self.shared_ocean_payload(vp.as_dict())
        items = self.fish_service.score_markers(ocean, vp)
        return {
            "ok": True,
            "source": "shared_ocean",
            "degraded": bool(ocean.get("degraded")),
            "items": items,
            "count": len(items),
            "timestamp": ocean.get("timestamp"),
            "ts": ocean.get("ts"),
            "sources": ocean.get("sources"),
        }

    def bait_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        ocean = self.shared_ocean_payload(vp.as_dict())
        scored = self.bait_service.score(ocean, vp)
        return {
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
        }

    def boats_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        ocean = self.shared_ocean_payload(vp.as_dict())
        boats = self.boat_service.agents(ocean, vp, count=12)
        return {
            "ok": True,
            "source": "shared_ocean",
            "degraded": bool(ocean.get("degraded")),
            "boats": boats,
            "count": len(boats),
            "timestamp": ocean.get("timestamp"),
            "ts": ocean.get("ts"),
            "sources": ocean.get("sources"),
        }

    def frame_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        weather = self._safe_weather_payload(vp)
        clouds = self.cloud_tiles_payload(vp.as_dict())
        ocean = self.ocean_service.build_shared_state(vp, weather)
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
            },
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
        }
