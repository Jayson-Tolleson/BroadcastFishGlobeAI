from __future__ import annotations

from typing import Any
import math


def _safe(v: Any, default: float = float('nan')) -> float:
    try:
        value = float(v)
    except Exception:
        return default
    return value if math.isfinite(value) else default


def _norm(v: float, lo: float, hi: float) -> float:
    if not math.isfinite(v) or hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def _lat_lon(i: int, j: int, ny: int, nx: int, bbox: list[float]) -> tuple[float, float]:
    west, south, east, north = bbox
    lat = south + ((i + 0.5) * (north - south) / max(1, ny))
    lon = west + ((j + 0.5) * (east - west) / max(1, nx))
    return lat, lon


def _resample_nearest(grid: list[list[float]], ny: int, nx: int) -> list[list[float]]:
    src_ny = len(grid)
    src_nx = len(grid[0]) if src_ny else 0
    if src_ny < 1 or src_nx < 1 or ny < 1 or nx < 1:
        return [[float('nan') for _ in range(max(0, nx))] for _ in range(max(0, ny))]
    out: list[list[float]] = []
    for i in range(ny):
        si = min(src_ny - 1, max(0, int(i * src_ny / ny)))
        row: list[float] = []
        for j in range(nx):
            sj = min(src_nx - 1, max(0, int(j * src_nx / nx)))
            row.append(_safe(grid[si][sj]))
        out.append(row)
    return out


def _resample_bilinear(grid: list[list[float]], ny: int, nx: int) -> list[list[float]]:
    src_ny = len(grid)
    src_nx = len(grid[0]) if src_ny else 0
    if src_ny < 1 or src_nx < 1 or ny < 1 or nx < 1:
        return [[float('nan') for _ in range(max(0, nx))] for _ in range(max(0, ny))]
    out: list[list[float]] = []
    for i in range(ny):
        y = ((i + 0.5) * src_ny / ny) - 0.5
        y0 = max(0, min(src_ny - 1, int(math.floor(y))))
        y1 = max(0, min(src_ny - 1, y0 + 1))
        fy = y - y0
        row: list[float] = []
        for j in range(nx):
            x = ((j + 0.5) * src_nx / nx) - 0.5
            x0 = max(0, min(src_nx - 1, int(math.floor(x))))
            x1 = max(0, min(src_nx - 1, x0 + 1))
            fx = x - x0
            q00 = _safe(grid[y0][x0])
            q10 = _safe(grid[y0][x1], q00)
            q01 = _safe(grid[y1][x0], q00)
            q11 = _safe(grid[y1][x1], q10)
            if not any(math.isfinite(v) for v in (q00, q10, q01, q11)):
                row.append(float('nan'))
                continue

            valid_corners = [v for v in (q00, q10, q01, q11) if math.isfinite(v)]
            fill_val = sum(valid_corners) / len(valid_corners) if valid_corners else 0.0
            if not math.isfinite(q00): q00 = fill_val
            if not math.isfinite(q10): q10 = fill_val
            if not math.isfinite(q01): q01 = fill_val
            if not math.isfinite(q11): q11 = fill_val
            top = q00 + ((q10 - q00) * fx)
            bottom = q01 + ((q11 - q01) * fx)
            row.append(top + ((bottom - top) * fy))
        out.append(row)
    return out


def _central_diff(grid: list[list[float]], i: int, j: int) -> tuple[float, float]:
    ny = len(grid)
    nx = len(grid[0]) if ny else 0
    if i <= 0 or j <= 0 or i >= ny - 1 or j >= nx - 1:
        return 0.0, 0.0
    left = _safe(grid[i][j - 1])
    right = _safe(grid[i][j + 1])
    down = _safe(grid[i - 1][j])
    up = _safe(grid[i + 1][j])
    if not all(math.isfinite(v) for v in (left, right, down, up)):
        return 0.0, 0.0
    return (right - left) * 0.5, (up - down) * 0.5


def _harbor_fill(grid: list[list[float]], i: int, j: int) -> float:
    vals: list[float] = []
    ny = len(grid)
    nx = len(grid[0]) if ny else 0
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        yi = i + dy
        xj = j + dx
        if 0 <= yi < ny and 0 <= xj < nx:
            v = _safe(grid[yi][xj])
            if math.isfinite(v):
                vals.append(v)
    return (sum(vals) / len(vals)) if vals else float('nan')


def _components(mask: list[list[bool]]) -> list[list[tuple[int, int]]]:
    ny = len(mask)
    nx = len(mask[0]) if ny else 0
    seen: set[tuple[int, int]] = set()
    comps: list[list[tuple[int, int]]] = []
    for i in range(ny):
        for j in range(nx):
            if not mask[i][j] or (i, j) in seen:
                continue
            stack = [(i, j)]
            comp: list[tuple[int, int]] = []
            while stack:
                y, x = stack.pop()
                if (y, x) in seen or not mask[y][x]:
                    continue
                seen.add((y, x))
                comp.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        nyy = y + dy
                        nxx = x + dx
                        if 0 <= nyy < ny and 0 <= nxx < nx and (nyy, nxx) not in seen:
                            stack.append((nyy, nxx))
            comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps


def _poly_from_cells(comp: list[tuple[int, int]], bbox: list[float], ny: int, nx: int) -> list[list[float]]:
    if not comp:
        return []
    lats: list[float] = []
    lons: list[float] = []
    west, south, east, north = bbox
    half_lat = (north - south) / max(1, ny) * 0.52
    half_lon = (east - west) / max(1, nx) * 0.52
    for i, j in comp:
        lat, lon = _lat_lon(i, j, ny, nx, bbox)
        lats.extend([lat - half_lat, lat + half_lat])
        lons.extend([lon - half_lon, lon + half_lon])
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _component_probability(comp: list[tuple[int, int]], score_grid: list[list[float]]) -> float:
    vals = [_safe(score_grid[i][j], 0.0) for i, j in comp]
    vals = [v for v in vals if math.isfinite(v)]
    return (sum(vals) / len(vals)) if vals else 0.0


def _build_polygons(mask: list[list[bool]], score_grid: list[list[float]], bbox: list[float], ny: int, nx: int, max_shapes: int) -> list[dict[str, Any]]:
    polygons: list[dict[str, Any]] = []
    for comp in _components(mask):
        if len(comp) < 2:
            continue
        ring = _poly_from_cells(comp, bbox, ny, nx)
        if len(ring) < 4:
            continue
        polygons.append({
            'coordinates': ring,
            'probability': round(_component_probability(comp, score_grid), 3),
        })
        if len(polygons) >= max_shapes:
            break
    return polygons


def _derive_front_lines_from_sst(sst: list[list[float]], bbox: list[float]) -> list[dict[str, Any]]:
    ny = len(sst)
    nx = len(sst[0]) if ny else 0
    lines: list[dict[str, Any]] = []
    if ny < 3 or nx < 3:
        return lines
    for i in range(1, ny - 1, max(1, ny // 20)):
        segment: list[list[float]] = []
        for j in range(1, nx - 1):
            gx, gy = _central_diff(sst, i, j)
            if math.hypot(gx, gy) < 0.22:
                continue
            lat, lon = _lat_lon(i, j, ny, nx, bbox)
            segment.append([lon, lat])
        if len(segment) >= 2:
            lines.append({'coordinates': segment[:48]})
        if len(lines) >= 8:
            break
    return lines


def derive_bait_payload(atmospheric: dict[str, Any], ocean: dict[str, Any], bio: dict[str, Any], *, bbox: list[float]) -> dict[str, Any]:
    weather = atmospheric or {}
    wind_u_raw = weather.get('wind_u') or weather.get('u') or []
    wind_v_raw = weather.get('wind_v') or weather.get('v') or []
    precip_raw = weather.get('precip_rate') or []
    cloud_raw = weather.get('cloud_total') or []

    sst_raw = (ocean or {}).get('sst') or []
    current_u_raw = (ocean or {}).get('current_u') or []
    current_v_raw = (ocean or {}).get('current_v') or []
    chlorophyll_raw = (bio or {}).get('chlorophyll') or []

    source_grid = sst_raw or wind_u_raw or wind_v_raw or chlorophyll_raw
    src_ny = len(source_grid)
    src_nx = len(source_grid[0]) if src_ny else 0
    if src_ny < 1 or src_nx < 1:
        return {
            'bait': {
                'status': 'incomplete',
                'source': 'suppressed_incomplete',
                'polygons': [],
                'outer_polygons': [],
                'inner_polygons': [],
                'core_polygons': [],
                'meta': {'reason': 'missing_source_grid', 'valid_cells': 0},
            },
            'bait_score': [],
            'front_lines': [],
            'convergence_polygons': [],
            'boil_probability_polygons': [],
            'confidence': {'overall': 0.0},
        }

    target_ny = min(220, max(80, src_ny * 2))
    target_nx = min(220, max(80, src_nx * 2))
    sst = _resample_bilinear(sst_raw, target_ny, target_nx) if sst_raw else [[float('nan') for _ in range(target_nx)] for _ in range(target_ny)]
    chlorophyll = _resample_bilinear(chlorophyll_raw, target_ny, target_nx) if chlorophyll_raw else [[0.12 for _ in range(target_nx)] for _ in range(target_ny)]
    current_u = _resample_bilinear(current_u_raw, target_ny, target_nx) if current_u_raw else [[0.0 for _ in range(target_nx)] for _ in range(target_ny)]
    current_v = _resample_bilinear(current_v_raw, target_ny, target_nx) if current_v_raw else [[0.0 for _ in range(target_nx)] for _ in range(target_ny)]
    wind_u = _resample_bilinear(wind_u_raw, target_ny, target_nx) if wind_u_raw else [[0.0 for _ in range(target_nx)] for _ in range(target_ny)]
    wind_v = _resample_bilinear(wind_v_raw, target_ny, target_nx) if wind_v_raw else [[0.0 for _ in range(target_nx)] for _ in range(target_ny)]
    precip = _resample_bilinear(precip_raw, target_ny, target_nx) if precip_raw else [[0.0 for _ in range(target_nx)] for _ in range(target_ny)]
    cloud = _resample_bilinear(cloud_raw, target_ny, target_nx) if cloud_raw else [[50.0 for _ in range(target_nx)] for _ in range(target_ny)]

    outer_mask = [[False for _ in range(target_nx)] for __ in range(target_ny)]
    inner_mask = [[False for _ in range(target_nx)] for __ in range(target_ny)]
    core_mask = [[False for _ in range(target_nx)] for __ in range(target_ny)]
    score_grid = [[0.0 for _ in range(target_nx)] for __ in range(target_ny)]
    bait_score: list[dict[str, Any]] = []

    valid_cells = 0
    harbor_filled_cells = 0
    for i in range(target_ny):
        for j in range(target_nx):
            sst_v = _safe(sst[i][j])
            if not math.isfinite(sst_v):
                sst_v = _harbor_fill(sst, i, j)
                if math.isfinite(sst_v):
                    harbor_filled_cells += 1
            if not math.isfinite(sst_v):
                continue
            chl_v = _safe(chlorophyll[i][j], 0.12)
            cu = _safe(current_u[i][j], 0.0)
            cv = _safe(current_v[i][j], 0.0)
            wu = _safe(wind_u[i][j], 0.0)
            wv = _safe(wind_v[i][j], 0.0)
            pr = _safe(precip[i][j], 0.0)
            cl = _safe(cloud[i][j], 50.0)

            sst_gx, sst_gy = _central_diff(sst, i, j)
            chl_gx, chl_gy = _central_diff(chlorophyll, i, j)
            cu_gx, cu_gy = _central_diff(current_u, i, j)
            cv_gx, cv_gy = _central_diff(current_v, i, j)
            sst_grad = math.hypot(sst_gx, sst_gy)
            chl_grad = math.hypot(chl_gx, chl_gy)
            convergence = max(0.0, -((cu_gx) + (cv_gy)))
            shear = math.hypot(cu_gy, cv_gx)
            wind_speed = math.hypot(wu, wv)
            current_speed = math.hypot(cu, cv)

            front_score = _norm(sst_grad, 0.04, 0.9)
            bio_edge_score = _norm(chl_grad, 0.005, 0.18)
            convergence_score = _norm(convergence, 0.0, 0.12)
            shear_score = _norm(shear, 0.0, 0.25)
            sst_score = 1.0 - abs(_norm(sst_v, 12.0, 28.0) - 0.5)
            chl_score = _norm(chl_v, 0.05, 2.0)
            current_score = _norm(current_speed, 0.02, 1.0)
            wind_score = 1.0 - _norm(wind_speed, 0.0, 18.0)
            rain_score = 1.0 - _norm(pr, 0.0, 1.0)
            cloud_score = 1.0 - abs(_norm(cl, 5.0, 95.0) - 0.45)

            score = (
                0.24 * front_score +
                0.15 * bio_edge_score +
                0.12 * convergence_score +
                0.08 * shear_score +
                0.16 * sst_score +
                0.12 * chl_score +
                0.07 * current_score +
                0.03 * wind_score +
                0.02 * rain_score +
                0.01 * cloud_score
            )
            score = max(0.0, min(1.0, score))
            score_grid[i][j] = score
            valid_cells += 1

            preferred_depth_m = max(2.0, min(45.0, 10.0 + (1.0 - chl_score) * 14.0 + max(0.0, sst_v - 20.0) * 0.9 - (front_score * 5.0)))
            depth_band_min = max(0.0, preferred_depth_m - 6.0)
            depth_band_max = preferred_depth_m + 8.0
            lat, lon = _lat_lon(i, j, target_ny, target_nx, bbox)
            bait_score.append({
                'lat': lat,
                'lon': lon,
                'probability': round(score, 3),
                'preferred_depth_m': round(preferred_depth_m, 1),
                'depth_min_m': round(depth_band_min, 1),
                'depth_max_m': round(depth_band_max, 1),
                'driver': 'front' if front_score >= max(bio_edge_score, convergence_score) else ('bio_edge' if bio_edge_score >= convergence_score else 'current_convergence'),
            })

            if score >= 0.40:
                outer_mask[i][j] = True
            if score >= 0.53:
                inner_mask[i][j] = True
            if score >= 0.66:
                core_mask[i][j] = True

    outer_polygons = _build_polygons(outer_mask, score_grid, bbox, target_ny, target_nx, max_shapes=24)
    inner_polygons = _build_polygons(inner_mask, score_grid, bbox, target_ny, target_nx, max_shapes=18)
    core_polygons = _build_polygons(core_mask, score_grid, bbox, target_ny, target_nx, max_shapes=12)

    if not inner_polygons and bait_score:
        strongest = sorted(bait_score, key=lambda b: b['probability'], reverse=True)[:18]
        west, south, east, north = bbox
        cell_dx = (east - west) / max(1, target_nx)
        cell_dy = (north - south) / max(1, target_ny)
        for c in strongest:
            lon = c['lon']
            lat = c['lat']
            dx = max(0.01, cell_dx * 0.6)
            dy = max(0.01, cell_dy * 0.6)
            inner_polygons.append({
                'coordinates': [[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy], [lon - dx, lat + dy], [lon - dx, lat - dy]],
                'probability': c['probability'],
                'preferred_depth_m': c['preferred_depth_m'],
                'depth_min_m': c['depth_min_m'],
                'depth_max_m': c['depth_max_m'],
                'driver': c['driver'],
            })

    def _attach_depth(polygons: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for poly in polygons:
            if 'preferred_depth_m' in poly:
                continue
            p = _safe(poly.get('probability'), 0.5)
            depth = max(2.0, min(45.0, 9.0 + ((1.0 - p) * 18.0)))
            poly['preferred_depth_m'] = round(depth, 1)
            poly['depth_min_m'] = round(max(0.0, depth - 6.0), 1)
            poly['depth_max_m'] = round(depth + 8.0, 1)
            poly['driver'] = poly.get('driver') or 'surface_front'
        return polygons

    outer_polygons = _attach_depth(outer_polygons)
    inner_polygons = _attach_depth(inner_polygons)
    core_polygons = _attach_depth(core_polygons)
    fronts = _derive_front_lines_from_sst(sst, bbox) if valid_cells > 0 else []
    overall = round((sum(item['probability'] for item in bait_score) / len(bait_score)), 3) if bait_score else 0.0

    return {
        'bait': {
            'status': 'ready' if valid_cells > 0 else 'incomplete',
            'source': 'full_stack' if valid_cells > 0 else 'suppressed_incomplete',
            'polygons': inner_polygons,
            'outer_polygons': outer_polygons,
            'inner_polygons': inner_polygons,
            'core_polygons': core_polygons,
            'meta': {
                'valid_cells': valid_cells,
                'harbor_filled_cells': harbor_filled_cells,
                'grid_ny': target_ny,
                'grid_nx': target_nx,
                'chlorophyll_available': bool(chlorophyll_raw),
            },
        },
        'bait_score': bait_score,
        'front_lines': fronts,
        'convergence_polygons': inner_polygons[: min(6, len(inner_polygons))],
        'boil_probability_polygons': [p for p in core_polygons if _safe(p.get('probability'), 0.0) >= 0.72],
        'confidence': {'overall': overall},
    }
