from __future__ import annotations

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
        while len(boats) < count and guard < 2000:
            guard += 1
            yi = (yi + 3) % len(lats)
            xi = (xi + 5) % len(lons)
            lat, lon = lats[yi], lons[xi]
            depth = sample_grid(fields.get("depth_m"), viewport, lat, lon)
            cur_u = sample_grid(fields.get("current_u"), viewport, lat, lon)
            cur_v = sample_grid(fields.get("current_v"), viewport, lat, lon)
            wave = sample_grid(fields.get("wave_height_m"), viewport, lat, lon)
            if depth < 30.0:
                continue
            speed = (cur_u**2 + cur_v**2) ** 0.5
            if speed < 0.08:
                continue
            state = "green" if wave < 1.5 else "yellow" if wave < 2.8 else "red"
            boats.append({
                "id": f"boat-{len(boats)+1}",
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "heading_deg": round(vector_heading_deg(cur_u, cur_v), 1),
                "state": state,
                "wave_m": round(float(wave), 2),
                "current_mps": round(float(speed), 2),
                "hover": f"Sea {state}; wave {wave:.2f}m; current {speed:.2f}m/s",
            })
        return boats
