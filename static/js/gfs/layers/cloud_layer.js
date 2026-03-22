export class CloudLayer { constructor(){ this.enabled=false; this.payload=null; this.lastStable=null; }
enable(){ this.enabled=true; }
disable(){ this.enabled=false; }
refresh(frame){ if(!this.enabled) return; const next=frame?.clouds; if(next){ this.payload=next; this.lastStable=next; } }
update(){}
destroy(){ this.payload=null; } }
