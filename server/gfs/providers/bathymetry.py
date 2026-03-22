from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BathymetryProvider:
    _cache_key: str | None = None
    _cache_grid: list[list[float]] | None = None

    def fetch(self, rows: int, cols: int, viewport: dict[str, float]) -> tuple[list[list[float]], bool]:
        key = f"{rows}x{cols}:{viewport.get('west')}:{viewport.get('south')}:{viewport.get('east')}:{viewport.get('north')}"
        if self._cache_key == key and self._cache_grid is not None:
            return self._cache_grid, False
        depth: list[list[float]] = []
        for iy in range(rows):
            row: list[float] = []
            lat_frac = iy / max(1, rows - 1)
            for ix in range(cols):
                lon_frac = ix / max(1, cols - 1)
                edge = min(lat_frac, 1 - lat_frac, lon_frac, 1 - lon_frac)
                row.append(max(0.0, edge * 4200.0))
            depth.append(row)
        self._cache_key = key
        self._cache_grid = depth
        return depth, False
