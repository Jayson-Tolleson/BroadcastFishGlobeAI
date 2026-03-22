export class FishLayer { constructor(){ this.enabled=false; this.items=[]; this.lastStable=[]; }
enable(v){ this.enabled=!!v; if(!this.enabled) this.items=this.lastStable; }
refresh(frame){ if(!this.enabled) return; const next=frame?.fish?.items; if(Array.isArray(next) && next.length){ this.items=next; this.lastStable=next; } }
update(){}
destroy(){ this.items=[]; this.lastStable=[]; } }
