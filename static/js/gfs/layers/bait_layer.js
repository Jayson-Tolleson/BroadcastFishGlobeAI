export class BaitLayer { constructor(){ this.enabled=false; this.polygons=[]; this.lastStable=[]; }
enable(){ this.enabled=true; }
disable(){ this.enabled=false; }
refresh(frame){ if(!this.enabled) return; const next=frame?.baitAdvanced?.bait?.polygons||frame?.baitBase?.bait?.polygons; if(Array.isArray(next)&&next.length){ this.polygons=next; this.lastStable=next; } }
update(){}
destroy(){ this.polygons=[]; } }
