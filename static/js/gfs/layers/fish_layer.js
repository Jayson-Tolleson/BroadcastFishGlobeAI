export class FishLayer { constructor(){ this.enabled=false; this.items=[]; this.lastStable=[]; }
enable(){ this.enabled=true; }
disable(){ this.enabled=false; }
refresh(frame){ if(!this.enabled) return; const next=frame?.fish?.items; if(Array.isArray(next) && next.length){ this.items=next; this.lastStable=next; } }
update(){}
destroy(){ this.items=[]; this.lastStable=[]; } }
