from __future__ import annotations

from typing import Any

from server.gfs.canonical import sample_grid


class BaitService:
    def score(self, ocean: dict[str, Any], viewport) -> dict[str, Any]:
        fields = ocean.get("fields") or {}
        lats = (ocean.get("grid") or {}).get("lats") or []
        lons = (ocean.get("grid") or {}).get("lons") or []
        points: list[dict[str, Any]] = []
        if not lats or not lons:
            return {"bait_score": points, "polygons": [], "source": "shared_ocean", "degraded": True}
        for yi in range(0, len(lats), max(1, len(lats) // 5)):
            for xi in range(0, len(lons), max(1, len(lons) // 5)):
                lat, lon = lats[yi], lons[xi]
                depth = sample_grid(fields.get("depth_m"), viewport, lat, lon)
                if depth <= 8:
                    continue
                chl = sample_grid(fields.get("chlorophyll_mg_m3"), viewport, lat, lon)
                cur = sample_grid(fields.get("current_speed"), viewport, lat, lon)
                wave = sample_grid(fields.get("wave_height_m"), viewport, lat, lon)
                intensity = max(0.0, min(1.0, (min(1.0, chl / 1.5) * 0.5) + (max(0.0, 1 - abs(cur - 0.8)) * 0.35) + (max(0.0, 1 - wave / 4.0) * 0.15)))
                reasons = [f"chl={chl:.2f}", f"current={cur:.2f}", f"wave={wave:.2f}"]
                points.append({"lat": lat, "lon": lon, "intensity": round(intensity, 3), "reason": ", ".join(reasons), "reasons": reasons})
        top = sorted(points, key=lambda x: x["intensity"], reverse=True)[:8]
        polygons = []
        for item in top:
            d = 0.18
            polygons.append({"coordinates": [[item['lon']-d, item['lat']-d], [item['lon']+d, item['lat']-d], [item['lon']+d, item['lat']+d], [item['lon']-d, item['lat']+d], [item['lon']-d, item['lat']-d]], "intensity": item["intensity"], "reason": item["reason"]})
        return {"bait_score": top, "polygons": polygons, "source": "shared_ocean", "degraded": len(polygons) == 0, "count": len(polygons)}
