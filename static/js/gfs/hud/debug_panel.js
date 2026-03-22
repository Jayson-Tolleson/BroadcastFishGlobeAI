export function renderDebugPanel(el, state) {
  if (!el) return;
  const debug = state?.debug || {};
  const ws = state?.ws || {};
  const sources = debug.sources || state?.ocean?.sources || {};
  const degraded = debug.degraded || state?.ocean?.degraded || {};
  const counts = debug.counts || {};
  const quality = state?.quality || state?.ocean?.quality || 'n/a';
  const stride = state?.stride || state?.ocean?.stride || 'n/a';
  const stale = state?.staleHold ? `yes (${state?.debugHoldReason || 'holding prior payload'})` : 'no';
  el.textContent = [
    `Cycle: ${debug.cycle || state?.ocean?.cycle || 'n/a'}`,
    `Viewport quality: ${quality}`,
    `Viewport stride: ${stride}`,
    `Weather source: ${sources.weather || 'n/a'}`,
    `Current source: ${sources.currents || 'n/a'}`,
    `Chlorophyll source: ${sources.chlorophyll || 'n/a'}`,
    `Wave source: ${sources.waves || 'n/a'}`,
    `Degraded: ${JSON.stringify(degraded)}`,
    `WebSocket: ${ws.connected ? 'connected' : 'disconnected'} (${ws.lastEvent || 'none'})`,
    `Counts: ${JSON.stringify(counts)}`,
    `Stale hold: ${stale}`,
  ].join('\n');
}
