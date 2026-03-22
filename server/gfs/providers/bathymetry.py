from __future__ import annotations

from typing import Any


def build_depth_grid(rows: int, cols: int, viewport: dict[str, float]) -> list[list[float]]:
    depth: list[list[float]] = []
    for iy in range(rows):
        row: list[float] = []
        lat_frac = iy / max(1, rows - 1)
        for ix in range(cols):
            lon_frac = ix / max(1, cols - 1)
            edge = min(lat_frac, 1 - lat_frac, lon_frac, 1 - lon_frac)
            row.append(max(5.0, (edge * 4200.0)))
        depth.append(row)
    return depth
