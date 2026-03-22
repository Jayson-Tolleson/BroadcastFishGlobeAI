import { fetchBoats } from '../api.js';

function validBoat(item){
  return item && item.id && Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lon)) && Number.isFinite(Number(item.heading_deg));
}

function deriveViewport(frame) {
  const ocean = frame?.ocean || {};
  const bbox = Array.isArray(ocean?.bbox) ? ocean.bbox : (Array.isArray(frame?.bbox) ? frame.bbox : null);
  if (!Array.isArray(bbox) || bbox.length < 4) return null;
  const [west, south, east, north] = bbox.map(Number);
  if (![west, south, east, north].every(Number.isFinite)) return null;
  return {
    west,
    south,
    east,
    north,
    quality: String(ocean?.quality || frame?.quality || 'coarse'),
    stride: Number(ocean?.stride || frame?.stride || 1),
  };
}

function viewportKey(vp) {
  if (!vp) return '';
  return `${vp.west},${vp.south},${vp.east},${vp.north}|${vp.quality}|${vp.stride}`;
}

export class BoatLayer {
  constructor(){ this.enabled=false; this.boats=[]; this.lastStable=[]; this.lastViewportKey=''; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  async refresh(frame, token){
    if(!this.enabled) return;
    const vp = deriveViewport(frame);
    const key = viewportKey(vp);
    if (key && key !== this.lastViewportKey) {
      this.lastViewportKey = key;
      const payload = await fetchBoats(vp, { abortPrevious: true }).catch(() => null);
      if (token?.aborted || key !== this.lastViewportKey) return;
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
