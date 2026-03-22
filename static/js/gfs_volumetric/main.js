
import {LayerEngine} from "./engine/layer_engine.js"
import {VolumetricCloudLayer} from "./layers/cloud_volumetric_renderer.js"
import {initLayerPills} from "./ui/layer_pills.js"

let map3d
let engine
let clouds

async function boot(){

await google.maps.importLibrary("maps3d")

map3d=document.querySelector("gmp-map-3d")

engine=new LayerEngine()

clouds=new VolumetricCloudLayer(map3d)

engine.register("clouds",clouds)

initLayerPills(engine)

animate()

}

function animate(){

requestAnimationFrame(animate)

engine.update()

}

boot()
