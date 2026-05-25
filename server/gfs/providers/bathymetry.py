from __future__ import annotations

from dataclasses import dataclass
import logging
import math

log = logging.getLogger("server.gfs.provider.bathymetry")


@dataclass
class BathymetryProvider:
    _cache_key: str | None = None
    _cache_grid: list[list[float]] | None = None

    def fetch(self, rows: int, cols: int, viewport: dict[str, float]) -> tuple[list[list[float]], bool]:
        key = f"{rows}x{cols}:{viewport.get('west')}:{viewport.get('south')}:{viewport.get('east')}:{viewport.get('north')}"
        if self._cache_key == key and self._cache_grid is not None:
            log.info("[gfs/upstream] source=bathymetry request_recipe=cached_grid bbox=%s rows=%s cols=%s", viewport, rows, cols)
            return self._cache_grid, False
        depth: list[list[float]] = []
        west = float(viewport.get("west", -180.0))
        east = float(viewport.get("east", 180.0))
        south = float(viewport.get("south", -90.0))
        north = float(viewport.get("north", 90.0))
        for iy in range(rows):
            row: list[float] = []
            for ix in range(cols):
                lat = south + ((iy + 0.5) / max(1, rows)) * (north - south)
                lon = west + ((ix + 0.5) / max(1, cols)) * (east - west)
                pseudo = -1200.0 - (2800.0 * (0.5 + 0.5 * math.sin(math.radians(lat * 1.3) + math.radians(lon * 0.8))))
                row.append(float(pseudo))
            depth.append(row)
        log.info("[gfs/upstream] source=bathymetry request_recipe=deterministic_static_model bbox=%s rows=%s cols=%s", viewport, rows, cols)
        self._cache_key = key
        self._cache_grid = depth
        return depth, False
