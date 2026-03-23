import { createPolygon3D } from './polygon3d.js';

const LAYER_CONFIG = {
  low: { threshold: 24, baseAlt: 900, topAlt: 2200, color: '#dcefff' },
  mid: { threshold: 22, baseAlt: 2600, topAlt: 5200, color: '#eef6ff' },
  high: { threshold: 18, baseAlt: 5800, topAlt: 9800, color: '#f7fbff' },
};

const BUDGETS = {
  far: { maxRegions: 18, maxHulls: 28, maxPuffs: 110, maxPuffsPerRegion: 8 },
  regional: { maxRegions: 36, maxHulls: 56, maxPuffs: 260, maxPuffsPerRegion: 14 },
  close: { maxRegions: 54, maxHulls: 84, maxPuffs: 480, maxPuffsPerRegion: 20 },
};

function to2D(value) {
  if (!Array.isArray(value) || !Array.isArray(value[0])) return [];
  if (Array.isArray(value[0][0])) return value[0];
  return value;
}

function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }
function toNum(v, d = 0) { const n = Number(v); return Number.isFinite(n) ? n : d; }

function inferLod(payload) {
  const box = payload?.bbox;
  if (!Array.isArray(box) || box.length < 4) return 'regional';
  const span = Math.max(Math.abs(toNum(box[2]) - toNum(box[0])), Math.abs(toNum(box[3]) - toNum(box[1])));
  if (span > 45) return 'far';
  if (span > 14) return 'regional';
  return 'close';
}

function indexToLatLon(i, j, lats, lons, bbox, ny, nx) {
  if (Array.isArray(lats) && lats.length === ny && Array.isArray(lons) && lons.length === nx) {
    return { lat: toNum(lats[i]), lon: toNum(lons[j]) };
  }
  const west = toNum(bbox?.[0], -180); const south = toNum(bbox?.[1], -80);
  const east = toNum(bbox?.[2], 180); const north = toNum(bbox?.[3], 80);
  return {
    lat: south + ((i + 0.5) / Math.max(1, ny)) * (north - south),
    lon: west + ((j + 0.5) / Math.max(1, nx)) * (east - west),
  };
}

function regionExtract(layerName, grid, threshold, lats, lons, bbox, windU, windV, cap) {
  const ny = grid.length;
  const nx = ny ? grid[0].length : 0;
  const seen = Array.from({ length: ny }, () => Array(nx).fill(false));
  const out = [];
  const dirs = [[1,0],[-1,0],[0,1],[0,-1]];

  for (let i = 0; i < ny; i += 1) {
    for (let j = 0; j < nx; j += 1) {
      const seed = toNum(grid[i]?.[j], 0);
      if (seed < threshold || seen[i][j]) continue;
      const q = [[i, j]];
      seen[i][j] = true;
      const cells = [];
      let sum = 0; let minI = i; let maxI = i; let minJ = j; let maxJ = j;
      let wu = 0; let wv = 0; let wCount = 0;
      while (q.length) {
        const [cy, cx] = q.pop();
        const val = toNum(grid[cy]?.[cx], 0);
        if (val < threshold) continue;
        sum += val;
        cells.push([cy, cx]);
        minI = Math.min(minI, cy); maxI = Math.max(maxI, cy);
        minJ = Math.min(minJ, cx); maxJ = Math.max(maxJ, cx);
        const localU = toNum(windU?.[cy]?.[cx], NaN);
        const localV = toNum(windV?.[cy]?.[cx], NaN);
        if (Number.isFinite(localU) && Number.isFinite(localV)) { wu += localU; wv += localV; wCount += 1; }
        for (const [dy, dx] of dirs) {
          const nyi = cy + dy; const nxi = cx + dx;
          if (nyi < 0 || nxi < 0 || nyi >= ny || nxi >= nx || seen[nyi][nxi]) continue;
          seen[nyi][nxi] = true;
          if (toNum(grid[nyi]?.[nxi], 0) >= threshold) q.push([nyi, nxi]);
        }
      }
      if (!cells.length) continue;
      const ci = Math.round((minI + maxI) / 2);
      const cj = Math.round((minJ + maxJ) / 2);
      const center = indexToLatLon(ci, cj, lats, lons, bbox, ny, nx);
      const nw = indexToLatLon(minI, minJ, lats, lons, bbox, ny, nx);
      const se = indexToLatLon(maxI, maxJ, lats, lons, bbox, ny, nx);
      out.push({
        id: `${layerName}:${ci}:${cj}`,
        layer: layerName,
        meanDensity: sum / cells.length,
        cellCount: cells.length,
        center,
        extent: { minLat: Math.min(nw.lat, se.lat), maxLat: Math.max(nw.lat, se.lat), minLon: Math.min(nw.lon, se.lon), maxLon: Math.max(nw.lon, se.lon) },
        elongation: (Math.abs(maxJ - minJ) + 1) / Math.max(1, (Math.abs(maxI - minI) + 1)),
        driftU: wCount ? wu / wCount : 0,
        driftV: wCount ? wv / wCount : 0,
      });
      if (out.length >= cap) return out;
    }
  }
  return out;
}

function classify(region, totalVal, lowVal, midVal, highVal) {
  if (region.meanDensity > 74 && totalVal > 82) return 'storm';
  if (region.layer === 'high' && region.elongation > 1.6) return 'cirrus';
  if (region.layer === 'low' && region.elongation > 1.5 && region.cellCount > 8) return 'stratus';
  if ((region.layer === 'low' || region.layer === 'mid') && region.cellCount <= 6 && Math.max(lowVal, midVal) > 55) return 'cumulus';
  return region.layer === 'high' ? 'cirrus' : 'stratus';
}

function polygonEllipse(lat, lon, latR, lonR, points = 10, rotDeg = 0) {
  const out = [];
  const rot = (rotDeg * Math.PI) / 180;
  const cr = Math.cos(rot); const sr = Math.sin(rot);
  for (let i = 0; i < points; i += 1) {
    const t = (i / points) * Math.PI * 2;
    const y = Math.sin(t) * latR;
    const x = Math.cos(t) * lonR;
    out.push({ lat: lat + (y * cr - x * sr), lng: lon + (y * sr + x * cr) });
  }
  return out;
}

function hullPath(region) {
  const { minLat, maxLat, minLon, maxLon } = region.extent;
  const latR = Math.max(0.06, (maxLat - minLat) * 0.58);
  const lonR = Math.max(0.06, (maxLon - minLon) * 0.58);
  return polygonEllipse(region.center.lat, region.center.lon, latR, lonR, 12, region.elongation > 1 ? 18 : 0);
}

function styleForFamily(family, density) {
  const alpha = clamp(0.12 + (density / 100) * 0.28, 0.12, 0.48);
  switch (family) {
    case 'storm': return { color: '#d4deeb', alpha: clamp(alpha + 0.12, 0.22, 0.56), puffAlpha: 0.22, vertical: 1.5 };
    case 'cumulus': return { color: '#edf6ff', alpha: alpha, puffAlpha: 0.18, vertical: 1.2 };
    case 'cirrus': return { color: '#ffffff', alpha: clamp(alpha - 0.08, 0.08, 0.26), puffAlpha: 0.1, vertical: 0.8 };
    default: return { color: '#e8f2ff', alpha: clamp(alpha - 0.03, 0.1, 0.4), puffAlpha: 0.14, vertical: 1.0 };
  }
}

function windHeading(u, v) {
  if (!Number.isFinite(u) || !Number.isFinite(v)) return 0;
  return ((Math.atan2(u, v) * 180) / Math.PI + 360) % 360;
}

function spawnPuffs(region, family, lod, budget, pool) {
  const cfg = BUDGETS[lod];
  const baseCount = Math.round(clamp(region.cellCount * (region.meanDensity / 100) * 0.9, 2, cfg.maxPuffsPerRegion));
  const count = Math.min(baseCount, cfg.maxPuffsPerRegion, Math.max(0, budget.left));
  if (count <= 0) return;
  const layerCfg = LAYER_CONFIG[region.layer] || LAYER_CONFIG.mid;
  const style = styleForFamily(family, region.meanDensity);
  const heading = windHeading(region.driftU, region.driftV);
  const latSpan = Math.max(0.03, (region.extent.maxLat - region.extent.minLat) * 0.6);
  const lonSpan = Math.max(0.03, (region.extent.maxLon - region.extent.minLon) * 0.6);
  for (let i = 0; i < count; i += 1) {
    const fx = ((i * 37) % 100) / 100;
    const fy = ((i * 61) % 100) / 100;
    const lat = region.center.lat + (fy - 0.5) * latSpan * 1.3;
    const lon = region.center.lon + (fx - 0.5) * lonSpan * 1.3;
    const alt = layerCfg.baseAlt + ((i % 5) / 4) * (layerCfg.topAlt - layerCfg.baseAlt) * style.vertical;
    const puff = createPolygon3D({
      path: polygonEllipse(lat, lon, latSpan * 0.22, lonSpan * 0.22, 8, heading),
      altitude: alt,
      altitudeMode: 'absolute',
      fillColor: style.color,
      fillOpacity: style.puffAlpha,
      strokeColor: style.color,
      strokeOpacity: 0,
      strokeWidth: 0,
      extrudedHeight: 120,
    });
    if (!puff) continue;
    pool.created.push(puff);
    pool.drift.push({ el: puff, u: region.driftU, v: region.driftV, lat, lon, latOff: 0, lonOff: 0, basePath: puff.path });
    budget.left -= 1;
    if (budget.left <= 0) break;
  }
}

function startDrift(items) {
  if (!items.length) return () => {};
  let raf = 0;
  let last = 0;
  let stop = false;
  const tick = (ts) => {
    if (stop) return;
    if (!last) last = ts;
    const dt = clamp((ts - last) / 1000, 0.01, 0.12);
    last = ts;
    for (const it of items) {
      it.latOff += (it.v * dt) / 111320;
      const lonScale = Math.max(0.2, Math.cos((it.lat * Math.PI) / 180));
      it.lonOff += (it.u * dt) / (111320 * lonScale);
      try {
        it.el.path = (it.basePath || []).map((p) => ({ lat: p.lat + it.latOff, lng: p.lng + it.lonOff, altitude: p.altitude }));
      } catch (_) {}
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => { stop = true; if (raf) cancelAnimationFrame(raf); };
}

export function renderCloudZones({ payload, map3DElement }) {
  if (!map3DElement || !payload || !payload.grid) return () => {};
  const started = performance.now();
  const lod = inferLod(payload);
  const budget = { ...BUDGETS[lod], left: BUDGETS[lod].maxPuffs };

  const low = to2D(payload.grid.low);
  const mid = to2D(payload.grid.mid);
  const high = to2D(payload.grid.high);
  const total = to2D(payload.grid.total);
  const windU = to2D(payload?.wind?.u);
  const windV = to2D(payload?.wind?.v);
  const gridRef = total.length ? total : (low.length ? low : (mid.length ? mid : high));
  const ny = gridRef.length;
  const nx = ny ? gridRef[0].length : 0;
  if (!ny || !nx) return () => {};

  console.info('[gfs clouds] payload received', { cells: ny * nx, lod, source: payload.source, analysis_time: payload.analysis_time });

  const regions = [
    ...regionExtract('low', low.length ? low : gridRef, LAYER_CONFIG.low.threshold, payload.grid.lats, payload.grid.lons, payload.bbox, windU, windV, budget.maxRegions),
    ...regionExtract('mid', mid.length ? mid : gridRef, LAYER_CONFIG.mid.threshold, payload.grid.lats, payload.grid.lons, payload.bbox, windU, windV, budget.maxRegions),
    ...regionExtract('high', high.length ? high : gridRef, LAYER_CONFIG.high.threshold, payload.grid.lats, payload.grid.lons, payload.bbox, windU, windV, budget.maxRegions),
  ].slice(0, budget.maxRegions);

  console.info('[gfs clouds] regions extracted', { count: regions.length, lod });

  const created = [];
  const drift = [];
  const frag = document.createDocumentFragment();
  let hulls = 0;

  for (const region of regions) {
    if (hulls >= budget.maxHulls) break;
    const ci = clamp(Math.round((region.extent.minLat + region.extent.maxLat) / 2), -90, 90);
    const cj = clamp(Math.round((region.extent.minLon + region.extent.maxLon) / 2), -180, 180);
    const totalVal = toNum(total?.[0]?.[0], region.meanDensity);
    const family = classify(region, totalVal, region.meanDensity, region.meanDensity, region.meanDensity);
    const layerCfg = LAYER_CONFIG[region.layer] || LAYER_CONFIG.mid;
    const style = styleForFamily(family, region.meanDensity);
    const hull = createPolygon3D({
      path: hullPath(region),
      altitude: layerCfg.baseAlt,
      altitudeMode: 'absolute',
      fillColor: style.color,
      fillOpacity: style.alpha,
      strokeColor: style.color,
      strokeOpacity: 0,
      strokeWidth: 0,
      extrudedHeight: Math.max(180, layerCfg.topAlt - layerCfg.baseAlt),
    });
    if (!hull) continue;
    frag.append(hull);
    created.push(hull);
    drift.push({ el: hull, u: region.driftU * 0.35, v: region.driftV * 0.35, lat: ci, lon: cj, latOff: 0, lonOff: 0, basePath: hull.path });
    hulls += 1;

    spawnPuffs(region, family, lod, budget, { created, drift });
  }

  map3DElement.append(frag);
  const stop = startDrift(drift);
  console.info('[gfs clouds] hulls rendered', { count: hulls, lod });
  console.info('[gfs clouds] puffs active', { count: created.length - hulls, cap: BUDGETS[lod].maxPuffs, lod });
  console.info('[gfs clouds] refresh ms', { ms: Number((performance.now() - started).toFixed(1)), lod });

  return () => {
    stop();
    for (const el of created) {
      try { el.remove(); } catch (_) {}
    }
  };
}

export function estimateCloudColumnAltitudes(cloudTotal = 0, layerMix = {}) {
  const low = toNum(layerMix.low, cloudTotal * 0.6);
  const mid = toNum(layerMix.mid, cloudTotal * 0.4);
  const high = toNum(layerMix.high, cloudTotal * 0.2);
  const dominant = high >= Math.max(low, mid) ? 'high' : (mid >= low ? 'mid' : 'low');
  const cfg = LAYER_CONFIG[dominant] || LAYER_CONFIG.mid;
  return {
    cloudBaseAltitude: cfg.baseAlt,
    cloudTopAltitude: cfg.topAlt,
    dominantBand: dominant,
    family: dominant === 'high' ? 'cirrus' : 'stratus',
    subtype: dominant,
  };
}
