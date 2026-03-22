export class HazardLayer {
  constructor(){ this.enabled=false; this.payload=null; this.lastStable=null; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  refresh(frame){
    if(this.enabled && frame?.hazards){ this.payload=frame.hazards; this.lastStable=frame.hazards; this.degraded=false; return; }
    if(this.lastStable){ this.payload=this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.payload=null; }
}
