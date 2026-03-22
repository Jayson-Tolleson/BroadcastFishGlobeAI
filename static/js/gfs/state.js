export function createGfsState() {
  return {
    frame: null,
    ocean: null,
    ws: { connected: false, lastEvent: null },
    debug: { cycle: null, sources: {}, degraded: {}, counts: {} },
    setFrame(frame) {
      this.frame = frame || null;
      this.ocean = frame?.ocean || null;
      this.debug = frame?.debug || this.debug;
    },
    setWs(connected, lastEvent = null) {
      this.ws = { connected: Boolean(connected), lastEvent };
    },
  };
}
