export class BoatLayer { constructor(){ this.enabled=false; this.boats=[]; this.lastStable=[]; }
enable(v){ this.enabled=!!v; if(!this.enabled) this.boats=this.lastStable; }
refresh(frame){ if(!this.enabled) return; const next=frame?.boats?.boats; if(Array.isArray(next)&&next.length){ this.boats=next; this.lastStable=next; } }
update(){}
destroy(){ this.boats=[]; } }
