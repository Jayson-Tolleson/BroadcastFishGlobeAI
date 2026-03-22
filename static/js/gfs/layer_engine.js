export class LayerEngine {
  constructor(){
    this.layers = {};
    this.lastTs = performance.now();
    this.latestData = null;
  }
  register(name, layer){
    this.layers[name] = { enabled:false, instance:layer };
    layer.disable?.();
  }
  setData(payload){
    this.latestData = payload || null;
    Object.entries(this.layers).forEach(([name, layer]) => {
      if (layer.enabled) {
        try { layer.instance.refresh?.(this.latestData); } catch (err) { console.error('[gfs layers] refresh failed', name, err); }
      }
    });
  }
  setEnabled(name, enabled){
    const layer = this.layers[name];
    if(!layer) return false;
    if(layer.enabled === enabled) return true;
    layer.enabled = enabled;
    if (enabled) {
      layer.instance.enable?.();
      if (this.latestData) layer.instance.refresh?.(this.latestData);
    } else {
      layer.instance.disable?.();
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
