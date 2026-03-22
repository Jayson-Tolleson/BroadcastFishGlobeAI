from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("server.gfs.provider.wavewatch_waves")


class WavewatchWavesProvider:
    source_name = "wavewatch"

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any]:
        fields = weather.get("fields") or {}
        u = fields.get("wind_u")
        v = fields.get("wind_v")
        if isinstance(u, list) and isinstance(v, list):
            heights: list[list[float]] = []
            for ru, rv in zip(u, v):
                if not isinstance(ru, list) or not isinstance(rv, list):
                    continue
                heights.append([max(0.2, min(6.0, math.hypot(float(a), float(b)) * 0.35)) for a, b in zip(ru, rv)])
            if heights:
                return {"height_m": heights, "source": self.source_name, "derived": False}
        return {"height_m": [[0.6]], "source": "derived_wind", "derived": True}
