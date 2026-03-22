import { normalizePolygonFieldPayload } from './polygon_math.js';
import { createPolygon3D } from './polygon3d.js';

const CLOUD_PRESSURE_BANDS = {
  low: { baseHpa: 940, topHpa: 760, threshold: 20, color: '#dcefff' },
  mid: { baseHpa: 760, topHpa: 520, threshold: 18, color: '#eef6ff' },
  high: { baseHpa: 520, topHpa: 220, threshold: 14, color: '#ffffff' },
  total: { baseHpa: 880, topHpa: 520, threshold: 35, color: '#e9f4ff' },
};
const MAX_CLOUD_BODIES = 280;
const MAX_ADVECTION_STEP_SEC = 0.08;

function polygonApiPath() {
  return window.google?.maps?.maps3d?.Polygon3DElement ? 'Polygon3DElement.path' : 'gmp-polygon-3d.path';
}

function toNumber(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
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

function cloudFeaturesFromContract(payload) {
  return normalizePolygonFieldPayload(payload?.polygon_field_v1 || null);
}

function cellSizeDeg(bbox, ny, nx) {
  return {
    lat: Math.abs((bbox.north - bbox.south) / Math.max(1, ny)),
    lon: Math.abs((bbox.east - bbox.west) / Math.max(1, nx)),
  };
}

function hashJitter(lat, lon, salt = 0) {
  const v = Math.sin((lat * 12.9898) + (lon * 78.233) + (salt * 19.19)) * 43758.5453;
  return v - Math.floor(v);
}

function pressureToHeightMeters(hpa) {
  const pressure = clamp(toNumber(hpa, 1013.25), 80, 1050);
  return 44330 * (1 - Math.pow(pressure / 1013.25, 0.1903));
}

function metersToLatDegrees(meters) {
  return meters / 111320;
}

function metersToLonDegrees(meters, lat) {
  const lonScale = Math.max(0.2, Math.cos((Number(lat) * Math.PI) / 180));
  return meters / (111320 * lonScale);
}

function advectPath(basePath, latOffsetDeg, lonOffsetDeg) {
  return basePath.map((point) => ({
    lat: point.lat + latOffsetDeg,
    lng: wrapLongitude(point.lng + lonOffsetDeg),
  }));
}

function roundedCloudPath({ lat, lon, latRadiusDeg, lonRadiusDeg, wobble = 0.18, points = 14, elongation = 1, headingDeg = 90 }) {
  const path = [];
  const basePhase = hashJitter(lat, lon) * Math.PI * 2;
  const heading = (headingDeg * Math.PI) / 180;
  const cosH = Math.cos(heading);
  const sinH = Math.sin(heading);
  for (let i = 0; i < points; i += 1) {
    const t = (i / points) * Math.PI * 2;
    const harmonic = Math.sin((t * 2) + basePhase) * wobble;
    const secondary = Math.cos((t * 3) - basePhase) * (wobble * 0.55);
    const scale = 1 + harmonic + secondary;
    const localLat = Math.sin(t) * latRadiusDeg * scale;
    const localLon = Math.cos(t) * lonRadiusDeg * scale * elongation;
    const rotLat = (localLat * cosH) - (localLon * sinH);
    const rotLon = (localLat * sinH) + (localLon * cosH);
    path.push({ lat: lat + rotLat, lng: lon + rotLon });
  }
  return path;
}

function buildCloudPressureBand(type, density, totalBoost, family = 'stratiform') {
  const band = CLOUD_PRESSURE_BANDS[type] || CLOUD_PRESSURE_BANDS.total;
  const weight = clamp(density / 100, 0, 1);
  const deepening = clamp((totalBoost - 0.82) / 0.45, 0, 1);
  const familyStretch = family === 'vertical' ? 1.3 : (family === 'cumuliform' ? 1.14 : (family === 'cirriform' ? 0.78 : 0.96));
  const baseHpa = band.baseHpa - ((band.baseHpa - band.topHpa) * weight * 0.16);
  const topHpa = band.topHpa - ((band.topHpa * 0.07) * deepening * weight * familyStretch);
  const baseAltitude = pressureToHeightMeters(baseHpa);
  const topAltitude = pressureToHeightMeters(topHpa);
  return {
    baseAltitude: Math.round(baseAltitude),
    height: Math.max(600, Math.round((topAltitude - baseAltitude) * familyStretch)),
    color: band.color,
    weight,
  };
}

function classifyCloudMorphology(feature) {
  const low = toNumber(feature?.cloud_low, 0);
  const mid = toNumber(feature?.cloud_mid, 0);
  const high = toNumber(feature?.cloud_high, 0);
  const total = toNumber(feature?.cloud_total, Math.max(low, mid, high));
  const precip = toNumber(feature?.precip_rate, 0);
  const dominant = high >= Math.max(low, mid) ? 'high' : (mid >= low ? 'mid' : 'low');

  if (precip >= 0.85 && total >= 72) return { family: 'vertical', subtype: 'cumulonimbus' };
  if (precip >= 0.35 && mid >= 45 && total >= 68) return { family: 'stratiform', subtype: 'nimbostratus' };
  if (high >= 58 && low < 35 && mid < 45) return { family: 'cirriform', subtype: high >= 78 ? 'cirrostratus' : 'cirrus' };
  if (low >= 58 && total < 75) return { family: 'cumuliform', subtype: low >= 78 ? 'towering-cumulus' : 'cumulus' };
  if (dominant === 'mid' && total >= 62) return { family: 'stratiform', subtype: 'altostratus' };
  return { family: 'stratiform', subtype: total >= 60 ? 'stratus' : 'stratocumulus' };
}

function shellBlueprints(morphology) {
  switch (morphology.family) {
    case 'cirriform':
      return [
        { shell: 'veil', latScale: 0.82, lonScale: 1.8, opacityBase: 0.07, opacitySpan: 0.08, wobble: 0.12, points: 16, elongation: 1.6 },
        { shell: 'streak', latScale: 0.56, lonScale: 1.45, opacityBase: 0.04, opacitySpan: 0.06, wobble: 0.08, points: 12, elongation: 1.9 },
      ];
    case 'vertical':
      return [
        { shell: 'core', latScale: 0.72, lonScale: 0.76, opacityBase: 0.16, opacitySpan: 0.18, wobble: 0.2, points: 14, elongation: 1.0 },
        { shell: 'tower', latScale: 0.5, lonScale: 0.54, opacityBase: 0.14, opacitySpan: 0.14, wobble: 0.24, points: 12, elongation: 0.92, baseLift: 0.22, heightBoost: 0.42 },
        { shell: 'anvil', latScale: 0.96, lonScale: 1.42, opacityBase: 0.08, opacitySpan: 0.1, wobble: 0.16, points: 16, elongation: 1.25, baseLift: 0.78, heightBoost: 0.18 },
      ];
    case 'cumuliform':
      return [
        { shell: 'body', latScale: 0.7, lonScale: 0.84, opacityBase: 0.12, opacitySpan: 0.2, wobble: 0.24, points: 14, elongation: 1.0 },
        { shell: 'tuft', latScale: 0.46, lonScale: 0.5, opacityBase: 0.08, opacitySpan: 0.14, wobble: 0.3, points: 11, elongation: 0.94, baseLift: 0.38, heightBoost: 0.26 },
      ];
    default:
      return [
        { shell: 'deck', latScale: 0.96, lonScale: 1.3, opacityBase: 0.11, opacitySpan: 0.16, wobble: 0.14, points: 16, elongation: 1.18 },
        { shell: 'underside', latScale: 0.82, lonScale: 1.08, opacityBase: 0.06, opacitySpan: 0.1, wobble: 0.1, points: 14, elongation: 1.12, baseLift: 0.14, heightBoost: 0.08 },
      ];
  }
}

function cloudBodiesForFeature(feature, footprintScale) {
  const low = toNumber(feature?.cloud_low, 0);
  const mid = toNumber(feature?.cloud_mid, 0);
  const high = toNumber(feature?.cloud_high, 0);
  const total = toNumber(feature?.cloud_total, Math.max(low, mid, high));
  const totalBoost = clamp(total / 100, 0.82, 1.25);
  const morphology = classifyCloudMorphology(feature);
  const blueprints = shellBlueprints(morphology);
  const layers = [];

  const appendLayer = (type, density) => {
    const band = buildCloudPressureBand(type, density, totalBoost, morphology.family);
    const weight = band.weight;
    if (weight <= 0) return;
    for (const bp of blueprints) {
      layers.push({
        baseAltitude: Math.round(band.baseAltitude + (band.height * (bp.baseLift || 0))),
        height: Math.round(band.height * (1 + (bp.heightBoost || 0))),
        opacity: Math.min(bp.opacityBase + (weight * bp.opacitySpan), 0.58),
        latRadiusDeg: footprintScale.lat * (bp.latScale + (weight * 0.42)),
        lonRadiusDeg: footprintScale.lon * (bp.lonScale + (weight * 0.48)),
        color: band.color,
        pressureBand: type,
        family: morphology.family,
        subtype: morphology.subtype,
        wobble: bp.wobble,
        points: bp.points,
        elongation: bp.elongation,
        shell: bp.shell,
      });
    }
  };

  if (low >= CLOUD_PRESSURE_BANDS.low.threshold) appendLayer('low', low);
  if (mid >= CLOUD_PRESSURE_BANDS.mid.threshold) appendLayer('mid', mid);
  if (high >= CLOUD_PRESSURE_BANDS.high.threshold) appendLayer('high', high);
  if (!layers.length && total >= CLOUD_PRESSURE_BANDS.total.threshold) appendLayer('total', total);
  return layers;
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

function windHeadingDeg(u, v) {
  if (!Number.isFinite(u) || !Number.isFinite(v)) return 90;
  return ((Math.atan2(u, v) * 180 / Math.PI) + 360) % 360;
}

function makeCloudBody({ lat, lon, baseAltitude, height, latRadiusDeg, lonRadiusDeg, color, opacity, windU = 0, windV = 0, family = 'stratiform', wobble = 0.16, points = 14, elongation = 1.0 }) {
  const headingDeg = windHeadingDeg(windU, windV);
  const basePath = roundedCloudPath({ lat, lon, latRadiusDeg, lonRadiusDeg, wobble, points, elongation: family === 'cirriform' ? Math.max(1.25, elongation) : elongation, headingDeg });
  const element = createPolygon3D({
    path: basePath,
    altitude: baseAltitude,
    altitudeMode: 'absolute',
    fillColor: color,
    fillOpacity: opacity,
    strokeColor: color,
    strokeOpacity: 0,
    strokeWidth: 0,
    extrudedHeight: height,
  });
  if (!element) return null;
  return {
    element,
    basePath,
    anchorLat: lat,
    anchorLon: lon,
    windU: toNumber(windU, 0),
    windV: toNumber(windV, 0),
    latOffsetDeg: 0,
    lonOffsetDeg: 0,
  };
}

function startCloudAdvection(items) {
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
      item.latOffsetDeg += metersToLatDegrees(item.windV * dtSec);
      item.lonOffsetDeg += metersToLonDegrees(item.windU * dtSec, item.anchorLat + item.latOffsetDeg);
      item.element.path = advectPath(item.basePath, item.latOffsetDeg, item.lonOffsetDeg);
    }
    rafId = requestAnimationFrame(tick);
  };

  rafId = requestAnimationFrame(tick);
  return () => {
    stopped = true;
    if (rafId) cancelAnimationFrame(rafId);
  };
}

export function estimateCloudColumnAltitudes(cloudTotal = 0, layerMix = {}) {
  const low = toNumber(layerMix.low, 0);
  const mid = toNumber(layerMix.mid, 0);
  const high = toNumber(layerMix.high, 0);
  const total = Math.max(cloudTotal, low, mid, high);
  const dominant = high >= Math.max(mid, low) && high >= 16
    ? 'high'
    : (mid >= Math.max(low, high) && mid >= 18 ? 'mid' : (low >= 20 ? 'low' : 'total'));
  const morphology = classifyCloudMorphology({ cloud_low: low, cloud_mid: mid, cloud_high: high, cloud_total: total });
  const band = buildCloudPressureBand(dominant, total, clamp(total / 100, 0.82, 1.24), morphology.family);
  return {
    cloudBaseAltitude: band.baseAltitude,
    cloudTopAltitude: band.baseAltitude + band.height,
    dominantBand: dominant,
    family: morphology.family,
    subtype: morphology.subtype,
  };
}

export function renderCloudZones({ payload, map3DElement }) {
  const created = [];
  const advected = [];
  if (!map3DElement || !payload) return () => {};
  console.info('[gfs clouds] polygon api', { api: polygonApiPath() });

  const bbox = bboxFromPayload(payload);
  if (!bbox) return () => {};

  const contractFeatures = cloudFeaturesFromContract(payload);
  if (contractFeatures.length) {
    const frag = document.createDocumentFragment();
    let bodyCount = 0;
    for (let i = 0; i < contractFeatures.length; i += 1) {
      const feature = contractFeatures[i]?.properties || contractFeatures[i] || {};
      const lat = toNumber(feature.lat, NaN);
      const lon = toNumber(feature.lon, NaN);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const footprint = { lat: Math.max(toNumber(feature.cell_lat_deg, 0.12) * 0.94, 0.05), lon: Math.max(toNumber(feature.cell_lon_deg, 0.12) * 0.94, 0.05) };
      const layers = cloudBodiesForFeature(feature, footprint);
      for (const layer of layers) {
        const body = makeCloudBody({ lat, lon, windU: feature.wind_u, windV: feature.wind_v, ...layer });
        if (!body) continue;
        frag.append(body.element);
        created.push(body.element);
        advected.push(body);
        bodyCount += 1;
        if (bodyCount >= MAX_CLOUD_BODIES) break;
      }
      if (bodyCount >= MAX_CLOUD_BODIES) break;
    }
    map3DElement.append(frag);
    const stopAdvection = startCloudAdvection(advected);
    console.info('[gfs clouds] rendered bodies', { bodies: bodyCount, mode: 'meteorological_family_uv_advected' });
    return () => {
      stopAdvection();
      created.forEach((el) => { try { el.remove(); } catch (_) {} });
    };
  }

  const low = to2DGrid(payload?.cloud_layers?.find((l) => l?.name === 'low')?.density);
  const mid = to2DGrid(payload?.cloud_layers?.find((l) => l?.name === 'mid')?.density);
  const high = to2DGrid(payload?.cloud_layers?.find((l) => l?.name === 'high')?.density);
  const total = to2DGrid(payload?.fields?.cloud_total || payload?.cloud_cover);
  const precip = to2DGrid(payload?.fields?.precip_rate || payload?.fields?.prate);
  const windUGrid = to2DGrid(payload?.fields?.wind_u);
  const windVGrid = to2DGrid(payload?.fields?.wind_v);
  const grid = low.length ? low : (mid.length ? mid : (high.length ? high : total));
  if (!grid.length) return () => {};

  const ny = grid.length;
  const nx = Array.isArray(grid[0]) ? grid[0].length : 0;
  if (!ny || !nx) return () => {};

  const step = Math.max(1, Math.floor(Math.max(nx, ny) / 26));
  const cell = cellSizeDeg(bbox, ny, nx);
  const frag = document.createDocumentFragment();
  let bodyCount = 0;
  let cellCount = 0;

  for (let i = 0; i < ny; i += step) {
    for (let j = 0; j < nx; j += step) {
      const lowVal = toNumber(low?.[i]?.[j], 0);
      const midVal = toNumber(mid?.[i]?.[j], 0);
      const highVal = toNumber(high?.[i]?.[j], 0);
      const precipVal = toNumber(precip?.[i]?.[j], 0);
      const totalVal = toNumber(total?.[i]?.[j], Math.max(lowVal, midVal, highVal));
      if (totalVal < 22 && precipVal < 0.06 && lowVal < 18 && midVal < 16 && highVal < 14) continue;
      const { lat, lon } = latLonFromIndex(i, j, ny, nx, bbox);
      const layers = cloudBodiesForFeature({ lat, lon, cloud_low: lowVal, cloud_mid: midVal, cloud_high: highVal, cloud_total: totalVal, precip_rate: precipVal }, {
        lat: Math.max(cell.lat * 0.92, 0.05),
        lon: Math.max(cell.lon * 0.92, 0.05),
      });
      const sampledWindU = sampleGridBilinear(windUGrid, bbox, lat, lon);
      const sampledWindV = sampleGridBilinear(windVGrid, bbox, lat, lon);
      for (const layer of layers) {
        const body = makeCloudBody({ lat, lon, windU: sampledWindU, windV: sampledWindV, ...layer });
        if (!body) continue;
        frag.append(body.element);
        created.push(body.element);
        advected.push(body);
        bodyCount += 1;
        if (bodyCount >= MAX_CLOUD_BODIES) break;
      }
      cellCount += 1;
      if (bodyCount >= MAX_CLOUD_BODIES) break;
    }
    if (bodyCount >= MAX_CLOUD_BODIES) break;
  }

  map3DElement.append(frag);
  const stopAdvection = startCloudAdvection(advected);
  console.info('[gfs clouds] rendered bodies', { cells: cellCount, bodies: bodyCount, mode: 'meteorological_family_uv_advected' });

  return () => {
    stopAdvection();
    created.forEach((el) => { try { el.remove(); } catch (_) {} });
  };
}
