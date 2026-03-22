import { getJsonSafe } from './api.js';

const BOAT_COUNT_MAX = 12;
const MODEL_SRC = '/static/models/boat_marker_26ft.glb';
const MODEL_SCALE = 7.9;
const MODEL_YAW_OFFSET_DEG = 0;
const LON_SCALE = 0.0045;
const LAT_SCALE = 0.0032;
const MAX_VISUAL_DRIFT_DEG = 1.6;
const MARKER_MIN_SCALE = 0.85;
const MARKER_MAX_SCALE = 2.8;
const RANGE_NEAR_M = 450000;
const RANGE_FAR_M = 3500000;

function maps3d() {
  return window.google?.maps?.maps3d || null;
}

function currentRangeMeters() {
  const globe = document.getElementById('globe');
  const raw = Number(globe?.getAttribute('range'));
  return Number.isFinite(raw) && raw > 0 ? raw : 1800000;
}

function visibleScaleForRange(rangeM) {
  const t = Math.max(0, Math.min(1, (Number(rangeM || RANGE_FAR_M) - RANGE_NEAR_M) / (RANGE_FAR_M - RANGE_NEAR_M)));
  return MARKER_MAX_SCALE - ((MARKER_MAX_SCALE - MARKER_MIN_SCALE) * t);
}

function colorForSafety(color) {
  if (color === 'red') return '#ff5f57';
  if (color === 'yellow') return '#ffd866';
  return '#57d46f';
}

function setHudContent(html) {
  const hud = document.getElementById('hudHoverWeather');
  if (hud) hud.innerHTML = html;
}

function formatSwell(label, swell) {
  if (!swell || (swell.heightFt == null && swell.periodS == null && swell.dirDeg == null)) return '';
  const bits = [];
  if (swell.heightFt != null) bits.push(`${swell.heightFt} ft`);
  if (swell.periodS != null) bits.push(`${swell.periodS} s`);
  if (swell.dirDeg != null) bits.push(`${swell.dirDeg}°`);
  return `<div><strong>${label}:</strong> ${bits.join(' / ')}</div>`;
}

function htmlForBoat(boat) {
  const row = (label, value) => value == null || value === '' ? '' : `<div><strong>${label}:</strong> ${value}</div>`;
  const waves = boat.waves || {};
  const marineStation = boat.marineStation?.id ? `${boat.marineStation.id}${boat.marineStation.distanceKm != null ? ` (${boat.marineStation.distanceKm} km)` : ''}` : null;
  return [
    '<div class="gfs-boat-hud">',
    row('Boating', `${(boat.safety?.color || 'unknown').toUpperCase()} — ${boat.safety?.label || 'Unavailable'}`),
    row('Current', boat.current?.speedKt != null ? `${boat.current.speedKt} kt @ ${boat.current.dirDeg}°` : null),
    row('Wave Height', waves.sigHeightFt != null ? `${waves.sigHeightFt} ft` : null),
    formatSwell('Primary Swell', waves.primary),
    formatSwell('Secondary Swell', waves.secondary),
    formatSwell('Tertiary Swell', waves.tertiary),
    row('Wind', boat.wind?.speedKt != null ? `${boat.wind.speedKt} kt @ ${boat.wind.dirDeg}°` : null),
    row('Water Temp', boat.water?.tempF != null ? `${boat.water.tempF} °F` : null),
    row('Air Temp', boat.water?.airTempF != null ? `${boat.water.airTempF} °F` : null),
    row('Marine Station', marineStation),
    row('Position', `${boat.lat.toFixed(3)}, ${boat.lon.toFixed(3)}`),
    '</div>',
  ].join('');
}

function createModelElement(boat) {
  const api = maps3d();
  if (!api?.Model3DElement) return null;
  return new api.Model3DElement({
    src: MODEL_SRC,
    position: { lat: boat.lat, lng: boat.lon, altitude: 3 },
    scale: MODEL_SCALE,
    sizePreserved: true,
    altitudeMode: api.AltitudeMode?.RELATIVE_TO_GROUND || 'RELATIVE_TO_GROUND',
    drawsOccludedSegments: true,
    orientation: `${boat.headingDeg + MODEL_YAW_OFFSET_DEG},0,0`,
  });
}

function createUnderglow(boat) {
  const el = document.createElement('gmp-marker-3d');
  el.position = `${boat.lat},${boat.lon},2`;
  el.drawsWhenOccluded = true;
  el.sizePreserved = true;
  const color = colorForSafety(boat.safety?.color);
  const svg = encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72"><circle cx="36" cy="36" r="19" fill="${color}" fill-opacity="0.22" stroke="${color}" stroke-opacity="0.9" stroke-width="3" /><path d="M24 41 L36 22 L48 41 L42 41 L42 50 L30 50 L30 41 Z" fill="white" fill-opacity="0.96" stroke="#062033" stroke-opacity="0.45" stroke-width="1.5"/></svg>`);
  el.innerHTML = `<template><img alt="boat status" src="data:image/svg+xml;charset=UTF-8,${svg}" /></template>`;
  return el;
}

function attachHudHandlers(target, boat) {
  target.setAttribute('title', `${boat.safety?.label || 'Boat marker'} | ${boat.current?.speedKt || 0} kt`);
  const onEnter = () => setHudContent(htmlForBoat(boat));
  target.addEventListener('mouseenter', onEnter);
  target.addEventListener('click', onEnter);
}

export async function fetchBoatsPayload({ bbox, viewport }) {
  const bboxQ = encodeURIComponent(`${bbox.west.toFixed(4)},${bbox.south.toFixed(4)},${bbox.east.toFixed(4)},${bbox.north.toFixed(4)}`);
  const safeViewport = {
    west: Number(viewport.west),
    south: Number(viewport.south),
    east: Number(viewport.east),
    north: Number(viewport.north),
    quality: String(viewport.quality || 'coarse'),
    camera: viewport.camera && viewport.camera.center ? {
      center: {
        lat: Number(viewport.camera.center.lat),
        lon: Number(viewport.camera.center.lon),
      },
      range: Number(viewport.camera.range),
      source: String(viewport.camera.source || ''),
    } : null,
  };
  const vpQ = encodeURIComponent(JSON.stringify(safeViewport));
  return getJsonSafe(`/gfs/api/frame?bbox=${bboxQ}&viewport=${vpQ}&quality=full`, null).then((frame) => frame?.boats || { boats: [] });
}

export function renderBoatsLayer({ payload, map3DElement }) {
  const boats = Array.isArray(payload?.boats) ? payload.boats.slice(0, BOAT_COUNT_MAX) : [];
  const instances = [];
  const validTime = payload?.resolvedTime || payload?.sourceTime || null;
  boats.forEach((boat) => {
    boat.originLat = boat.lat;
    boat.originLon = boat.lon;
    boat.displayHeadingDeg = boat.headingDeg ?? 0;
    const model = createModelElement(boat);
    const underglow = createUnderglow(boat);
    if (model) {
      map3DElement.append(model);
      attachHudHandlers(model, boat);
    }
    map3DElement.append(underglow);
    attachHudHandlers(underglow, boat);
    instances.push({ boat, model, underglow });
  });

  let frame = null;
  let last = performance.now();
  const tick = (now) => {
    const dt = Math.min(1.0, (now - last) / 1000);
    last = now;
    for (const instance of instances) {
      const boat = instance.boat;
      const du = Number(boat.current?.u || 0);
      const dv = Number(boat.current?.v || 0);
      const mag = Math.hypot(du, dv);
      if (mag > 1.0e-4) {
        const nextHeading = boat.current?.dirDeg ?? boat.headingDeg ?? 0;
        boat.displayHeadingDeg = nextHeading;
      }
      boat.lon += du * dt * LON_SCALE;
      boat.lat += dv * dt * LAT_SCALE;
      boat.lon = boat.originLon + Math.max(-MAX_VISUAL_DRIFT_DEG, Math.min(MAX_VISUAL_DRIFT_DEG, boat.lon - boat.originLon));
      boat.lat = boat.originLat + Math.max(-MAX_VISUAL_DRIFT_DEG * 0.5, Math.min(MAX_VISUAL_DRIFT_DEG * 0.5, boat.lat - boat.originLat));
      if (boat.lon > 180) boat.lon -= 360;
      if (boat.lon < -180) boat.lon += 360;
      const visibleScale = visibleScaleForRange(currentRangeMeters());
      if (instance.model) {
        instance.model.position = { lat: boat.lat, lng: boat.lon, altitude: 3 };
        instance.model.orientation = `${boat.displayHeadingDeg + MODEL_YAW_OFFSET_DEG},0,0`;
        instance.model.scale = Math.max(MODEL_SCALE * 0.7, MODEL_SCALE * visibleScale);
      }
      instance.underglow.position = `${boat.lat},${boat.lon},2`;
      if (typeof instance.underglow.scale !== 'undefined') instance.underglow.scale = visibleScale;
    }
    frame = window.requestAnimationFrame(tick);
  };

  if (boats.length) {
    setHudContent(`<div><strong>Boater Awareness</strong>${validTime ? `<div><strong>Valid:</strong> ${validTime}</div>` : ''}<div>${boats.length} boat markers active.</div></div>`);
  }
  frame = window.requestAnimationFrame(tick);
  console.info('[gfs boats] rendered', { boats: boats.length, model: MODEL_SRC, validTime });
  return () => {
    if (frame) window.cancelAnimationFrame(frame);
    instances.forEach(({ model, underglow }) => {
      try { model?.remove(); } catch (_) {}
      try { underglow?.remove(); } catch (_) {}
    });
  };
}
