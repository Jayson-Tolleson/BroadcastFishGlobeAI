export function renderDebugPanel(el, state) {
  if (!el) return;
  const debug = state?.debug || {};
  const ws = state?.ws || {};
  const ocean = state?.ocean || {};
  const sources = debug.sources || ocean.sources || {};
  const degraded = debug.degraded || ocean.degraded || {};
  const counts = debug.counts || {};
  const quality = state?.quality || ocean.quality || 'n/a';
  const stride = state?.stride || ocean.stride || 'n/a';
  const stale = state?.staleHold ? `yes (${state?.debugHoldReason || 'holding prior payload'})` : 'no';
  const warm = ocean.warm ?? debug.warm;
  const locationsSource = state?.locationsSource || state?.cache?.locations?.source || 'unknown';
  el.textContent = [
    `Cycle: ${debug.cycle || ocean.cycle || 'n/a'}`,
    `Warm ready: ${String(warm)}`,
    `Viewport quality: ${quality}`,
    `Viewport stride: ${stride}`,
    `Locations source: ${locationsSource}`,
    `Weather source: ${sources.weather || 'n/a'}`,
    `Current source: ${sources.currents || 'n/a'}`,
    `Chlorophyll source: ${sources.chlorophyll || 'n/a'}`,
    `Wave source: ${sources.waves || 'n/a'}`,
    `Degraded: ${JSON.stringify(degraded)}`,
    `WebSocket: ${ws.connected ? 'connected' : 'disconnected'} (${ws.lastEvent || 'none'})`,
    `Counts: ${JSON.stringify(counts)}`,
    `Boat viewport: shared_ocean canonical`,
    `Stale hold: ${stale}`,
  ].join('\n');
}
