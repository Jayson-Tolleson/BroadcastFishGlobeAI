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
        })
        return ParsedIntent(BBox(vp.west, vp.south, vp.east, vp.north))

    async def weather_payload(self, intent: ParsedIntent) -> dict[str, Any]:
        return self.generate_weather_payload({"west": intent.bbox.west, "south": intent.bbox.south, "east": intent.bbox.east, "north": intent.bbox.north})

    def shared_ocean_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        weather = self.generate_weather_payload(vp.as_dict())
        return self.ocean_service.build_shared_state(vp, weather)

    def fish_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        ocean = self.shared_ocean_payload(vp.as_dict())
        items = self.fish_service.score_markers(ocean, vp)
        return {"ok": True, "items": items, "count": len(items), "ts": ocean.get("ts"), "sources": ocean.get("sources")}

    def bait_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        ocean = self.shared_ocean_payload(vp.as_dict())
        scored = self.bait_service.score(ocean, vp)
        return {"ok": True, "bbox": vp.as_bbox(), "bait": {"status": "ready", "source": "shared_ocean", "polygons": scored.get("polygons") or []}, "bait_score": scored.get("bait_score") or [], "ts": ocean.get("ts"), "sources": ocean.get("sources")}

    def boats_from_ocean(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        ocean = self.shared_ocean_payload(vp.as_dict())
        boats = self.boat_service.agents(ocean, vp, count=12)
        return {"ok": True, "boats": boats, "count": len(boats), "ts": ocean.get("ts")}

    def frame_payload(self, bbox: dict[str, float] | None) -> dict[str, Any]:
        vp = canonicalize_viewport(bbox)
        weather = self.generate_weather_payload(vp.as_dict())
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
            "fish": {"items": fish_items},
            "baitBase": {"ok": True, "bait_score": bait.get("bait_score") or [], "bait": {"status": "ready", "polygons": bait.get("polygons") or []}},
            "baitAdvanced": {"ok": True, "bait_score": bait.get("bait_score") or [], "bait": {"status": "ready", "source": "shared_ocean", "polygons": bait.get("polygons") or []}},
            "boats": {"boats": boats},
            "recursiveGrid": {"bbox": vp.as_bbox(), "polygons": {"boater": [{"coordinates": poly["coordinates"]} for poly in (bait.get("polygons") or [])]}},
            "debug": {
                "cycle": ocean.get("cycle"),
                "sources": ocean.get("sources"),
                "degraded": ocean.get("degraded"),
                "counts": {"fish": len(fish_items), "bait": len(bait.get("polygons") or []), "boats": len(boats)},
            },
        }
