from __future__ import annotations

from dataclasses import dataclass
import logging

log = logging.getLogger("server.gfs.provider.bathymetry")


@dataclass
class BathymetryProvider:
    _cache_key: str | None = None
    _cache_grid: list[list[float]] | None = None

    def fetch(self, rows: int, cols: int, viewport: dict[str, float]) -> tuple[list[list[float]], bool]:
        key = f"{rows}x{cols}:{viewport.get('west')}:{viewport.get('south')}:{viewport.get('east')}:{viewport.get('north')}"
        if self._cache_key == key and self._cache_grid is not None:
            log.info("[gfs/upstream] source=bathymetry request_recipe=cached_grid bbox=%s rows=%s cols=%s", viewport, rows, cols)
            return self._cache_grid, True
        depth: list[list[float]] = []
        for iy in range(rows):
            row: list[float] = []
            for ix in range(cols):
                _ = (iy, ix)
                row.append(float("nan"))
            depth.append(row)
        log.info("[gfs/upstream] source=bathymetry request_recipe=sample_or_nearest_valid bbox=%s rows=%s cols=%s", viewport, rows, cols)
        log.warning("[gfs/upstream] source=bathymetry status=unavailable reason=provider_not_configured sample_mode=none approximated=false masked=true rows=%s cols=%s", rows, cols)
        self._cache_key = key
        self._cache_grid = depth
        return depth, True
