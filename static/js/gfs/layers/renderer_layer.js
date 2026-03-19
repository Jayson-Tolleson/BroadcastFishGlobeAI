function defaultSignature(frame, payload) {
  const bbox = Array.isArray(payload?.bbox) ? payload.bbox.join(',') : (Array.isArray(frame?.bbox) ? frame.bbox.join(',') : '');
  const valid = payload?.valid_time || frame?.valid_time || '';
  const source = payload?.source_time || frame?.source_time || '';
  const resolved = payload?.resolved_time || frame?.resolved_time || '';
  const hint = [
    Array.isArray(payload?.cloud_layers) ? payload.cloud_layers.length : 0,
    Array.isArray(payload?.front_lines) ? payload.front_lines.length : 0,
    Array.isArray(payload?.bait?.polygons) ? payload.bait.polygons.length : 0,
    Array.isArray(payload?.boats) ? payload.boats.length : 0,
    Array.isArray(payload?.polygons?.boater) ? payload.polygons.boater.length : 0,
  ].join(':');
  return `${bbox}|${valid}|${source}|${resolved}|${hint}`;
}

export class RendererLayer {
  constructor(map3DElement, { name, selector, renderer, signature }) {
    this.map = map3DElement;
    this.name = name;
    this.selector = selector;
    this.renderer = renderer;
    this.signature = signature || defaultSignature;
    this.visible = false;
    this.currentFrame = null;
    this.currentDisposer = null;
    this.lastSignature = '';
  }

  show() {
    this.visible = true;
    if (this.currentFrame) this.onData(this.currentFrame);
  }

  hide() {
    this.visible = false;
    this.clear();
  }

  clear() {
    this.lastSignature = '';
    if (typeof this.currentDisposer === 'function') {
      try { this.currentDisposer(); } catch (err) { console.warn('[gfs renderer layer] disposer failed', this.name, err); }
    }
    this.currentDisposer = null;
  }

  onData(frame) {
    this.currentFrame = frame || null;
    if (!this.visible || !this.map || !frame) return;
    const payload = this.selector?.(frame) || null;
    if (!payload) {
      this.clear();
      return;
    }
    const nextSignature = String(this.signature(frame, payload));
    if (nextSignature && nextSignature === this.lastSignature) return;
    this.clear();
    this.lastSignature = nextSignature;
    const viewportReason = frame?.render_reason || frame?.meta?.render_reason || 'steady';
    this.currentDisposer = this.renderer?.({
      frame,
      payload,
      map3DElement: this.map,
      viewportReason,
      layerName: this.name,
    }) || null;
  }

  update() {}
}
