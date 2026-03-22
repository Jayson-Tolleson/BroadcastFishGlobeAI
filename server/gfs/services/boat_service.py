from __future__ import annotations

import math
from typing import Any

from server.gfs.canonical import sample_grid, vector_heading_deg


class BoatService:
    def agents(self, ocean: dict[str, Any], viewport, count: int = 12) -> list[dict[str, Any]]:
        fields = ocean.get("fields") or {}
        lats = (ocean.get("grid") or {}).get("lats") or []
        lons = (ocean.get("grid") or {}).get("lons") or []
        boats: list[dict[str, Any]] = []
        if not lats or not lons:
            return boats
        yi = 0
        xi = 0
        guard = 0
        while len(boats) < count and guard < 3000:
            guard += 1
            yi = (yi + 3) % len(lats)
            xi = (xi + 5) % len(lons)
            lat, lon = lats[yi], lons[xi]
            depth = sample_grid(fields.get("depth_m"), viewport, lat, lon)
            cur_u = sample_grid(fields.get("current_u"), viewport, lat, lon)
            cur_v = sample_grid(fields.get("current_v"), viewport, lat, lon)
            wave_m = sample_grid(fields.get("wave_height_m"), viewport, lat, lon)
            if not math.isfinite(depth) or depth < 30.0:
                continue
            speed_mps = (cur_u**2 + cur_v**2) ** 0.5
            if not math.isfinite(speed_mps) or speed_mps < 0.08:
                continue
            safety = "green" if wave_m < 1.5 else "yellow" if wave_m < 2.8 else "red"
            boats.append({
                "id": f"boat-{len(boats)+1}",
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "heading_deg": round(vector_heading_deg(cur_u, cur_v), 1),
                "safety": safety,
                "state": safety,
                "current_kts": round(float(speed_mps) * 1.94384, 2),
                "wave_height_ft": round(float(wave_m) * 3.28084, 2),
                "hover": f"Sea {safety}; wave {wave_m*3.28084:.1f}ft; current {speed_mps*1.94384:.1f}kts",
            })
        return boats
