from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("server.gfs.provider.wavewatch_waves")


class WavewatchWavesProvider:
    source_name = "wavewatch"

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any] | None:
        _ = (weather, viewport)
        log.warning("[gfs/upstream] source=wavewatch status=unavailable reason=provider_not_configured")
        return None
