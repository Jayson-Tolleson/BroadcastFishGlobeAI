import { normalizePolygonFieldPayload } from './polygon_math.js';
import { clamp01 } from './greek_math.js';
import { createPolygon3D } from './polygon3d.js';

const MAX_POLYGONS_PER_FRAME = 54;

function polygonApiPath() {
  return window.google?.maps?.maps3d?.Polygon3DElement ? 'Polygon3DElement.path' : 'gmp-polygon-3d.path';
}

function toNumber(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function clampProbability(value) {
  return clamp01(toNumber(value, 0));
}

function toHexByte(value) {
  const clamped = Math.max(0, Math.min(255, Math.round(value)));
  return clamped.toString(16).padStart(2, '0');
}

function rgbHex(r, g, b) {
  return `#${toHexByte(r)}${toHexByte(g)}${toHexByte(b)}`;
}

function interpolateColor(a, b, t) {
  const p = clampProbability(t);
  return {
    r: a.r + ((b.r - a.r) * p),
    g: a.g + ((b.g - a.g) * p),
    b: a.b + ((b.b - a.b) * p),
  };
}

function probabilityBaseColor(probability) {
  const p = clampProbability(probability);
  const red = { r: 255, g: 32, b: 32 };
  const yellow = { r: 255, g: 232, b: 64 };
  const green = { r: 64, g: 214, b: 92 };
  return p < 0.5
    ? interpolateColor(red, yellow, p / 0.5)
    : interpolateColor(yellow, green, (p - 0.5) / 0.5);
}

function probabilityColorRamp(probability) {
  const base = probabilityBaseColor(probability);
  const toLayerHex = (mix) => rgbHex(
    base.r + ((255 - base.r) * mix),
    base.g + ((255 - base.g) * mix),
    base.b + ((255 - base.b) * mix),
  );
  return {
    coreColor: toLayerHex(0),
    innerColor: toLayerHex(0.2),
    outerColor: toLayerHex(0.4),
  };
}

function sanitizePath(path) {
  const cleaned = [];
  for (const point of path || []) {
    const lat = Number(point?.lat);
    const lng = Number(point?.lng);
    const altitude = Number(point?.altitude ?? 20);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    const prev = cleaned[cleaned.length - 1];
    if (prev && Math.abs(prev.lat - lat) < 1e-6 && Math.abs(prev.lng - lng) < 1e-6) continue;
    cleaned.push({ lat, lng, altitude: Number.isFinite(altitude) ? altitude : 20 });
  }
  if (cleaned.length >= 2) {
    const first = cleaned[0];
    const last = cleaned[cleaned.length - 1];
    if (Math.abs(first.lat - last.lat) < 1e-6 && Math.abs(first.lng - last.lng) < 1e-6) {
      cleaned.pop();
    }
  }
  return cleaned;
}

function toPath(coords, altitude = 20) {
  if (!Array.isArray(coords)) return [];
  return sanitizePath(coords
    .filter((p) => Array.isArray(p) && p.length >= 2)
    .map((p) => ({ lat: toNumber(p[1]), lng: toNumber(p[0]), altitude })));
}

function makePolygonLayer(path, fillColor, fillOpacity, extrudedHeight) {
  return createPolygon3D({
    path,
    altitude: 20,
    altitudeMode: 'relative',
    fillColor,
    fillOpacity,
    strokeColor: fillColor,
    strokeOpacity: Math.min(fillOpacity + 0.08, 0.92),
    strokeWidth: 0.8,
    extrudedHeight,
  });
}

function makeLineOverlay(line) {
  const el = document.createElement('gmp-polyline-3d');
  const pts = Array.isArray(line?.coordinates) ? line.coordinates : [];
  const path = sanitizePath(pts
    .filter((p) => Array.isArray(p) && p.length >= 2)
    .map((p) => ({ lat: toNumber(p[1]), lng: toNumber(p[0]), altitude: 15 })));
  if (path.length < 2) return null;
  el.path = path;
  el.setAttribute('altitude-mode', 'relative-to-ground');
  el.setAttribute('stroke-color', '#ffe38d');
  el.setAttribute('stroke-width', '2');
  el.setAttribute('stroke-opacity', '0.85');
  return el;
}

function enqueuePolygonBand(queue, polygons, band) {
  (Array.isArray(polygons) ? polygons : []).forEach((poly) => {
    const path = toPath(poly?.coordinates, 20);
    if (path.length < 3) return;
    queue.push({
      path,
      probability: poly?.probability,
      band,
    });
  });
}

function startFrameBatch({ queue, map3DElement, created }) {
  let rafId = null;
  let disposed = false;

  const pump = () => {
    if (disposed) return;
    let injected = 0;
    const frag = document.createDocumentFragment();
    while (queue.length && injected < MAX_POLYGONS_PER_FRAME) {
      const poly = queue.shift();
      const p = clampProbability(poly?.probability);
      const { coreColor, innerColor, outerColor } = probabilityColorRamp(p);
      let el = null;
      if (poly.band === 'outer') {
        el = makePolygonLayer(poly.path, outerColor, 0.16, 28);
      } else if (poly.band === 'inner') {
        el = makePolygonLayer(poly.path, innerColor, 0.34, 48);
      } else {
        el = makePolygonLayer(poly.path, coreColor, 0.72, 72);
      }
      if (!el) continue;
      frag.append(el);
      created.push(el);
      injected += 1;
    }
    if (injected) {
      map3DElement.append(frag);
    }
    if (queue.length) {
      rafId = requestAnimationFrame(pump);
    }
  };

  rafId = requestAnimationFrame(pump);

  return () => {
    disposed = true;
    if (rafId) cancelAnimationFrame(rafId);
  };
}

export function renderBaitZones({ payload, map3DElement, viewportReason = 'steady' }) {
  const created = [];
  if (!map3DElement || !payload) return () => {};
  console.info('[gfs bait] polygon api', { api: polygonApiPath() });
  if (viewportReason !== 'steady') {
    console.info('[gfs bait] suppressed render', { reason: viewportReason });
    return () => {};
  }

  const bait = payload?.bait || {};
  const legacyPolygonField = payload?.polygon_field_v1;
  if (legacyPolygonField) {
    normalizePolygonFieldPayload(legacyPolygonField);
  }
  if (bait.status !== 'ready' || bait.source !== 'full_stack') {
    console.info('[gfs bait] suppressed render', { status: bait.status, source: bait.source });
    return () => {};
  }

  const outerPolygons = Array.isArray(bait.outer_polygons) ? bait.outer_polygons : [];
  const innerPolygons = Array.isArray(bait.inner_polygons) ? bait.inner_polygons : (Array.isArray(bait.polygons) ? bait.polygons : []);
  const corePolygons = Array.isArray(bait.core_polygons) ? bait.core_polygons : [];

  const polygonQueue = [];
  enqueuePolygonBand(polygonQueue, outerPolygons, 'outer');
  enqueuePolygonBand(polygonQueue, innerPolygons, 'inner');
  enqueuePolygonBand(polygonQueue, corePolygons, 'core');

  const frag = document.createDocumentFragment();
  const lines = Array.isArray(payload?.front_lines) ? payload.front_lines : [];
  lines.forEach((line) => {
    const el = makeLineOverlay(line);
    if (!el) return;
    frag.append(el);
    created.push(el);
  });
  if (created.length) {
    map3DElement.append(frag);
  }

  const stopBatch = startFrameBatch({ queue: polygonQueue, map3DElement, created });
  console.info('[gfs bait] queued full-stack polygons', {
    totalPolygons: polygonQueue.length,
    outer: outerPolygons.length,
    inner: innerPolygons.length,
    core: corePolygons.length,
    lines: lines.length,
    batchSize: MAX_POLYGONS_PER_FRAME,
  });

  return () => {
    stopBatch();
    created.forEach((el) => {
      try { el.remove(); } catch (_) {}
    });
  };
}
