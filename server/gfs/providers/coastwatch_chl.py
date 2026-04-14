from __future__ import annotations

import logging
from typing import Any

from server.gfs.models import BBox
from server.gfs.providers.coastwatch import CoastwatchProvider

log = logging.getLogger("server.gfs.provider.coastwatch_chl")


class CoastwatchChlProvider:
    source_name = "coastwatch"

    def __init__(self) -> None:
        self._provider = CoastwatchProvider()

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> list[list[float]] | None:
        _ = weather
        bbox = BBox(
            west=float(viewport.get("west", -180.0)),
            south=float(viewport.get("south", -90.0)),
            east=float(viewport.get("east", 180.0)),
            north=float(viewport.get("north", 90.0)),
        )
        stride = int(viewport.get("stride") or 1)
        log.info("[gfs/upstream] source=coastwatch request_recipe=erddap_griddap_subset bbox=%s stride=%s", viewport, stride)
        try:
            subset, _ = self._provider._fetch_subset_sync(bbox=bbox, stride=stride, valid_time=None)  # noqa: SLF001
        except Exception as exc:
            log.warning("[gfs/upstream] source=coastwatch status=error bbox=%s err=%s", viewport, exc)
            return None
        grid = subset.get("chlorophyll") if isinstance(subset, dict) else None
        if not isinstance(grid, list) or not grid:
            return None
        return grid
