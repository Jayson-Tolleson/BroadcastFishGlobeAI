
export class LayerEngine{

constructor(){
this.layers={}
this.clock=new THREE.Clock()
}

register(name,layer){
this.layers[name]={enabled:false,instance:layer}
}

toggle(name){

const l=this.layers[name]
if(!l) return

l.enabled=!l.enabled

if(l.enabled){
l.instance.show()
}else{
l.instance.hide()
}

}

update(){

const dt=this.clock.getDelta()

for(const k in this.layers){

const l=this.layers[k]

if(l.enabled && l.instance.update){
l.instance.update(dt)
}

}

}

}
