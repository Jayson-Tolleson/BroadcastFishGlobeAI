function validCurrentFields(fields){ return fields && Array.isArray(fields.current_u) && Array.isArray(fields.current_v); }
export class CurrentLayer {
  constructor(){ this.enabled = false; this.payload = null; this.lastStable = null; this.degraded=false; }
  enable(){ this.enabled = true; }
  disable(){ this.enabled = false; }
  refresh(frame){
    if (!this.enabled) return;
    const next = frame?.ocean?.fields || null;
    if (validCurrentFields(next)) { this.payload = next; this.lastStable = next; this.degraded=false; return; }
    if (this.lastStable) { this.payload = this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.payload = null; }
}
