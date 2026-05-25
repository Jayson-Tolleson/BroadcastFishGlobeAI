export function renderHoverHud(el, payload) {
  if (!el) return;
  if (!payload) { el.textContent = ''; return; }
  const reason = payload.reason || payload.hover || '';
  el.textContent = reason;
}
