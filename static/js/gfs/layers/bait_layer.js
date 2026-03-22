export class BaitLayer { constructor(){ this.enabled=false; this.polygons=[]; this.lastStable=[]; }
enable(v){ this.enabled=!!v; if(!this.enabled) this.polygons=this.lastStable; }
refresh(frame){ if(!this.enabled) return; const next=frame?.baitAdvanced?.bait?.polygons||frame?.baitBase?.bait?.polygons; if(Array.isArray(next)&&next.length){ this.polygons=next; this.lastStable=next; } }
update(){}
destroy(){ this.polygons=[]; } }
