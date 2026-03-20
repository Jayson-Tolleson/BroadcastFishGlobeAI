from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.gfs.models import BBox


@dataclass
class _Intent:
    bbox: BBox


class _AtmosphericProvider:
    async def fetch_subset(self, **_: Any):
        return {}, None


class GfsEngine:
    def __init__(self, *_: Any, **__: Any) -> None:
        self._ws_clients: set[str] = set()
        self.atmospheric = _AtmosphericProvider()

    def parse_intent(self, args: Any) -> _Intent:
        raw = args.get("bbox") if hasattr(args, "get") else None
        if isinstance(raw, str):
            try:
                west, south, east, north = [float(v.strip()) for v in raw.split(",")]
                return _Intent(bbox=BBox(west, south, east, north))
            except Exception:
                pass
        return _Intent(bbox=BBox(-118.6, 32.6, -117.8, 33.4))

    async def weather_payload(self, intent: _Intent) -> dict[str, Any]:
        return {
            "bbox": intent.bbox.as_list(),
            "fields": {},
            "valid_time": None,
        }
