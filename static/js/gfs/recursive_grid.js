import { getJsonSafe } from "./api.js";

export async function loadRecursiveInterpretation(bbox, quality = "full") {
  return await getJsonSafe(`/gfs/api/frame?bbox=${bbox}&quality=full`, null).then((frame) => frame?.recursiveGrid || null);
}
