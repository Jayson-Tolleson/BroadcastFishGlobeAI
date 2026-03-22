import { fetchBoats } from '../api.js';

function validBoat(item){
  return item && item.id && Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lon)) && Number.isFinite(Number(item.heading_deg));
}

export class BoatLayer {
  constructor(){ this.enabled=false; this.boats=[]; this.lastStable=[]; this.lastViewport=''; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  async refresh(frame, token){
    if(!this.enabled) return;
    const vp = frame?.ocean?.bbox || frame?.bbox;
    const vpKey = Array.isArray(vp) ? vp.join(',') : '';
    if (vpKey && vpKey !== this.lastViewport) {
      this.lastViewport = vpKey;
      const payload = await fetchBoats(vpKey, { abortPrevious: true }).catch(() => null);
      if (token?.aborted) return;
      const next = Array.isArray(payload?.boats) ? payload.boats.filter(validBoat) : [];
      if (next.length) { this.boats=next; this.lastStable=next; this.degraded=false; return; }
    }
    const side = Array.isArray(frame?.boats?.boats) ? frame.boats.boats.filter(validBoat) : [];
    if(side.length){ this.boats=side; this.lastStable=side; this.degraded=false; return; }
    if(this.lastStable.length){ this.boats=this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.boats=[]; }
}
