from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("server.gfs.provider.wavewatch_waves")


class WavewatchWavesProvider:
    source_name = "wavewatch"

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any] | None:
        fields = weather.get("fields") if isinstance(weather, dict) else {}
        log.info("[gfs/upstream] source=wavewatch request_recipe=wavewatch_or_weather_fallback bbox=%s", viewport)
        height = fields.get("wave_height_m") if isinstance(fields, dict) else None
        period = fields.get("wave_period_s") if isinstance(fields, dict) else None
        direction = fields.get("wave_direction_deg") if isinstance(fields, dict) else None
        if isinstance(height, list) and height:
            return {
                "height_m": height,
                "period_s": period if isinstance(period, list) and period else [[float("nan") for _ in row] for row in height],
                "direction_deg": direction if isinstance(direction, list) and direction else [[float("nan") for _ in row] for row in height],
                "source": "wavewatch",
                "source_status": "available",
                "ok": True,
            }
        wind_u = fields.get("wind_u") if isinstance(fields, dict) else None
        wind_v = fields.get("wind_v") if isinstance(fields, dict) else None
        if not (isinstance(wind_u, list) and isinstance(wind_v, list) and wind_u and wind_v):
            return None
        est_height: list[list[float]] = []
        est_period: list[list[float]] = []
        est_direction: list[list[float]] = []
        for i, ru in enumerate(wind_u):
            rv = wind_v[i] if i < len(wind_v) and isinstance(wind_v[i], list) else []
            h_row: list[float] = []
            p_row: list[float] = []
            d_row: list[float] = []
            for j, u in enumerate(ru if isinstance(ru, list) else []):
                v = rv[j] if j < len(rv) else 0.0
                try:
                    u_f = float(u)
                    v_f = float(v)
                    speed = (u_f * u_f + v_f * v_f) ** 0.5
                    h_row.append(max(0.0, min(8.0, speed * 0.08)))
                    p_row.append(max(2.0, min(18.0, 4.0 + speed * 0.18)))
                    d_row.append(float((180.0 + math.degrees(math.atan2(u_f, v_f))) % 360.0))
                except Exception:
                    h_row.append(float("nan"))
                    p_row.append(float("nan"))
                    d_row.append(float("nan"))
            est_height.append(h_row)
            est_period.append(p_row)
            est_direction.append(d_row)
        return {
            "height_m": est_height,
            "period_s": est_period,
            "direction_deg": est_direction,
            "source": "wavewatch",
            "source_status": "derived_from_wind",
            "ok": True,
            "degraded": True,
        }
