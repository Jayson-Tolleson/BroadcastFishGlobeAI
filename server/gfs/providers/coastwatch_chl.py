from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("server.gfs.provider.coastwatch_chl")


class CoastwatchChlProvider:
    source_name = "coastwatch"

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> list[list[float]] | None:
        _ = weather
        log.info("[gfs/upstream] source=coastwatch request_recipe=erddap_chlorophyll bbox=%s", viewport)
        log.warning("[gfs/upstream] source=coastwatch status=unavailable reason=provider_not_configured bbox=%s", viewport)
        return None
