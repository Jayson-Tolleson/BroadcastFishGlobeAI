from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

import xarray as xr

from server.gfs.models import BBox
from server.gfs.providers.adapters import build_station_enrichment_request, split_antimeridian, viewport_from_bbox
from server.gfs.serializers import iso_utc


log = logging.getLogger("server.gfs.provider.ocean")

NOAA_TIDES_API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
HYCOM_NCSS_GRID = os.getenv(
    "GFS_HYCOM_NCSS_GRID",
    "https://ncss.hycom.org/thredds/ncss/grid/FMRC_ESPC-D-V02_all/FMRC_ESPC-D-V02_all_best.ncd",
)
ERDDAP_EKMAN_CSV = os.getenv("GFS_ERDDAP_EKMAN_CSV", "https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDNRTcurrentsDaily")

COOPS_STATIONS = (
    ("9414290", 37.806, -122.465),
    ("8720218", 21.306, -157.867),
    ("8454000", 41.355, -71.968),
    ("8771013", 29.673, -93.836),
    ("9461380", 58.301, -134.419),
)

HYCOM_DATASET_META = {
    "dataset": HYCOM_NCSS_GRID,
    "lon_convention": "0360",
    "lat_descending": False,
    "extra_dimensions": [],
    # Prefer native surface variables from HYCOM NCSS Best Time Series.
    # They avoid vertical-coordinate ambiguity and are stable for bait/current overlays.
    "request_vars": ["sst", "ssu", "ssv", "sss", "surf_el"],
}

SST_DATASET_META = {
    "dataset": HYCOM_NCSS_GRID,
    "var_name": "sst",
    "lon_convention": "0360",
    "lat_descending": False,
    "extra_dimensions": [],
    "request_vars": ["sst", "ssu", "ssv", "sss", "surf_el"],
}

CURRENT_DATASET_META = {
    "dataset": HYCOM_NCSS_GRID,
    "u_name": "u_current",
    "v_name": "v_current",
    "speed_name": "mod_current",
    "lon_convention": "pm180",
    "lat_descending": False,
    "extra_dimensions": [],
}


def _safe(value: Any, default: float = float("nan")) -> float:
    try:
        v = float(value)
        if math.isnan(v):
            return default
        return v
    except Exception:
        return default


def _lon360(lon: float) -> float:
    while lon < 0.0:
        lon += 360.0
    while lon >= 360.0:
        lon -= 360.0
    return lon


def _ncss_accept(value: str) -> str:
    value = str(value or '').strip().lower()
    return 'netCDF4' if value in {'netcdf4', 'netcdf4-classic', 'netcdf4classic'} else 'netCDF'


def _build_ncss_query(*, west: float, south: float, east: float, north: float, stride: int, time_value: str = 'present') -> str:
    params: list[tuple[str, str]] = []
    for var_name in HYCOM_DATASET_META['request_vars']:
        params.append(('var', var_name))
    params.extend([
        ('north', f'{north:.6f}'),
        ('south', f'{south:.6f}'),
        ('west', f'{west:.6f}'),
        ('east', f'{east:.6f}'),
        ('horizStride', str(max(1, int(stride or 1)))),
        ('time', time_value or 'present'),
        ('addLatLon', 'true'),
        ('accept', _ncss_accept('netcdf4')),
    ])
    return urllib.parse.urlencode(params)


def _selector_expr(value: str) -> str:
    value = str(value).strip()
    if value == "last":
        value = "(last)"
    elif not (value.startswith("(") and value.endswith(")")):
        value = f"({value})"
    return f"[{value}:1:{value}]"


def _range_expr(start: float, stop: float, stride: int) -> str:
    return f"[({start}):{max(1, int(stride or 1))}:({stop})]"


class RtofsProvider:
    """Ocean forcing provider.

    Option A production pass:
    - HYCOM NCSS request for surface SST / currents / salinity in a single request
    - NOAA CO-OPS station fallback for currents if HYCOM currents are unavailable
    """

    def __init__(self) -> None:
        self._last_error: str | None = None
        self._last_fetch_at: datetime | None = None

    @staticmethod
    def _nearest_station(lat: float, lon: float) -> str:
        def dist2(item: tuple[str, float, float]) -> float:
            _, slat, slon = item
            return (lat - slat) ** 2 + (lon - slon) ** 2

        return min(COOPS_STATIONS, key=dist2)[0]

    @staticmethod
    def _http_json(url: str, timeout_s: float = 6.5) -> dict[str, Any] | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LFTR-GFS/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_s) as res:
                return json.loads(res.read().decode("utf-8", errors="replace"))
        except Exception:
            return None

    @staticmethod
    def _http_bytes(url: str, timeout_s: float = 25.0) -> bytes | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LFTR-GFS/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_s) as res:
                return res.read()
        except Exception:
            return None

    @staticmethod
    def _download_netcdf(url: str) -> str | None:
        payload = RtofsProvider._http_bytes(url)
        if not payload:
            return None
        # ERDDAP may return an HTML/XML error payload with status 200 for malformed constraints.
        # Reject obvious non-NetCDF payloads before xarray opens the temp file.
        head = payload[:256].lstrip()
        if head.startswith(b"<") or b"Error {" in head[:128] or b"Malformed or unexpected Constraint" in payload[:1024]:
            return None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".nc") as tmp:
            tmp.write(payload)
            return tmp.name

    @staticmethod
    def _open_dataset(tmp_path: str) -> tuple[xr.Dataset | None, str | None]:
        engines = ["netcdf4", "h5netcdf", "scipy", None]
        last_exc: Exception | None = None
        for engine in engines:
            try:
                ds = xr.open_dataset(tmp_path, engine=engine) if engine else xr.open_dataset(tmp_path)
                return ds, engine or "default"
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        return None, None

    @staticmethod
    def _find_array(ds: xr.Dataset, *names: str):
        for name in names:
            if name in ds.variables:
                return ds[name]
            if name in ds.coords:
                return ds.coords[name]
        return None

    @staticmethod
    def _extract_2d(ds: xr.Dataset, var_name: str) -> list[list[float]]:
        arr = RtofsProvider._find_array(ds, var_name)
        if arr is None:
            return []
        arr = arr.squeeze(drop=True)
        if getattr(arr, "ndim", 0) > 2:
            while getattr(arr, "ndim", 0) > 2:
                arr = arr.isel({arr.dims[0]: 0}, drop=True)
        if getattr(arr, "ndim", 0) != 2:
            return []
        values = arr.values
        ny = int(values.shape[0]) if len(values.shape) > 0 else 0
        nx = int(values.shape[1]) if len(values.shape) > 1 else 0
        out: list[list[float]] = []
        for i in range(ny):
            row: list[float] = []
            for j in range(nx):
                row.append(_safe(values[i][j], float("nan")))
            out.append(row)
        return out

    @staticmethod
    def _build_hycom_urls(*, west: float, south: float, east: float, north: float, stride: int, valid_time: datetime | None) -> list[str]:
        lat_min = max(-80.0, min(south, north))
        lat_max = min(90.0, max(south, north))
        stride_val = max(1, int(stride or 1))
        time_value = iso_utc(valid_time) if valid_time else 'present'

        west360 = _lon360(west)
        east360 = _lon360(east)
        if west360 <= east360:
            lon_ranges = [(west360, east360)]
        else:
            lon_ranges = [(west360, 359.920044), (0.0, east360)]

        urls: list[str] = []
        for lon_min, lon_max in lon_ranges:
            query = _build_ncss_query(
                west=lon_min,
                south=lat_min,
                east=lon_max,
                north=lat_max,
                stride=stride_val,
                time_value=time_value,
            )
            urls.append(f"{HYCOM_NCSS_GRID}?{query}")
        return urls

    @staticmethod
    def _merge_antimeridian_parts(parts: list[list[list[float]]]) -> list[list[float]]:
        grids = [g for g in parts if g]
        if not grids:
            return []
        if len(grids) == 1:
            return grids[0]
        min_rows = min(len(g) for g in grids)
        merged: list[list[float]] = []
        for i in range(min_rows):
            row: list[float] = []
            for g in grids:
                row.extend(g[i])
            merged.append(row)
        return merged

    def _fetch_hycom_bundle(self, *, west: float, south: float, east: float, north: float, stride: int, valid_time: datetime | None):
        urls = self._build_hycom_urls(west=west, south=south, east=east, north=north, stride=stride, valid_time=valid_time)
        sst_parts: list[list[list[float]]] = []
        u_parts: list[list[list[float]]] = []
        v_parts: list[list[list[float]]] = []
        sal_parts: list[list[list[float]]] = []
        opened_urls: list[str] = []
        previews: list[str] = []
        diagnostics: list[dict[str, Any]] = []

        for url in urls:
            tmp_path = self._download_netcdf(url)
            opened_urls.append(url)
            if not tmp_path:
                previews.append("download_failed_or_constraint_rejected")
                diagnostics.append({"url": url, "status": "download_failed_or_constraint_rejected"})
                continue
            ds = None
            try:
                ds, engine = self._open_dataset(tmp_path)
                sst_grid = self._extract_2d(ds, "sst")
                u_grid = self._extract_2d(ds, "ssu")
                v_grid = self._extract_2d(ds, "ssv")
                sal_grid = self._extract_2d(ds, "sss")
                lat_arr = self._find_array(ds, "lat", "latitude", "y")
                lon_arr = self._find_array(ds, "lon", "longitude", "x")
                diag = {
                    "url": url,
                    "engine": engine,
                    "dims": {k: int(v) for k, v in ds.sizes.items()},
                    "vars": list(ds.variables)[:16],
                    "coords": list(ds.coords)[:16],
                    "lat_shape": list(getattr(getattr(lat_arr, "shape", None), "__iter__", lambda: [])()) if lat_arr is not None and hasattr(lat_arr, "shape") else [],
                    "lon_shape": list(getattr(getattr(lon_arr, "shape", None), "__iter__", lambda: [])()) if lon_arr is not None and hasattr(lon_arr, "shape") else [],
                    "sst_shape": [len(sst_grid), len(sst_grid[0]) if sst_grid else 0],
                    "ssu_shape": [len(u_grid), len(u_grid[0]) if u_grid else 0],
                    "ssv_shape": [len(v_grid), len(v_grid[0]) if v_grid else 0],
                    "sss_shape": [len(sal_grid), len(sal_grid[0]) if sal_grid else 0],
                }
                diagnostics.append(diag)
                sst_parts.append(sst_grid)
                u_parts.append(u_grid)
                v_parts.append(v_grid)
                sal_parts.append(sal_grid)
                previews.append(json.dumps(diag, separators=(",", ":"))[:800])
                log.info("hycom ncss raw dataset url=%s engine=%s dims=%s vars=%s coords=%s lat_shape=%s lon_shape=%s sst_shape=%s ssu_shape=%s ssv_shape=%s sss_shape=%s", url, engine, diag["dims"], diag["vars"], diag["coords"], diag["lat_shape"], diag["lon_shape"], diag["sst_shape"], diag["ssu_shape"], diag["ssv_shape"], diag["sss_shape"])
                ds.close()
                ds = None
            except Exception as exc:
                previews.append(f"open_failed:{exc}")
                diagnostics.append({"url": url, "status": "open_failed", "error": str(exc)})
            finally:
                if ds is not None:
                    try:
                        ds.close()
                    except Exception:
                        pass
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return (
            self._merge_antimeridian_parts(sst_parts),
            self._merge_antimeridian_parts(u_parts),
            self._merge_antimeridian_parts(v_parts),
            self._merge_antimeridian_parts(sal_parts),
            opened_urls,
            previews,
            diagnostics,
        )

    def _fetch_station_currents(self, *, center_lat: float, center_lon: float) -> tuple[float | None, float | None]:
        station_id = self._nearest_station(center_lat, center_lon)
        url = (
            f"{NOAA_TIDES_API}?product=currents_predictions&application=lftr&station={station_id}"
            "&time_zone=gmt&units=english&interval=MAX_SLACK&format=json"
        )
        payload = self._http_json(url)
        arr = (payload or {}).get("current_predictions") or (payload or {}).get("cp") or []
        if not arr:
            return None, None
        p0 = arr[0]
        try:
            speed = float(p0.get("Velocity_Major") or p0.get("v") or p0.get("speed"))
            direction = float(p0.get("Direction_Bin") or p0.get("d") or p0.get("direction"))
        except Exception:
            return None, None
        rad = math.radians(direction)
        return speed * math.sin(rad), speed * math.cos(rad)

    @staticmethod
    def _constant_grid(ny: int, nx: int, value: float | None) -> list[list[float]]:
        if value is None or ny < 1 or nx < 1:
            return []
        return [[round(value, 4) for _ in range(nx)] for __ in range(ny)]

    def _ekman_fallback_from_station(self, ny: int, nx: int, center_lat: float, center_lon: float) -> tuple[list[list[float]], list[list[float]], str]:
        u, v = self._fetch_station_currents(center_lat=center_lat, center_lon=center_lon)
        return self._constant_grid(ny, nx, u), self._constant_grid(ny, nx, v), "noaa_coops_aux"

    def _fetch_subset_sync(self, *, bbox: BBox, stride: int, valid_time: datetime | None) -> tuple[dict[str, Any], datetime | None]:
        viewport = viewport_from_bbox(bbox)
        slices = split_antimeridian(viewport)
        sst, current_u, current_v, salinity, subset_urls, previews, diagnostics = self._fetch_hycom_bundle(
            west=viewport.west,
            south=viewport.south,
            east=viewport.east,
            north=viewport.north,
            stride=stride,
            valid_time=valid_time,
        )

        ny = len(sst)
        nx = len(sst[0]) if ny else 0
        station_req = build_station_enrichment_request(viewport, valid_time)
        current_source = "hycom_ncss"
        if not (current_u and current_v and ny and nx):
            current_u, current_v, current_source = self._ekman_fallback_from_station(ny, nx, station_req["center_lat"], station_req["center_lon"])

        current_speed: list[list[float]] = []
        if current_u and current_v:
            for u_row, v_row in zip(current_u, current_v):
                speed_row: list[float] = []
                for u_val, v_val in zip(u_row, v_row):
                    if math.isfinite(u_val) and math.isfinite(v_val):
                        speed_row.append((u_val * u_val + v_val * v_val) ** 0.5)
                    else:
                        speed_row.append(float("nan"))
                current_speed.append(speed_row)

        payload = {
            "sst": sst,
            "current_u": current_u,
            "current_v": current_v,
            "current_speed": current_speed,
            "salinity": salinity,
            "source_meta": {
                "ocean_source": "hycom_ncss",
                "current_source": current_source,
                "sst_source": "hycom_ncss",
                "subset_urls": len(subset_urls),
                "lon_convention": "0360",
                "real_subset": bool(sst),
                "lat_descending": False,
                "effective_stride": max(1, int(stride or 1)),
                "extra_dimensions": [],
                "mode": "option_a_hycom_ncss_surface_optional_bio",
                "sst_dataset_url": HYCOM_NCSS_GRID,
                "current_dataset_url": HYCOM_NCSS_GRID,
            },
        }
        self._last_fetch_at = datetime.utcnow()
        self._last_error = None
        log.info(
            "ocean subset fetched bbox=%s viewport=%s hycom_slices=%s stride=%s sst_shape=%sx%s real_subset=%s lat_descending=%s",
            bbox.as_list(),
            {"west": viewport.west, "south": viewport.south, "east": viewport.east, "north": viewport.north},
            [{"lon_start": s.lon_start, "lon_stop": s.lon_stop} for s in slices],
            max(1, int(stride or 1)),
            ny,
            nx,
            bool(sst),
            False,
        )
        if not sst:
            log.warning(
                "hycom subset empty bbox=%s dataset=%s vars=%s urls=%s rows=%s lat=%s lon=%s parser_rejected=%s http_success_no_data=%s lon_convention=%s lat_descending=%s preview=%s",
                bbox.as_list(),
                HYCOM_NCSS_GRID,
                ["sst", "ssu", "ssv", "sss", "surf_el", "lat", "lon"],
                subset_urls,
                [len(sst)],
                [ny],
                [nx],
                [0],
                True,
                "0360",
                False,
                previews,
            )
            if diagnostics:
                log.warning("hycom subset diagnostics bbox=%s diagnostics=%s", bbox.as_list(), diagnostics)
        return payload, valid_time

    async def fetch_subset(self, *, bbox: BBox, stride: int, valid_time: datetime | None) -> tuple[dict[str, Any], datetime | None]:
        try:
            return await asyncio.to_thread(self._fetch_subset_sync, bbox=bbox, stride=stride, valid_time=valid_time)
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("ocean subset failed bbox=%s horizStride=%s err=%s", bbox.as_list(), stride, exc)
            return {
                "sst": [],
                "current_u": [],
                "current_v": [],
                "current_speed": [],
                "source_meta": {"ocean_source": "hycom_ncss", "current_source": "noaa_coops_aux", "real_subset": False, "error": str(exc)},
            }, valid_time

    def health(self) -> dict[str, Any]:
        return {
            "provider": "ocean",
            "status": "viewport_subset_only",
            "upstreams": ["hycom_ncss", "noaa_coops_aux"],
            "sst_dataset_url": HYCOM_NCSS_GRID,
            "current_dataset_url": HYCOM_NCSS_GRID,
            "last_fetch_at": iso_utc(self._last_fetch_at),
            "last_error": self._last_error,
        }
