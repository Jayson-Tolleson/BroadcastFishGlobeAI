export class RainLayer { constructor(){ this.enabled=false; this.payload=null; this.lastStable=null; }
enable(){ this.enabled=true; }
disable(){ this.enabled=false; }
refresh(frame){ if(this.enabled && frame?.weather){ this.payload=frame.weather; this.lastStable=frame.weather; } }
update(){}
destroy(){ this.payload=null; } }
