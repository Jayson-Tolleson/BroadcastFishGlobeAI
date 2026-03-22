(function () {
  const NS = (window.LFTRWeather = window.LFTRWeather || {});

  let cloudRenderTask = null;

  function hashUnit(key) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < key.length; i += 1) {
      h ^= key.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0) / 4294967295;
  }

  const CLOUD_PRESSURE_BANDS = {
    low: { baseHpa: 940, topHpa: 760, threshold: 20, color: '#dcefff' },
    mid: { baseHpa: 760, topHpa: 520, threshold: 18, color: '#eef6ff' },
    high: { baseHpa: 520, topHpa: 220, threshold: 14, color: '#ffffff' },
    total: { baseHpa: 880, topHpa: 520, threshold: 35, color: '#e9f4ff' },
  };

  // Legacy profile, will be phased out by new morphology system.
  function regimeProfile(regime) {
    if (regime === 'deep_convection') return { threshold: 0.34, layers: 7, lobes: 12, spread: 1.12, anvil: 1.45 };
    if (regime === 'marine_stratocumulus' || regime === 'frontal_shield') return { threshold: 0.28, layers: 4, lobes: 8, spread: 1.32, anvil: 1.0 };
    if (regime === 'cirrus_sheet') return { threshold: 0.24, layers: 5, lobes: 7, spread: 1.52, anvil: 1.08 };
    return { threshold: 0.31, layers: 5, lobes: 9, spread: 1.18, anvil: 1.12 };
  }

  // --- New Meteorological & Shape Functions (ported from cloud-zones.js) ---

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function hashJitter(lat, lon, salt = 0) {
    const v = Math.sin((lat * 12.9898) + (lon * 78.233) + (salt * 19.19)) * 43758.5453;
    return v - Math.floor(v);
  }

  function pressureToHeightMeters(hpa) {
    const pressure = clamp(Number(hpa) || 1013.25, 80, 1050);
    return 44330 * (1 - (pressure / 1013.25) ** 0.1903);
  }

  function windHeadingDeg(u, v) {
    if (!Number.isFinite(u) || !Number.isFinite(v)) return 90;
    return ((Math.atan2(u, v) * 180) / Math.PI + 360) % 360;
  }

  function roundedCloudPath({ lat, lon, latRadiusDeg, lonRadiusDeg, wobble = 0.18, points = 14, elongation = 1, headingDeg = 90 }) {
    const path = [];
    const basePhase = hashJitter(lat, lon) * Math.PI * 2;
    const heading = (headingDeg * Math.PI) / 180;
    const cosH = Math.cos(heading);
    const sinH = Math.sin(heading);
    for (let i = 0; i < points; i += 1) {
      const t = (i / points) * Math.PI * 2;
      const harmonic = Math.sin((t * 2) + basePhase) * wobble;
      const secondary = Math.cos((t * 3) - basePhase) * (wobble * 0.55);
      const scale = 1 + harmonic + secondary;
      const localLat = Math.sin(t) * latRadiusDeg * scale;
      const localLon = Math.cos(t) * lonRadiusDeg * scale * elongation;
      const rotLat = (localLat * cosH) - (localLon * sinH);
      const rotLon = (localLat * sinH) + (localLon * cosH);
      path.push({ lat: lat + rotLat, lng: lon + rotLon });
    }
    return path;
  }

  function classifyCloudMorphology(feature) {
    const toNumber = (v, fallback = 0) => (Number.isFinite(Number(v)) ? Number(v) : fallback);
    const low = toNumber(feature?.cloud_low, 0);
    const mid = toNumber(feature?.cloud_mid, 0);
    const high = toNumber(feature?.cloud_high, 0);
    const total = toNumber(feature?.cloud_total, Math.max(low, mid, high));
    const precip = toNumber(feature?.precip_rate, 0);
    const dominant = high >= Math.max(low, mid) ? 'high' : (mid >= low ? 'mid' : 'low');

    if (precip >= 0.85 && total >= 72) return { family: 'vertical', subtype: 'cumulonimbus' };
    if (precip >= 0.35 && mid >= 45 && total >= 68) return { family: 'stratiform', subtype: 'nimbostratus' };
    if (high >= 58 && low < 35 && mid < 45) return { family: 'cirriform', subtype: high >= 78 ? 'cirrostratus' : 'cirrus' };
    if (low >= 58 && total < 75) return { family: 'cumuliform', subtype: low >= 78 ? 'towering-cumulus' : 'cumulus' };
    if (dominant === 'mid' && total >= 62) return { family: 'stratiform', subtype: 'altostratus' };
    return { family: 'stratiform', subtype: total >= 60 ? 'stratus' : 'stratocumulus' };
  }

  function shellBlueprints(morphology) {
    switch (morphology.family) {
      case 'cirriform':
        return [{ shell: 'veil', latScale: 0.82, lonScale: 1.8, opacityBase: 0.07, opacitySpan: 0.08, wobble: 0.12, points: 16, elongation: 1.6 }];
      case 'vertical':
        return [
          { shell: 'core', latScale: 0.72, lonScale: 0.76, opacityBase: 0.16, opacitySpan: 0.18, wobble: 0.2, points: 14, elongation: 1.0 },
          { shell: 'tower', latScale: 0.5, lonScale: 0.54, opacityBase: 0.14, opacitySpan: 0.14, wobble: 0.24, points: 12, elongation: 0.92, baseLift: 0.22, heightBoost: 0.42 },
          { shell: 'anvil', latScale: 0.96, lonScale: 1.42, opacityBase: 0.08, opacitySpan: 0.1, wobble: 0.16, points: 16, elongation: 1.25, baseLift: 0.78, heightBoost: 0.18 },
        ];
      case 'cumuliform':
        return [
          { shell: 'body', latScale: 0.7, lonScale: 0.84, opacityBase: 0.12, opacitySpan: 0.2, wobble: 0.24, points: 14, elongation: 1.0 },
          { shell: 'tuft', latScale: 0.46, lonScale: 0.5, opacityBase: 0.08, opacitySpan: 0.14, wobble: 0.3, points: 11, elongation: 0.94, baseLift: 0.38, heightBoost: 0.26 },
        ];
      default: // stratiform
        return [{ shell: 'deck', latScale: 0.96, lonScale: 1.3, opacityBase: 0.11, opacitySpan: 0.16, wobble: 0.14, points: 16, elongation: 1.18 }];
    }
  }

  function buildCloudPressureBand(type, density, totalBoost, family = 'stratiform') {
    const band = CLOUD_PRESSURE_BANDS[type] || CLOUD_PRESSURE_BANDS.total;
    const weight = clamp(density / 100, 0, 1);
    const deepening = clamp((totalBoost - 0.82) / 0.45, 0, 1);
    const familyStretch = family === 'vertical' ? 1.3 : (family === 'cumuliform' ? 1.14 : (family === 'cirriform' ? 0.78 : 0.96));
    const baseHpa = band.baseHpa - ((band.baseHpa - band.topHpa) * weight * 0.16);
    const topHpa = band.topHpa - ((band.topHpa * 0.07) * deepening * weight * familyStretch);
    const baseAltitude = pressureToHeightMeters(baseHpa);
    const topAltitude = pressureToHeightMeters(topHpa);
    return {
      baseAltitude: Math.round(baseAltitude),
      height: Math.max(600, Math.round((topAltitude - baseAltitude) * familyStretch)),
      color: band.color,
      weight,
    };
  }

  function buildCloudBodies(feature, footprintScale) {
    const toNumber = (v, fallback = 0) => (Number.isFinite(Number(v)) ? Number(v) : fallback);
    const low = toNumber(feature?.cloud_low, 0);
    const mid = toNumber(feature?.cloud_mid, 0);
    const high = toNumber(feature?.cloud_high, 0);
    const total = toNumber(feature?.cloud_total, Math.max(low, mid, high));
    const totalBoost = clamp(total / 100, 0.82, 1.25);
    const morphology = classifyCloudMorphology(feature);
    const blueprints = shellBlueprints(morphology);
    const bodies = [];

    const appendBody = (type, density) => {
      const band = buildCloudPressureBand(type, density, totalBoost, morphology.family);
      if (band.weight <= 0) return;
      for (const bp of blueprints) {
        bodies.push({
          baseAltitude: Math.round(band.baseAltitude + (band.height * (bp.baseLift || 0))),
          extrusion: Math.round(band.height * (1 + (bp.heightBoost || 0))),
          opacity: Math.min(bp.opacityBase + (band.weight * bp.opacitySpan), 0.58),
          latRadiusDeg: footprintScale.lat * (bp.latScale + (band.weight * 0.42)),
          lonRadiusDeg: footprintScale.lon * (bp.lonScale + (band.weight * 0.48)),
          color: band.color,
          pressureBand: type,
          family: morphology.family,
          subtype: morphology.subtype,
          wobble: bp.wobble,
          points: bp.points,
          elongation: bp.elongation,
          shell: bp.shell,
          layerT: type === 'high' ? 0.85 : type === 'mid' ? 0.5 : 0.15,
        });
      }
    };

    if (low >= CLOUD_PRESSURE_BANDS.low.threshold) appendBody('low', low);
    if (mid >= CLOUD_PRESSURE_BANDS.mid.threshold) appendBody('mid', mid);
    if (high >= CLOUD_PRESSURE_BANDS.high.threshold) appendBody('high', high);
    if (!bodies.length && total >= CLOUD_PRESSURE_BANDS.total.threshold) appendBody('total', total);
    return bodies;
  }

  function cloudMassParts(ctx, tile, lod) {
    const baseLat = Number(tile.lat ?? tile.bounds?.lat_center ?? 0);
    const baseLon = Number(tile.lon ?? tile.bounds?.lon_center ?? 0);
    if (!Number.isFinite(baseLat) || !Number.isFinite(baseLon)) return [];

    const feature = {
      cloud_low: tile.cloud_low ?? tile.low_density,
      cloud_mid: tile.cloud_mid ?? tile.mid_density,
      cloud_high: tile.cloud_high ?? tile.high_density,
      cloud_total: tile.cloud_total ?? tile.density,
      precip_rate: tile.precip_rate ?? tile.rain_intensity,
      wind_u: tile.wind_u,
      wind_v: tile.wind_v,
    };

    const scaleKm = Number(tile.bands?.mid?.lateral_scale_km || tile.bands?.low?.lateral_scale_km || 85);
    const baseSpread = 1.18;
    const footprintScale = {
      lat: (0.09 + scaleKm / 240) * baseSpread,
      lon: (0.1 + scaleKm / 220) * baseSpread,
    };

    const bodies = buildCloudBodies(feature, footprintScale);
    const parts = [];
    const lonCorrection = 1 / Math.max(0.1, Math.cos((baseLat * Math.PI) / 180));
    const stormEnergy = clamp((feature.precip_rate || 0) / 15, 0, 1);

    for (let i = 0; i < bodies.length; i++) {
      const body = bodies[i];
      const key = `${tile.tile_id || 'tile'}:${body.shell}:${i}`;
      const headingDeg = windHeadingDeg(feature.wind_u, feature.wind_v);

      const path = roundedCloudPath({
        lat: baseLat,
        lon: baseLon,
        latRadiusDeg: body.latRadiusDeg,
        lonRadiusDeg: body.lonRadiusDeg * lonCorrection,
        wobble: body.wobble,
        points: body.points,
        elongation: body.elongation,
        headingDeg,
      });

      parts.push({
        role: body.shell,
        path: ctx.buildAltitudePath(path, body.baseAltitude, body.extrusion),
        z: 10 + i,
        occ: body.opacity,
        stormEnergy,
        layerT: body.layerT,
        interactive: body.family === 'vertical' && body.opacity > 0.35 && Number(tile.importance || 0) > 0.62,
        extruded: true,
        title: `Cloud (${body.subtype})`,
      });
    }
    return parts;
  }

  function cloudPaint(ctx, part) {
    const sun = ctx.getSunState ? ctx.getSunState() : { daylight: 0.7 };
    const baseShade = 229 - part.stormEnergy * 45 - part.layerT * 25 + sun.daylight * 10;
    const shade = Math.max(150, Math.min(245, Math.round(baseShade)));
    const alpha = Math.max(0.05, Math.min(0.6, part.occ * 1.1));
    return {
      fillColor: `rgba(${shade},${Math.min(252, shade + 7)},${Math.min(255, shade + 16)},${alpha.toFixed(3)})`,
      strokeColor: `rgba(245,249,255,${Math.max(0.05, alpha * 0.36).toFixed(3)})`,
      strokeWidth: part.layerT > 0.7 ? 0.32 : 0.54,
      zIndex: part.z,
    };
  }

  async function renderCloudVolumes(ctx) {
    if (cloudRenderTask) {
      cloudRenderTask.cancel();
    }
    ctx.clearCloudPolygons();
    const { state } = ctx;
    if (!state.feature.clouds || !state.mapReady || !state.cloudTiles.length || !state.maps3dLib) return;

    const lod = ctx.cloudLodProfile();
    const tiles = [...state.cloudTiles].sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0)).slice(0, lod.tileLimit);
    let budget = 0;
    let tileIndex = 0;

    const task = {
      cancelled: false,
      cancel() { this.cancelled = true; },
      run() {
        if (this.cancelled) return;
        const frameStart = performance.now();

        // Process tiles in chunks, yielding to the main thread to avoid UI freezes.
        // The 8ms budget leaves time for other work within a 16ms frame (for 60fps).
        while (tileIndex < tiles.length && (performance.now() - frameStart) < 8) {
          if (budget >= lod.cloudPartBudget) break;
          const tile = tiles[tileIndex];
          const parts = cloudMassParts(ctx, tile, lod);

          for (const part of parts) {
            if (budget >= lod.cloudPartBudget || this.cancelled) break;
            try {
              const paint = cloudPaint(ctx, part);
              const poly = ctx.appendPolygon3D(part.path, {
                type: 'elevated',
                featureType: `cloud-${part.role}`,
                interactive: !!part.interactive,
                extruded: !!part.extruded,
                fillColor: paint.fillColor,
                strokeColor: paint.strokeColor,
                strokeWidth: paint.strokeWidth,
                zIndex: paint.zIndex,
                drawsOccludedSegments: true,
              });
              if (!poly) continue;
              if (part.interactive) {
                poly.addEventListener('gmp-click', () => ctx.setHudMessage(part.title || 'Cloud cell'));
                state.cloudInteractivePolygons.push(poly);
              } else {
                state.cloudPolygons.push(poly);
              }
              budget += 1;
            } catch (err) {
              console.warn('[gfs] cloud part render skipped', err);
            }
          }
          tileIndex += 1;
        }

        if (!this.cancelled && tileIndex < tiles.length && budget < lod.cloudPartBudget) {
          requestAnimationFrame(this.run.bind(this));
        } else {
          cloudRenderTask = null;
        }
      },
    };
    cloudRenderTask = task;
    requestAnimationFrame(task.run.bind(task));
  }

  NS.renderCloudVolumes = renderCloudVolumes;
})();
