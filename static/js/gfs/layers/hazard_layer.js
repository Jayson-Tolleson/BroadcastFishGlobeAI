export class HazardLayer { constructor(){ this.enabled=false; this.payload=null; }
enable(v){ this.enabled=!!v; }
refresh(frame){ if(this.enabled) this.payload=frame?.hazards||null; }
update(){}
destroy(){ this.payload=null; } }
