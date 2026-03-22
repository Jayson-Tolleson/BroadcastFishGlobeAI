export class HazardLayer { constructor(){ this.enabled=false; this.payload=null; this.lastStable=null; }
enable(){ this.enabled=true; }
disable(){ this.enabled=false; }
refresh(frame){ if(this.enabled && frame?.hazards){ this.payload=frame.hazards; this.lastStable=frame.hazards; } }
update(){}
destroy(){ this.payload=null; } }
