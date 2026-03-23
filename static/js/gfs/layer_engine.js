export class LayerEngine {
  constructor(){
    this.layers = {};
    this.lastTs = performance.now();
    this.latestData = null;
    this.inflight = {};
  }
  register(name, layer){
    this.layers[name] = { enabled:false, instance:layer };
    layer.disable?.();
  }
  async setData(payload){
    console.info('[gfs layers] setData start', {
      hasPayload: Boolean(payload),
      fish_items: Array.isArray(payload?.fish?.items) ? payload.fish.items.length : 0,
      boats: Array.isArray(payload?.boats?.boats) ? payload.boats.boats.length : 0,
      bait_polygons: Array.isArray(payload?.baitAdvanced?.bait?.polygons) ? payload.baitAdvanced.bait.polygons.length : 0,
    });
    if (payload?.locations && payload?.entity_type === 'fish_intelligence') {
      console.warn('[gfs layers] rejected mixed payload: fish entity carrying locations collection', { entity_type: payload?.entity_type, derived: payload?.derived });
      payload = { ...payload, locations: [] };
    }
    if (payload?.locations && payload?.derived === true) {
      console.warn('[gfs layers] rejected derived locations payload contract', { entity_type: payload?.entity_type, derived: payload?.derived });
      payload = { ...payload, locations: [] };
    }
    this.latestData = payload || null;
    await Promise.all(Object.entries(this.layers).map(async ([name, layer]) => {
      if (!layer.enabled) return;
      if (this.inflight[name]) {
        try { this.inflight[name].abort?.(); } catch (_) {}
      }
      const token = { aborted: false, abort(){ this.aborted = true; } };
      this.inflight[name] = token;
      try {
        await layer.instance.refresh?.(this.latestData, token);
      } catch (err) {
        console.error('[gfs layers] refresh failed', name, err);
      }
      finally { if (this.inflight[name] === token) this.inflight[name] = null; }
    }));
  }
  setEnabled(name, enabled){
    const layer = this.layers[name];
    if(!layer) return false;
    if(layer.enabled === enabled) return true;
    layer.enabled = enabled;
    if (enabled) {
      layer.instance.enable?.();
      if (this.latestData) {
        console.info('[gfs layers] toggle on -> refresh', { layer: name });
        layer.instance.refresh?.(this.latestData);
      }
    } else {
      layer.instance.disable?.();
      console.info('[gfs layers] toggle off', { layer: name });
    }
    return true;
  }
  refresh(name){
    const layer = this.layers[name];
    if (!layer || !layer.enabled) return;
    layer.instance.refresh?.(this.latestData);
  }
  destroy(){
    Object.values(this.layers).forEach((layer) => {
      try { layer.instance.destroy?.(); } catch (_) {}
    });
  }
  update(){
    const now = performance.now();
    const dt = Math.max(0, (now - this.lastTs) / 1000);
    this.lastTs = now;
    Object.values(this.layers).forEach((layer) => {
      if(layer.enabled){
        try { layer.instance.update?.(dt, this.latestData); } catch (err) { console.error('[gfs layers] update failed', err); }
      }
    });
  }
}
