
export function initLayerPills(engine){

document.querySelectorAll(".pill").forEach(btn=>{

btn.addEventListener("click",()=>{

const layer=btn.dataset.layer

engine.toggle(layer)

btn.classList.toggle("active")

})

})

}
