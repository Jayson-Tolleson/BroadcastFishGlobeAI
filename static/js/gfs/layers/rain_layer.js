export class RainLayer {
  constructor(){ this.enabled=false; this.payload=null; this.lastStable=null; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  refresh(frame){
    if(this.enabled && frame?.weather?.fields){ this.payload=frame.weather; this.lastStable=frame.weather; this.degraded=false; return; }
    if(this.lastStable){ this.payload=this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.payload=null; }
}
