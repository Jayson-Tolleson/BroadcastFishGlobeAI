export class JetstreamLayer { constructor(){ this.enabled=false; }
enable(v){ this.enabled=!!v; if(typeof window.setJetBalloonsEnabled==='function') window.setJetBalloonsEnabled(this.enabled); }
refresh(){}
update(){}
destroy(){ this.enable(false); } }
