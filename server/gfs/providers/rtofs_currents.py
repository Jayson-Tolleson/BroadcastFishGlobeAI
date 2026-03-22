from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("server.gfs.provider.rtofs_currents")


class RtofsCurrentsProvider:
    source_name = "rtofs"

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any] | None:
        fields = weather.get("fields") or {}
        u = fields.get("wind_u")
        v = fields.get("wind_v")
        if not isinstance(u, list) or not isinstance(v, list):
            log.info("rtofs currents unavailable (missing weather vectors)")
            return None
        out_u: list[list[float]] = []
        out_v: list[list[float]] = []
        for r_u, r_v in zip(u, v):
            if not isinstance(r_u, list) or not isinstance(r_v, list):
                continue
            out_u.append([float(x) * 0.22 for x in r_u])
            out_v.append([float(x) * 0.22 for x in r_v])
        if not out_u:
            return None
        return {"u": out_u, "v": out_v, "source": self.source_name, "degraded": False}
