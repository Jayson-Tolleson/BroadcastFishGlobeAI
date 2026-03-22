export function renderDebugPanel(el, state) {
  if (!el) return;
  const debug = state?.debug || {};
  const ws = state?.ws || {};
  const sources = debug.sources || {};
  const degraded = debug.degraded || {};
  const counts = debug.counts || {};
  el.innerHTML = [
    `Cycle: ${debug.cycle || 'n/a'}`,
    `Weather source: ${sources.weather || 'n/a'}`,
    `Current source: ${sources.currents || 'n/a'}`,
    `Chlorophyll source: ${sources.chlorophyll || 'n/a'}`,
    `Wave source: ${sources.waves || 'n/a'}`,
    `Degraded: ${JSON.stringify(degraded)}`,
    `WebSocket: ${ws.connected ? 'connected' : 'disconnected'} (${ws.lastEvent || 'none'})`,
    `Counts: ${JSON.stringify(counts)}`,
  ].join('\n');
}
