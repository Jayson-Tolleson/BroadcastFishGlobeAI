from __future__ import annotations

import logging
import time
from typing import Any

from server.gfs.canonical import build_canonical_grid, vector_speed
from server.gfs.providers.bathymetry import BathymetryProvider
from server.gfs.providers.coastwatch_chl import CoastwatchChlProvider
from server.gfs.providers.hycom_currents import HycomCurrentsProvider
from server.gfs.providers.wavewatch_waves import WavewatchWavesProvider

log = logging.getLogger("server.gfs.ocean")


class OceanService:
    def __init__(self) -> None:
        self.hycom = HycomCurrentsProvider()
        self.chl = CoastwatchChlProvider()
        self.waves = WavewatchWavesProvider()
        self.depth = BathymetryProvider()
        self._chl_last_good: list[list[float]] | None = None

    def _empty_grid(self, rows: int, cols: int) -> list[list[float]]:
        return [[float("nan") for _ in range(cols)] for _ in range(rows)]

    def build_shared_state(self, viewport, weather: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        grid = build_canonical_grid(viewport)
        log.info("canonical grid rows=%s cols=%s cell_deg=%s", grid.rows, grid.cols, grid.cell_deg)
        log.info("[gfs/source-policy] currents=hycom chlorophyll=coastwatch waves=wavewatch bathymetry=bathymetry weather=ncss")

        currents_started = time.time()
        currents = self.hycom.fetch(weather, viewport.as_dict())
        currents_status = {"primary": "hycom", "selected_source": (currents or {}).get("source") if isinstance(currents, dict) else "none"}
        if currents is None:
            currents = {"u": self._empty_grid(grid.rows, grid.cols), "v": self._empty_grid(grid.rows, grid.cols), "source": "hycom", "degraded": True, "ok": False, "source_status": "unavailable"}
            currents_status["degraded"] = True
            currents_status["reason"] = "hycom_unavailable"
        else:
            currents_status["degraded"] = bool(currents.get("degraded"))
            currents["ok"] = True
            currents.setdefault("source_status", "available")
        log.info("currents source=%s source_status=%s degraded=%s", currents.get("source"), currents.get("source_status"), currents.get("degraded"))
        currents_ms = (time.time() - currents_started) * 1000

        chl_started = time.time()
        chlorophyll = self.chl.fetch(weather, viewport.as_dict())
        chl_source = "coastwatch"
        if chlorophyll is None and self._chl_last_good is not None:
            chlorophyll = self._chl_last_good
            chl_source = "cache_last_good"
            chl_source_status = "stale_last_good"
            chl_ok = True
        if chlorophyll is None:
            chlorophyll = self._empty_grid(grid.rows, grid.cols)
            chl_source = "unavailable"
            chl_source_status = "unavailable"
            chl_ok = False
        else:
            chl_source_status = "available" if chl_source == "coastwatch" else "stale_last_good"
            chl_ok = True
        if chlorophyll and chl_source == "coastwatch":
            self._chl_last_good = chlorophyll
        log.info("chlorophyll source=%s source_status=%s", chl_source, chl_source_status)
        chl_ms = (time.time() - chl_started) * 1000

        waves_started = time.time()
        waves = self.waves.fetch(weather, viewport.as_dict())
        wave_ok = isinstance(waves, dict) and isinstance(waves.get("height_m"), list)
        if not wave_ok:
            waves = {"height_m": self._empty_grid(grid.rows, grid.cols), "period_s": self._empty_grid(grid.rows, grid.cols), "direction_deg": self._empty_grid(grid.rows, grid.cols), "source": "wavewatch", "source_status": "unavailable", "ok": False}
        else:
            waves.setdefault("source", "wavewatch")
            waves.setdefault("source_status", "available")
            waves["ok"] = True
        waves_ms = (time.time() - waves_started) * 1000
        depth_started = time.time()
        depth_grid, depth_degraded = self.depth.fetch(grid.rows, grid.cols, viewport.as_dict())
        depth_ms = (time.time() - depth_started) * 1000
        sst = self._empty_grid(grid.rows, grid.cols)

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
                "weather": "ncss_weather",
                "currents": currents.get("source"),
                "chlorophyll": chl_source,
                "waves": waves.get("source"),
                "depth": "bathymetry_cacheable",
                "sst": "unavailable",
            },
            "source_status": {
                "currents": currents.get("source_status"),
                "chlorophyll": chl_source_status,
                "waves": waves.get("source_status"),
                "depth": "unavailable" if depth_degraded else "available",
            },
            "degraded": {
                "currents": bool(currents.get("degraded")),
                "waves": not bool(waves.get("ok")),
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
                "wave_period_s": waves.get("period_s") or [],
                "wave_direction_deg": waves.get("direction_deg") or [],
                "depth_m": depth_grid,
            },
            "count": grid.rows * grid.cols,
            "latency_ms": round((time.time() - started) * 1000, 2),
        }
        log.info(
            "[gfs-perf] ocean-service rows=%s cols=%s currents_ms=%.2f chl_ms=%.2f waves_ms=%.2f depth_ms=%.2f total_ms=%.2f",
            grid.rows,
            grid.cols,
            currents_ms,
            chl_ms,
            waves_ms,
            depth_ms,
            (time.time() - started) * 1000,
        )
        return payload
