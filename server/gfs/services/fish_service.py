from __future__ import annotations

import math
from typing import Any

from server.gfs.canonical import sample_grid


class FishService:
    def score_markers(self, ocean: dict[str, Any], viewport) -> list[dict[str, Any]]:
        fields = ocean.get("fields") or {}
        lats = (ocean.get("grid") or {}).get("lats") or []
        lons = (ocean.get("grid") or {}).get("lons") or []
        if not lats or not lons:
            return []
        out: list[dict[str, Any]] = []
        step_lat = max(1, len(lats) // 4)
        step_lon = max(1, len(lons) // 4)
        for yi in range(0, len(lats), step_lat):
            for xi in range(0, len(lons), step_lon):
                lat = lats[yi]
                lon = lons[xi]
                sst = sample_grid(fields.get("sst_k"), viewport, lat, lon)
                chl = sample_grid(fields.get("chlorophyll_mg_m3"), viewport, lat, lon)
                cur = sample_grid(fields.get("current_speed"), viewport, lat, lon)
                depth = sample_grid(fields.get("depth_m"), viewport, lat, lon)
                temp_score = max(0.0, 1.0 - abs(sst - 292.0) / 8.0) if math.isfinite(sst) else 0.35
                chl_score = min(1.0, chl / 1.8) if math.isfinite(chl) else 0.2
                cur_score = max(0.0, 1.0 - abs(cur - 0.7) / 1.0) if math.isfinite(cur) else 0.2
                depth_score = max(0.0, 1.0 - abs(depth - 900.0) / 1400.0) if math.isfinite(depth) else 0.2
                suitability = max(0.0, min(1.0, (temp_score * 0.35) + (chl_score * 0.3) + (cur_score * 0.2) + (depth_score * 0.15)))
                reasons = [
                    f"SST score {temp_score:.2f}",
                    f"chlorophyll score {chl_score:.2f}",
                    f"current score {cur_score:.2f}",
                    f"depth score {depth_score:.2f}",
                ]
                out.append({
                    "id": f"fish-{yi}-{xi}",
                    "name": "Pelagic zone",
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "score": round(suitability * 100.0, 1),
                    "suitability": round(suitability, 3),
                    "reason": "; ".join(reasons),
                    "reasons": reasons,
                    "confidence": round(suitability, 3),
                    "probability": round(suitability, 3),
                })
        return sorted(out, key=lambda item: item["score"], reverse=True)[:18]
