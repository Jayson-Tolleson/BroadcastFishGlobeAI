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

    @staticmethod
    def _usable_vectors(grid: list[list[float]] | None) -> bool:
        if not isinstance(grid, list) or not grid:
            return False
        for row in grid:
            if not isinstance(row, list):
                continue
            for val in row:
                try:
                    if float(val) == float(val):
                        return True
                except Exception:
                    continue
        return False

    @staticmethod
    def _padded_bbox(bbox: BBox, pad_deg: float) -> BBox:
        return BBox(
            west=max(-179.9, bbox.west - pad_deg),
            south=max(-89.9, bbox.south - pad_deg),
            east=min(179.9, bbox.east + pad_deg),
            north=min(89.9, bbox.north + pad_deg),
        )

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any] | None:
        _ = weather
        bbox = BBox(
            west=float(viewport.get("west", -180.0)),
            south=float(viewport.get("south", -90.0)),
            east=float(viewport.get("east", 180.0)),
            north=float(viewport.get("north", 90.0)),
        )
        stride = int(viewport.get("stride") or 1)
        attempts = [
            {"stride": max(1, stride), "padded": False, "pad": 0.0},
            {"stride": 2, "padded": False, "pad": 0.0},
            {"stride": 4, "padded": False, "pad": 0.0},
            {"stride": 4, "padded": True, "pad": 0.2},
        ]
        for idx, attempt in enumerate(attempts, start=1):
            use_bbox = self._padded_bbox(bbox, float(attempt["pad"])) if attempt["padded"] else bbox
            try:
                subset, _ = self._provider._fetch_subset_sync(bbox=use_bbox, stride=int(attempt["stride"]), valid_time=None)  # noqa: SLF001
            except Exception as exc:
                log.warning("[gfs/ocean] hycom attempt=%s stride=%s padded=%s result=error err=%s", idx, attempt["stride"], attempt["padded"], exc)
                continue
            u = subset.get("current_u") if isinstance(subset, dict) else None
            v = subset.get("current_v") if isinstance(subset, dict) else None
            if not (isinstance(u, list) and isinstance(v, list) and u and v and self._usable_vectors(u) and self._usable_vectors(v)):
                log.warning("[gfs/ocean] hycom attempt=%s stride=%s padded=%s result=empty_or_unusable", idx, attempt["stride"], attempt["padded"])
                continue
            ny = len(u)
            nx = len(u[0]) if ny and isinstance(u[0], list) else 0
            log.info("[gfs/ocean] hycom attempt=%s stride=%s padded=%s result=success shape=%sx%s", idx, attempt["stride"], attempt["padded"], ny, nx)
            return {
                "u": u,
                "v": v,
                "source": "hycom",
                "degraded": False,
                "ok": True,
                "source_status": "available",
                "metadata": subset.get("source_meta") if isinstance(subset, dict) else {},
            }
        return None
