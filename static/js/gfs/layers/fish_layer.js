function validFish(item){
  return item && Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lon)) && item.id;
}
export class FishLayer {
  constructor(){ this.enabled=false; this.items=[]; this.lastStable=[]; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  refresh(frame){
    if(!this.enabled) return;
    const next=Array.isArray(frame?.fish?.items) ? frame.fish.items.filter(validFish) : [];
    if(next.length){ this.items=next; this.lastStable=next; this.degraded=false; return; }
    if (Array.isArray(this.lastStable) && this.lastStable.length) { this.items=this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.items=[]; this.lastStable=[]; }
}
