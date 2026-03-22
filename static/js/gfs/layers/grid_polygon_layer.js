import { createPolygon3D } from '../polygon3d.js';
import { loadRecursiveInterpretation } from '../recursive_grid.js';

function colorStyles(name) {
  switch (name) {
    case 'clouds': return { fillColor: '#f5fbff', fillOpacity: 0.18, strokeColor: '#d9efff', strokeOpacity: 0.4, strokeWidth: 1, altitude: 1800, extrudedHeight: 900 };
    case 'rain': return { fillColor: '#4ca7ff', fillOpacity: 0.24, strokeColor: '#7cc0ff', strokeOpacity: 0.5, strokeWidth: 1, altitude: 1200, extrudedHeight: 650 };
    case 'bait': return { fillColor: '#00f0b5', fillOpacity: 0.22, strokeColor: '#6bffe0', strokeOpacity: 0.55, strokeWidth: 1, altitude: 20, extrudedHeight: 24 };
    case 'boater': return { fillColor: '#ffb347', fillOpacity: 0.22, strokeColor: '#ffd28e', strokeOpacity: 0.55, strokeWidth: 1, altitude: 30, extrudedHeight: 40 };
    default: return { fillColor: '#ffffff', fillOpacity: 0.2, strokeColor: '#ffffff', strokeOpacity: 0.5, strokeWidth: 1, altitude: 10, extrudedHeight: 20 };
  }
}

function toPath(coords) {
  if (!Array.isArray(coords)) return [];
  return coords.map((pair) => ({ lng: Number(pair[0]), lat: Number(pair[1]) })).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng));
}

function recursivePayload(payload) {
  if (payload?.recursiveGrid?.polygons) return payload.recursiveGrid;
  if (payload?.polygons) return payload;
  return null;
}

export class GridPolygonLayer {
  constructor(map3d, layerName) {
    this.map = map3d;
    this.layerName = layerName;
    this.visible = false;
    this.rendered = [];
    this.lastKey = '';
    this.pending = null;
  }

  async ensureData() {
    const bbox = window.currentBBox || window.__gfsLastBbox;
    if (!bbox) return null;
    if (!window.__gfsRecursiveGrid?.latest || window.__gfsRecursiveGrid?.bbox !== bbox) {
      this.pending = this.pending || loadRecursiveInterpretation(bbox, 'full').then((payload) => {
        window.__gfsRecursiveGrid = { latest: payload, bbox };
        this.pending = null;
        return payload;
      }).catch((err) => { this.pending = null; console.warn('[gfs grid layer] recursive grid fetch failed', err); return null; });
      return await this.pending;
    }
    return window.__gfsRecursiveGrid.latest;
  }

  async show() {
    this.visible = true;
    const data = await this.ensureData();
    if (data) this.onData(data);
  }

  hide() {
    this.visible = false;
    this.clear();
  }

  clear() {
    this.lastKey = '';
    this.rendered.forEach((el) => { try { el.remove(); } catch (_) {} });
    this.rendered = [];
  }

  onData(payload) {
    if (!this.visible || !this.map) return;
    const source = recursivePayload(payload);
    const polys = Array.isArray(source?.polygons?.[this.layerName]) ? source.polygons[this.layerName] : [];
    const key = `${this.layerName}:${source?.bbox?.join(',')}:${polys.length}`;
    if (key === this.lastKey) return;
    this.clear();
    this.lastKey = key;
    const style = colorStyles(this.layerName);
    const frag = document.createDocumentFragment();
    polys.slice(0, 96).forEach((poly) => {
      const path = toPath(poly.coordinates);
      if (path.length < 3) return;
      const el = createPolygon3D({ path, ...style, altitudeMode: 'relative' });
      if (!el) return;
      frag.append(el);
      this.rendered.push(el);
    });
    if (this.rendered.length) this.map.append(frag);
  }

  update() {}
}
