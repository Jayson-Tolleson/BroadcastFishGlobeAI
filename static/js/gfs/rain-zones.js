import { estimateCloudColumnAltitudes } from './cloud-zones.js';

const MAX_MARKERS_PER_FRAME = 84;
const MAX_COLUMNS = 140;
const MAX_ADVECTION_STEP_SEC = 0.08;
const RAIN_FALL_SPEED_MPS = 7.4;

function polygonApiPath() {
  return 'gmp-marker-3d.template.svg';
}

function toNumber(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function to2DGrid(value) {
  if (!Array.isArray(value)) return [];
  if (!Array.isArray(value[0])) return [];
  if (Array.isArray(value[0][0])) return value[0];
  return value;
}

function bboxFromPayload(payload) {
  const box = Array.isArray(payload?.bbox) ? payload.bbox : null;
  if (!box || box.length < 4) return null;
  return { west: toNumber(box[0]), south: toNumber(box[1]), east: toNumber(box[2]), north: toNumber(box[3]) };
}

function latLonFromIndex(i, j, ny, nx, bbox) {
  const lat = bbox.south + ((i + 0.5) / Math.max(1, ny)) * (bbox.north - bbox.south);
  const lon = bbox.west + ((j + 0.5) / Math.max(1, nx)) * (bbox.east - bbox.west);
  return { lat, lon };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function wrapLongitude(lon) {
  let value = Number(lon) || 0;
  while (value < -180) value += 360;
  while (value >= 180) value -= 360;
  return value;
}

function uniqueId(prefix = 'rain') {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function metersToLatDegrees(meters) {
  return meters / 111320;
}

function metersToLonDegrees(meters, lat) {
  const lonScale = Math.max(0.2, Math.cos((Number(lat) * Math.PI) / 180));
  return meters / (111320 * lonScale);
}

function sampleGridBilinear(grid, bbox, lat, lon) {
  if (!Array.isArray(grid) || !Array.isArray(grid[0]) || !bbox) return null;
  const arr = Array.isArray(grid[0][0]) ? grid[0] : grid;
  const ny = arr.length;
  const nx = Array.isArray(arr[0]) ? arr[0].length : 0;
  if (!ny || !nx) return null;
  const y = clamp(((lat - bbox.south) / Math.max(1e-6, bbox.north - bbox.south)) * (ny - 1), 0, ny - 1);
  const x = clamp(((lon - bbox.west) / Math.max(1e-6, bbox.east - bbox.west)) * (nx - 1), 0, nx - 1);
  const y0 = Math.floor(y);
  const x0 = Math.floor(x);
  const y1 = Math.min(ny - 1, y0 + 1);
  const x1 = Math.min(nx - 1, x0 + 1);
  const fy = y - y0;
  const fx = x - x0;
  const q11 = toNumber(arr[y0]?.[x0], NaN);
  const q21 = toNumber(arr[y0]?.[x1], q11);
  const q12 = toNumber(arr[y1]?.[x0], q11);
  const q22 = toNumber(arr[y1]?.[x1], q21);
  if (![q11, q21, q12, q22].every(Number.isFinite)) return null;
  return (q11 * (1 - fx) * (1 - fy)) + (q21 * fx * (1 - fy)) + (q12 * (1 - fx) * fy) + (q22 * fx * fy);
}

function rainStyleForRate(rate) {
  if (rate <= 0.08) return { color: '#ffffff', size: 14, opacity: 0.82, label: 'trace' };
  if (rate <= 0.2) return { color: '#4db2ff', size: 16, opacity: 0.84, label: 'light' };
  if (rate <= 0.45) return { color: '#35d16f', size: 18, opacity: 0.86, label: 'moderate' };
  if (rate <= 0.75) return { color: '#ffd84d', size: 20, opacity: 0.88, label: 'fresh' };
  if (rate <= 1.2) return { color: '#ff9a3d', size: 22, opacity: 0.9, label: 'heavy' };
  if (rate <= 2.0) return { color: '#ff4d4f', size: 24, opacity: 0.92, label: 'very_heavy' };
  return { color: '#111111', size: 26, opacity: 0.96, label: 'extreme' };
}

function makeSphereTemplate(rate) {
  const style = rainStyleForRate(rate);
  const uid = uniqueId('rain-sphere');
  const tpl = document.createElement('template');
  tpl.innerHTML = `
    <svg width="${style.size}" height="${style.size}" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="pointer-events:none">
      <defs>
        <radialGradient id="${uid}-core" cx="32%" cy="28%" r="70%">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.98"/>
          <stop offset="38%" stop-color="${style.color}" stop-opacity="0.95"/>
          <stop offset="100%" stop-color="#03131d" stop-opacity="0.58"/>
        </radialGradient>
        <radialGradient id="${uid}-halo" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="${style.color}" stop-opacity="0.46"/>
          <stop offset="100%" stop-color="${style.color}" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <circle cx="24" cy="24" r="18" fill="url(#${uid}-halo)" fill-opacity="${style.opacity.toFixed(2)}"/>
      <circle cx="24" cy="24" r="11.5" fill="url(#${uid}-core)"/>
      <ellipse cx="19" cy="17" rx="4.2" ry="2.4" fill="#ffffff" fill-opacity="0.82" transform="rotate(-24 19 17)"/>
    </svg>`;
  return tpl;
}

function createRainMarker({ lat, lon, altitude, rate }) {
  const marker = document.createElement('gmp-marker-3d');
  marker.position = { lat, lng: lon, altitude };
  marker.drawsWhenOccluded = true;
  marker.sizePreserved = true;
  marker.append(makeSphereTemplate(rate));
  return marker;
}

function buildRainColumn({ lat, lon, precipRate, cloudTotal, layerMix, windU = 0, windV = 0 }) {
  const cloudAltitudes = estimateCloudColumnAltitudes(cloudTotal, layerMix);
  const topAltitude = Math.max(900, Math.round(cloudAltitudes.cloudTopAltitude - 180));
  const bottomAltitude = Math.max(160, Math.round(cloudAltitudes.cloudBaseAltitude * 0.16));
  const drops = clamp(Math.round(3 + (precipRate * 4.8)), 3, 11);
  const spacing = (topAltitude - bottomAltitude) / Math.max(1, drops - 1);
  const lateralSpread = 0.008 + Math.min(0.04, precipRate * 0.024);
  const markers = [];
  for (let idx = 0; idx < drops; idx += 1) {
    const phase = idx / Math.max(1, drops - 1);
    const latOffset = Math.sin((phase * Math.PI * 2) + (lat * 0.7)) * lateralSpread * 0.35;
    const lonOffset = Math.cos((phase * Math.PI * 2) + (lon * 0.7)) * lateralSpread * 0.45;
    markers.push({
      lat: lat + latOffset,
      lon: lon + lonOffset,
      anchorLat: lat + latOffset,
      anchorLon: lon + lonOffset,
      altitude: Math.round(topAltitude - (spacing * idx)),
      topAltitude,
      bottomAltitude,
      fallPhase: phase,
      rate: precipRate,
      windU: toNumber(windU, 0),
      windV: toNumber(windV, 0),
      latOffsetDeg: 0,
      lonOffsetDeg: 0,
    });
  }
  return markers;
}

function startFrameBatch({ queue, map3DElement, created, advected }) {
  let rafId = null;
  let disposed = false;

  const pump = () => {
    if (disposed) return;
    let injected = 0;
    const frag = document.createDocumentFragment();
    while (queue.length && injected < MAX_MARKERS_PER_FRAME) {
      const item = queue.shift();
      const marker = createRainMarker(item);
      item.marker = marker;
      frag.append(marker);
      created.push(marker);
      advected.push(item);
      injected += 1;
    }
    if (injected) map3DElement.append(frag);
    if (queue.length) rafId = requestAnimationFrame(pump);
  };

  rafId = requestAnimationFrame(pump);
  return () => {
    disposed = true;
    if (rafId) cancelAnimationFrame(rafId);
  };
}

function startRainAdvection(items) {
  if (!items.length) return () => {};
  let rafId = 0;
  let stopped = false;
  let lastTs = 0;

  const tick = (ts) => {
    if (stopped) return;
    if (!lastTs) lastTs = ts;
    const dtSec = Math.min(MAX_ADVECTION_STEP_SEC, Math.max(0.01, (ts - lastTs) * 0.001));
    lastTs = ts;
    for (const item of items) {
      if (!item.marker) continue;
      item.latOffsetDeg += metersToLatDegrees(item.windV * dtSec);
      item.lonOffsetDeg += metersToLonDegrees(item.windU * dtSec, item.anchorLat + item.latOffsetDeg);
      item.fallPhase = (item.fallPhase + ((RAIN_FALL_SPEED_MPS * dtSec) / Math.max(120, item.topAltitude - item.bottomAltitude))) % 1;
      const altitude = item.topAltitude - ((item.topAltitude - item.bottomAltitude) * item.fallPhase);
      item.marker.position = {
        lat: item.anchorLat + item.latOffsetDeg,
        lng: wrapLongitude(item.anchorLon + item.lonOffsetDeg),
        altitude: Math.max(item.bottomAltitude, Math.round(altitude)),
      };
    }
    rafId = requestAnimationFrame(tick);
  };

  rafId = requestAnimationFrame(tick);
  return () => {
    stopped = true;
    if (rafId) cancelAnimationFrame(rafId);
  };
}

export function renderRainZones({ payload, map3DElement, viewportReason = 'steady' }) {
  const created = [];
  const advected = [];
  if (!map3DElement || !payload?.fields) return () => {};
  console.info('[gfs rain] polygon api', { api: polygonApiPath() });
  if (viewportReason !== 'steady') {
    console.info('[gfs rain] suppressed render', { reason: viewportReason });
    return () => {};
  }

  const bbox = bboxFromPayload(payload);
  if (!bbox) return () => {};

  const queue = [];
  const columns = [];
  const contractFeatures = Array.isArray(payload?.polygon_field_v1?.features) ? payload.polygon_field_v1.features : [];
  const windUGrid = to2DGrid(payload?.fields?.wind_u);
  const windVGrid = to2DGrid(payload?.fields?.wind_v);
  if (contractFeatures.length) {
    const count = Math.min(contractFeatures.length, 200);
    for (let i = 0; i < count; i += 1) {
      const f = contractFeatures[i]?.properties || contractFeatures[i] || {};
      const precipRate = Math.max(0, toNumber(f.precip_rate, 0));
      if (precipRate <= 0.03) continue;
      const lat = toNumber(f.lat, NaN);
      const lon = toNumber(f.lon, NaN);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const columnMarkers = buildRainColumn({
        lat,
        lon,
        precipRate,
        cloudTotal: Math.max(0, toNumber(f.cloud_total, 0)),
        layerMix: { low: toNumber(f.cloud_low, 0), mid: toNumber(f.cloud_mid, 0), high: toNumber(f.cloud_high, 0) },
        windU: sampleGridBilinear(windUGrid, bbox, lat, lon),
        windV: sampleGridBilinear(windVGrid, bbox, lat, lon),
      });
      queue.push(...columnMarkers);
      columns.push({ lat, lon, precipRate, drops: columnMarkers.length });
      if (columns.length >= MAX_COLUMNS) break;
    }
  } else {
    const precip = to2DGrid(payload?.fields?.precip_rate || payload?.fields?.prate);
    const clouds = to2DGrid(payload?.fields?.cloud_total);
    if (!precip.length) return () => {};
    const ny = precip.length;
    const nx = Array.isArray(precip[0]) ? precip[0].length : 0;
    const step = Math.max(1, Math.floor(Math.max(nx, ny) / 22));
    for (let i = 0; i < ny; i += step) {
      for (let j = 0; j < nx; j += step) {
        const precipRate = Math.max(0, toNumber(precip?.[i]?.[j], 0));
        if (precipRate <= 0.03) continue;
        const { lat, lon } = latLonFromIndex(i, j, ny, nx, bbox);
        const cloudTotal = Math.max(0, toNumber(clouds?.[i]?.[j], 0));
        const columnMarkers = buildRainColumn({
          lat,
          lon,
          precipRate,
          cloudTotal,
          layerMix: { low: cloudTotal * 0.55, mid: cloudTotal * 0.4, high: cloudTotal * 0.2 },
          windU: sampleGridBilinear(windUGrid, bbox, lat, lon),
          windV: sampleGridBilinear(windVGrid, bbox, lat, lon),
        });
        queue.push(...columnMarkers);
        columns.push({ lat, lon, precipRate, drops: columnMarkers.length });
        if (columns.length >= MAX_COLUMNS) break;
      }
      if (columns.length >= MAX_COLUMNS) break;
    }
  }

  const stopBatch = startFrameBatch({ queue, map3DElement, created, advected });
  const stopAdvection = startRainAdvection(advected);
  console.info('[gfs rain] queued columns', { columns: columns.length, markers: queue.length, batchSize: MAX_MARKERS_PER_FRAME, mode: 'cloud_anchor_uv_advected_falling' });
  return () => {
    stopBatch();
    stopAdvection();
    created.forEach((el) => { try { el.remove(); } catch (_) {} });
  };
}
