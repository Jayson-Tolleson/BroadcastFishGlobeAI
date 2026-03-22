export function createGfsState() {
  return {
    viewport: null,
    quality: 'coarse',
    stride: 1,
    frame: null,
    ocean: null,
    ws: { connected: false, lastEvent: null },
    layers: {},
    debug: { cycle: null, sources: {}, degraded: {}, counts: {}, warm: null },
    cache: { locations: null, boats: null, bait: null },
    staleHold: false,
    debugHoldReason: '',
    locationsSource: null,
    setFrame(frame, viewport = null) {
      this.frame = frame || null;
      this.ocean = frame?.ocean || this.ocean;
      this.viewport = viewport || this.viewport;
      this.quality = frame?.ocean?.quality || this.quality;
      this.stride = frame?.ocean?.stride || this.stride;
      this.debug = frame?.debug || this.debug;
      this.debug.warm = frame?.ocean?.warm ?? this.debug.warm;
      this.staleHold = false;
    },
    setLayer(name, enabled) {
      this.layers[name] = Boolean(enabled);
    },
    setWs(connected, lastEvent = null) {
      this.ws = { connected: Boolean(connected), lastEvent };
    },
    setCache(key, payload) {
      this.cache[key] = payload;
      if (key === 'locations' && payload) {
        this.locationsSource = payload.source || null;
      }
    },
    setStaleHold(reason) {
      this.staleHold = true;
      this.debugHoldReason = String(reason || 'holding stale payload');
    },
  };
}
