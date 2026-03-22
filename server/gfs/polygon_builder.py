from __future__ import annotations

import math
from typing import Any


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return number


def build_bait_ocean_field_v1(
    *,
    bbox: list[float],
    cell_size_deg: float,
    source_time: str | None,
    quality: str,
    ocean: dict[str, Any],
    max_count: int = 5000,
) -> dict[str, Any]:
    west, south, east, north = [float(v) for v in bbox]
    sst = ocean.get("sst") or []
    chl = ocean.get("chlorophyll") or []
    cu = ocean.get("current_u") or []
    cv = ocean.get("current_v") or []
    ssh = ocean.get("optional_ssh_anomaly") or []

    rows = len(sst)
    cols = len(sst[0]) if rows and isinstance(sst[0], list) else 0
    fields = {k: [] for k in ["lat", "lon", "sst", "chlorophyll", "current_u", "current_v", "water_color_index", "optional_ssh_anomaly"]}
    count = 0
    for iy in range(rows):
        for ix in range(cols):
            sst_val = sst[iy][ix] if iy < len(sst) and ix < len(sst[iy]) else None
            sst_num = _safe_num(sst_val, default=float("nan"))
            if not math.isfinite(sst_num):
                continue
            if count >= max_count:
                break
            lat = south + ((iy + 0.5) / max(1, rows)) * (north - south)
            lon = west + ((ix + 0.5) / max(1, cols)) * (east - west)
            chl_num = _safe_num(chl[iy][ix] if iy < len(chl) and ix < len(chl[iy]) else 0.0)
            cu_num = _safe_num(cu[iy][ix] if iy < len(cu) and ix < len(cu[iy]) else 0.0)
            cv_num = _safe_num(cv[iy][ix] if iy < len(cv) and ix < len(cv[iy]) else 0.0)
            ssh_num = _safe_num(ssh[iy][ix] if iy < len(ssh) and ix < len(ssh[iy]) else 0.0)
            fields["lat"].append(round(lat, 6))
            fields["lon"].append(round(lon, 6))
            fields["sst"].append(round(sst_num, 6))
            fields["chlorophyll"].append(round(chl_num, 6))
            fields["current_u"].append(round(cu_num, 6))
            fields["current_v"].append(round(cv_num, 6))
            fields["water_color_index"].append(round(chl_num, 6))
            fields["optional_ssh_anomaly"].append(round(ssh_num, 6))
            count += 1
        if count >= max_count:
            break
    return {
        "schema": "bait_ocean_field_v1",
        "bbox": bbox,
        "cell_size_deg": float(cell_size_deg),
        "source_time": source_time,
        "quality": quality,
        "count": count,
        "fields": fields,
    }
