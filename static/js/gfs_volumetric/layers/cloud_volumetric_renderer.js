
import * as THREE from "https://unpkg.com/three@0.160.0/build/three.module.js"

export class VolumetricCloudLayer{

constructor(map3d){

this.map=map3d
this.scene=map3d.scene
this.visible=false
this.cloudMaterial=null
this.cloudMesh=null
this.time=0

}

show(){

if(this.visible) return
this.visible=true
this.buildVolume()

}

hide(){

this.visible=false
if(this.cloudMesh){
this.scene.remove(this.cloudMesh)
}

}

buildVolume(){

const geometry=new THREE.SphereGeometry(
6371000+12000,
64,
64
)

this.cloudMaterial=this.createShader()

this.cloudMesh=new THREE.Mesh(
geometry,
this.cloudMaterial
)

this.scene.add(this.cloudMesh)

}

createShader(){

return new THREE.ShaderMaterial({

transparent:true,
depthWrite:false,

uniforms:{
time:{value:0},
wind:{value:new THREE.Vector2(0.1,0.05)}
},

vertexShader:`

varying vec3 vWorld;

void main(){

vec4 worldPosition=modelMatrix*vec4(position,1.0);

vWorld=worldPosition.xyz;

gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);

}

`,

fragmentShader:`

precision highp float;

varying vec3 vWorld;

uniform float time;
uniform vec2 wind;

float hash(vec3 p){
return fract(sin(dot(p,vec3(12.9898,78.233,37.719)))*43758.5453);
}

float noise(vec3 p){

vec3 i=floor(p);
vec3 f=fract(p);

float n000=hash(i+vec3(0,0,0));
float n001=hash(i+vec3(0,0,1));
float n010=hash(i+vec3(0,1,0));
float n011=hash(i+vec3(0,1,1));
float n100=hash(i+vec3(1,0,0));
float n101=hash(i+vec3(1,0,1));
float n110=hash(i+vec3(1,1,0));
float n111=hash(i+vec3(1,1,1));

vec3 u=f*f*(3.0-2.0*f);

return mix(
mix(mix(n000,n100,u.x),mix(n010,n110,u.x),u.y),
mix(mix(n001,n101,u.x),mix(n011,n111,u.x),u.y),
u.z
);

}

float fbm(vec3 p){

float value=0.0;
float amp=0.5;

for(int i=0;i<5;i++){

value+=noise(p)*amp;
p*=2.0;
amp*=0.5;

}

return value;

}

float cloudDensity(vec3 p){

p.xy+=wind*time*0.05;

float n=fbm(p*0.0002);

return smoothstep(0.4,0.8,n);

}

void main(){

float height=length(vWorld)-6371000.0;

if(height<1000.0||height>12000.0)
discard;

float d=cloudDensity(vWorld);

if(d<0.1)
discard;

gl_FragColor=vec4(vec3(1.0),d*0.8);

}

`

})

}

update(dt){

if(!this.visible) return

this.time+=dt

if(this.cloudMaterial){
this.cloudMaterial.uniforms.time.value=this.time
}

}

}
