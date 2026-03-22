export class CloudLayer {
  constructor(){ this.enabled=false; this.payload=null; this.lastStable=null; this.degraded=false; }
  enable(){ this.enabled=true; }
  disable(){ this.enabled=false; }
  refresh(frame){
    if(!this.enabled) return;
    const next=frame?.clouds;
    if(next && (Array.isArray(next.items) || Array.isArray(next.cloud_layers))){ this.payload=next; this.lastStable=next; this.degraded=false; return; }
    if(this.lastStable){ this.payload=this.lastStable; this.degraded=true; }
  }
  update(){}
  destroy(){ this.payload=null; }
}
