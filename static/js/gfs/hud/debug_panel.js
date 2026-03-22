export function renderDebugPanel(el, state) {
  if (!el) return;
  const debug = state?.debug || {};
  const ws = state?.ws || {};
  el.innerHTML = `
    <div>Cycle: ${debug.cycle || 'n/a'}</div>
    <div>Sources: ${JSON.stringify(debug.sources || {})}</div>
    <div>Degraded: ${JSON.stringify(debug.degraded || {})}</div>
    <div>Counts: ${JSON.stringify(debug.counts || {})}</div>
    <div>WebSocket: ${ws.connected ? 'connected' : 'offline'}</div>
  `;
}
