export function createGfsState() {
  return {
    viewport: null,
    quality: 'coarse',
    frame: null,
    ocean: null,
    ws: { connected: false, lastEvent: null },
    layers: {},
    debug: { cycle: null, sources: {}, degraded: {}, counts: {} },
    cache: { locations: null, boats: null, bait: null },
    setFrame(frame, viewport = null) {
      this.frame = frame || null;
      this.ocean = frame?.ocean || this.ocean;
      this.viewport = viewport || this.viewport;
      this.quality = frame?.ocean?.quality || this.quality;
      this.debug = frame?.debug || this.debug;
    },
    setLayer(name, enabled) {
      this.layers[name] = Boolean(enabled);
    },
    setWs(connected, lastEvent = null) {
      this.ws = { connected: Boolean(connected), lastEvent };
    },
    setCache(key, payload) {
      this.cache[key] = payload;
    },
  };
}
