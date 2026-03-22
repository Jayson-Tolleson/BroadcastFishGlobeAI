import { fetchBoats } from '../api.js';

export class BoatLayer {
  constructor(){ this.enabled=false; this.boats=[]; this.lastStable=[]; this.lastViewport=''; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  async refresh(frame){
    if(!this.enabled) return;
    const vp = frame?.ocean?.bbox || frame?.bbox;
    const vpKey = Array.isArray(vp) ? vp.join(',') : '';
    if (vpKey && vpKey !== this.lastViewport) {
      this.lastViewport = vpKey;
      const payload = await fetchBoats(vpKey).catch(() => null);
      const next = payload?.boats;
      if (Array.isArray(next) && next.length) { this.boats=next; this.lastStable=next; return; }
    }
    const side = frame?.boats?.boats;
    if(Array.isArray(side)&&side.length){ this.boats=side; this.lastStable=side; }
  }
  update(){}
  destroy(){ this.boats=[]; }
}
