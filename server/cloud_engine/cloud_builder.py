from __future__ import annotations

from typing import Any

def _to_f(val: Any) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def build_cloud_clusters(
    lat: Any,
    lon: Any,
    z: int,
    cloud_low: Any,
    cloud_mid: Any,
    cloud_high: Any,
    cloud_total: Any,
    precip_rate: Any,
    wind_u: Any,
    wind_v: Any,
) -> list[dict[str, Any]]:
    """Create LOD cloud polygons with vertical profile metadata."""
    stride = 12 if z < 3 else 6 if z < 6 else 3
    out: list[dict[str, Any]] = []
    grid = cloud_total if cloud_total is not None else cloud_low
    if grid is None:
        return []
    h, w = grid.shape[0], grid.shape[1]

    for y in range(0, h - 1, stride):
        for x in range(0, w - 1, stride):
            total_val = _to_f(grid[y, x])
            if total_val < 15.0:
                continue

            out.append({
                "id": f"cloud-{y}-{x}",
                "lat": _to_f(lat[y, x]),
                "lon": _to_f(lon[y, x]),
                "cloud_low": _to_f(cloud_low[y, x] if cloud_low is not None else 0.0),
                "cloud_mid": _to_f(cloud_mid[y, x] if cloud_mid is not None else 0.0),
                "cloud_high": _to_f(cloud_high[y, x] if cloud_high is not None else 0.0),
                "cloud_total": total_val,
                "precip_rate": _to_f(precip_rate[y, x] if precip_rate is not None else 0.0),
                "wind_u": _to_f(wind_u[y, x] if wind_u is not None else 0.0),
                "wind_v": _to_f(wind_v[y, x] if wind_v is not None else 0.0),
            })
    return out
