/**
 * map_kit.mjs — Cinema-Grade Real Cartography Helper (Natural Earth 10m/50m + d3-geo + topojson-client)
 * =====================================================================================================
 * Renders 100% geographically accurate maps offline at 1920x1080 (or any aspect) inside motion_runner.mjs.
 * NEVER hand-draw continents, peninsulas, or islands with fake SVG polygons!
 *
 * Usage inside any motion HTML:
 *   <script src="/__runtime/d3-geo/dist/d3-geo.min.js"></script>
 *   <script src="/__runtime/topojson-client/dist/topojson-client.min.js"></script>
 *   <script type="module">
 *     import { createRealMap } from '/__kit/map_kit.mjs';
 *     const map = await createRealMap(svgEl, {
 *       detail: '10m',             // '10m' (ultra-detailed regional) | '50m' (continental) | '110m' (world)
 *       projection: 'mercator',    // 'mercator' | 'naturalEarth1' | 'orthographic'
 *       center: [103.82, 1.35],    // [lon, lat]
 *       scale: 3800,
 *       highlightIds: ['702'],     // ISO-3166 numeric IDs (e.g. '702'=Singapore, '458'=Malaysia, '360'=Indonesia)
 *       theme: 'editorial_atlas',  // 'editorial_atlas' | 'dark_geopolitics' | 'warm_archival'
 *     });
 *     const route = map.addRoute([[94.5, 6.2], [99.8, 3.8], [103.82, 1.25], [108.5, 4.0], [114.2, 8.5]], { color: '#C8102E' });
 *     const pin = map.addPin([103.82, 1.35], { label: 'SINGAPURA', sub: '1.35°N 103.82°E', color: '#C8102E' });
 *     window.drawFrame = (t) => {
 *       route.setProgress(Math.min(1, t / 3.0));
 *       pin.setPulse(t);
 *     };
 *   </script>
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

export const MAP_THEMES = {
  editorial_atlas: {
    oceanBg: ['#D4E4EA', '#B6CED8'],
    graticule: 'rgba(28, 63, 79, 0.16)',
    coastGlow: 'rgba(19, 55, 72, 0.22)',
    landFill: '#EDE6D6',
    landStroke: '#6D6556',
    borderStroke: 'rgba(92, 84, 70, 0.55)',
    highlightFill: '#D9534F',
    highlightStroke: '#7F1D1D',
    labelColor: '#2B2620',
    oceanLabel: 'rgba(28, 63, 79, 0.56)',
  },
  dark_geopolitics: {
    oceanBg: ['#0B1522', '#070E18'],
    graticule: 'rgba(148, 163, 184, 0.12)',
    coastGlow: 'rgba(56, 189, 248, 0.24)',
    landFill: '#1B283A',
    landStroke: '#475569',
    borderStroke: 'rgba(148, 163, 184, 0.30)',
    highlightFill: '#DC2626',
    highlightStroke: '#FCA5A5',
    labelColor: '#E2E8F0',
    oceanLabel: 'rgba(148, 163, 184, 0.44)',
  },
  warm_archival: {
    oceanBg: ['#DFE6DF', '#C4D2CA'],
    graticule: 'rgba(42, 62, 56, 0.16)',
    coastGlow: 'rgba(34, 52, 46, 0.22)',
    landFill: '#F2E9D5',
    landStroke: '#5B5142',
    borderStroke: 'rgba(91, 81, 66, 0.48)',
    highlightFill: '#C8102E',
    highlightStroke: '#7F091C',
    labelColor: '#29231C',
    oceanLabel: 'rgba(42, 62, 56, 0.54)',
  },
};

function el(tag, attrs = {}, parent = null) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  if (parent) parent.appendChild(n);
  return n;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(s);
  });
}

async function ensureCartographyDeps() {
  if (!window.d3 || !window.d3.Adder) {
    await loadScript('/__runtime/d3-array/dist/d3-array.min.js');
  }
  if (!window.d3 || !window.d3.geoMercator) {
    await loadScript('/__runtime/d3-geo/dist/d3-geo.min.js');
  }
  if (!window.topojson) {
    await loadScript('/__runtime/topojson-client/dist/topojson-client.min.js');
  }
}

function rewindRings(rings, d3) {
  if (!Array.isArray(rings) || !rings.length) return rings;
  // Exterior ring in d3-geo spherical coordinates must be clockwise (area < 2*PI)
  const outer = { type: 'Polygon', coordinates: [rings[0]] };
  const reversed = d3.geoArea(outer) > 2 * Math.PI;
  if (!reversed) return rings;
  return rings.map(r => [...r].reverse());
}

function rewindGeoJSON(gj, d3) {
  const fixGeom = (g) => {
    if (!g) return g;
    if (g.type === 'Polygon') {
      return { ...g, coordinates: rewindRings(g.coordinates, d3) };
    }
    if (g.type === 'MultiPolygon') {
      return { ...g, coordinates: g.coordinates.map(poly => rewindRings(poly, d3)) };
    }
    if (g.type === 'GeometryCollection') {
      return { ...g, geometries: g.geometries.map(fixGeom) };
    }
    return g;
  };
  if (gj.type === 'FeatureCollection') {
    return { ...gj, features: gj.features.map(f => ({ ...f, geometry: fixGeom(f.geometry) })) };
  }
  if (gj.type === 'Feature') {
    return { ...gj, geometry: fixGeom(gj.geometry) };
  }
  return fixGeom(gj);
}

export async function createRealMap(svgEl, opts = {}) {
  await ensureCartographyDeps();
  const d3 = window.d3;
  const topojson = window.topojson;
  if (!d3?.geoMercator || !topojson?.feature) {
    throw new Error('map_kit.mjs failed to load d3-array / d3-geo / topojson-client');
  }

  const width = opts.width || 1920;
  const height = opts.height || 1080;
  const detail = opts.detail || '10m';
  const theme = typeof opts.theme === 'object' ? { ...MAP_THEMES.editorial_atlas, ...opts.theme } : (MAP_THEMES[opts.theme] || MAP_THEMES.editorial_atlas);
  const highlightSet = new Set((opts.highlightIds || []).map(String));
  const secondarySet = new Set((opts.secondaryIds || []).map(String));

  svgEl.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svgEl.innerHTML = '';

  const res = await fetch(`/__runtime/world-atlas/countries-${detail}.json`);
  if (!res.ok) throw new Error(`Failed loading world-atlas countries-${detail}.json`);
  const topo = await res.json();
  const countries = rewindGeoJSON(topojson.feature(topo, topo.objects.countries), d3);
  const land = topo.objects.land ? rewindGeoJSON(topojson.feature(topo, topo.objects.land), d3) : countries;
  const borders = topojson.mesh(topo, topo.objects.countries, (a, b) => a !== b);

  const projName = opts.projection || 'mercator';
  const cLon = opts.center?.[0] ?? 0;
  const cLat = opts.center?.[1] ?? 20;
  let proj;
  if (projName === 'orthographic') {
    proj = d3.geoOrthographic()
      .rotate(opts.rotate || [-cLon, -cLat, 0])
      .scale(opts.scale || 460)
      .translate(opts.translate || [width / 2, height / 2])
      .clipAngle(90);
  } else if (projName === 'naturalEarth1') {
    proj = d3.geoNaturalEarth1()
      .scale(opts.scale || 340)
      .translate(opts.translate || [width / 2, height / 2])
      .clipExtent([[0, 0], [width, height]]);
  } else {
    proj = d3.geoMercator()
      .rotate([-cLon, 0])
      .center([0, cLat])
      .scale(opts.scale || 1800)
      .translate(opts.translate || [width / 2, height / 2])
      .clipExtent([[-20, -20], [width + 20, height + 20]]);
  }
  const pathGen = d3.geoPath(proj);

  // Defs: subtle ocean radial gradient + coastal drop shadow
  const defs = el('defs', {}, svgEl);
  const bgGrad = el('radialGradient', { id: 'mkOceanGrad', cx: '52%', cy: '48%', r: '72%' }, defs);
  el('stop', { offset: '0%', 'stop-color': theme.oceanBg[0] }, bgGrad);
  el('stop', { offset: '100%', 'stop-color': theme.oceanBg[1] }, bgGrad);

  const coastFilter = el('filter', { id: 'mkCoastShadow', x: '-8%', y: '-8%', width: '116%', height: '116%' }, defs);
  el('feDropShadow', { dx: '0', dy: '6', stdDeviation: '8', 'flood-color': theme.coastGlow, 'flood-opacity': '1' }, coastFilter);

  // Layer 0: Ocean
  el('rect', { x: 0, y: 0, width, height, fill: 'url(#mkOceanGrad)' }, svgEl);

  // Layer 1: Real Lat/Lon Graticule
  const gratStep = opts.graticuleStep || (opts.scale > 3000 ? 2 : opts.scale > 1200 ? 5 : 15);
  const graticule = d3.geoGraticule().step([gratStep, gratStep]);
  el('path', {
    d: pathGen(graticule()) || '',
    fill: 'none',
    stroke: theme.graticule,
    'stroke-width': 1.2,
    'stroke-dasharray': opts.graticuleDash || '4 6',
  }, svgEl);

  // Layer 2: Soft coastal shadow under real landmass
  const landGroup = el('g', { id: 'mk-land-layer' }, svgEl);
  el('path', {
    d: pathGen(land) || '',
    fill: theme.landFill,
    filter: 'url(#mkCoastShadow)',
  }, landGroup);

  // Layer 3: Individual Real Countries (ISO-3166 numeric IDs)
  for (const feat of countries.features) {
    const d = pathGen(feat);
    if (!d) continue;
    const fid = String(feat.id || '').padStart(3, '0');
    const isHi = highlightSet.has(fid) || highlightSet.has(String(feat.id));
    const isSec = secondarySet.has(fid) || secondarySet.has(String(feat.id));
    el('path', {
      d,
      'data-iso': fid,
      'data-name': feat.properties?.name || '',
      fill: isHi ? theme.highlightFill : (isSec ? (opts.secondaryFill || '#E3D5BA') : theme.landFill),
      stroke: isHi ? theme.highlightStroke : theme.landStroke,
      'stroke-width': isHi ? 2.4 : 1.15,
      'stroke-linejoin': 'round',
    }, landGroup);
  }

  // Layer 4: Crisp International Borders
  el('path', {
    d: pathGen(borders) || '',
    fill: 'none',
    stroke: theme.borderStroke,
    'stroke-width': 1.25,
    'stroke-dasharray': '5 4',
  }, landGroup);

  const routesLayer = el('g', { id: 'mk-routes-layer' }, svgEl);
  const labelsLayer = el('g', { id: 'mk-labels-layer' }, svgEl);
  const pinsLayer = el('g', { id: 'mk-pins-layer' }, svgEl);

  function addGeoLabel(lonLat, text, labelOpts = {}) {
    const pt = proj(lonLat);
    if (!pt) return null;
    const g = el('g', { opacity: labelOpts.opacity ?? 1 }, labelsLayer);
    const t = el('text', {
      x: pt[0].toFixed(1),
      y: pt[1].toFixed(1),
      'text-anchor': labelOpts.anchor || 'middle',
      'font-family': labelOpts.font || 'IBM Plex Mono, monospace',
      'font-size': labelOpts.size || 22,
      'font-weight': labelOpts.weight || 700,
      'letter-spacing': labelOpts.tracking || '0.16em',
      fill: labelOpts.ocean ? theme.oceanLabel : (labelOpts.color || theme.labelColor),
      ...(labelOpts.halo ? { 'paint-order': 'stroke', stroke: labelOpts.halo, 'stroke-width': 6, 'stroke-linejoin': 'round' } : {}),
    }, g);
    t.textContent = text;
    return g;
  }

  function addRoute(coordsLonLat, routeOpts = {}) {
    const pts = coordsLonLat.map(c => proj(c)).filter(Boolean);
    if (pts.length < 2) return { setProgress: () => {} };
    // Smooth Catmull-Rom cubic Bezier through exact projected geo coordinates
    let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[Math.min(pts.length - 1, i + 2)];
      const c1x = p1[0] + (p2[0] - p0[0]) / 6;
      const c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6;
      const c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    const color = routeOpts.color || '#C8102E';
    const glow = el('path', { d, fill: 'none', stroke: color, 'stroke-width': (routeOpts.width || 6) * 3, 'stroke-linecap': 'round', opacity: 0.18 }, routesLayer);
    const main = el('path', { d, fill: 'none', stroke: color, 'stroke-width': routeOpts.width || 6, 'stroke-linecap': 'round' }, routesLayer);
    const totalLen = main.getTotalLength();
    for (const p of [glow, main]) {
      p.setAttribute('stroke-dasharray', totalLen.toFixed(1));
      p.setAttribute('stroke-dashoffset', totalLen.toFixed(1));
    }
    const head = routeOpts.arrow === false ? null : el('polygon', {
      points: '0,-10 24,0 0,10 6,0',
      fill: routeOpts.arrowColor || '#141210',
      stroke: '#F7F3EB',
      'stroke-width': 2.2,
      opacity: 0,
    }, routesLayer);

    return {
      totalLen,
      mainEl: main,
      setProgress(prog) {
        const p = Math.max(0, Math.min(1, prog));
        const off = (totalLen * (1 - p)).toFixed(1);
        glow.setAttribute('stroke-dashoffset', off);
        main.setAttribute('stroke-dashoffset', off);
        if (head) {
          if (p <= 0.01) {
            head.setAttribute('opacity', '0');
          } else {
            const dist = totalLen * p;
            const cur = main.getPointAtLength(dist);
            const prev = main.getPointAtLength(Math.max(0, dist - 8));
            const deg = Math.atan2(cur.y - prev.y, cur.x - prev.x) * (180 / Math.PI);
            head.setAttribute('opacity', '1');
            head.setAttribute('transform', `translate(${cur.x.toFixed(1)}, ${cur.y.toFixed(1)}) rotate(${deg.toFixed(1)})`);
          }
        }
      },
    };
  }

  function addPin(lonLat, pinOpts = {}) {
    const pt = proj(lonLat);
    if (!pt) return { setPulse: () => {}, setOpacity: () => {} };
    const color = pinOpts.color || '#C8102E';
    const g = el('g', { transform: `translate(${pt[0].toFixed(1)}, ${pt[1].toFixed(1)})`, opacity: pinOpts.opacity ?? 1 }, pinsLayer);
    const pulse1 = el('circle', { cx: 0, cy: 0, r: 14, fill: 'none', stroke: color, 'stroke-width': 3.5, opacity: 0 }, g);
    const pulse2 = el('circle', { cx: 0, cy: 0, r: 14, fill: 'none', stroke: color, 'stroke-width': 2, opacity: 0 }, g);
    el('circle', { cx: 0, cy: 0, r: pinOpts.radius || 11, fill: color, stroke: '#FFFFFF', 'stroke-width': 4 }, g);

    return {
      el: g,
      point: pt,
      setOpacity(v) { g.setAttribute('opacity', String(Math.max(0, Math.min(1, v)))); },
      setPulse(t) {
        const p1 = (t * 0.78) % 1;
        pulse1.setAttribute('r', (14 + p1 * 68).toFixed(1));
        pulse1.setAttribute('opacity', ((1 - p1) * 0.75).toFixed(3));
        const p2 = ((t * 0.78) + 0.5) % 1;
        pulse2.setAttribute('r', (14 + p2 * 68).toFixed(1));
        pulse2.setAttribute('opacity', ((1 - p2) * 0.45).toFixed(3));
      },
    };
  }

  return { projection: proj, pathGen, countries, land, addGeoLabel, addRoute, addPin, theme };
}
