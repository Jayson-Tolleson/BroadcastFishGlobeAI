const inflight = new Map();
const abortControllers = new Map();

function warn(prefix, detail) {
  console.warn(`[gfs/api] ${prefix}`, detail || '');
}

function makeError(message, extra = {}) {
  const err = new Error(message);
  Object.assign(err, extra);
  return err;
}

function isExpectedEntity(payload, expectedType, expectedDerived) {
  if (!payload || typeof payload !== 'object') return false;
  const t = String(payload.entity_type || '');
  const d = Boolean(payload.derived);
  return t === expectedType && d === expectedDerived;
}

function normalizeLocationsPayload(payload) {
  if (isExpectedEntity(payload, 'location', false)) return payload;
  warn('locations payload contract mismatch', {
    entity_type: payload?.entity_type,
    derived: payload?.derived,
    source: payload?.source,
  });
  return {
    ok: false,
    entity_type: 'location',
    derived: false,
    source: payload?.source || 'unknown',
    locations: [],
    count: 0,
    error: 'locations_contract_mismatch',
    contract_mismatch: true,
  };
}

function normalizeFishPayload(payload) {
  if (isExpectedEntity(payload, 'fish', true)) return payload;
  warn('fish payload contract mismatch', {
    entity_type: payload?.entity_type,
    derived: payload?.derived,
    source: payload?.source,
  });
  return {
    ok: false,
    entity_type: 'fish',
    derived: true,
    source: payload?.source || 'unknown',
    items: [],
    count: 0,
    error: 'fish_contract_mismatch',
    contract_mismatch: true,
  };
}

function normalizeOceanPayload(payload) {
  if (payload && typeof payload === 'object' && String(payload.source || '') === 'shared_ocean') return payload;
  warn('ocean payload contract mismatch', { source: payload?.source });
  return {
    ok: false,
    source: 'shared_ocean',
    degraded: true,
    fields: {},
    cache: 'invalid',
    error: 'ocean_contract_mismatch',
    contract_mismatch: true,
  };
}

function normalizeOptions(opts = {}) {
  if (opts instanceof AbortSignal) return { signal: opts };
  if (!opts || typeof opts !== 'object') return {};
  return opts;
}

function shouldAbortPreviousGet(url, options) {
  if (options?.abortPrevious === false) return false;
  return typeof url === 'string' && url.startsWith('/gfs/api/');
}

function gfsRequestKey(url) {
  try {
    const u = new URL(url, window.location.origin);
    if (u.pathname === '/gfs/api/frame') return u.pathname;
    if (u.pathname === '/gfs/api/bait-advanced' || u.pathname === '/gfs/api/bait/advanced') return u.pathname;
    return `${u.pathname}${u.search}`;
  } catch (_) {
    return String(url || '');
  }
}

function requestKey(url, method = 'GET') {
  return `${String(method || 'GET').toUpperCase()} ${String(url)}`;
}

function shouldDedupe(method, dedupe) {
  return dedupe !== false && String(method || 'GET').toUpperCase() === 'GET';
}

function timeoutSignal(timeoutMs) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return { signal: undefined, cancel: () => {} };
  }
  const controller = new AbortController();
  const id = setTimeout(() => {
    try { controller.abort(); } catch (_) {}
  }, timeoutMs);
  return {
    signal: controller.signal,
    cancel: () => clearTimeout(id),
  };
}

function mergeSignals(signals) {
  const valid = signals.filter(Boolean);
  if (!valid.length) return { signal: undefined, cleanup: () => {} };
  if (valid.length === 1) return { signal: valid[0], cleanup: () => {} };

  const controller = new AbortController();
  const onAbort = () => {
    if (!controller.signal.aborted) {
      try { controller.abort(); } catch (_) {}
    }
  };

  for (const signal of valid) {
    if (signal.aborted) {
      try { controller.abort(); } catch (_) {}
      return { signal: controller.signal, cleanup: () => {} };
    }
    signal.addEventListener('abort', onAbort, { once: true });
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      for (const signal of valid) {
        try { signal.removeEventListener('abort', onAbort); } catch (_) {}
      }
    },
  };
}

function buildGetSignal(url, options = {}) {
  const externalSignal = options?.signal || null;
  if (!shouldAbortPreviousGet(url, options)) {
    return { signal: externalSignal, controller: null, key: '' };
  }

  const key = gfsRequestKey(url);
  const prior = abortControllers.get(key);
  if (prior) {
    try { prior.abort(); } catch (_) {}
  }

  const controller = new AbortController();
  abortControllers.set(key, controller);

  const merged = mergeSignals([externalSignal, controller.signal]);
  return { signal: merged.signal, controller, key, cleanup: merged.cleanup };
}

async function parseJsonResponse(response, url) {
  const text = await response.text();
  if (!text || !text.trim()) {
    throw makeError('empty response body', { url, status: response.status, responseText: text });
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    throw makeError(`json parse failed ${err?.message || err}`, {
      url,
      status: response.status,
      responseText: text.slice(0, 500),
    });
  }
}

export async function getJson(url, opts = {}) {
  const {
    signal: callerSignal,
    timeoutMs = 15000,
    dedupe = true,
    abortPrevious = true,
    fetchOptions = {},
    method = 'GET',
    fallback,
  } = normalizeOptions(opts);

  const upperMethod = String(fetchOptions.method || method || 'GET').toUpperCase();
  const dedupeKey = requestKey(url, upperMethod);
  if (shouldDedupe(upperMethod, dedupe) && inflight.has(dedupeKey)) {
    return inflight.get(dedupeKey);
  }

  const run = (async () => {
    const timeout = timeoutSignal(timeoutMs);
    const autoAbort = upperMethod === 'GET'
      ? buildGetSignal(url, { signal: callerSignal, abortPrevious })
      : { signal: callerSignal, controller: null, key: '', cleanup: () => {} };
    const merged = autoAbort.signal === callerSignal || !timeout.signal
      ? mergeSignals([autoAbort.signal, timeout.signal].filter(Boolean))
      : { signal: autoAbort.signal, cleanup: () => {} };

    try {
      const response = await fetch(url, {
        credentials: 'same-origin',
        ...fetchOptions,
        method: upperMethod,
        signal: merged.signal,
        headers: {
          Accept: 'application/json',
          ...(fetchOptions.headers || {}),
        },
      });

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        throw makeError('GET non-ok', { url, status: response.status, responseText: text.slice(0, 500) });
      }

      return await parseJsonResponse(response, url);
    } catch (err) {
      const aborted = err?.name === 'AbortError' || merged.signal?.aborted || timeout.signal?.aborted || callerSignal?.aborted;
      if (aborted) {
        const abortErr = makeError('The operation was aborted.', { url, aborted: true });
        if (fallback !== undefined) return fallback;
        throw abortErr;
      }
      if (fallback !== undefined) {
        warn(err?.message || 'GET failure', { url, err: err?.message || err });
        return fallback;
      }
      throw err instanceof Error ? err : makeError(String(err), { url });
    } finally {
      timeout.cancel();
      try { merged.cleanup(); } catch (_) {}
      try { autoAbort.cleanup?.(); } catch (_) {}
      if (autoAbort.controller && autoAbort.key && abortControllers.get(autoAbort.key) === autoAbort.controller) {
        abortControllers.delete(autoAbort.key);
      }
    }
  })();

  if (shouldDedupe(upperMethod, dedupe)) {
    inflight.set(dedupeKey, run);
    run.finally(() => {
      if (inflight.get(dedupeKey) === run) inflight.delete(dedupeKey);
    });
  }

  return run;
}

export async function getJsonSafe(url, fallback = null, options = {}) {
  return getJson(url, { ...normalizeOptions(options), fallback });
}

export async function postJsonSafe(url, payload = {}, fallback = null, options = {}) {
  try {
    return await getJson(url, {
      ...normalizeOptions(options),
      method: 'POST',
      dedupe: false,
      abortPrevious: false,
      fallback,
      fetchOptions: {
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload || {}),
      },
    });
  } catch (err) {
    warn('POST network failure', { url, err: err?.message || err });
    return fallback;
  }
}

export async function uploadSafe(url, file, fields = {}, fallback = null, options = {}) {
  try {
    const fd = new FormData();
    Object.entries(fields || {}).forEach(([k, v]) => fd.append(k, v));
    fd.append('file', file);
    fd.append('video', file);
    return await getJson(url, {
      ...normalizeOptions(options),
      method: 'POST',
      dedupe: false,
      abortPrevious: false,
      fallback,
      fetchOptions: {
        body: fd,
      },
    });
  } catch (err) {
    warn('UPLOAD network failure', { url, err: err?.message || err });
    return fallback;
  }
}

export async function jget(url, opts = {}) {
  const normalized = normalizeOptions(opts);
  if (normalized && Object.keys(normalized).length && !('fallback' in normalized)) {
    return getJson(url, normalized);
  }
  return getJsonSafe(url, null, normalized);
}

export const jpost = postJsonSafe;
export const upload = uploadSafe;

export function clearInflightRequests() {
  inflight.clear();
  for (const controller of abortControllers.values()) {
    try { controller.abort(); } catch (_) {}
  }
  abortControllers.clear();
}



function viewportQuery(viewport = {}) {
  if (typeof viewport === 'string') {
    // compatibility shim: raw bbox string still supported
    return `bbox=${encodeURIComponent(viewport)}&quality=coarse&stride=1`;
  }
  const west = Number(viewport.west ?? -180);
  const south = Number(viewport.south ?? -80);
  const east = Number(viewport.east ?? 180);
  const north = Number(viewport.north ?? 80);
  const quality = String(viewport.quality || 'coarse');
  const stride = Number(viewport.stride || 1);
  const bbox = `${west.toFixed(4)},${south.toFixed(4)},${east.toFixed(4)},${north.toFixed(4)}`;
  return `bbox=${encodeURIComponent(bbox)}&quality=${encodeURIComponent(quality)}&stride=${encodeURIComponent(stride)}`;
}

export async function fetchOceanState(viewport, options = {}) {
  const merged = { timeoutMs: 8000, abortPrevious: true, ...options };
  const payload = await getJsonSafe(`/gfs/api/ocean?${viewportQuery(viewport)}`, null, merged);
  return normalizeOceanPayload(payload);
}

export async function fetchLocations(viewport, options = {}) {
  const merged = { timeoutMs: 2500, abortPrevious: false, ...options };
  const payload = await getJsonSafe(`/gfs/api/locations?${viewportQuery(viewport)}`, { ok: false, locations: [] }, merged);
  return normalizeLocationsPayload(payload);
}

export async function fetchLocation(id, options = {}) {
  return getJsonSafe(`/gfs/api/location/${encodeURIComponent(String(id || ''))}`, null, options);
}

export async function fetchLocationLive(id, options = {}) {
  return getJsonSafe(`/gfs/api/location/${encodeURIComponent(String(id || ''))}/live`, null, options);
}

export async function fetchBait(viewport, options = {}) {
  return getJsonSafe(`/gfs/api/bait?${viewportQuery(viewport)}`, null, options);
}

export async function fetchBoats(viewport, options = {}) {
  return getJsonSafe(`/gfs/api/boats?${viewportQuery(viewport)}`, null, options);
}

export async function fetchFish(viewport, options = {}) {
  const payload = await getJsonSafe(`/gfs/api/fish?${viewportQuery(viewport)}`, { items: [] }, options);
  return normalizeFishPayload(payload);
}

export function getGfsWebSocketUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/gfs`;
}

// compatibility thin aliases
export const getOceanState = fetchOceanState;
