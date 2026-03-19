from __future__ import annotations

import math
from typing import Any

BOAT_COUNT_MAX = 12
WAVE_GREEN_MAX_FT = 3.0
WAVE_YELLOW_MAX_FT = 4.0


def _to_grid(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or not value:
        return []
    if isinstance(value[0], list) and value[0] and isinstance(value[0][0], list):
        return value[0]
    if isinstance(value[0], list):
        return value
    return []


def _safe(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except Exception:
        pass
    return default


def _finite_or_none(value: Any) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _finite_or_default(value: Any, default: float) -> float:
    out = _finite_or_none(value)
    return default if out is None else out


def _safe_round(value: Any, digits: int = 1) -> float | None:
    out = _finite_or_none(value)
    if out is None:
        return None
    return round(out, digits)


def _safe_int_period(value: Any, fallback: float = 6.0, scale: float = 1.0, minimum: int = 3) -> int:
    out = _finite_or_none(value)
    if out is None:
        out = fallback
    return max(minimum, round(out * scale))


def _meters_to_feet(value_m: float | None) -> float | None:
    value_m = _finite_or_none(value_m)
    if value_m is None:
        return None
    return round(value_m * 3.28084, 1)


def _c_to_f(value_c: float | None) -> float | None:
    value_c = _finite_or_none(value_c)
    if value_c is None:
        return None
    return round((value_c * 9.0 / 5.0) + 32.0, 1)


def _cell_center(bbox: list[float], ny: int, nx: int, i: int, j: int) -> tuple[float, float]:
    west, south, east, north = bbox
    span_lon = east - west if east >= west else (east + 360.0) - west
    lon = west + ((j + 0.5) / max(1, nx)) * span_lon
    while lon > 180.0:
        lon -= 360.0
    while lon <= -180.0:
        lon += 360.0
    lat = south + ((i + 0.5) / max(1, ny)) * (north - south)
    return lat, lon


def heading_from_uv(u: float, v: float, fallback_deg: float = 0.0) -> float:
    mag = math.hypot(u or 0.0, v or 0.0)
    if not math.isfinite(mag) or mag < 1.0e-6:
        return fallback_deg
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


def safety_color_from_wave_ft(wave_ft: float | None, wind_kt: float | None = None) -> tuple[str, str]:
    level = "green"
    if wave_ft is not None and math.isfinite(wave_ft):
        if wave_ft >= WAVE_YELLOW_MAX_FT:
            level = "red"
        elif wave_ft >= WAVE_GREEN_MAX_FT:
            level = "yellow"
    if wind_kt is not None and math.isfinite(wind_kt):
        if wind_kt >= 30.0 and level == "yellow":
            level = "red"
        elif wind_kt >= 25.0 and level == "green":
            level = "yellow"
    labels = {
        "green": "Calm boating conditions",
        "yellow": "Moderate boating conditions",
        "red": "Hazardous boating conditions",
    }
    return level, labels[level]


def _proxy_wave_ft(wind_u: float, wind_v: float, current_speed_kt: float) -> float | None:
    wind_speed_ms = math.hypot(wind_u, wind_v)
    if not math.isfinite(wind_speed_ms):
        return None
    wave_ft = max(0.5, wind_speed_ms * 0.9 + current_speed_kt * 0.35)
    return round(wave_ft * 1.15, 1)


def _station_wave_bundle(station: dict[str, Any] | None, heading_deg: float) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    if not station:
        return ({"sigHeightFt": None, "primary": None, "secondary": None, "tertiary": None}, {"speedKt": None, "dirDeg": None}, {"tempF": None, "airTempF": None}, "proxy")

    wave_ft = _meters_to_feet(_safe(station.get("waveHeightM")))
    dominant_period = _finite_or_none(_safe(station.get("dominantPeriodS")))
    average_period = _finite_or_none(_safe(station.get("averagePeriodS")))
    wave_dir = _finite_or_none(_safe(station.get("waveDirDeg"), heading_deg))
    wind_speed_mps = _finite_or_none(_safe(station.get("windSpeedMps")))
    wind_dir = _finite_or_none(_safe(station.get("windDirDeg"), heading_deg))

    base_period = _finite_or_default(average_period if average_period is not None else dominant_period, 6.0)
    base_dir = _finite_or_default(wave_dir, heading_deg)

    waves = {
        "sigHeightFt": _safe_round(wave_ft, 1),
        "primary": {
            "heightFt": _safe_round(wave_ft, 1),
            "periodS": _safe_round(dominant_period, 1),
            "dirDeg": _safe_round(base_dir, 1),
        } if wave_ft is not None else None,
        "secondary": {
            "heightFt": _safe_round(max(0.2, wave_ft * 0.55), 1),
            "periodS": _safe_round(average_period, 1),
            "dirDeg": _safe_round((base_dir + 18.0) % 360.0, 1),
        } if wave_ft is not None and average_period is not None else None,
        "tertiary": {
            "heightFt": _safe_round(max(0.2, wave_ft * 0.3), 1),
            "periodS": _safe_int_period(base_period, fallback=6.0, scale=0.65, minimum=3),
            "dirDeg": _safe_round((base_dir + 42.0) % 360.0, 1),
        } if wave_ft is not None else None,
    }
    wind = {
        "speedKt": _safe_round(wind_speed_mps * 1.94384, 1) if wind_speed_mps is not None else None,
        "dirDeg": _safe_round(wind_dir, 1),
    }
    water = {
        "tempF": _c_to_f(_safe(station.get("waterTempC"))),
        "airTempF": _c_to_f(_safe(station.get("airTempC"))),
    }
    return waves, wind, water, "ndbc_latest_obs"


def derive_boats_payload(*, bbox: list[float], weather: dict[str, Any], ocean: dict[str, Any], marine_observations: list[dict[str, Any]] | None = None, max_boats: int = BOAT_COUNT_MAX) -> list[dict[str, Any]]:
    sst = _to_grid(ocean.get("sst"))
    current_u = _to_grid(ocean.get("current_u"))
    current_v = _to_grid(ocean.get("current_v"))
    wind_u = _to_grid((weather.get("fields") or {}).get("wind_u"))
    wind_v = _to_grid((weather.get("fields") or {}).get("wind_v"))
    air_temp = _to_grid((weather.get("fields") or {}).get("air_temp") or (weather.get("fields") or {}).get("temp2m"))

    ny = len(sst)
    nx = len(sst[0]) if ny else 0
    if not ny or not nx:
        return []

    marine_observations = marine_observations or []

    candidates: list[tuple[float, int, int, dict[str, Any]]] = []
    for i in range(ny):
        for j in range(nx):
            sst_c = _safe(sst[i][j])
            if not math.isfinite(sst_c):
                continue
            u = _safe(current_u[i][j], 0.0) if i < len(current_u) and j < len(current_u[i]) else 0.0
            v = _safe(current_v[i][j], 0.0) if i < len(current_v) and j < len(current_v[i]) else 0.0
            current_speed_kt = math.hypot(u, v)
            if not math.isfinite(current_speed_kt):
                continue
            if current_speed_kt < 0.05:
                continue
            lat, lon = _cell_center(bbox, ny, nx, i, j)
            wu = _safe(wind_u[i][j], 0.0) if i < len(wind_u) and j < len(wind_u[i]) else 0.0
            wv = _safe(wind_v[i][j], 0.0) if i < len(wind_v) and j < len(wind_v[i]) else 0.0
            fallback_wind_kt = math.hypot(wu, wv) * 1.94384
            heading_deg = heading_from_uv(u, v, 0.0)

            station = None
            if marine_observations:
                best_km = float("inf")
                for obs in marine_observations:
                    slat = _safe(obs.get("lat"))
                    slon = _safe(obs.get("lon"))
                    if not math.isfinite(slat) or not math.isfinite(slon):
                        continue
                    km = 111.0 * math.hypot(lat - slat, (lon - slon) * math.cos(math.radians(lat)))
                    if km < best_km:
                        best_km = km
                        station = dict(obs)
                        station["distanceKm"] = round(km, 1)

            waves, wind, water, marine_source = _station_wave_bundle(station, heading_deg)
            if wind["speedKt"] is None:
                wind = {
                    "speedKt": _safe_round(fallback_wind_kt, 1) if math.isfinite(fallback_wind_kt) else None,
                    "dirDeg": _safe_round(heading_from_uv(wu, wv, heading_deg), 1) if math.isfinite(fallback_wind_kt) else None,
                }
            if water["tempF"] is None:
                water["tempF"] = round((sst_c * 9.0 / 5.0) + 32.0, 1)
            if water["airTempF"] is None and i < len(air_temp) and j < len(air_temp[i]) and math.isfinite(_safe(air_temp[i][j])):
                water["airTempF"] = round(((_safe(air_temp[i][j]) - 273.15) * 9.0 / 5.0) + 32.0, 1)

            wave_ft = waves.get("sigHeightFt")
            if wave_ft is None:
                wave_ft = _proxy_wave_ft(wu, wv, current_speed_kt)
                waves["sigHeightFt"] = wave_ft
                if wave_ft is not None and waves.get("primary") is None:
                    waves["primary"] = {"heightFt": _safe_round(wave_ft, 1), "periodS": None, "dirDeg": _safe_round(heading_deg, 1)}
            safety_color, safety_label = safety_color_from_wave_ft(wave_ft, wind.get("speedKt"))
            boat = {
                "id": f"boat_{i}_{j}",
                "lon": round(lon, 5),
                "lat": round(lat, 5),
                "displayLengthFt": 26,
                "headingDeg": round(heading_deg, 1),
                "current": {
                    "u": round(u, 4),
                    "v": round(v, 4),
                    "speedKt": round(current_speed_kt, 2),
                    "dirDeg": round(heading_deg, 1),
                },
                "safety": {
                    "color": safety_color,
                    "label": safety_label,
                    "derivedFrom": marine_source if wave_ft is not None and marine_source != "proxy" else ("wind_current_proxy" if wave_ft is not None else "current_only"),
                },
                "waves": waves,
                "wind": wind,
                "water": water,
                "marineStation": {
                    "id": station.get("stationId"),
                    "distanceKm": station.get("distanceKm"),
                } if station else None,
            }
            severity_bias = 0.0 if safety_color == "green" else 0.25 if safety_color == "yellow" else 0.5
            score = current_speed_kt + severity_bias + (0.15 if station else 0.0)
            candidates.append((score, i, j, boat))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[int, int, dict[str, Any]]] = []
    min_spacing = max(2, int(min(ny, nx) / 10))
    for _score, i, j, boat in candidates:
        if any(abs(i - si) < min_spacing and abs(j - sj) < min_spacing for si, sj, _ in selected):
            continue
        selected.append((i, j, boat))
        if len(selected) >= max_boats:
            break
    return [boat for _i, _j, boat in selected]
