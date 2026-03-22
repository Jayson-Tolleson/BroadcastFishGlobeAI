export class CurrentLayer {
  constructor(){ this.enabled = false; this.payload = null; }
  enable(v){ this.enabled = !!v; }
  refresh(frame){ if (!this.enabled) return; this.payload = frame?.ocean?.fields || null; }
  update(){}
  destroy(){ this.payload = null; }
}
