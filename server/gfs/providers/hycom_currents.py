from __future__ import annotations

import logging
from typing import Any

from server.gfs.models import BBox
from server.gfs.providers.rtofs import RtofsProvider

log = logging.getLogger("server.gfs.provider.hycom_currents")


class HycomCurrentsProvider:
    source_name = "hycom"

    def __init__(self) -> None:
        self._provider = RtofsProvider()

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any] | None:
        _ = weather
        bbox = BBox(
            west=float(viewport.get("west", -180.0)),
            south=float(viewport.get("south", -90.0)),
            east=float(viewport.get("east", 180.0)),
            north=float(viewport.get("north", 90.0)),
        )
        stride = int(viewport.get("stride") or 1)
        log.info("[gfs/upstream] source=hycom request_recipe=hycom_ncss_subset bbox=%s stride=%s", viewport, stride)
        try:
            subset, _ = self._provider._fetch_subset_sync(bbox=bbox, stride=stride, valid_time=None)  # noqa: SLF001
        except Exception as exc:
            log.warning("[gfs/upstream] source=hycom status=error bbox=%s err=%s", viewport, exc)
            return None
        u = subset.get("current_u") if isinstance(subset, dict) else None
        v = subset.get("current_v") if isinstance(subset, dict) else None
        if not isinstance(u, list) or not isinstance(v, list) or not u or not v:
            return None
        return {
            "u": u,
            "v": v,
            "source": "hycom",
            "degraded": False,
            "ok": True,
            "source_status": "available",
            "metadata": subset.get("source_meta") if isinstance(subset, dict) else {},
        }
