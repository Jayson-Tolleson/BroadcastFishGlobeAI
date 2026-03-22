from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("server.gfs.provider.coastwatch_chl")


class CoastwatchChlProvider:
    source_name = "coastwatch"

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> list[list[float]] | None:
        fields = weather.get("fields") or {}
        cloud = fields.get("cloud_total")
        if not isinstance(cloud, list):
            return None
        out: list[list[float]] = []
        for row in cloud:
            if not isinstance(row, list):
                continue
            out.append([max(0.02, min(4.0, (1.0 - float(v)) * 1.5)) for v in row])
        if not out:
            return None
        log.info("coastwatch chlorophyll prepared")
        return out
