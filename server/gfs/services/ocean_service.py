from __future__ import annotations

import logging
import time
from typing import Any

from server.gfs.canonical import build_canonical_grid, vector_speed
from server.gfs.providers.bathymetry import BathymetryProvider
from server.gfs.providers.coastwatch_chl import CoastwatchChlProvider
from server.gfs.providers.hycom_currents import HycomCurrentsProvider
from server.gfs.providers.rtofs_currents import RtofsCurrentsProvider
from server.gfs.providers.wavewatch_waves import WavewatchWavesProvider

log = logging.getLogger("server.gfs.ocean")


class OceanService:
    def __init__(self) -> None:
        self.rtofs = RtofsCurrentsProvider()
        self.hycom = HycomCurrentsProvider()
        self.chl = CoastwatchChlProvider()
        self.waves = WavewatchWavesProvider()
        self.depth = BathymetryProvider()
        self._chl_last_good: list[list[float]] | None = None

    def _ekman_from_weather(self, weather: dict[str, Any]) -> dict[str, Any]:
        fields = weather.get("fields") or {}
        u = fields.get("wind_u") or [[0.0]]
        v = fields.get("wind_v") or [[0.0]]
        out_u: list[list[float]] = []
        out_v: list[list[float]] = []
        for ru, rv in zip(u, v):
            if not isinstance(ru, list) or not isinstance(rv, list):
                continue
            out_u.append([float(x) * 0.1 for x in ru])
            out_v.append([float(x) * 0.1 for x in rv])
        return {"u": out_u or [[0.0]], "v": out_v or [[0.0]], "source": "gfs_ekman", "degraded": True}

    def _sst_grid(self, weather: dict[str, Any]) -> list[list[float]]:
        temp = (weather.get("fields") or {}).get("air_temp")
        if not isinstance(temp, list):
            return [[289.0]]
        return [[float(v) - 0.7 for v in row] for row in temp if isinstance(row, list)] or [[289.0]]

    def build_shared_state(self, viewport, weather: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        grid = build_canonical_grid(viewport)
        log.info("canonical grid rows=%s cols=%s cell_deg=%s", grid.rows, grid.cols, grid.cell_deg)

        currents = self.rtofs.fetch(weather, viewport.as_dict())
        currents_status = dict(getattr(self.rtofs, "last_status", {}) or {})
        if currents is None:
            currents = self.hycom.fetch(weather, viewport.as_dict())
            currents_status["selected_source"] = currents.get("source") if isinstance(currents, dict) else "none"
            currents_status["degraded"] = True
            currents_status.setdefault("reason", "missing_weather_vectors")
        if currents is None:
            currents = self._ekman_from_weather(weather)
            currents_status["selected_source"] = currents.get("source")
            currents_status["degraded"] = True
            currents_status.setdefault("reason", "fallback_to_ekman")
        log.info("currents source=%s degraded=%s", currents.get("source"), currents.get("degraded"))

        chlorophyll = self.chl.fetch(weather, viewport.as_dict())
        chl_source = "coastwatch"
        if chlorophyll is None and self._chl_last_good is not None:
            chlorophyll = self._chl_last_good
            chl_source = "cache_last_good"
        if chlorophyll is None:
            chlorophyll = []
            chl_source = "unavailable"
        if chlorophyll:
            self._chl_last_good = chlorophyll
        log.info("chlorophyll source=%s", chl_source)

        waves = self.waves.fetch(weather, viewport.as_dict())
        depth_grid, depth_degraded = self.depth.fetch(grid.rows, grid.cols, viewport.as_dict())
        sst = self._sst_grid(weather)

        speed: list[list[float]] = []
        for ru, rv in zip(currents.get("u") or [], currents.get("v") or []):
            speed.append([vector_speed(float(u), float(v)) for u, v in zip(ru, rv)])

        payload = {
            "ok": True,
            "timestamp": int(time.time() * 1000),
            "ts": int(time.time() * 1000),
            "cycle": weather.get("source_time") or weather.get("valid_time"),
            "bbox": viewport.as_bbox(),
            "quality": viewport.quality,
            "stride": viewport.stride,
            "grid": {"rows": grid.rows, "cols": grid.cols, "lats": grid.lats, "lons": grid.lons, "cell_deg": grid.cell_deg},
            "source": "shared_ocean",
            "sources": {
                "weather": "gfs",
                "currents": currents.get("source"),
                "chlorophyll": chl_source,
                "waves": waves.get("source"),
                "depth": "bathymetry_cacheable",
                "sst": "gfs_air_temp_adjusted",
            },
            "degraded": {
                "currents": bool(currents.get("degraded")),
                "waves": bool(waves.get("derived")),
                "chlorophyll": chl_source != "coastwatch",
                "depth": bool(depth_degraded),
            },
            "diagnostics": {
                "currents": currents_status,
            },
            "fields": {
                "current_u": currents.get("u") or [],
                "current_v": currents.get("v") or [],
                "current_speed": speed,
                "sst_k": sst,
                "chlorophyll_mg_m3": chlorophyll,
                "wave_height_m": waves.get("height_m") or [],
                "depth_m": depth_grid,
            },
            "count": grid.rows * grid.cols,
            "latency_ms": round((time.time() - started) * 1000, 2),
        }
        return payload
