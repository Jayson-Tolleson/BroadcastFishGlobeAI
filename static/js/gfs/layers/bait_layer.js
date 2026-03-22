function validPoly(poly){ return Array.isArray(poly?.coordinates) && poly.coordinates.length >= 4; }
export class BaitLayer {
  constructor(){ this.enabled=false; this.polygons=[]; this.lastStable=[]; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  refresh(frame){
    if(!this.enabled) return;
    const nextRaw = frame?.baitAdvanced?.bait?.polygons||frame?.baitBase?.bait?.polygons;
    const next = Array.isArray(nextRaw) ? nextRaw.filter(validPoly) : [];
    if(next.length){ this.polygons=next; this.lastStable=next; this.degraded=false; return; }
    if(this.lastStable.length){ this.polygons=this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.polygons=[]; }
}
