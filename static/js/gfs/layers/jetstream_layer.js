export class JetstreamLayer { constructor(){ this.enabled=false; }
enable(){ this.enabled=true; if(typeof window.setJetBalloonsEnabled==='function') window.setJetBalloonsEnabled(true); }
disable(){ this.enabled=false; if(typeof window.setJetBalloonsEnabled==='function') window.setJetBalloonsEnabled(false); }
refresh(){}
update(){}
destroy(){ this.disable(); } }
