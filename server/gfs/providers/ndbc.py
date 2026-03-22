from __future__ import annotations

import asyncio
import logging
import math
import time
import urllib.request
from typing import Any

log = logging.getLogger("server.gfs.provider.ndbc")

LATEST_OBS_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
_CACHE_TTL_S = 600.0
_MAX_NEAREST_KM = 350.0


class NdbcProvider:
    def __init__(self) -> None:
        self._cache: tuple[float, list[dict[str, Any]]] | None = None
        self._last_error: str | None = None

    @staticmethod
    def _http_text(url: str, timeout_s: float = 8.5) -> str | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LFTR-GFS/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_s) as res:
                return res.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    @staticmethod
    def _to_float(value: str) -> float | None:
        try:
            out = float(value)
            return out if math.isfinite(out) else None
        except Exception:
            return None

    def _parse_latest_obs(self, text: str | None) -> list[dict[str, Any]]:
        if not text:
            return []
        rows = [line.strip() for line in text.splitlines() if line.strip()]
        if len(rows) < 3:
            return []
        header = rows[0].split()
        stations: list[dict[str, Any]] = []
        for row in rows[2:]:
            parts = row.split()
            if len(parts) < len(header):
                continue
            rec = dict(zip(header, parts))
            lat = self._to_float(rec.get("LAT", ""))
            lon = self._to_float(rec.get("LON", ""))
            if lat is None or lon is None:
                continue
            stations.append(
                {
                    "stationId": rec.get("#STN") or rec.get("STN") or rec.get("station"),
                    "lat": lat,
                    "lon": lon,
                    "waveHeightM": self._to_float(rec.get("WVHT", "")),
                    "dominantPeriodS": self._to_float(rec.get("DPD", "")),
                    "averagePeriodS": self._to_float(rec.get("APD", "")),
                    "waveDirDeg": self._to_float(rec.get("MWD", "")),
                    "windDirDeg": self._to_float(rec.get("WDIR", "")),
                    "windSpeedMps": self._to_float(rec.get("WSPD", "")),
                    "waterTempC": self._to_float(rec.get("WTMP", "")),
                    "airTempC": self._to_float(rec.get("ATMP", "")),
                    "pressureHpa": self._to_float(rec.get("PRES", "")),
                }
            )
        return stations

    async def latest_observations(self) -> list[dict[str, Any]]:
        now = time.time()
        if self._cache and (now - self._cache[0]) < _CACHE_TTL_S:
            return self._cache[1]

        def _fetch() -> list[dict[str, Any]]:
            text = self._http_text(LATEST_OBS_URL)
            return self._parse_latest_obs(text)

        try:
            rows = await asyncio.to_thread(_fetch)
            self._cache = (now, rows)
            self._last_error = None
            log.info("ndbc latest observations fetched count=%s", len(rows))
            return rows
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("ndbc latest observations failed err=%s", exc)
            if self._cache:
                return self._cache[1]
            return []

    @staticmethod
    def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(min(1.0, math.sqrt(a)))

    def nearest_station(self, *, stations: list[dict[str, Any]], lat: float, lon: float, max_km: float = _MAX_NEAREST_KM) -> dict[str, Any] | None:
        best = None
        best_km = float("inf")
        for station in stations:
            slat = station.get("lat")
            slon = station.get("lon")
            if not isinstance(slat, (int, float)) or not isinstance(slon, (int, float)):
                continue
            km = self._distance_km(lat, lon, float(slat), float(slon))
            if km < best_km:
                best_km = km
                best = station
        if best is None or best_km > max_km:
            return None
        enriched = dict(best)
        enriched["distanceKm"] = round(best_km, 1)
        return enriched

    def health(self) -> dict[str, Any]:
        return {
            "provider": "ndbc",
            "upstreams": ["latest_obs_txt"],
            "healthy": self._last_error is None,
            "last_error": self._last_error,
            "cache_age_s": None if not self._cache else round(max(0.0, time.time() - self._cache[0]), 1),
        }
