import { getJsonSafe, postJsonSafe, uploadSafe } from './api.js';
import { loadLocationVideos, renderVideoFrame } from './media.js';

function clamp(value, lo = 0, hi = 100) {
  const n = Number(value);
  if (!Number.isFinite(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

function pct(value, digits = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'n/a';
  return `${n.toFixed(digits)}%`;
}

function safeFixed(value, digits = 1, suffix = '') {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : 'n/a';
}

function cToF(value) {
  const n = Number(value);
  return Number.isFinite(n) ? ((n * 9) / 5) + 32 : NaN;
}

function normalizeMaybeFahrenheit(value, referenceF = NaN) {
  const raw = Number(value);
  if (!Number.isFinite(raw)) return NaN;
  const ref = Number(referenceF);
  const asF = raw;
  const asConverted = cToF(raw);
  if (!Number.isFinite(ref)) {
    return (raw >= -20 && raw <= 45) ? asConverted : asF;
  }
  if (!Number.isFinite(asConverted)) return asF;
  return Math.abs(asConverted - ref) + 2 < Math.abs(asF - ref) ? asConverted : asF;
}

function averageGrid(grid, fallback = NaN) {
  if (!Array.isArray(grid) || !Array.isArray(grid[0])) return fallback;
  const arr = Array.isArray(grid[0][0]) ? grid[0] : grid;
  let sum = 0;
  let count = 0;
  for (const row of arr) {
    if (!Array.isArray(row)) continue;
    for (const value of row) {
      const n = Number(value);
      if (Number.isFinite(n)) {
        sum += n;
        count += 1;
      }
    }
  }
  return count ? (sum / count) : fallback;
}

function geoDistanceNm(lat1, lon1, lat2, lon2) {
  const a1 = Number(lat1);
  const o1 = Number(lon1);
  const a2 = Number(lat2);
  const o2 = Number(lon2);
  if (![a1, o1, a2, o2].every(Number.isFinite)) return NaN;
  const meanLat = ((a1 + a2) / 2) * Math.PI / 180;
  const dLatNm = (a2 - a1) * 60;
  const dLonNm = (o2 - o1) * 60 * Math.cos(meanLat);
  return Math.hypot(dLatNm, dLonNm);
}

function nearestPoint(points, lat, lon, maxDeg = 5) {
  if (!Array.isArray(points) || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  let best = null;
  let bestD = Infinity;
  for (const point of points) {
    const plat = Number(point?.lat);
    const plon = Number(point?.lon);
    if (!Number.isFinite(plat) || !Number.isFinite(plon)) continue;
    const d = Math.hypot(plat - lat, plon - lon);
    if (d < bestD) {
      best = point;
      bestD = d;
    }
  }
  if (!best) return null;
  const distanceNm = geoDistanceNm(lat, lon, best.lat, best.lon);
  return { ...best, _distance_deg: bestD, _distance_nm: distanceNm };
}

function interpolateBoatScalar(boats, lat, lon, getter, maxDistanceNm = 90, maxPoints = 4) {
  if (!Array.isArray(boats) || !Number.isFinite(lat) || !Number.isFinite(lon)) return NaN;
  const samples = [];
  for (const boat of boats) {
    const plat = Number(boat?.lat);
    const plon = Number(boat?.lon);
    const value = Number(getter?.(boat));
    if (!Number.isFinite(plat) || !Number.isFinite(plon) || !Number.isFinite(value)) continue;
    const distanceNm = geoDistanceNm(lat, lon, plat, plon);
    if (!Number.isFinite(distanceNm) || distanceNm > maxDistanceNm) continue;
    samples.push({ value, distanceNm });
  }
  if (!samples.length) return NaN;
  samples.sort((a, b) => a.distanceNm - b.distanceNm);
  const top = samples.slice(0, maxPoints);
  if (top[0].distanceNm <= 0.25) return top[0].value;
  let weighted = 0;
  let weightSum = 0;
  for (const sample of top) {
    const weight = 1 / Math.max(sample.distanceNm, 0.25);
    weighted += sample.value * weight;
    weightSum += weight;
  }
  return weightSum ? (weighted / weightSum) : NaN;
}

function to2DGrid(value) {
  if (!Array.isArray(value) || !Array.isArray(value[0])) return null;
  return Array.isArray(value[0][0]) ? value[0] : value;
}

function gridValueAt(arr, yi, xi) {
  const row = arr?.[yi];
  return Number(row?.[xi]);
}

function bilinearSample(arr, bbox, lat, lon) {
  const grid = to2DGrid(arr);
  if (!grid || !Array.isArray(bbox) || bbox.length < 4) return NaN;
  const ny = grid.length;
  const nx = Array.isArray(grid[0]) ? grid[0].length : 0;
  if (!ny || !nx) return NaN;
  const west = Number(bbox[0]);
  const south = Number(bbox[1]);
  const east = Number(bbox[2]);
  const north = Number(bbox[3]);
  const spanX = (east - west) || 1;
  const spanY = (north - south) || 1;
  let x = ((Number(lon) - west) / spanX) * Math.max(0, nx - 1);
  let y = ((Number(lat) - south) / spanY) * Math.max(0, ny - 1);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return NaN;
  x = Math.max(0, Math.min(nx - 1, x));
  y = Math.max(0, Math.min(ny - 1, y));
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const x1 = Math.min(nx - 1, x0 + 1);
  const y1 = Math.min(ny - 1, y0 + 1);
  const tx = x - x0;
  const ty = y - y0;
  const q11 = gridValueAt(grid, y0, x0);
  const q21 = gridValueAt(grid, y0, x1);
  const q12 = gridValueAt(grid, y1, x0);
  const q22 = gridValueAt(grid, y1, x1);
  if (![q11, q21, q12, q22].every(Number.isFinite)) return NaN;
  const a = q11 * (1 - tx) + q21 * tx;
  const b = q12 * (1 - tx) + q22 * tx;
  return a * (1 - ty) + b * ty;
}

function fieldSample(payload, fieldName, lat, lon) {
  return bilinearSample(payload?.fields?.[fieldName], payload?.bbox, lat, lon);
}

function formatUnavailable(value, formatter) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'Unavailable';
  return formatter(n);
}

function normalizeEnvironment({ wx, ocean, boats, lat, lon, cloudPct, rainRate, windKt, windDir, currentKt, currentDir, swellFt }) {
  const sampledSstK = fieldSample(ocean, 'sst_k', lat, lon);
  const sampledChl = fieldSample(ocean, 'chlorophyll_mg_m3', lat, lon);
  const sampledCurrentSpeed = fieldSample(ocean, 'current_speed', lat, lon);
  const sampledCurrentU = fieldSample(ocean, 'current_u', lat, lon);
  const sampledCurrentV = fieldSample(ocean, 'current_v', lat, lon);
  const sampledDepth = fieldSample(ocean, 'depth_m', lat, lon);
  const sampledWaveHeightM = fieldSample(ocean, 'wave_height_m', lat, lon);
  const sampledWavePeriodS = Number(interpolateBoatScalar(boats?.boats, lat, lon, (entry) => entry?.waves?.primary?.periodS, 120, 4));
  const sampledWindU = fieldSample(wx, 'wind_u', lat, lon);
  const sampledWindV = fieldSample(wx, 'wind_v', lat, lon);
  const sampledPressurePa = fieldSample(wx, 'pressure_msl', lat, lon);
  const sampledGustKt = fieldSample(wx, 'wind_gust', lat, lon);
  const currentDirFromVector = Number.isFinite(sampledCurrentU) && Number.isFinite(sampledCurrentV)
    ? ((Math.atan2(sampledCurrentU, sampledCurrentV) * 180 / Math.PI) + 360) % 360
    : NaN;
  const windDirFromVector = Number.isFinite(sampledWindU) && Number.isFinite(sampledWindV)
    ? ((Math.atan2(sampledWindU, sampledWindV) * 180 / Math.PI) + 360) % 360
    : NaN;
  const windSpeedFromVectorKt = Number.isFinite(sampledWindU) && Number.isFinite(sampledWindV)
    ? Math.hypot(sampledWindU, sampledWindV) * 1.94384
    : NaN;
  const seaSurfaceTempF = Number.isFinite(sampledSstK) ? (((sampledSstK - 273.15) * 9) / 5) + 32 : NaN;
  return {
    sea_surface_temp: seaSurfaceTempF,
    chlorophyll: sampledChl,
    current_speed: Number.isFinite(currentKt) ? currentKt : sampledCurrentSpeed,
    current_direction: Number.isFinite(currentDir) ? currentDir : currentDirFromVector,
    wave_height: Number.isFinite(swellFt) ? swellFt : (Number.isFinite(sampledWaveHeightM) ? sampledWaveHeightM * 3.28084 : NaN),
    wave_period: sampledWavePeriodS,
    depth: sampledDepth,
    wind_speed: Number.isFinite(windKt) ? windKt : windSpeedFromVectorKt,
    wind_direction: Number.isFinite(windDir) ? windDir : windDirFromVector,
    cloud_cover: cloudPct,
    rain_rate: rainRate,
    pressure_mb: Number.isFinite(sampledPressurePa) ? sampledPressurePa / 100 : NaN,
    wind_gust_kt: Number.isFinite(sampledGustKt) ? sampledGustKt * 1.94384 : NaN,
    source_flags: {
      weather: wx?.source || 'unknown',
      ocean: ocean?.source || 'unknown',
      degraded: Boolean(ocean?.degraded || wx?.degraded_mode),
    },
  };
}

function scoreText(score) {
  if (score >= 80) return 'High';
  if (score >= 62) return 'Good';
  if (score >= 45) return 'Moderate';
  return 'Low';
}

function trendText(score, baitState, frontCount, boilCount) {
  if (score >= 78 && (baitState === 'stacking' || boilCount > 0)) return 'Building';
  if (frontCount > 0 || baitState === 'moving') return 'Active';
  if (score >= 55) return 'Stable';
  return 'Watch';
}

function classifyBaitState(baitScore, fronts, boils) {
  if (baitScore >= 78 && (fronts >= 1 || boils >= 1)) return 'stacking';
  if (baitScore >= 62 && fronts >= 1) return 'holding';
  if (baitScore >= 48) return 'moving';
  return 'scattered';
}

function confidenceLabel(score) {
  if (score >= 80) return 'High';
  if (score >= 58) return 'Medium';
  return 'Low';
}

function safetyLabel(score) {
  if (score >= 78) return 'Good';
  if (score >= 55) return 'Moderate';
  return 'Rough';
}

function speciesTempWindow(tempF, center, halfSpan) {
  const t = Number(tempF);
  if (!Number.isFinite(t)) return 0.5;
  const diff = Math.abs(t - center);
  return clamp((1 - (diff / halfSpan)) * 100, 0, 100) / 100;
}

function summarizeReports(reports) {
  const joined = Array.isArray(reports) ? reports.join(' • ').toLowerCase() : '';
  return {
    joined,
    sardine: /sardine/.test(joined),
    anchovy: /anchov/.test(joined),
    jig: /(jig|iron)/.test(joined),
    flyline: /flyline/.test(joined),
    fresh: /(trout|catfish|largemouth|smallmouth|striper|stocked|powerbait)/.test(joined),
    salt: /(tuna|yellowtail|dorado|mackerel|mack|barracuda|halibut|corbina|shark|calico|kelp bass)/.test(joined),
  };
}

function recommendTackle(speciesRows, reportHints, baitState, profile) {
  if (Array.isArray(profile?.tackle_hints) && profile.tackle_hints.length) {
    const lead = profile.tackle_hints[0];
    if (baitState === 'stacking' && Array.isArray(profile.tackle_hints) && profile.tackle_hints[1]) return `${lead} • ${profile.tackle_hints[1]}`;
    return lead;
  }
  const ordered = Array.isArray(speciesRows) ? [...speciesRows].sort((a, b) => b.score - a.score) : [];
  const top = ordered[0]?.key || 'coastal_general';
  if (top === 'tuna') return reportHints.sardine ? 'Flylined sardine / sinker rig / knife jig' : 'Flylined bait / sinker rig / knife jig';
  if (top === 'yellowtail') return reportHints.jig ? 'Surface iron / yo-yo jig / flylined bait' : 'Flylined sardine / surface iron / yo-yo jig';
  if (top === 'dorado') return 'Small paddletail / troll feather / live bait near moving water';
  if (top === 'trout') return 'PowerBait / mini jig / slip-float at first light';
  if (top === 'catfish') return 'Cut bait / stink bait / night soak near channel edge';
  if (top === 'largemouth_bass' || top === 'bass') return 'Swimbait / finesse worm / live bait near structure';
  if (baitState === 'stacking') return 'Sabiki / small live bait / finesse presentation';
  return reportHints.anchovy ? 'Anchovy / small jig / light leader' : 'Small live bait / anchovy / sabiki at active periods';
}

function speciesPoolForClass(markerClass = 'coastal') {
  if (markerClass === 'inland') {
    return [
      { key: 'trout', label: 'Trout', temp_center_f: 58, temp_half_span_f: 9, structure_bias: 0.18, current_bias: 0.08, bait_bias: 0.14, hint_boost: 6 },
      { key: 'largemouth_bass', label: 'Largemouth Bass', temp_center_f: 68, temp_half_span_f: 11, structure_bias: 0.26, current_bias: 0.04, bait_bias: 0.12, hint_boost: 4 },
      { key: 'catfish', label: 'Catfish', temp_center_f: 72, temp_half_span_f: 13, structure_bias: 0.2, current_bias: 0.02, bait_bias: 0.08, hint_boost: 4 },
      { key: 'panfish', label: 'Panfish', temp_center_f: 66, temp_half_span_f: 12, structure_bias: 0.14, current_bias: 0.03, bait_bias: 0.1, hint_boost: 2 },
    ];
  }
  if (markerClass === 'offshore') {
    return [
      { key: 'tuna', label: 'Tuna', temp_center_f: 68, temp_half_span_f: 9, structure_bias: 0.08, current_bias: 0.2, bait_bias: 0.32, hint_boost: 8 },
      { key: 'yellowtail', label: 'Yellowtail', temp_center_f: 65, temp_half_span_f: 10, structure_bias: 0.14, current_bias: 0.16, bait_bias: 0.26, hint_boost: 6 },
      { key: 'dorado', label: 'Dorado', temp_center_f: 72, temp_half_span_f: 9, structure_bias: 0.06, current_bias: 0.14, bait_bias: 0.22, hint_boost: 4 },
      { key: 'wahoo', label: 'Wahoo', temp_center_f: 73, temp_half_span_f: 8, structure_bias: 0.05, current_bias: 0.18, bait_bias: 0.2, hint_boost: 3 },
    ];
  }
  if (markerClass === 'estuary') {
    return [
      { key: 'halibut', label: 'Halibut', temp_center_f: 62, temp_half_span_f: 10, structure_bias: 0.24, current_bias: 0.08, bait_bias: 0.2, hint_boost: 5 },
      { key: 'striped_bass', label: 'Striped Bass', temp_center_f: 64, temp_half_span_f: 11, structure_bias: 0.2, current_bias: 0.1, bait_bias: 0.18, hint_boost: 5 },
      { key: 'corbina', label: 'Corbina', temp_center_f: 67, temp_half_span_f: 11, structure_bias: 0.17, current_bias: 0.05, bait_bias: 0.16, hint_boost: 3 },
      { key: 'calico_bass', label: 'Calico Bass', temp_center_f: 64, temp_half_span_f: 10, structure_bias: 0.18, current_bias: 0.08, bait_bias: 0.16, hint_boost: 3 },
    ];
  }
  return [
    { key: 'mackerel', label: 'Mackerel', temp_center_f: 63, temp_half_span_f: 12, structure_bias: 0.1, current_bias: 0.12, bait_bias: 0.24, hint_boost: 2 },
    { key: 'bass', label: 'Bass', temp_center_f: 62, temp_half_span_f: 10, structure_bias: 0.24, current_bias: 0.08, bait_bias: 0.18, hint_boost: 2 },
    { key: 'halibut', label: 'Halibut', temp_center_f: 62, temp_half_span_f: 9, structure_bias: 0.26, current_bias: 0.06, bait_bias: 0.2, hint_boost: 2 },
    { key: 'shark', label: 'Shark', temp_center_f: 64, temp_half_span_f: 14, structure_bias: 0.1, current_bias: 0.1, bait_bias: 0.18, hint_boost: 0 },
  ];
}

function moonBiasText() {
  const day = Math.floor(Date.now() / 86400000) % 29;
  if (day < 7) return 'New-to-first-quarter push';
  if (day < 15) return 'Waxing moon energy';
  if (day < 22) return 'Full-moon recovery window';
  return 'Waning moon reset';
}

function updateMeter(node, value) {
  if (!node) return;
  node.style.width = `${clamp(value)}%`;
}

function listToHtml(items) {
  if (!Array.isArray(items) || !items.length) return '<li>Signal build pending</li>';
  return items.map((item) => `<li>${item}</li>`).join('');
}

function deriveIntel({ loc, wx, bait, clouds, boats, ocean, localOverlay, reports, videos, profile }) {
  const lat = Number(loc?.lat);
  const lon = Number(loc?.lon);
  const markerClass = String(loc?.marker_class || profile?.waterbody_class || 'coastal');
  const baitApplicable = Boolean(loc?.bait_applicable ?? !['inland'].includes(markerClass));
  const nearestBait = nearestPoint(bait?.bait_score, lat, lon, 8);
  const baitProbRaw = (Number(nearestBait?.probability ?? bait?.confidence?.overall ?? NaN));
  const baitProb = baitApplicable && Number.isFinite(baitProbRaw) ? clamp(baitProbRaw * 100) : NaN;
  const frontCount = Array.isArray(bait?.front_lines) ? bait.front_lines.length : 0;
  const boilCount = Array.isArray(bait?.boil_probability_polygons) ? bait.boil_probability_polygons.length : 0;
  const convCount = Array.isArray(bait?.convergence_polygons) ? bait.convergence_polygons.length : 0;
  const baitState = classifyBaitState(baitProb, frontCount, boilCount);

  const boat = nearestPoint(boats?.boats, lat, lon, 8);
  const sampledCloudPct = fieldSample(wx, 'cloud_total', lat, lon);
  const sampledRainRate = fieldSample(wx, 'precip_rate', lat, lon);
  const sampledWindU = fieldSample(wx, 'wind_u', lat, lon);
  const sampledWindV = fieldSample(wx, 'wind_v', lat, lon);
  const sampledTempK = fieldSample(wx, 'air_temp', lat, lon);
  const cloudPct = Number.isFinite(Number(localOverlay?.cloudCover)) ? Number(localOverlay.cloudCover) : (Number.isFinite(sampledCloudPct) ? sampledCloudPct : averageGrid(wx?.fields?.cloud_total, averageGrid(clouds?.cloud_layers?.find((l) => l?.name === 'low')?.density, NaN)));
  const rainRate = Number.isFinite(Number(localOverlay?.rainRate)) ? Number(localOverlay.rainRate) : (Number.isFinite(sampledRainRate) ? sampledRainRate : averageGrid(wx?.fields?.precip_rate, NaN));
  const sampledAirTempF = Number.isFinite(sampledTempK) ? (((sampledTempK - 273.15) * 9) / 5) + 32 : NaN;
  const sampledWindKt = Number.isFinite(sampledWindU) && Number.isFinite(sampledWindV) ? Math.hypot(sampledWindU, sampledWindV) * 1.94384 : NaN;
  const sampledWindDir = Number.isFinite(sampledWindU) && Number.isFinite(sampledWindV) ? ((Math.atan2(sampledWindU, sampledWindV) * 180 / Math.PI) + 360) % 360 : NaN;
  const sampledWaterTempF = interpolateBoatScalar(boats?.boats, lat, lon, (entry) => entry?.water?.tempF, 90, 4);
  const sampledBoatAirTempRaw = interpolateBoatScalar(boats?.boats, lat, lon, (entry) => entry?.water?.airTempF, 90, 4);
  const sampledBoatAirTempF = normalizeMaybeFahrenheit(sampledBoatAirTempRaw, sampledAirTempF);
  const boatAirTempRaw = Number(boat?.water?.airTempF);
  const boatAirTempF = normalizeMaybeFahrenheit(boatAirTempRaw, sampledAirTempF);
  const waterTempF = Number.isFinite(sampledWaterTempF) ? sampledWaterTempF : Number(boat?.water?.tempF);
  const airTempF = Number.isFinite(sampledBoatAirTempF) ? sampledBoatAirTempF : (Number.isFinite(boatAirTempF) ? boatAirTempF : sampledAirTempF);
  const currentKt = Number(boat?.current?.speedKt);
  const currentDir = Number(boat?.current?.dirDeg);
  const windKt = Number.isFinite(Number(boat?.wind?.speedKt)) ? Number(boat?.wind?.speedKt) : sampledWindKt;
  const windDir = Number.isFinite(Number(boat?.wind?.dirDeg)) ? Number(boat?.wind?.dirDeg) : sampledWindDir;
  const swellFt = Number(boat?.waves?.sigHeightFt);
  const swell1 = boat?.waves?.primary || null;
  const swell2 = boat?.waves?.secondary || null;
  const swell3 = boat?.waves?.tertiary || null;
  const reportHints = summarizeReports(reports);
  const environment = normalizeEnvironment({
    wx, ocean, boats, lat, lon, cloudPct, rainRate, windKt, windDir, currentKt, currentDir, swellFt,
  });

  const structureEdge = clamp(38 + (frontCount * 11) + (convCount * 6));
  const weatherPenalty = clamp((Number.isFinite(windKt) ? windKt * 1.7 : 16) + (Number.isFinite(swellFt) ? swellFt * 8.5 : 18) + (Number.isFinite(rainRate) ? rainRate * 180 : 0), 0, 100);
  const safetyScore = clamp(100 - weatherPenalty + (Number.isFinite(cloudPct) && cloudPct < 80 ? 4 : 0));
  const confidenceScore = clamp(
    34
      + (Number.isFinite(baitProb) ? 28 : 0)
      + (boat ? 18 : 0)
      + (frontCount > 0 ? 8 : 0)
      + (videos?.length ? 6 : 0)
      + (reports?.length ? 6 : 0)
      + (profile?.species?.length ? 4 : 0)
  );

  const activeSpecies = Array.isArray(profile?.species) && profile.species.length
    ? profile.species.slice(0, 4)
    : speciesPoolForClass(markerClass);

  const speciesRows = activeSpecies.map((spec) => {
    const tempWindow = speciesTempWindow(waterTempF, spec.temp_center_f || 64, spec.temp_half_span_f || 12) * 28;
    const currentSupport = Math.min(Number.isFinite(currentKt) ? currentKt : 0, 3) * (spec.current_bias || 0.1) * 18;
    const structureSupport = structureEdge * (spec.structure_bias || 0.15);
    const baitSupport = (Number.isFinite(baitProb) ? baitProb : 0) * (spec.bait_bias || 0.22);
    const score = clamp(tempWindow + currentSupport + structureSupport + baitSupport + Number(spec.hint_boost || 0));
    return { key: spec.key, label: spec.label, score };
  });

  const predatorScore = clamp((Math.max(...speciesRows.map((row) => row.score), 0) * 0.62) + ((Number.isFinite(baitProb) ? baitProb : 0) * 0.24) + (structureEdge * 0.14));
  const opportunityScore = clamp((baitProb * 0.33) + (predatorScore * 0.34) + (safetyScore * 0.18) + (confidenceScore * 0.15));
  const trend = trendText(opportunityScore, baitState, frontCount, boilCount);

  const reasons = [];
  if (profile?.waterbody) reasons.push(`${profile.waterbody} rules are active for this marker instead of a one-size-fits-all ocean list`);
  if (baitProb >= 68) reasons.push('Bait probability is elevated around this orb');
  if (frontCount > 0) reasons.push(`Thermal edge activity showing ${frontCount} front line${frontCount === 1 ? '' : 's'} in the local window`);
  if (convCount > 0) reasons.push(`Current convergence pockets detected (${convCount})`);
  if (Number.isFinite(currentKt) && currentKt >= 1.0) reasons.push(`Current is moving with intent at ${currentKt.toFixed(1)} kt`);
  if (Number.isFinite(swellFt) && swellFt <= 3.0) reasons.push('Sea state is still fishable for a small-to-mid boat');
  if (reports?.length) reasons.push('Historic location reports reinforce this node');
  if (Number.isFinite(boat?._distance_nm)) reasons.push(`Boat / sea-state solve is wired ${boat._distance_nm.toFixed(1)} nm from the orb anchor`);
  if (Number.isFinite(nearestBait?._distance_nm)) reasons.push(`Bait solve is wired ${nearestBait._distance_nm.toFixed(1)} nm from the orb anchor`);
  if (!reasons.length) reasons.push('Data induction is online but this node is still waiting on a stronger stack');

  const risks = [];
  if (Number.isFinite(windKt) && windKt >= 18) risks.push('Wind is starting to tax clean presentations');
  if (Number.isFinite(swellFt) && swellFt >= 4) risks.push('Wave energy is pushing boating conditions into caution');
  if (Number.isFinite(rainRate) && rainRate > 0.04) risks.push('Active precip may muddy the read');
  if (cloudPct >= 85) risks.push('Heavy cloud deck may flatten the visual read on the water');
  if (!risks.length) risks.push('No major short-fuse risk flag from the local stack');

  return {
    opportunityScore,
    baitScore: baitProb,
    predatorScore,
    safetyScore,
    confidenceScore,
    trend,
    cloudPct,
    rainRate,
    frontCount,
    convCount,
    boilCount,
    baitState,
    baitApplicable,
    markerClass,
    currentKt,
    currentDir,
    windKt,
    windDir,
    swellFt,
    swell1,
    swell2,
    swell3,
    waterTempF,
    airTempF,
    speciesRows,
    reasons,
    risks,
    tackle: recommendTackle(speciesRows, reportHints, baitState, profile),
    moonBias: moonBiasText(),
    boat,
    positioning: {
      markerLat: lat,
      markerLon: lon,
      boatLat: Number(boat?.lat),
      boatLon: Number(boat?.lon),
      boatDistanceNm: Number(boat?._distance_nm),
      baitLat: Number(nearestBait?.lat),
      baitLon: Number(nearestBait?.lon),
      baitDistanceNm: Number(nearestBait?._distance_nm),
      matchedZone: profile?.matched_zone || null,
      classificationMethod: profile?.classification_method || null,
      coastDistanceNm: Number(profile?.coast_distance_deg) * 60,
    },
    environment,
  };
}

export function createHud({ root, onStartLive, onStopLive, onSelectLocation, getOverlaySummary }) {
  const el = {
    panel: root,
    close: document.getElementById('hudClose'),
    title: document.getElementById('hudLocation'),
    coords: document.getElementById('hudCoords'),
    waterbody: document.getElementById('hudWaterbody'),
    positioning: document.getElementById('hudPositioning'),
    statusLine: document.getElementById('hudStatusLine'),
    opportunityScore: document.getElementById('hudOpportunityScore'),
    opportunityFill: document.getElementById('hudOpportunityFill'),
    confidence: document.getElementById('hudConfidence'),
    trend: document.getElementById('hudTrend'),
    safetyLine: document.getElementById('hudSafetyLine'),
    baitSummary: document.getElementById('hudBaitSummary'),
    baitFill: document.getElementById('hudBaitFill'),
    baitDrivers: document.getElementById('hudBaitDrivers'),
    baitMovement: document.getElementById('hudBaitMovement'),
    predatorLabel1: document.getElementById('hudPredatorLabel1'),
    predatorLabel2: document.getElementById('hudPredatorLabel2'),
    predatorLabel3: document.getElementById('hudPredatorLabel3'),
    predatorLabel4: document.getElementById('hudPredatorLabel4'),
    predatorScore1: document.getElementById('hudPredatorScore1'),
    predatorScore2: document.getElementById('hudPredatorScore2'),
    predatorScore3: document.getElementById('hudPredatorScore3'),
    predatorScore4: document.getElementById('hudPredatorScore4'),
    predatorFill1: document.getElementById('hudPredatorFill1'),
    predatorFill2: document.getElementById('hudPredatorFill2'),
    predatorFill3: document.getElementById('hudPredatorFill3'),
    predatorFill4: document.getElementById('hudPredatorFill4'),
    envNow: document.getElementById('hudEnvNow'),
    envMore: document.getElementById('hudEnvMore'),
    envPosition: document.getElementById('hudEnvPosition'),
    windowText: document.getElementById('hudWindowText'),
    moonBias: document.getElementById('hudMoonBias'),
    reasons: document.getElementById('hudReasons'),
    risks: document.getElementById('hudRisks'),
    videoFrame: document.getElementById('hudVideoFrame'),
    lastReport: document.getElementById('hudLastReport'),
    reports: document.getElementById('hudReports'),
    reportInput: document.getElementById('hudReportInput'),
    saveReport: document.getElementById('hudSaveReport'),
    uploadFile: document.getElementById('hudUploadFile'),
    uploadVideo: document.getElementById('hudUploadVideo'),
    goLive: document.getElementById('hudGoLive'),
    stopLive: document.getElementById('hudStopLive'),
    tackle: document.getElementById('hudTackle'),
    hoverWeather: document.getElementById('hudHoverWeather'),
  };

  let selected = null;

  el.close.onclick = () => {
    el.panel.classList.add('closed');
    el.panel.setAttribute('aria-hidden', 'true');
  };

  function renderImmediateFromMarker(marker) {
    el.title.textContent = marker?.name || 'Fishing location';
    const lat = Number(marker?.lat);
    const lon = Number(marker?.lon);
    el.coords.textContent = Number.isFinite(lat) && Number.isFinite(lon)
      ? `${lat.toFixed(4)}, ${lon.toFixed(4)} • orb anchor`
      : 'Coordinates unavailable';
    const quick = marker?.quick_snapshot || {};
    const qWeather = marker?.quick_weather || quick?.weather || {};
    const qOcean = marker?.quick_ocean || quick?.ocean || {};
    const markerClass = marker?.marker_class || quick?.marker_class || 'coastal';
    const baitApplicable = Boolean(marker?.bait_applicable ?? quick?.bait_applicable ?? markerClass !== 'inland');
    el.waterbody.textContent = `Curated CSV location marker • ${markerClass}`;
    el.statusLine.textContent = 'Loading detailed intelligence…';
    el.baitSummary.textContent = baitApplicable
      ? `${safeFixed(quick?.bait_score, 0, '%')} • ${quick?.bait_intensity || 'warming'}`
      : 'Not applicable (inland/weather-primary)';
    el.envNow.textContent = markerClass === 'inland'
      ? `Air ${formatUnavailable(qWeather?.air_temp_c, (v) => `${(((v * 9) / 5) + 32).toFixed(1)}°F`)} • Wind ${formatUnavailable(qWeather?.wind_speed_kt, (v) => `${v.toFixed(1)} kt`)} • Cloud ${formatUnavailable(qWeather?.cloud_cover_pct, (v) => `${v.toFixed(0)}%`)}`
      : `SST ${formatUnavailable(qOcean?.sst_c, (v) => `${(((v * 9) / 5) + 32).toFixed(1)}°F`)} • Current ${formatUnavailable(qOcean?.current_speed_kt, (v) => `${v.toFixed(2)} kt`)} • Wave ${formatUnavailable(qOcean?.wave_height_ft, (v) => `${v.toFixed(1)} ft`)}`;
    el.envMore.textContent = `Pressure ${formatUnavailable(qWeather?.pressure_mb, (v) => `${v.toFixed(1)} mb`)} • Wind dir ${formatUnavailable(qWeather?.wind_direction_deg, (v) => `${v.toFixed(0)}°`)} • Source ${qWeather?.source_tier || qOcean?.source_tier || 'Unavailable'}`;
    el.envPosition.textContent = 'Detailed environment loading…';
  }

  async function refresh() {
    if (!selected) return;
    const loc = await getJsonSafe(`/gfs/api/location/${encodeURIComponent(selected.id)}`, null);
    if (!loc) {
      el.statusLine.textContent = 'Location intelligence unavailable';
      return;
    }

    el.title.textContent = loc.name || selected.name;
    el.coords.textContent = `${Number(loc.lat || selected.lat).toFixed(4)}, ${Number(loc.lon || selected.lon).toFixed(4)} • orb anchor`;

    const frameBox = `${(Number(loc.lon) - 1.8).toFixed(4)},${(Number(loc.lat) - 1.8).toFixed(4)},${(Number(loc.lon) + 1.8).toFixed(4)},${(Number(loc.lat) + 1.8).toFixed(4)}`;

    let [frame, vids, node] = await Promise.all([
      getJsonSafe(`/gfs/api/frame?bbox=${frameBox}&quality=full`, null),
      loadLocationVideos(selected.id),
      getJsonSafe(`/gfs/api/intelligence/node/${encodeURIComponent(selected.id)}`, null),
    ]);

    let wx = frame?.weather || null;
    let bait = frame?.baitAdvanced || null;
    let clouds = frame?.clouds || null;
    let boats = frame?.boats || null;
    let ocean = frame?.ocean || null;

    const reports = [...(loc.reports || [])];
    const localOverlay = typeof getOverlaySummary === 'function' ? getOverlaySummary(loc) : null;
    const profile = node?.profile || null;
    const intel = deriveIntel({ loc, wx, bait, clouds, boats, ocean, localOverlay, reports, videos: vids, profile });

    el.waterbody.textContent = profile?.waterbody
      ? `${profile.waterbody} • ${profile.headline_species}`
      : 'Curated CSV location marker • fishloclist.csv';
    el.positioning.textContent = [
      profile?.matched_zone ? `Zone ${profile.matched_zone}` : null,
      profile?.classification_method ? `Classifier ${profile.classification_method}` : null,
      Number.isFinite(Number(profile?.coast_distance_deg)) ? `Coast ${ (Number(profile.coast_distance_deg) * 60).toFixed(1) } nm` : null,
    ].filter(Boolean).join(' • ') || 'Marker wiring pending';
    el.statusLine.textContent = `CSV truth marker • ${scoreText(intel.opportunityScore)} setup • ${trendText(intel.opportunityScore, intel.baitState, intel.frontCount, intel.boilCount)} trend • ${safetyLabel(intel.safetyScore)} boating`;
    el.opportunityScore.textContent = `${Math.round(intel.opportunityScore)}%`;
    updateMeter(el.opportunityFill, intel.opportunityScore);
    el.confidence.textContent = `${confidenceLabel(intel.confidenceScore)} confidence • ${Math.round(intel.confidenceScore)}%`;
    el.trend.textContent = `${intel.trend} window`;
    el.safetyLine.textContent = `Safety ${Math.round(intel.safetyScore)}% • ${safetyLabel(intel.safetyScore)} • valid ${localOverlay?.validTime || wx?.valid_time || clouds?.valid_time || bait?.valid_time || 'n/a'}`;

    el.baitSummary.textContent = intel.baitApplicable
      ? `${Math.round(Number(intel.baitScore) || 0)}% • ${intel.baitState}`
      : 'Not applicable (inland/weather-primary)';
    updateMeter(el.baitFill, intel.baitApplicable ? (Number(intel.baitScore) || 0) : 0);
    el.baitDrivers.innerHTML = listToHtml([
      profile?.summary || null,
      profile?.classification_reason || null,
      intel.markerClass ? `Marker class ${intel.markerClass}` : null,
      intel.frontCount > 0 ? `Temp breaks live in the box (${intel.frontCount})` : null,
      intel.convCount > 0 ? `Convergence support pockets (${intel.convCount})` : null,
      Number.isFinite(intel.currentKt) ? `Current pulse ${intel.currentKt.toFixed(1)} kt` : null,
      Number.isFinite(intel.cloudPct) ? `Cloud cover ${intel.cloudPct.toFixed(0)}% at orb` : null,
      Number.isFinite(intel.positioning?.baitDistanceNm) ? `Nearest bait solve is ${intel.positioning.baitDistanceNm.toFixed(1)} nm off the orb` : null,
      (intel.baitApplicable && bait?.bait?.meta?.valid_cells) ? `${bait.bait.meta.valid_cells} active ocean cells in solve` : null,
      !intel.baitApplicable ? 'Bait model intentionally omitted for inland/non-SST location' : null,
    ].filter(Boolean));
    el.baitMovement.textContent = Number.isFinite(intel.currentKt)
      ? `Drifting ${safeFixed(intel.currentDir, 0, '°')} at ${safeFixed(intel.currentKt, 1, ' kt')} • bait state ${intel.baitState}`
      : `Movement read pending • bait state ${intel.baitState}`;

    const speciesSlots = [intel.speciesRows?.[0], intel.speciesRows?.[1], intel.speciesRows?.[2], intel.speciesRows?.[3]];
    [
      [el.predatorLabel1, el.predatorScore1, el.predatorFill1, speciesSlots[0]],
      [el.predatorLabel2, el.predatorScore2, el.predatorFill2, speciesSlots[1]],
      [el.predatorLabel3, el.predatorScore3, el.predatorFill3, speciesSlots[2]],
      [el.predatorLabel4, el.predatorScore4, el.predatorFill4, speciesSlots[3]],
    ].forEach(([labelEl, scoreEl, fillEl, row], idx) => {
      labelEl.textContent = row?.label || `Species ${idx + 1}`;
      scoreEl.textContent = row ? `${Math.round(row.score)}%` : '—';
      updateMeter(fillEl, row?.score || 0);
    });

    const env = intel.environment || {};
    const isInland = intel.markerClass === 'inland';
    if (isInland) {
      el.envNow.textContent = `Air ${formatUnavailable(intel.airTempF, (v) => `${v.toFixed(1)}°F`)} • Wind ${formatUnavailable(env.wind_speed, (v) => `${v.toFixed(1)} kt`)} @ ${formatUnavailable(env.wind_direction, (v) => `${v.toFixed(0)}°`)} • Cloud ${formatUnavailable(env.cloud_cover, (v) => `${v.toFixed(0)}%`)}`;
      el.envMore.textContent = `Pressure ${formatUnavailable(env.pressure_mb, (v) => `${v.toFixed(1)} mb`)} • Gust ${formatUnavailable(env.wind_gust_kt, (v) => `${v.toFixed(1)} kt`)} • Rain ${formatUnavailable(env.rain_rate, (v) => `${v.toFixed(3)}`)} • Ocean fields omitted for inland marker`;
    } else {
      el.envNow.textContent = `SST ${formatUnavailable(env.sea_surface_temp, (v) => `${v.toFixed(1)}°F`)} • Chl ${formatUnavailable(env.chlorophyll, (v) => `${v.toFixed(2)} mg/m³`)} • Current ${formatUnavailable(env.current_speed, (v) => `${v.toFixed(2)} kt`)} @ ${formatUnavailable(env.current_direction, (v) => `${v.toFixed(0)}°`)}`;
      el.envMore.textContent = `Wave ${formatUnavailable(env.wave_height, (v) => `${v.toFixed(1)} ft`)} • Period ${formatUnavailable(env.wave_period, (v) => `${v.toFixed(0)} s`)} • Depth ${formatUnavailable(env.depth, (v) => `${v.toFixed(0)} m`)} • Wind ${formatUnavailable(env.wind_speed, (v) => `${v.toFixed(1)} kt`)} @ ${formatUnavailable(env.wind_direction, (v) => `${v.toFixed(0)}°`)}`;
    }
    const boatSolveText = Number.isFinite(intel.positioning?.boatDistanceNm)
      ? `Boat solve ${intel.positioning.boatDistanceNm.toFixed(1)} nm from orb`
      : 'Boat solve sparse — using regional ocean conditions';
    const baitSolveText = Number.isFinite(intel.positioning?.baitDistanceNm)
      ? `Bait solve ${intel.positioning.baitDistanceNm.toFixed(1)} nm from orb`
      : 'Bait solve sparse — expanding regional bait model';
    el.envPosition.textContent = [
      boatSolveText,
      baitSolveText,
      `Cloud ${formatUnavailable(env.cloud_cover, (v) => `${v.toFixed(0)}%`)}`,
      `Rain ${formatUnavailable(env.rain_rate, (v) => `${v.toFixed(3)}`)}`,
      `Sources wx:${env.source_flags?.weather || 'unknown'} ocean:${env.source_flags?.ocean || 'unknown'}${env.source_flags?.degraded ? ' (degraded)' : ''}`,
      Number.isFinite(intel.positioning?.boatLat) && Number.isFinite(intel.positioning?.boatLon) ? `Boat cell ${intel.positioning.boatLat.toFixed(3)}, ${intel.positioning.boatLon.toFixed(3)}` : null,
      Number.isFinite(intel.positioning?.baitLat) && Number.isFinite(intel.positioning?.baitLon) ? `Bait cell ${intel.positioning.baitLat.toFixed(3)}, ${intel.positioning.baitLon.toFixed(3)}` : null,
    ].filter(Boolean).join(' • ');

    const primary = intel.swell1 ? `${safeFixed(intel.swell1.heightFt, 1, ' ft')} @ ${safeFixed(intel.swell1.periodS, 0, 's')}` : 'n/a';
    const secondary = intel.swell2 ? `${safeFixed(intel.swell2.heightFt, 1, ' ft')} @ ${safeFixed(intel.swell2.periodS, 0, 's')}` : 'n/a';
    const tertiary = intel.swell3 ? `${safeFixed(intel.swell3.heightFt, 1, ' ft')} @ ${safeFixed(intel.swell3.periodS, 0, 's')}` : 'n/a';
    el.windowText.textContent = `Bias: dawn push → midday check → sunset recycle • Primary swell ${primary} • Secondary ${secondary} • Third ${tertiary}`;
    el.moonBias.textContent = intel.moonBias;

    el.reasons.innerHTML = listToHtml(intel.reasons);
    el.risks.innerHTML = listToHtml(intel.risks);

    el.lastReport.textContent = reports.slice(-1)[0] || 'No reports yet';
    el.reports.innerHTML = '';
    reports.slice().reverse().forEach((r) => {
      const li = document.createElement('li');
      li.textContent = r;
      el.reports.appendChild(li);
    });

    el.tackle.textContent = intel.tackle;
    renderVideoFrame(el.videoFrame, vids);
  }

  el.saveReport.onclick = async () => {
    if (!selected) return;
    const text = el.reportInput.value.trim();
    if (!text) return;
    await postJsonSafe(`/gfs/api/location/${encodeURIComponent(selected.id)}/reports`, { report: text }, null);
    el.reportInput.value = '';
    await refresh();
  };

  el.uploadVideo.onclick = async () => {
    if (!selected || !el.uploadFile.files?.[0]) return;
    await uploadSafe(`/gfs/api/location/${encodeURIComponent(selected.id)}/upload`, el.uploadFile.files[0], {}, null);
    await refresh();
  };

  el.goLive.onclick = () => selected && onStartLive(selected);
  el.stopLive.onclick = () => selected && onStopLive(selected);

  return {
    async open(location) {
      selected = location;
      if (onSelectLocation) onSelectLocation(location);
      el.panel.classList.remove('closed');
      el.panel.setAttribute('aria-hidden', 'false');
      renderImmediateFromMarker(location || {});
      refresh().catch((err) => {
        console.warn('[gfs hud] async enrichment failed', err?.message || err);
      });
    },
    selected: () => selected,
    updateHover(point, sample, baitInfo) {
      if (!el.hoverWeather) return;
      const lat = Number(point?.lat);
      const lon = Number(point?.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        el.hoverWeather.textContent = 'Move cursor over globe';
        return;
      }
      const tempF = Number.isFinite(Number(sample?.temperature_f))
        ? Number(sample.temperature_f)
        : cToF(sample?.temperature_c);
      const pressure = Number(sample?.pressure_hpa);
      const wind = Number(sample?.wind_speed_mps);
      const baitDepth = Number(baitInfo?.preferred_depth_m);
      const baitProb = Number(baitInfo?.probability);
      const baitBandMin = Number(baitInfo?.depth_min_m);
      const baitBandMax = Number(baitInfo?.depth_max_m);
      const baitDriver = typeof baitInfo?.driver === 'string' ? baitInfo.driver.replace(/_/g, ' ') : '';
      const baitText = Number.isFinite(baitDepth)
        ? ` • Bait ${Number.isFinite(baitProb) ? Math.round(baitProb * 100) : 'n/a'}% @ ${baitDepth.toFixed(0)} m${Number.isFinite(baitBandMin) && Number.isFinite(baitBandMax) ? ` (${baitBandMin.toFixed(0)}–${baitBandMax.toFixed(0)} m)` : ''}${baitDriver ? ` • ${baitDriver}` : ''}`
        : '';
      el.hoverWeather.textContent = `@ ${lat.toFixed(3)}, ${lon.toFixed(3)} • Temp ${Number.isFinite(tempF) ? tempF.toFixed(1) : 'n/a'}°F • Pressure ${Number.isFinite(pressure) ? pressure.toFixed(1) : 'n/a'} hPa • Wind ${Number.isFinite(wind) ? wind.toFixed(1) : 'n/a'} m/s${baitText}`;
    },
  };
}
