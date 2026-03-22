from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .viewport import CanonicalViewport


@dataclass(frozen=True)
class CanonicalGrid:
    rows: int
    cols: int
    lats: list[float]
    lons: list[float]


def build_canonical_grid(viewport: CanonicalViewport, *, cell_deg: float = 0.25) -> CanonicalGrid:
    lat_span = max(0.25, viewport.north - viewport.south)
    lon_span = max(0.25, viewport.east - viewport.west)
    rows = max(1, int(round(lat_span / cell_deg)))
    cols = max(1, int(round(lon_span / cell_deg)))
    lats = [viewport.south + ((iy + 0.5) / rows) * lat_span for iy in range(rows)]
    lons = [viewport.west + ((ix + 0.5) / cols) * lon_span for ix in range(cols)]
    return CanonicalGrid(rows=rows, cols=cols, lats=lats, lons=lons)


def sample_grid(grid: list[list[float]] | None, vp: CanonicalViewport, lat: float, lon: float) -> float:
    if not isinstance(grid, list) or not grid or not isinstance(grid[0], list):
        return float("nan")
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if rows < 1 or cols < 1:
        return float("nan")
    yi = max(0, min(rows - 1, int(((lat - vp.south) / ((vp.north - vp.south) or 1.0)) * rows)))
    xi = max(0, min(cols - 1, int(((lon - vp.west) / ((vp.east - vp.west) or 1.0)) * cols)))
    try:
        return float(grid[yi][xi])
    except Exception:
        return float("nan")


def vector_heading_deg(u: float, v: float) -> float:
    if not math.isfinite(u) or not math.isfinite(v):
        return 0.0
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


def vector_speed(u: float, v: float) -> float:
    if not math.isfinite(u) or not math.isfinite(v):
        return 0.0
    return math.hypot(u, v)


def flatten_grid(name: str, grid: list[list[float]] | None) -> dict[str, Any]:
    if not isinstance(grid, list) or not grid:
        return {"name": name, "rows": 0, "cols": 0, "values": []}
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    vals: list[float] = []
    for row in grid:
        if not isinstance(row, list):
            continue
        vals.extend(float(x) if isinstance(x, (int, float)) else 0.0 for x in row)
    return {"name": name, "rows": rows, "cols": cols, "values": vals}
