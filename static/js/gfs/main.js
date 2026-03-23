import { getJsonSafe, uploadSafe, fetchLocationLive, fetchLocations, getGfsWebSocketUrl, normalizeOceanPayload } from './api.js';
import { ensureMaps3D, libs } from './globe.js';
import { renderMarkers } from './markers.js';
import { createHud } from './hud.js';
import { startLive, stopLive } from './live.js';
import { LayerEngine } from './layer_engine.js';
import { GridPolygonLayer } from './layers/grid_polygon_layer.js';
import { RendererLayer } from './layers/renderer_layer.js';
import { renderCloudZones } from './cloud-zones.js';
import { renderRainZones } from './rain-zones.js';
import { renderBaitZones } from './bait-zones.js';
import { createGfsState } from './state.js';
import { renderDebugPanel } from './hud/debug_panel.js';

const statusEl = document.getElementById('status');
const globeEl = document.getElementById('globe');
const fallbackEl = document.getElementById('globeFallback');

let activeLocation = null;
let liveManuallyDismissed = false;
let selectedLocation = null;
let liveStatePollId = null;
const missingLiveLocationIds = new Set();
const GFS_DEBUG = Boolean(window.__GFS_DEBUG);

const gfsState = createGfsState();
const STEADY_EVENTS = ['gmp-centerchange', 'gmp-headingchange', 'gmp-rangechange', 'gmp-rollchange', 'gmp-tiltchange', 'gmp-camerapositionchange'];

const layerRuntime = {
  engine: null,
  rafId: 0,
};
const markerRuntime = {
  maps3d: null,
  teardownLocations: null,
};

function syncPillState(name, enabled) {
  const btn = document.querySelector(`.overlay-pill[data-layer="${name}"]`);
  if (!btn) return;
  btn.classList.toggle('active', enabled);
  btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
}


function baitAdvancedReady(payload) {
  if (!payload || !payload.bait) return false;
  const polygons = payload.bait.polygons;
  const hasPolygons = Array.isArray(polygons) && polygons.length > 0;
  const hasField = Array.isArray(payload.bait_score) && payload.bait_score.length > 0;
  const src = String(payload.bait.source || payload.source || '');
  const hasSource = src.length > 0 && ['shared_ocean', 'full_stack'].includes(src) || src.length > 0;
  return Boolean(payload.bait.status === 'ready' && hasSource && (hasPolygons || hasField));
}

function preferStableBaitAdvanced(nextPayload, fallbackPayload) {
  if (baitAdvancedReady(nextPayload)) return nextPayload;
  if (baitAdvancedReady(fallbackPayload)) return fallbackPayload;
  return nextPayload || fallbackPayload || null;
}

function initLayerSystem() {
  if (layerRuntime.engine) return layerRuntime.engine;
  const engine = new LayerEngine();
  const clouds = new RendererLayer(globeEl, {
    name: 'clouds',
    selector: (frame) => frame?.clouds || null,
    renderer: ({ payload, map3DElement }) => renderCloudZones({ payload, map3DElement }),
  });
  const rain = new RendererLayer(globeEl, {
    name: 'rain',
    selector: (frame) => {
      if (!frame?.weather) return null;
      return {
        ...frame.weather,
        cloud_layers: frame.clouds?.cloud_layers || [],
      };
    },
    renderer: ({ payload, map3DElement, viewportReason }) => renderRainZones({ payload, map3DElement, viewportReason: viewportReason === 'boot' ? 'steady' : viewportReason }),
  });
  const bait = new RendererLayer(globeEl, {
    name: 'bait',
    selector: (frame) => frame?.baitAdvanced || frame?.baitBase || null,
    renderer: ({ payload, map3DElement, viewportReason }) => renderBaitZones({ payload, map3DElement, viewportReason: viewportReason === 'boot' ? 'steady' : viewportReason }),
  });
  const boater = new GridPolygonLayer(globeEl, 'boater');
  engine.register('clouds', clouds);
  engine.register('rain', rain);
  engine.register('jetstream', { show(){ if (typeof window.setJetBalloonsEnabled === 'function') window.setJetBalloonsEnabled(true); }, hide(){ if (typeof window.setJetBalloonsEnabled === 'function') window.setJetBalloonsEnabled(false); }, update(){} });
  engine.register('bait', bait);
  engine.register('boater', boater);
  document.querySelectorAll('.overlay-pill[data-layer]').forEach((btn) => {
    btn.addEventListener('click', (ev) => {
      const name = btn.dataset.layer;
      if (name === 'jetstream') {
        ev.preventDefault();
        ev.stopPropagation();
      }
      const layer = engine.layers[name];
      const nextEnabled = !(layer && layer.enabled);
      engine.setEnabled(name, nextEnabled);
      syncPillState(name, nextEnabled);
    });
  });
  ['clouds','rain','jetstream','bait','boater'].forEach((name) => { engine.setEnabled(name, true); syncPillState(name, true); });
  layerRuntime.engine = engine;
  const tick = () => {
    layerRuntime.rafId = window.requestAnimationFrame(tick);
    engine.update();
  };
  tick();
  return engine;
}

const dataState = {
  lastRequestOutcome: 'ok',
  inFlight: false,
  requestSeq: 0,
  latestGeneration: 0,
  activeAbort: null,
  lastSignature: '',
  lastHeavySignature: '',
  lastCloudSignature: '',
  lastBoatSignature: '',
  latest: {
    bbox: null,
    weather: null,
    clouds: null,
    baitBase: null,
    baitAdvanced: null,
    boats: null,
    locations: null,
  },
};

const viewportRefresh = {
  restDebounceMs: 400,
  refreshMs: 15000,
  restTimer: 0,
  refreshTimer: 0,
  isMoving: false,
  lastIdleSignature: '',
};

window.__gfsDataInduction = {
  get latest() {
    return dataState.latest;
  },
  get signature() {
    return dataState.lastSignature;
  },
  refresh(reason = 'manual') {
    return refreshData(reason);
  },
};

function showStatus(text) {
  statusEl.textContent = text;
}

function hideLiveOverlay() {
  const overlay = document.getElementById('liveOverlay');
  if (overlay) overlay.remove();
}

function showLiveOverlay() {
  if (liveManuallyDismissed) return;
  let overlay = document.getElementById('liveOverlay');
  if (overlay) return;

  overlay = document.createElement('div');
  overlay.id = 'liveOverlay';
  overlay.className = 'live-overlay';
  overlay.innerHTML = `
    <div class="live-card glass">
      <div class="live-header">
        <div>
          <div class="eyebrow">Live</div>
          <strong>Broadcast preview</strong>
        </div>
        <button id="liveOverlayClose" type="button">Close</button>
      </div>
      <video id="livePreview" autoplay playsinline muted></video>
    </div>`;
  document.body.appendChild(overlay);

  overlay.querySelector('#liveOverlayClose')?.addEventListener('click', async () => {
    liveManuallyDismissed = true;
    if (activeLocation) await stopLive({ locationId: activeLocation.id });
    hideLiveOverlay();
  });
}

function currentLiveOverlayRefs() {
  return {
    overlayEl: document.getElementById('liveOverlay'),
    videoEl: document.getElementById('livePreview'),
  };
}

async function refreshSelectedLiveState() {
  if (!selectedLocation) return;
  const locationId = String(selectedLocation.id);
  if (missingLiveLocationIds.has(selectedLocation.id)) return;
  const payload = await fetchLocationLive(locationId, { abortPrevious: true });
  if (!payload) return;
  if (payload?.error === 'location_not_found' || payload?.ok === false) {
    missingLiveLocationIds.add(selectedLocation.id);
    console.info('[gfs live] stop polling missing location', { locationId: selectedLocation.id });
    return;
  }
  if (payload?.live?.active) showLiveOverlay();
  else hideLiveOverlay();
}

function startLivePolling() {
  if (liveStatePollId) return;
  liveStatePollId = setInterval(refreshSelectedLiveState, 12000);
}

function stopLivePolling() {
  if (!liveStatePollId) return;
  clearInterval(liveStatePollId);
  liveStatePollId = null;
}

function parseCenter() {
  const raw = globeEl.getAttribute('center') || '';
  const parts = raw.split(',').map((x) => Number(x.trim()));
  if (parts.length >= 2 && Number.isFinite(parts[0]) && Number.isFinite(parts[1])) {
    return { lat: parts[0], lon: parts[1] };
  }
  return { lat: 34.2, lon: -120 };
}

function parseRangeMeters() {
  const attr = Number(globeEl.getAttribute('range'));
  if (Number.isFinite(attr) && attr > 0) return attr;
  return 1800000;
}

function parseBoundsAttr(raw) {
  if (!raw || typeof raw !== 'string') return null;
  const parts = raw.split(',').map((x) => Number(x.trim()));
  if (parts.length < 4 || parts.some((n) => !Number.isFinite(n))) return null;
  return { west: parts[0], south: parts[1], east: parts[2], north: parts[3] };
}

function trueViewportFromGlobeBounds() {
  const attrCandidates = [
    globeEl.getAttribute('bounds'),
    globeEl.getAttribute('view-bounds'),
    globeEl.getAttribute('visible-bounds'),
  ];
  for (const raw of attrCandidates) {
    const parsed = parseBoundsAttr(raw);
    if (parsed) return parsed;
  }
  if (typeof globeEl.getBounds === 'function') {
    try {
      const b = globeEl.getBounds();
      if (b && Number.isFinite(b.west) && Number.isFinite(b.south) && Number.isFinite(b.east) && Number.isFinite(b.north)) {
        return { west: b.west, south: b.south, east: b.east, north: b.north };
      }
    } catch (_) {}
  }
  return null;
}

function getCanonicalViewport() {
  const c = parseCenter();
  const range = parseRangeMeters();
  const fromBounds = trueViewportFromGlobeBounds();
  if (fromBounds) {
    const rawLatSpan = Math.max(0.1, fromBounds.north - fromBounds.south);
    const rawLonSpan = Math.max(0.1, fromBounds.east - fromBounds.west);
    if (rawLatSpan <= 10 && rawLonSpan <= 14) {
      return snapViewport({
        west: Math.max(-179.9, fromBounds.west),
        south: Math.max(-89.9, fromBounds.south),
        east: Math.min(179.9, fromBounds.east),
        north: Math.min(89.9, fromBounds.north),
        quality: 'full',
        camera: { center: c, range, source: 'visible_bounds' },
      });
    }
  }

  const latSpan = Math.max(1.2, Math.min(10, range / 75000));
  const lonSpan = Math.min(14, latSpan / Math.max(Math.cos((c.lat * Math.PI) / 180), 0.35));
  return snapViewport({
    west: Math.max(-179.9, c.lon - lonSpan / 2),
    south: Math.max(-89.9, c.lat - latSpan / 2),
    east: Math.min(179.9, c.lon + lonSpan / 2),
    north: Math.min(89.9, c.lat + latSpan / 2),
    quality: 'full',
    camera: { center: c, range, source: 'camera_heuristic' },
  });
}


function effectiveViewportStride(v) {
  void v;
  return 1;
}

function snapToGrid(value, step) {
  return Math.round(value / step) * step;
}

function snapViewport(v) {
  const stride = effectiveViewportStride(v);
  const step = 0.25 * stride;
  return {
    ...v,
    west: Math.max(-179.9, snapToGrid(v.west, step)),
    south: Math.max(-89.9, snapToGrid(v.south, step)),
    east: Math.min(179.9, snapToGrid(v.east, step)),
    north: Math.min(89.9, snapToGrid(v.north, step)),
    sourceStride: stride,
  };
}

function bboxToQuery(b) {
  return `${b.west.toFixed(4)},${b.south.toFixed(4)},${b.east.toFixed(4)},${b.north.toFixed(4)}`;
}

function sanitizeViewportForQuery(viewport) {
  if (!viewport || !Number.isFinite(viewport.west) || !Number.isFinite(viewport.south) || !Number.isFinite(viewport.east) || !Number.isFinite(viewport.north)) {
    throw new Error('Invalid viewport object before frame request');
  }
  const camera = viewport.camera && viewport.camera.center
    ? {
        center: {
          lat: Number(viewport.camera.center.lat),
          lon: Number(viewport.camera.center.lon),
        },
        range: Number(viewport.camera.range),
        source: String(viewport.camera.source || ''),
      }
    : null;
  return {
    west: Number(viewport.west),
    south: Number(viewport.south),
    east: Number(viewport.east),
    north: Number(viewport.north),
    quality: String(viewport.quality || 'full'),
    camera,
  };
}

function viewportToQuery(viewport) {
  return encodeURIComponent(JSON.stringify(sanitizeViewportForQuery(viewport)));
}

function bboxSignature(b) {
  const range = parseRangeMeters();
  return `${b.west.toFixed(1)}:${b.south.toFixed(1)}:${b.east.toFixed(1)}:${b.north.toFixed(1)}:${Math.round(range / 50000)}:${b.sourceStride || 1}`;
}

function normalizeFramePayload(payload) {
  if (!payload || typeof payload !== 'object') return null;
  if (payload.ok !== true) return null;
  if (!payload.ocean || String(payload.ocean.source || '') !== 'shared_ocean') return null;
  return payload;
}

async function refreshData(reason = 'manual') {
  const viewport = getCanonicalViewport();
  const signature = bboxSignature(viewport);

  if (dataState.lastSignature === signature && reason !== 'boot' && reason !== 'steady') {
    if (GFS_DEBUG) console.debug('[gfs data] skipped refresh; signature unchanged', { reason, signature });
    return dataState.latest;
  }

  if (dataState.inFlight) return dataState.latest;
  if (dataState.activeAbort) {
    try { dataState.activeAbort.abort(); } catch (_) {}
  }

  const controller = new AbortController();
  const generation = dataState.latestGeneration + 1;
  dataState.latestGeneration = generation;
  dataState.requestSeq = generation;
  dataState.inFlight = true;
  dataState.activeAbort = controller;
  dataState.latest.bbox = viewport;
  dataState.lastSignature = signature;

  try {
    const bboxQ = encodeURIComponent(bboxToQuery(viewport));
    const vpQ = viewportToQuery(viewport);
    const frameQuality = 'full';
    const frameStride = 1;
    const frameUrl = `/gfs/api/frame?bbox=${bboxQ}&viewport=${vpQ}&mode=live&quality=${encodeURIComponent(frameQuality)}&stride=${encodeURIComponent(frameStride)}`;
    const frame = await getJsonSafe(frameUrl, null, { signal: controller.signal, timeoutMs: 2000, abortPrevious: true });
    fetchLocations(viewport, { timeoutMs: 1800, abortPrevious: false })
      .then((locationsPayload) => {
        if (!locationsPayload || generation !== dataState.latestGeneration) return;
        dataState.latest.locations = locationsPayload;
        gfsState.setCache('locations', locationsPayload || null);
        renderMarkerSets('steady');
      })
      .catch((err) => console.info('[gfs locations] deferred fetch failed', err?.message || err));
    const ocean = normalizeOceanPayload(frame?.ocean);
    const locationsPayload = dataState.latest.locations || { locations: [] };
    console.info('[gfs markers] endpoint hit', {
      endpoint: '/gfs/api/locations',
      entity_type: locationsPayload?.entity_type,
      item_count_received: Array.isArray(locationsPayload?.locations) ? locationsPayload.locations.length : 0,
      contract_mismatch: Boolean(locationsPayload?.contract_mismatch),
      rejection_reason: locationsPayload?.contract_mismatch ? 'locations_contract_mismatch' : null,
    });
    if (frame && ocean) frame.ocean = ocean;
    const normalizedFrame = normalizeFramePayload(frame);
    if (!ocean) gfsState.setStaleHold('ocean payload unavailable; holding prior ocean metadata');
    if (!normalizedFrame) { gfsState.debugHoldReason = 'frame missing/invalid; held previous visuals'; return dataState.latest; }
    if (generation !== dataState.latestGeneration) return dataState.latest;

    dataState.latest.weather = normalizedFrame.weather || null;
    dataState.latest.clouds = normalizedFrame.clouds || null;
    dataState.latest.baitBase = normalizedFrame.baitBase || null;
    dataState.latest.baitAdvanced = preferStableBaitAdvanced(normalizedFrame.baitAdvanced || null, dataState.latest.baitAdvanced || null);
    normalizedFrame.baitAdvanced = dataState.latest.baitAdvanced;
    dataState.latest.boats = normalizedFrame.boats || { boats: [] };
    dataState.latest.recursiveGrid = normalizedFrame.recursiveGrid || null;
    dataState.latest.locations = locationsPayload || { locations: [] };
    gfsState.setCache('locations', locationsPayload || null);
    normalizedFrame.render_reason = (reason === 'boot' || reason === 'manual') ? 'steady' : reason;
    dataState.latest.frame = normalizedFrame;

    window.__gfsLastBbox = bboxToQuery(viewport);
    window.__gfsLastFrame = normalizedFrame;
    window.currentBBox = window.__gfsLastBbox;
    window.__gfsRecursiveGrid = { latest: dataState.latest.recursiveGrid, bbox: bboxToQuery(viewport) };
    gfsState.debugHoldReason = '';
    gfsState.setFrame(normalizedFrame, viewport);
    renderMarkerSets(reason);
    const debugEl = document.getElementById('debugPrompt');
    renderDebugPanel(debugEl, gfsState);
    await layerRuntime.engine?.setData?.(normalizedFrame || null);
    console.info('[gfs data] refreshed', {
      reason,
      signature,
      frame: Boolean(normalizedFrame),
      weather: Boolean(dataState.latest.weather),
      clouds: Boolean(dataState.latest.clouds),
      baitBase: Boolean(dataState.latest.baitBase),
      baitAdvanced: Boolean(dataState.latest.baitAdvanced),
      boats: Array.isArray(dataState.latest.boats?.boats) ? dataState.latest.boats.boats.length : 0,
      sigmaClouds: Array.isArray(normalizedFrame?.sigmaClouds) ? normalizedFrame.sigmaClouds.length : 0,
      csvLocations: Array.isArray(dataState.latest.locations?.locations) ? dataState.latest.locations.locations.length : 0,
    });
    if (reason === 'boot' || reason === 'manual') {
      refreshDeferredBaitAdvanced(viewport, reason).catch((err) => console.info('[gfs bait advanced] deferred fetch skipped', { message: err?.message || String(err) }));
    }
    return dataState.latest;
  } catch (err) {
    if (err?.name === 'AbortError') {
      dataState.lastRequestOutcome = 'intentional_abort';
    } else if (String(err?.message || '').toLowerCase().includes('timeout')) {
      dataState.lastRequestOutcome = 'timeout_fallback';
      gfsState.setStaleHold('refresh timeout; holding prior visuals');
      console.warn('[gfs data] refresh timeout', err?.message || err);
    } else {
      dataState.lastRequestOutcome = 'error';
      console.warn('[gfs data] refresh failed', err?.message || err);
    }
    return dataState.latest;
  } finally {
    if (dataState.activeAbort === controller) dataState.activeAbort = null;
    if (generation === dataState.latestGeneration) dataState.inFlight = false;
  }
}

function toHudMarker(item) {
  if (!item || !Number.isFinite(Number(item.lat)) || !Number.isFinite(Number(item.lon))) return null;
  return {
    ...item,
    id: String(item.id || item.location_key || `location_csv-${Number(item.lat).toFixed(4)}-${Number(item.lon).toFixed(4)}`),
    name: item.name || 'Fishing location',
    entity_type: 'location_markers',
    derived: false,
    marker_kind: 'location_csv',
    source: item.source || 'fish_csv',
    reason: item.reason,
    reasons: item.reasons,
    score: item.score,
    fish_index: item.fish_index,
    confidence: item.confidence,
    probability: item.probability,
  };
}

function renderMarkerSets(reason = 'manual') {
  if (!markerRuntime.maps3d) {
    console.warn('[gfs markers] render suppressed: maps3d unavailable', { reason });
    return;
  }
  const rawLocations = Array.isArray(dataState.latest.locations?.locations) ? dataState.latest.locations.locations : [];
  const locationMarkers = rawLocations.map((item) => toHudMarker(item)).filter(Boolean);
  console.info('[gfs markers] normalize counts', {
    reason,
    locations_received: rawLocations.length,
    locations_accepted: locationMarkers.length,
    marker_source: 'fishloclist.csv',
    locations_entity_type: dataState.latest.locations?.entity_type,
  });
  if (markerRuntime.teardownLocations) markerRuntime.teardownLocations();
  try {
    markerRuntime.teardownLocations = renderMarkers({
      locations: locationMarkers,
      globeEl,
      maps3d: markerRuntime.maps3d,
      markerKind: 'location_csv',
      onSelect: (loc) => { gfsSocket.connect(); hud.open(loc); },
    });
  } catch (err) {
    console.error('[gfs markers] location marker render failed', { reason, error: String(err) });
  }
  if (!locationMarkers.length) {
    console.warn('[gfs markers] layer toggles may be enabled but zero markers rendered', {
      reason,
      locations_source: dataState.latest.locations?.source,
      suppression_reason: dataState.latest.locations?.contract_mismatch ? 'locations_contract_mismatch' : 'no_locations_in_viewport',
    });
  }
}


async function refreshDeferredBaitAdvanced(viewport, reason = 'manual') {
  const bboxQ = encodeURIComponent(bboxToQuery(viewport));
  const vpQ = viewportToQuery(viewport);
  const payload = await getJsonSafe(`/gfs/api/bait-advanced?bbox=${bboxQ}&viewport=${vpQ}&quality=full`, null, { abortPrevious: true });
  if (!payload) { gfsState.debugHoldReason = 'bait refresh unavailable; holding prior payload'; return null; }
  dataState.latest.baitAdvanced = preferStableBaitAdvanced(payload, dataState.latest.baitAdvanced || null);
  console.info('[gfs bait advanced] refreshed', { reason, polygons: Array.isArray(payload?.bait?.polygons) ? payload.bait.polygons.length : 0, status: payload?.bait?.status });
  return payload;
}
function installSteadyRefresh() {
  const clearRestTimer = () => {
    if (!viewportRefresh.restTimer) return;
    clearTimeout(viewportRefresh.restTimer);
    viewportRefresh.restTimer = 0;
  };
  const clearRefreshTimer = () => {
    if (!viewportRefresh.refreshTimer) return;
    clearInterval(viewportRefresh.refreshTimer);
    viewportRefresh.refreshTimer = 0;
  };
  const scheduleIdleRefresh = () => {
    clearRefreshTimer();
    viewportRefresh.refreshTimer = setInterval(() => {
      if (viewportRefresh.isMoving || dataState.inFlight) return;
      refreshData('steady');
    }, viewportRefresh.refreshMs);
  };
  const triggerRestFetch = () => {
    if (viewportRefresh.isMoving) return;
    const signature = bboxSignature(getCanonicalViewport());
    if (signature === viewportRefresh.lastIdleSignature && !dataState.inFlight) return;
    viewportRefresh.lastIdleSignature = signature;
    refreshData('steady');
    scheduleIdleRefresh();
  };
  const onMove = () => {
    viewportRefresh.isMoving = true;
    clearRestTimer();
    clearRefreshTimer();
    viewportRefresh.restTimer = setTimeout(() => {
      viewportRefresh.isMoving = false;
      triggerRestFetch();
    }, viewportRefresh.restDebounceMs);
  };

  STEADY_EVENTS.forEach((evt) => globeEl.addEventListener(evt, onMove));
  onMove();

  return () => {
    STEADY_EVENTS.forEach((evt) => globeEl.removeEventListener(evt, onMove));
    clearRestTimer();
    clearRefreshTimer();
  };
}

function createGfsSocket() {
  let ws = null;
  let reconnectTimer = null;
  let pingTimer = null;
  let backoffMs = 1000;
  const MIN_BACKOFF_MS = 1000;
  const MAX_BACKOFF_MS = 20000;
  let manualClose = false;
  let connecting = false;

  const clearTimers = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (pingTimer) clearInterval(pingTimer);
    reconnectTimer = null;
    pingTimer = null;
  };

  const scheduleReconnect = () => {
    if (manualClose || reconnectTimer) return;
    const jitter = 0.85 + (Math.random() * 0.3);
    const delay = Math.round(backoffMs * jitter);
    console.info('[gfs/ws] reconnect scheduled', { delayMs: delay, nextBackoffMs: Math.min(MAX_BACKOFF_MS, backoffMs * 2) });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
    backoffMs = Math.min(MAX_BACKOFF_MS, backoffMs * 2);
  };

  const startHeartbeat = () => {
    pingTimer = setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      try { ws.send(JSON.stringify({ type: 'ping' })); } catch (_) {}
    }, 20000);
  };

  const setWsState = (connected, reason) => gfsState.setWs(Boolean(connected), reason);

  const handleMessage = (msg) => {
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'snapshot_changed' && msg.detail?.location_id) {
      if (selectedLocation && msg.detail.location_id === selectedLocation.id) {
        if (msg.detail.active) showLiveOverlay();
        else hideLiveOverlay();
      }
    }
  };

  const connect = () => {
    if (manualClose || connecting || (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING))) return;
    connecting = true;
    const wsUrl = getGfsWebSocketUrl();
    console.info('[gfs/ws] connecting', { url: wsUrl });
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      connecting = false;
      backoffMs = MIN_BACKOFF_MS;
      clearTimers();
      startHeartbeat();
      setWsState(true, 'open');
      console.info('[gfs/ws] connected');
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg?.type === 'status') setWsState(true, 'status');
        if (msg?.type === 'hello') setWsState(true, 'hello');
        handleMessage(msg);
      } catch (_) {}
    };
    ws.onerror = (err) => { setWsState(false, 'error'); console.warn('[gfs/ws] socket error', err); };
    ws.onclose = (ev) => {
      setWsState(false, 'close');
      connecting = false;
      clearTimers();
      console.info('[gfs/ws] closed', { code: ev?.code, reason: ev?.reason || '', wasClean: Boolean(ev?.wasClean) });
      if (!manualClose) scheduleReconnect();
    };
  };

  const close = () => {
    manualClose = true;
    clearTimers();
    if (ws) {
      try { ws.close(1000, 'page unload'); } catch (_) {}
      ws = null;
    }
  };

  return { connect, close };
}

const gfsSocket = createGfsSocket();

function sampleGrid(grid, bbox, lat, lon) {
  if (!bbox || !Array.isArray(grid) || !Array.isArray(grid[0])) return NaN;
  const arr = Array.isArray(grid[0][0]) ? grid[0] : grid;
  const ny = arr.length;
  const nx = Array.isArray(arr[0]) ? arr[0].length : 0;
  if (!ny || !nx) return NaN;
  const yi = Math.max(0, Math.min(ny - 1, Math.floor(((lat - bbox.south) / (bbox.north - bbox.south || 1)) * ny)));
  const xi = Math.max(0, Math.min(nx - 1, Math.floor(((lon - bbox.west) / (bbox.east - bbox.west || 1)) * nx)));
  return Number(arr[yi]?.[xi]);
}

function nearestOverlaySummary(loc) {
  const bbox = dataState.latest.bbox;
  const weather = dataState.latest.weather;
  const clouds = dataState.latest.clouds;
  const bait = dataState.latest.baitAdvanced || dataState.latest.baitBase;
  const lat = Number(loc?.lat);
  const lon = Number(loc?.lon);
  if (!bbox || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  return {
    validTime: weather?.valid_time || clouds?.valid_time || bait?.valid_time || null,
    cloudCover: sampleGrid(weather?.fields?.cloud_total, bbox, lat, lon),
    rainRate: sampleGrid(weather?.fields?.precip_rate, bbox, lat, lon),
    lowCloud: sampleGrid(clouds?.cloud_layers?.find((layer) => layer?.name === 'low')?.density, bbox, lat, lon),
    baitOverall: Number(bait?.confidence?.overall ?? NaN),
  };
}

function sampleWeatherAt(lat, lon) {
  const bbox = dataState.latest.bbox;
  const weather = dataState.latest.weather;
  if (!bbox || !weather) return null;
  const windU = sampleGrid(weather?.fields?.wind_u, bbox, lat, lon);
  const windV = sampleGrid(weather?.fields?.wind_v, bbox, lat, lon);
  const tempK = sampleGrid(weather?.fields?.air_temp, bbox, lat, lon);
  const pressurePa = sampleGrid(weather?.fields?.pressure_msl, bbox, lat, lon);
  return {
    temperature_k: Number.isFinite(tempK) ? tempK : NaN,
    temperature_c: Number.isFinite(tempK) ? (tempK - 273.15) : NaN,
    temperature_f: Number.isFinite(tempK) ? (((tempK - 273.15) * 9) / 5) + 32 : NaN,
    pressure_pa: Number.isFinite(pressurePa) ? pressurePa : NaN,
    pressure_hpa: Number.isFinite(pressurePa) ? (pressurePa / 100) : NaN,
    wind_speed_mps: Number.isFinite(windU) && Number.isFinite(windV) ? Math.hypot(windU, windV) : NaN,
  };
}

function nearestBaitAt(lat, lon) {
  const bait = dataState.latest.baitAdvanced || dataState.latest.baitBase;
  const pts = Array.isArray(bait?.bait_score) ? bait.bait_score : [];
  if (!pts.length || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  let best = null;
  let bestD2 = Infinity;
  for (const item of pts) {
    const plat = Number(item?.lat);
    const plon = Number(item?.lon);
    if (!Number.isFinite(plat) || !Number.isFinite(plon)) continue;
    const d2 = ((plat - lat) * (plat - lat)) + ((plon - lon) * (plon - lon));
    if (d2 < bestD2) {
      bestD2 = d2;
      best = item;
    }
  }
  return best;
}

const hud = createHud({
  root: document.getElementById('locationHud'),
  getOverlaySummary: nearestOverlaySummary,
  onSelectLocation: (loc) => {
    selectedLocation = loc;
    if (loc?.id) missingLiveLocationIds.delete(loc.id);
    gfsSocket.connect();
    refreshSelectedLiveState();
  },
  onStartLive: async (loc) => {
    activeLocation = loc;
    selectedLocation = loc;
    liveManuallyDismissed = false;
    showLiveOverlay();
    const refs = currentLiveOverlayRefs();
    await startLive({ locationId: loc.id, videoEl: refs.videoEl, overlayEl: refs.overlayEl });
    showStatus(`Live started: ${loc.name}`);
  },
  onStopLive: async (loc) => {
    await stopLive({
      locationId: loc.id,
      onBlob: async (blob) => {
        const f = new File([blob], `live-${Date.now()}.webm`, { type: 'video/webm' });
        await uploadSafe(`/gfs/api/location/${encodeURIComponent(loc.id)}/upload`, f, {}, null);
      },
    });
    hideLiveOverlay();
    showStatus(`Live stopped: ${loc.name}`);
    await hud.open(loc);
  },
});

function installHoverHud() {
  const handler = (ev) => {
    const d = ev?.detail || {};
    const lat = Number(d?.latLng?.lat ?? d?.position?.lat ?? d?.lat);
    const lon = Number(d?.latLng?.lng ?? d?.position?.lng ?? d?.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const sample = sampleWeatherAt(lat, lon);
    hud.updateHover({ lat, lon }, sample, nearestBaitAt(lat, lon));
    if (typeof window.updateHUD === 'function') {
      window.updateHUD(sample);
    }
  };
  globeEl.addEventListener('gmp-click', handler);
  globeEl.addEventListener('gmp-pointermove', handler);
  return () => {
    globeEl.removeEventListener('gmp-click', handler);
    globeEl.removeEventListener('gmp-pointermove', handler);
  };
}

window.addEventListener('beforeunload', () => {
  stopLivePolling();
  gfsSocket.close();
  if (dataState.activeAbort) {
    try { dataState.activeAbort.abort(); } catch (_) {}
  }
});

async function boot() {
  hideLiveOverlay();

  const ready = await ensureMaps3D(globeEl, fallbackEl);
  if (!ready.ok) {
    showStatus(`Globe unavailable (${ready.reason})`);
    return;
  }

  const { maps3d } = await libs();
  markerRuntime.maps3d = maps3d;
  initLayerSystem();
  const teardownSteady = installSteadyRefresh();
  const teardownHoverHud = installHoverHud();

  await refreshData('boot');

  const locationCount = Array.isArray(dataState.latest.locations?.locations) ? dataState.latest.locations.locations.length : 0;
  showStatus(`Ready • ${locationCount} CSV locations`);
  startLivePolling();

  window.addEventListener('beforeunload', teardownSteady, { once: true });
  window.addEventListener('beforeunload', teardownHoverHud, { once: true });
}

boot().catch((e) => {
  showStatus(`Error: ${e.message}`);
  console.error(e);
});
