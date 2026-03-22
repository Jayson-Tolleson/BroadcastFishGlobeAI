from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.gfs.models import BBox
from server.gfs_service import GFSService


@dataclass(frozen=True)
class ParsedIntent:
    bbox: BBox


class GfsEngine(GFSService):
    def __init__(self, config: Any | None = None, static_dir: str | None = None) -> None:
        super().__init__(static_dir or "static")
        self.config_obj = config

    def parse_intent(self, args: Any) -> ParsedIntent:
        raw_bbox = None
        if args is not None:
            getter = getattr(args, "get", None)
            if callable(getter):
                raw_bbox = getter("bbox")
        if isinstance(raw_bbox, str) and raw_bbox.strip():
            try:
                west, south, east, north = [float(part.strip()) for part in raw_bbox.split(",")]
                return ParsedIntent(BBox(west, south, east, north))
            except Exception:
                pass
        bbox = self._default_bbox()
        return ParsedIntent(BBox(bbox["west"], bbox["south"], bbox["east"], bbox["north"]))

    async def weather_payload(self, intent: ParsedIntent) -> dict[str, Any]:
        return self.generate_weather_payload({"west": intent.bbox.west, "south": intent.bbox.south, "east": intent.bbox.east, "north": intent.bbox.north})
