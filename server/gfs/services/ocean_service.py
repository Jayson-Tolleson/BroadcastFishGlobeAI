from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
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
        self.provider_budgets_ms = {
            "hycom": 2500,
            "coastwatch": 2000,
            "wavewatch": 1600,
            "bathymetry": 600,
        }
        self._component_cache: dict[str, dict[str, Any]] = {}
        self._component_ttl_s = {
            "currents": 60,
            "chlorophyll": 900,
            "waves": 300,
            "depth": 86400,
            "ocean": 60,
        }

    def _empty_grid(self, rows: int, cols: int) -> list[list[float]]:
        return [[float("nan") for _ in range(cols)] for _ in range(rows)]

    def _run_with_budget(self, name: str, fn, default):
        budget_ms = int(self.provider_budgets_ms.get(name, 1500))
        started = time.time()
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(fn)
            try:
                out = fut.result(timeout=max(0.1, budget_ms / 1000.0))
                return out, (time.time() - started) * 1000, False
            except FutureTimeout:
                fut.cancel()
                log.warning("[gfs/ocean] provider timeout name=%s budget_ms=%s", name, budget_ms)
                return default, (time.time() - started) * 1000, True
            except Exception as exc:
                log.warning("[gfs/ocean] provider failed name=%s err=%s", name, exc)
                return default, (time.time() - started) * 1000, True

    def _cache_key(self, viewport, component: str) -> str:
        return f"{component}:{viewport.west:.2f}:{viewport.south:.2f}:{viewport.east:.2f}:{viewport.north:.2f}:s{viewport.stride}:q{viewport.quality}"

    def _cache_get(self, viewport, component: str) -> dict[str, Any] | None:
        key = self._cache_key(viewport, component)
        item = self._component_cache.get(key)
        if not isinstance(item, dict):
            return None
        age_s = time.time() - float(item.get("built_at", 0.0))
        if age_s > float(self._component_ttl_s.get(component, 60)):
            return None
        return item

    def _cache_put(self, viewport, component: str, payload: dict[str, Any]) -> None:
        key = self._cache_key(viewport, component)
        self._component_cache[key] = {"built_at": time.time(), "payload": payload, "bbox": viewport.as_bbox(), "component": component}

    def _find_compatible_currents(self, viewport) -> dict[str, Any] | None:
        exact = self._cache_get(viewport, "currents")
        if exact:
            return exact
        fallback = None
        for item in self._component_cache.values():
            if not isinstance(item, dict) or item.get("component") != "currents":
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if not isinstance(payload.get("u"), list) or not payload.get("u"):
                continue
            fallback = item
            break
        return fallback

    def build_shared_state(self, viewport, weather: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        grid = build_canonical_grid(viewport)
        log.info("canonical grid rows=%s cols=%s cell_deg=%s", grid.rows, grid.cols, grid.cell_deg)
        log.info("[gfs/source-policy] currents=hycom chlorophyll=coastwatch waves=wavewatch bathymetry=bathymetry weather=ncss")

        log.info("[gfs/ocean] request key=%s cache=miss", self._cache_key(viewport, "ocean"))
        currents, currents_ms, currents_timed_out = self._run_with_budget(
            "hycom",
            lambda: self.hycom.fetch(weather, viewport.as_dict()),
            None,
        )
        currents_status = {"primary": "hycom", "selected_source": (currents or {}).get("source") if isinstance(currents, dict) else "none"}
        currents_cache_used = False
        if currents is None:
            cached_currents = self._find_compatible_currents(viewport)
            if cached_currents and isinstance(cached_currents.get("payload"), dict):
                cpay = cached_currents["payload"]
                currents = {
                    "u": cpay.get("u") or self._empty_grid(grid.rows, grid.cols),
                    "v": cpay.get("v") or self._empty_grid(grid.rows, grid.cols),
                    "source": "hycom_cached",
                    "degraded": False,
                    "ok": True,
                    "source_status": "available_cached",
                }
                currents_cache_used = True
                currents_status["reason"] = "hycom_cache_fallback"
            else:
                currents = {"u": self._empty_grid(grid.rows, grid.cols), "v": self._empty_grid(grid.rows, grid.cols), "source": "hycom", "degraded": True, "ok": False, "source_status": "unavailable"}
                currents_status["degraded"] = True
                currents_status["reason"] = "hycom_unavailable"
        else:
            currents_status["degraded"] = bool(currents.get("degraded"))
            currents["ok"] = True
            currents.setdefault("source_status", "available")
            self._cache_put(viewport, "currents", {"u": currents.get("u") or [], "v": currents.get("v") or [], "source_status": currents.get("source_status"), "degraded": False})
        log.info("currents source=%s source_status=%s degraded=%s", currents.get("source"), currents.get("source_status"), currents.get("degraded"))
        if currents_timed_out:
            currents_status["reason"] = "hycom_timeout_or_error"

        chlorophyll, chl_ms, chl_timed_out = self._run_with_budget(
            "coastwatch",
            lambda: self.chl.fetch(weather, viewport.as_dict()),
            None,
        )
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
            self._cache_put(viewport, "chlorophyll", {"chlorophyll": chlorophyll, "source_status": "available"})
        log.info("chlorophyll source=%s source_status=%s", chl_source, chl_source_status)
        if chl_timed_out and chl_source == "coastwatch":
            chl_source = "timeout"
            chl_source_status = "timeout"

        waves, waves_ms, waves_timed_out = self._run_with_budget(
            "wavewatch",
            lambda: self.waves.fetch(weather, viewport.as_dict()),
            None,
        )
        wave_ok = isinstance(waves, dict) and isinstance(waves.get("height_m"), list)
        if not wave_ok:
            waves = {"height_m": self._empty_grid(grid.rows, grid.cols), "period_s": self._empty_grid(grid.rows, grid.cols), "direction_deg": self._empty_grid(grid.rows, grid.cols), "source": "wavewatch", "source_status": "unavailable", "ok": False}
        else:
            waves.setdefault("source", "wavewatch")
            waves.setdefault("source_status", "available")
            waves["ok"] = True
        if waves_timed_out:
            waves["source_status"] = "timeout"
        elif isinstance(waves.get("height_m"), list) and waves.get("height_m"):
            self._cache_put(viewport, "waves", {"waves": waves, "source_status": waves.get("source_status")})
        (depth_grid, depth_degraded), depth_ms, depth_timed_out = self._run_with_budget(
            "bathymetry",
            lambda: self.depth.fetch(grid.rows, grid.cols, viewport.as_dict()),
            (self._empty_grid(grid.rows, grid.cols), True),
        )
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
                "currents": bool(currents.get("degraded")) and not currents_cache_used,
                "waves": not bool(waves.get("ok")),
                "chlorophyll": chl_source != "coastwatch",
                "depth": bool(depth_degraded or depth_timed_out),
            },
            "diagnostics": {
                "currents": currents_status,
                "provider_ms": {
                    "hycom": round(currents_ms, 2),
                    "coastwatch": round(chl_ms, 2),
                    "wavewatch": round(waves_ms, 2),
                    "bathymetry": round(depth_ms, 2),
                },
                "provider_timeouts": {
                    "hycom": bool(currents_timed_out),
                    "coastwatch": bool(chl_timed_out),
                    "wavewatch": bool(waves_timed_out),
                    "bathymetry": bool(depth_timed_out),
                },
                "cache_used": {
                    "currents": bool(currents_cache_used),
                    "chlorophyll": chl_source == "cache_last_good",
                },
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
            "source_build_latency_ms": round((time.time() - started) * 1000, 2),
        }
        self._cache_put(viewport, "ocean", payload)
        log.info(
            "[gfs/ocean] resolve currents source=%s status=%s degraded=%s cache_used=%s",
            currents.get("source"),
            currents.get("source_status"),
            payload["degraded"]["currents"],
            currents_cache_used,
        )
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
