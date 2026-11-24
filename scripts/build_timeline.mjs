#!/usr/bin/env node
/**
 * build_timeline.mjs (v4.0) — Deterministic Native Timeline Studio (.timeline v3) Builder & Validator
 * ===================================================================================================
 * Converts a verified `edit_plan.json` (visual clips, bespoke motion MP4s, optional transparent
 * PNG overlays, narration VO, basic CC0 SFX on separate lane, optional BGM, captions, markers)
 * into a 100% native portable `.timeline` ZIP archive for `MartinDelophy/ai-video-editor`.
 *
 * v4.0 Native Documentary Finishing Engine:
 *   - Varied Non-Warm-Biased Cinematic Color Grades (`YT_AUTO_FILTER_PRESETS` + `GRADE_PRESETS`),
 *     mathematically calibrated against Timeline Studio's `colorGrade.js` so wheel chroma NEVER
 *     triggers accidental `sepia()` or positive `hue-rotate` warm cast!
 *   - Smart Varied Native Transitions (~30-38% of cuts + chapter/motion boundaries, never consecutive
 *     repeats, duration clamped safely to <= 25% of adjacent clip lengths).
 *   - Organic Varied Native Photo Motion (`keyframes` + `baseTransform`: zoom-in, zoom-out, pan-left,
 *     pan-right, drift, periodic clean hold) on static `image` clips ONLY — zero black edges, never
 *     applied to code-drawn `kind: "motion"` clips (`NO_LAZY_CAM_ZOOM` preserved!).
 *   - Full native Timeline Studio property pass-through: `baseTransform`, `keyframes`, `transition`,
 *     `animation`, `colorGrade`, `gradePreset`, `mask`, `speedCurve`, `playbackRate`, `splitScreenRect`,
 *     `fitMode`, `effectClips` (clean pool incl. `ink-print`; `grain`/`halo` hard-blocked).
 *   - Runs `audit_visuals.py` v4.0 + `ffprobe` + `timeline-command.mjs project.inspect` (`ok: true`).
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, isAbsolute, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

import { resolveRuntime } from './_runtime_paths.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const RT = resolveRuntime(SCRIPT_DIR);
const TS_DIR = RT.tsDir;
const TS_SFX_DIR = RT.tsSfxDir;
const KIT_SFX_DIR = RT.sfxDir;
const TS_CLI = RT.tsCli;
const PYTHON_BIN = RT.pythonBin;
const fflateAnchor = existsSync(join(TS_DIR, 'node_modules', 'fflate'))
  ? join(TS_DIR, 'package.json')
  : (existsSync(RT.motionRuntimePkg) ? RT.motionRuntimePkg : join(TS_DIR, 'package.json'));
const reqTS = createRequire(fflateAnchor);
const { strToU8, zipSync } = reqTS('fflate');

const argv = process.argv.slice(2);
const has = k => argv.includes('--' + k);
const opt = (k, d) => { const i = argv.indexOf('--' + k); return i >= 0 ? argv[i + 1] : d; };

const projectDirArg = opt('project-dir', '');
const planArg = opt('plan', projectDirArg ? join(projectDirArg, 'edit_plan.json') : '');
if (!planArg || !existsSync(planArg)) {
  console.error('Usage: node build_timeline.mjs --project-dir <dir> [--plan <edit_plan.json>] [--out <out.timeline>] [--skip-audit] [--record-memory]');
  process.exit(2);
}
const planAbs = resolve(planArg);
const projectDir = resolve(projectDirArg || dirname(planAbs));
const plan = JSON.parse(readFileSync(planAbs, 'utf8'));

// 1. Run deterministic Anti-Vício & Anti-Shadow-Clip audit first
if (!has('skip-audit')) {
  const audit = spawnSync(PYTHON_BIN, ['-B', join(SCRIPT_DIR, 'audit_visuals.py'), '--project-dir', projectDir, '--plan', planAbs], { encoding: 'utf8' });
  if (audit.status !== 0) {
    console.error('[AUDIT_VISUALS FAIL]\n' + audit.stdout + '\n' + audit.stderr);
    process.exit(1);
  }
}

const MIME_MAP = {
  '.mp4': ['video', 'video/mp4'],
  '.webm': ['video', 'video/webm'],
  '.mov': ['video', 'video/quicktime'],
  '.jpg': ['image', 'image/jpeg'],
  '.jpeg': ['image', 'image/jpeg'],
  '.png': ['image', 'image/png'],
  '.webp': ['image', 'image/webp'],
  '.mp3': ['audio', 'audio/mpeg'],
  '.wav': ['audio', 'audio/wav'],
  '.m4a': ['audio', 'audio/mp4'],
  '.ogg': ['audio', 'audio/ogg'],
  '.aac': ['audio', 'audio/aac'],
};

// Curated aliases for clean basic SFX (maps friendly names -> real CC0 files)
const SFX_ALIASES = {
  'whoosh': join(KIT_SFX_DIR, 'air-woosh-1.mp3'),
  'whoosh-1': join(KIT_SFX_DIR, 'air-woosh-1.mp3'),
  'whoosh-2': join(KIT_SFX_DIR, 'air-woosh-2.mp3'),
  'whoosh-3': join(KIT_SFX_DIR, 'air-woosh-3.mp3'),
  'whoosh-4': join(KIT_SFX_DIR, 'air-woosh-4.mp3'),
  'whoosh-heavy': join(KIT_SFX_DIR, 'Whoosh 1.mp3'),
  'riser': join(KIT_SFX_DIR, 'warm-riser-1.wav'),
  'shutter': join(KIT_SFX_DIR, 'camera-shutter-1.wav'),
  'paper': join(KIT_SFX_DIR, 'paper-slide-1.wav'),
  'click': join(KIT_SFX_DIR, 'soft-click-1.wav'),
  'soft-thud': join(TS_SFX_DIR, 'soft-thud.mp3'),
  'impact': join(TS_SFX_DIR, 'soft-thud.mp3'),
  'bell': join(TS_SFX_DIR, 'bell-hit.mp3'),
  'ui-click': join(TS_SFX_DIR, 'ui-click-1.mp3'),
  'ui-open': join(TS_SFX_DIR, 'ui-open-1.mp3'),
  'ui-confirm': join(TS_SFX_DIR, 'ui-confirm-1.mp3'),
  'ui-tick': join(TS_SFX_DIR, 'ui-tick-1.mp3'),
  'page-turn': join(TS_SFX_DIR, 'page-turn-1.mp3'),
  'card-slide': join(TS_SFX_DIR, 'card-slide-1.mp3'),
};

function safeName(v, fb = 'asset') {
  return String(v || fb).replace(/[^a-zA-Z0-9._-]+/g, '-').slice(0, 88) || fb;
}

function resolveFile(rawPath) {
  if (!rawPath) return '';
  if (SFX_ALIASES[rawPath] && existsSync(SFX_ALIASES[rawPath])) return SFX_ALIASES[rawPath];
  const tsSfxCand = join(TS_SFX_DIR, rawPath.endsWith('.mp3') ? rawPath : `${rawPath}.mp3`);
  if (existsSync(tsSfxCand)) return tsSfxCand;
  const kitSfxCand = join(KIT_SFX_DIR, rawPath);
  if (existsSync(kitSfxCand)) return kitSfxCand;
  if (isAbsolute(rawPath)) return rawPath;
  return resolve(projectDir, rawPath);
}

function probeMedia(filePath) {
  const r = spawnSync('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration:stream=codec_type,width,height,duration',
    '-of', 'json',
    filePath,
  ], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`ffprobe failed for ${filePath}: ${r.stderr}`);
  const meta = JSON.parse(r.stdout);
  const v = (meta.streams || []).find(s => s.codec_type === 'video') || {};
  return {
    duration: Number(meta.format?.duration) || Number(v.duration) || 0,
    width: Number(v.width) || 0,
    height: Number(v.height) || 0,
  };
}

const files = {};
const media = { visuals: [], audioSegments: [], audio: null, sourceAudio: null, music: null };
const embeddedByHash = new Map();

function embedBinary(filePath, folder, nameHint) {
  const bytes = new Uint8Array(readFileSync(filePath));
  if (!bytes.length) throw new Error(`Empty media file: ${filePath}`);
  const ext = extname(filePath).toLowerCase();
  const inferred = MIME_MAP[ext];
  if (!inferred) throw new Error(`Unsupported extension ${ext} on ${filePath}`);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const cacheKey = `${folder}:${sha256}`;
  if (embeddedByHash.has(cacheKey)) return embeddedByHash.get(cacheKey);
  const archivePath = `media/${folder}/${sha256.slice(0, 10)}-${safeName(nameHint || basename(filePath))}`;
  files[archivePath] = bytes;
  const entry = { path: archivePath, mediaType: inferred[0], mimeType: inferred[1], size: bytes.length, sha256 };
  embeddedByHash.set(cacheKey, entry);
  return entry;
}

const ALLOWED_EFFECT_IDS = new Set([
  'ripple', 'glitch', 'shake', 'glow', 'vignette', 'chromatic', 'ink-print',
  'beat-zoom', 'beat-backdrop', 'shape-flash', 'seven-slat-reveal', 'film-orbit', 'beat-strip', 'memory-vortex',
]);

const ALLOWED_TRANSITION_IDS = new Set([
  'none', 'fade', 'zoom', 'flash', 'wipe-left', 'wipe-up', 'blur', 'split', 'glitch',
  'diagonal-fold', 'ripple-mask', 'step-mask', 'shutter-mask',
]);

// ============================================================================================
// v4.0 Color Grade Presets — Mathematically calibrated for Timeline Studio `src/lib/colorGrade.js`
// IMPORTANT: In Timeline Studio `colorGrade.js`, wheel saturation > 0 triggers `sepia(chroma * 0.26)`
// and negative `temperature` triggers `hue-rotate(+temperatureCool * 188deg)` (warm shift!).
// Keeping wheel saturation=0 and shaping tone via `tint`, `saturation`, and wheel `luminance`
// delivers TRUE cool, steel-cyan, neutral, moody-emerald, vivid, desaturated, and B&W looks
// with ZERO accidental warm/sepia cast! (Only 1 of 7 auto presets is subtly warm.)
// ============================================================================================
const ZERO_W = (lum = 0) => ({ hue: 0, saturation: 0, luminance: lum });

const YT_AUTO_FILTER_PRESETS = [
  {
    id: 'crisp_cool_slate',
    family: 'cool',
    label: 'YT Frio Ardosia',
    colorGrade: { temperature: 0, tint: -55, saturation: -14, shadows: ZERO_W(-34), midtones: ZERO_W(-4), highlights: ZERO_W(24), offset: ZERO_W(-6) },
    effects: [{ effect: 'vignette', intensity: 0.24 }],
  },
  {
    id: 'steel_cyan_doc',
    family: 'cool',
    label: 'YT Ciano Aco',
    colorGrade: { temperature: 0, tint: -85, saturation: -6, shadows: ZERO_W(-28), midtones: ZERO_W(0), highlights: ZERO_W(22), offset: ZERO_W(-4) },
    effects: [{ effect: 'vignette', intensity: 0.22 }],
  },
  {
    id: 'neutral_high_contrast',
    family: 'neutral',
    label: 'YT Alto Contraste Neutro',
    colorGrade: { temperature: 0, tint: 0, saturation: -8, shadows: ZERO_W(-40), midtones: ZERO_W(4), highlights: ZERO_W(36), offset: ZERO_W(-4) },
    effects: [{ effect: 'vignette', intensity: 0.25 }],
  },
  {
    id: 'muted_desat_film',
    family: 'desat',
    label: 'YT Pelicula Dessaturada',
    colorGrade: { temperature: 0, tint: 10, saturation: -34, shadows: ZERO_W(-36), midtones: ZERO_W(-6), highlights: ZERO_W(22), offset: ZERO_W(-8) },
    effects: [{ effect: 'vignette', intensity: 0.28 }],
  },
  {
    id: 'deep_emerald_moody',
    family: 'moody',
    label: 'YT Sombrio Esmeralda',
    colorGrade: { temperature: 0, tint: 62, saturation: -20, shadows: ZERO_W(-42), midtones: ZERO_W(-10), highlights: ZERO_W(18), offset: ZERO_W(-10) },
    effects: [{ effect: 'vignette', intensity: 0.30 }],
  },
  {
    id: 'vivid_editorial_clean',
    family: 'vivid',
    label: 'YT Editorial Nitido',
    colorGrade: { temperature: 0, tint: -22, saturation: 18, shadows: ZERO_W(-26), midtones: ZERO_W(8), highlights: ZERO_W(28), offset: ZERO_W(2) },
    effects: [{ effect: 'glow', intensity: 0.14 }, { effect: 'vignette', intensity: 0.20 }],
  },
  {
    id: 'subtle_warm_vintage',
    family: 'warm',
    label: 'YT Arquivo Quente Sutil',
    colorGrade: { temperature: 12, tint: 4, saturation: -12, shadows: ZERO_W(-28), midtones: ZERO_W(4), highlights: ZERO_W(24), offset: ZERO_W(-4) },
    effects: [{ effect: 'vignette', intensity: 0.24 }],
  },
];

// Additional named presets available via explicit `v.gradePreset` on any scene (photo or video)
const EXTRA_GRADE_PRESETS = {
  silver_noir_archival: {
    id: 'silver_noir_archival',
    family: 'bw',
    label: 'Noir Prata P&B',
    colorGrade: { temperature: 0, tint: 0, saturation: -100, shadows: ZERO_W(-44), midtones: ZERO_W(4), highlights: ZERO_W(34), offset: ZERO_W(-6) },
    effects: [{ effect: 'vignette', intensity: 0.28 }],
  },
  ink_archival: {
    id: 'ink_archival',
    family: 'bw',
    label: 'Imprensa Halftone',
    colorGrade: { temperature: 0, tint: 0, saturation: -85, shadows: ZERO_W(-36), midtones: ZERO_W(6), highlights: ZERO_W(30), offset: ZERO_W(-4) },
    effects: [{ effect: 'ink-print', intensity: 0.35 }],
  },
  clean_neutral: {
    id: 'clean_neutral',
    family: 'neutral',
    label: 'Neutro Limpo',
    colorGrade: { temperature: 0, tint: 0, saturation: 0, shadows: ZERO_W(-18), midtones: ZERO_W(2), highlights: ZERO_W(16), offset: ZERO_W(0) },
    effects: [],
  },
};

const ALL_GRADE_PRESETS = Object.fromEntries([
  ...YT_AUTO_FILTER_PRESETS.map(p => [p.id, p]),
  ...Object.entries(EXTRA_GRADE_PRESETS),
]);

// ============================================================================================
// v4.0 Organic Native Photo Motion (Ken Burns via native Timeline Studio `keyframes`)
// Math guarantees ZERO black edges on 16:9 images: whenever scale=1.00, x=0 and y=0;
// whenever panning, scale >= 1.08 (slack = 4.0% each side, pan max = +-2.2%).
// ============================================================================================
const PHOTO_MOTION_PRESETS = [
  'zoom_in',
  'zoom_out',
  'pan_right',
  'zoom_in_drift_up',
  'pan_left',
  'zoom_out_drift_right',
  'hold',
];

function buildPhotoMotionKeyframes(mode, dur) {
  const d = Number(Math.max(0.2, dur).toFixed(3));
  if (mode === 'zoom_in') {
    return {
      baseTransform: { x: 0, y: 0, scale: 1.0, rotation: 0, opacity: 1 },
      keyframes: [{ time: 0, scale: 1.0, x: 0, y: 0 }, { time: d, scale: 1.09, x: 0, y: 0 }],
    };
  }
  if (mode === 'zoom_out') {
    return {
      baseTransform: { x: 0, y: 0, scale: 1.09, rotation: 0, opacity: 1 },
      keyframes: [{ time: 0, scale: 1.09, x: 0, y: 0 }, { time: d, scale: 1.0, x: 0, y: 0 }],
    };
  }
  if (mode === 'pan_right') {
    return {
      baseTransform: { x: -2.2, y: 0, scale: 1.08, rotation: 0, opacity: 1 },
      keyframes: [{ time: 0, scale: 1.08, x: -2.2, y: 0 }, { time: d, scale: 1.08, x: 2.2, y: 0 }],
    };
  }
  if (mode === 'pan_left') {
    return {
      baseTransform: { x: 2.2, y: 0, scale: 1.08, rotation: 0, opacity: 1 },
      keyframes: [{ time: 0, scale: 1.08, x: 2.2, y: 0 }, { time: d, scale: 1.08, x: -2.2, y: 0 }],
    };
  }
  if (mode === 'zoom_in_drift_up') {
    return {
      baseTransform: { x: 0, y: 0, scale: 1.0, rotation: 0, opacity: 1 },
      keyframes: [{ time: 0, scale: 1.0, x: 0, y: 0 }, { time: d, scale: 1.09, x: -1.3, y: -1.2 }],
    };
  }
  if (mode === 'zoom_out_drift_right') {
    return {
      baseTransform: { x: -1.4, y: 1.0, scale: 1.09, rotation: 0, opacity: 1 },
      keyframes: [{ time: 0, scale: 1.09, x: -1.4, y: 1.0 }, { time: d, scale: 1.0, x: 0, y: 0 }],
    };
  }
  return null; // 'hold' or 'none'
}

// Curated documentary-clean native transitions (verified in Timeline Studio preview & export)
const DOC_TRANSITION_POOL = [
  { id: 'fade', duration: 0.40 },
  { id: 'blur', duration: 0.34 },
  { id: 'wipe-left', duration: 0.36 },
  { id: 'zoom', duration: 0.32, realOnly: true },
  { id: 'wipe-up', duration: 0.36 },
  { id: 'shutter-mask', duration: 0.38 },
  { id: 'split', duration: 0.36 },
];

function isYoutubeVisual(v, fp) {
  const b = basename(fp || '').toLowerCase();
  const nm = String(v.name || '').toLowerCase();
  const src = String(v.source || '').toLowerCase();
  return src === 'youtube' || b.startsWith('yt_') || b.includes('_yt_') || /\(yt\b|youtube/.test(nm);
}

function isMotionVisual(v, fp) {
  return String(v.kind || '').toLowerCase() === 'motion' || String(v.file || fp || '').replace(/\\/g, '/').includes('motion/');
}

function normalizeColorWheel(w = {}) {
  const num = (v, fb = 0) => (Number.isFinite(Number(v)) ? Number(v) : fb);
  return {
    hue: ((num(w.hue, 0) % 360) + 360) % 360,
    saturation: Math.max(0, Math.min(100, num(w.saturation, 0))),
    luminance: Math.max(-100, Math.min(100, num(w.luminance, 0))),
  };
}

function normalizeColorGrade(g) {
  if (!g || typeof g !== 'object') return null;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, Number.isFinite(Number(v)) ? Number(v) : 0));
  return {
    temperature: clamp(g.temperature, -100, 100),
    tint: clamp(g.tint, -100, 100),
    saturation: clamp(g.saturation, -100, 100),
    shadows: normalizeColorWheel(g.shadows),
    midtones: normalizeColorWheel(g.midtones),
    highlights: normalizeColorWheel(g.highlights),
    offset: normalizeColorWheel(g.offset),
  };
}

function normalizeTransform(t) {
  if (!t || typeof t !== 'object') return null;
  return {
    x: Number(t.x) || 0,
    y: Number(t.y) || 0,
    scale: Math.max(0.1, Number(t.scale) || 1),
    rotation: Number(t.rotation) || 0,
    opacity: Math.max(0, Math.min(1, Number.isFinite(Number(t.opacity)) ? Number(t.opacity) : 1)),
  };
}

// Build Visual Segments (contiguous main track)
const visualSegments = [];
const visualMeta = [];
const visualRangesById = new Map();
const autoEffectClips = [];
const usedYtPresetIdx = new Set();
let lastYtFamily = '';
let lastPhotoMotion = '';
let photoMotionCount = 0;
let autoGradedCount = 0;
let timelineCursor = 0;

const rawVisuals = Array.isArray(plan.visuals) ? plan.visuals : [];
if (!rawVisuals.length) throw new Error('edit_plan.json must contain at least one item in `visuals`.');

const autoPhotoMotionEnabled = plan.autoPhotoMotion !== false;
const autoTransitionsEnabled = plan.autoTransitions !== false;
const markerTimes = (plan.markers || []).map(m => Number(m.time)).filter(Number.isFinite);

for (let i = 0; i < rawVisuals.length; i++) {
  const v = rawVisuals[i];
  const fp = resolveFile(v.file);
  if (!existsSync(fp)) throw new Error(`Visual file missing (${v.id}): ${fp}`);
  const bin = embedBinary(fp, 'visuals', v.name || basename(fp));
  const probe = probeMedia(fp);
  const id = v.id || `visual-${String(i + 1).padStart(2, '0')}`;
  const isVideo = bin.mediaType === 'video';
  const isMotion = isMotionVisual(v, fp);
  const sourceStart = Math.max(0, Number(v.sourceStart) || 0);
  const maxAvail = isVideo ? Math.max(0.1, probe.duration - sourceStart) : 60;

  // Anchor-locked timing: enforce zero cumulative drift
  if (Number.isFinite(Number(v.start))) {
    const reqStart = Number(v.start);
    const drift = Math.abs(timelineCursor - reqStart);
    if (drift > 0.25) {
      throw new Error(`TIMELINE_DRIFT_FAIL on ${id}: plan start=${reqStart.toFixed(2)}s != cumulative timeline cursor=${timelineCursor.toFixed(2)}s (drift=${drift.toFixed(2)}s). Adjust previous scene end/duration so scenes lock cleanly to speech!`);
    }
  }
  const rangeDur = (Number.isFinite(Number(v.start)) && Number.isFinite(Number(v.end)) && Number(v.end) > Number(v.start))
    ? (Number(v.end) - Number(v.start))
    : 0;
  let dur = rangeDur > 0 ? rangeDur : (Number(v.duration) > 0 ? Number(v.duration) : (isVideo ? Math.min(6, maxAvail) : 4));
  const playbackRate = Math.max(0.25, Math.min(4, Number(v.playbackRate) || 1));
  if (isVideo && dur * playbackRate > maxAvail + 0.05) {
    throw new Error(`ZERO_FREEZE violation on ${id}: requested ${(dur * playbackRate).toFixed(2)}s > available ${maxAvail.toFixed(2)}s`);
  }
  if (isVideo && !v.speedCurve) dur = Math.min(dur, maxAvail / playbackRate);

  let keyframes = Array.isArray(v.keyframes) ? v.keyframes : [];
  let baseTransform = normalizeTransform(v.baseTransform);

  // Auto organic Ken Burns (zoom-in / zoom-out / pan) on static real PHOTOS ONLY (never on motions!)
  if (!isVideo && !isMotion && !keyframes.length && autoPhotoMotionEnabled && v.photoMotion !== 'none') {
    let mode = typeof v.photoMotion === 'string' && v.photoMotion ? v.photoMotion : '';
    if (!mode || mode === 'auto') {
      const seed = parseInt(bin.sha256.slice(0, 8), 16) + i * 7;
      let pick = PHOTO_MOTION_PRESETS[seed % PHOTO_MOTION_PRESETS.length];
      if (pick === lastPhotoMotion) {
        pick = PHOTO_MOTION_PRESETS[(seed + 1) % PHOTO_MOTION_PRESETS.length];
      }
      mode = pick;
    }
    const km = buildPhotoMotionKeyframes(mode, dur);
    if (km) {
      keyframes = km.keyframes;
      if (!baseTransform) baseTransform = km.baseTransform;
      photoMotionCount += 1;
    }
    lastPhotoMotion = mode;
  }

  const seg = {
    id,
    archiveMediaId: id,
    name: v.name || basename(fp),
    type: bin.mediaType,
    duration: Number(dur.toFixed(3)),
    width: probe.width || 1920,
    height: probe.height || 1080,
    sourceStart: Number(sourceStart.toFixed(3)),
    sourceDuration: isVideo ? Number(probe.duration.toFixed(3)) : 0,
    playbackRate,
    volume: v.keepAudio ? (Number(v.volume) || 1) : 0,
    muted: !v.keepAudio,
    ...(isVideo ? { sourceAudioUnmapped: true, sourceAudioDisabled: !v.keepAudio } : {}),
    ...(baseTransform ? { baseTransform } : {}),
    keyframes,
    integrity: { sha256: bin.sha256, size: bin.size, archivePath: bin.path },
  };
  if (v.fitMode && ['cover', 'contain'].includes(v.fitMode)) seg.fitMode = v.fitMode;
  if (v.mask && typeof v.mask === 'object') seg.mask = v.mask;
  if (v.speedCurve && typeof v.speedCurve === 'object') seg.speedCurve = v.speedCurve;
  if (v.splitScreenRect && typeof v.splitScreenRect === 'object') seg.splitScreenRect = v.splitScreenRect;
  if (typeof v.filterId === 'string' && v.filterId && v.filterId !== 'none') {
    seg.filterId = v.filterId;
  }

  // Color grade resolution: explicit colorGrade -> explicit gradePreset -> auto non-warm-biased YT preset
  let cg = normalizeColorGrade(v.colorGrade);
  if (!cg && typeof v.gradePreset === 'string' && ALL_GRADE_PRESETS[v.gradePreset]) {
    const preset = ALL_GRADE_PRESETS[v.gradePreset];
    cg = normalizeColorGrade(preset.colorGrade);
    for (let eIdx = 0; eIdx < (preset.effects || []).length; eIdx++) {
      const pe = preset.effects[eIdx];
      autoEffectClips.push({
        id: `fx-preset-${id}-${pe.effect}`,
        clipId: id,
        effect: pe.effect,
        name: `${preset.label} (${pe.effect})`,
        intensity: pe.intensity,
        lane: eIdx,
      });
    }
  } else if (!cg && isVideo && isYoutubeVisual(v, fp) && v.disableAutoYoutubeFilter !== true) {
    let pickIdx = parseInt(bin.sha256.slice(0, 8), 16) % YT_AUTO_FILTER_PRESETS.length;
    for (let step = 0; step < YT_AUTO_FILTER_PRESETS.length; step++) {
      const cand = (pickIdx + step) % YT_AUTO_FILTER_PRESETS.length;
      if (!usedYtPresetIdx.has(cand) && YT_AUTO_FILTER_PRESETS[cand].family !== lastYtFamily) {
        pickIdx = cand;
        break;
      }
    }
    usedYtPresetIdx.add(pickIdx);
    if (usedYtPresetIdx.size >= YT_AUTO_FILTER_PRESETS.length) usedYtPresetIdx.clear();
    const preset = YT_AUTO_FILTER_PRESETS[pickIdx];
    lastYtFamily = preset.family;
    autoGradedCount += 1;
    cg = normalizeColorGrade(preset.colorGrade);
    for (let eIdx = 0; eIdx < preset.effects.length; eIdx++) {
      const pe = preset.effects[eIdx];
      autoEffectClips.push({
        id: `fx-auto-${id}-${pe.effect}`,
        clipId: id,
        effect: pe.effect,
        name: `${preset.label} (${pe.effect})`,
        intensity: pe.intensity,
        lane: eIdx,
      });
    }
  }
  if (cg) seg.colorGrade = cg;
  if (v.animation) seg.animation = v.animation;

  visualRangesById.set(id, { start: Number(timelineCursor.toFixed(3)), duration: seg.duration });
  visualSegments.push(seg);
  visualMeta.push({ raw: v, isMotion, isVideo, sha: bin.sha256, end: timelineCursor + seg.duration });
  media.visuals.push({ id, name: seg.name, path: bin.path, type: bin.mimeType, size: bin.size, sha256: bin.sha256 });
  timelineCursor += seg.duration;
}

// Pass 2: Explicit & smart auto-varied native transitions between contiguous clips
let transitionsApplied = 0;
let lastAutoTransId = '';
for (let i = 0; i < visualSegments.length - 1; i++) {
  const seg = visualSegments[i];
  const nextSeg = visualSegments[i + 1];
  const meta = visualMeta[i];
  const nextMeta = visualMeta[i + 1];
  const maxSafeDur = Number(Math.min(0.45, seg.duration * 0.25, nextSeg.duration * 0.25).toFixed(3));
  if (maxSafeDur < 0.14) continue;

  const explicit = meta.raw.transition;
  if (explicit !== undefined) {
    const tId = typeof explicit === 'string' ? explicit : explicit?.id;
    const tDur = typeof explicit === 'object' && explicit?.duration ? Number(explicit.duration) : 0.36;
    if (tId && tId !== 'none') {
      if (!ALLOWED_TRANSITION_IDS.has(tId)) {
        throw new Error(`Unsupported transition id on ${seg.id}: ${tId}`);
      }
      seg.transition = { id: tId, duration: Number(Math.min(tDur, maxSafeDur).toFixed(3)) };
      transitionsApplied += 1;
      lastAutoTransId = tId;
    }
    continue;
  }

  if (!autoTransitionsEnabled) continue;
  // Place tasteful transitions at chapter markers, motion entrances/exits, and ~every 3rd scene beat
  const nearChapter = markerTimes.some(mt => Math.abs(mt - meta.end) <= 1.2);
  const motionBoundary = meta.isMotion !== nextMeta.isMotion;
  const rhythmicBeat = (i % 3 === 2);
  if (!nearChapter && !motionBoundary && !rhythmicBeat) continue;

  const pool = DOC_TRANSITION_POOL.filter(t => {
    if (t.realOnly && (meta.isMotion || nextMeta.isMotion)) return false;
    if (t.id === lastAutoTransId) return false;
    // Use crisp subtle fades/blurs on motion boundaries, full varied editorial pool on chapter/scene beats
    if (motionBoundary && !['fade', 'blur', 'wipe-left', 'wipe-up'].includes(t.id)) return false;
    return true;
  });
  const seed = parseInt(meta.sha.slice(0, 6), 16) + i * 13;
  const pick = pool[seed % pool.length] || { id: 'fade', duration: 0.35 };
  seg.transition = { id: pick.id, duration: Number(Math.min(pick.duration, maxSafeDur).toFixed(3)) };
  lastAutoTransId = pick.id;
  transitionsApplied += 1;
}

// Build Visual Overlay Segments (optional transparent PNGs / overlays — audited for EDGE_ALPHA_CLIP!)
const visualOverlaySegments = [];
for (let i = 0; i < (plan.overlays || []).length; i++) {
  const ov = plan.overlays[i];
  const fp = resolveFile(ov.file);
  if (!existsSync(fp)) throw new Error(`Overlay file missing (${ov.id}): ${fp}`);
  const bin = embedBinary(fp, 'visuals', ov.name || basename(fp));
  const probe = probeMedia(fp);
  const id = ov.id || `overlay-${String(i + 1).padStart(2, '0')}`;
  const dur = Number(ov.duration) > 0 ? Number(ov.duration) : (bin.mediaType === 'video' ? probe.duration : 3.5);
  const seg = {
    id,
    archiveMediaId: id,
    name: ov.name || basename(fp),
    type: bin.mediaType,
    width: probe.width || 1920,
    height: probe.height || 1080,
    sourceStart: Number(ov.sourceStart) || 0,
    sourceDuration: bin.mediaType === 'video' ? Number(probe.duration.toFixed(3)) : 0,
    playbackRate: 1,
    start: Math.max(0, Number(ov.start) || 0),
    duration: Number(dur.toFixed(3)),
    muted: true,
    layer: Number(ov.layer) || (i + 1),
    baseTransform: {
      x: Number(ov.x ?? 0),
      y: Number(ov.y ?? 0),
      scale: Number(ov.scale ?? 1),
      rotation: Number(ov.rotation ?? 0),
      opacity: Number(ov.opacity ?? 1),
    },
    ...(ov.mask ? { mask: ov.mask } : {}),
    ...(ov.splitScreenRect ? { splitScreenRect: ov.splitScreenRect } : {}),
    ...(ov.animation ? { animation: ov.animation } : { animation: { in: { id: 'fade', duration: 0.3 }, out: { id: 'fade', duration: 0.25 } } }),
    keyframes: Array.isArray(ov.keyframes) ? ov.keyframes : [],
  };
  visualOverlaySegments.push(seg);
  media.visuals.push({ id, name: seg.name, path: bin.path, type: bin.mimeType, size: bin.size, sha256: bin.sha256 });
}

// Build Audio Segments: Voiceover (lane 0) + Basic SFX (lane 1..N)
const audioSegments = [];
let primaryVoiceId = '';
const voiceItems = Array.isArray(plan.voiceover)
  ? plan.voiceover
  : (plan.voiceover ? [typeof plan.voiceover === 'string' ? { file: plan.voiceover } : plan.voiceover] : []);

for (let i = 0; i < voiceItems.length; i++) {
  const vo = voiceItems[i];
  const fp = resolveFile(vo.file);
  if (!existsSync(fp)) throw new Error(`Voiceover file missing: ${fp}`);
  const bin = embedBinary(fp, 'audio', vo.name || basename(fp));
  const probe = probeMedia(fp);
  const id = vo.id || `voice-${String(i + 1).padStart(2, '0')}`;
  if (!primaryVoiceId) primaryVoiceId = id;
  const dur = Number(vo.duration) > 0 ? Math.min(Number(vo.duration), probe.duration) : probe.duration;
  audioSegments.push({
    id,
    name: vo.name || 'Narration',
    start: Math.max(0, Number(vo.start) || 0),
    duration: Number(dur.toFixed(3)),
    sourceStart: Math.max(0, Number(vo.sourceStart) || 0),
    sourceDuration: Number(probe.duration.toFixed(3)),
    playbackRate: 1,
    volume: Number(vo.volume ?? 1),
    fadeIn: Number(vo.fadeIn ?? 0),
    fadeOut: Number(vo.fadeOut ?? 0),
    muted: false,
    lane: 0,
    sourceKind: 'upload',
    integrity: { sha256: bin.sha256, size: bin.size, archivePath: bin.path },
  });
  media.audioSegments.push({ id, path: bin.path, name: vo.name || 'Narration', type: bin.mimeType, size: bin.size, sha256: bin.sha256 });
}

// Basic SFX (placed cleanly on lane 1 / 2 — never colliding with lane 0 narration)
const sfxItems = Array.isArray(plan.sfx) ? plan.sfx : [];
for (let i = 0; i < sfxItems.length; i++) {
  const sx = sfxItems[i];
  const fp = resolveFile(sx.file || sx.sfx);
  if (!fp || !existsSync(fp)) throw new Error(`SFX file/alias not found: ${sx.file || sx.sfx}`);
  const bin = embedBinary(fp, 'audio', sx.name || basename(fp));
  const probe = probeMedia(fp);
  const id = sx.id || `sfx-${String(i + 1).padStart(2, '0')}`;
  const start = Math.max(0, Number(sx.start) || 0);
  const dur = Number(sx.duration) > 0 ? Math.min(Number(sx.duration), probe.duration) : probe.duration;
  audioSegments.push({
    id,
    name: sx.name || `SFX ${sx.sfx || basename(fp, extname(fp))}`,
    start: Number(start.toFixed(3)),
    duration: Number(dur.toFixed(3)),
    sourceStart: 0,
    sourceDuration: Number(probe.duration.toFixed(3)),
    playbackRate: 1,
    volume: Number(sx.volume ?? 0.24),
    fadeIn: Number(sx.fadeIn ?? 0.02),
    fadeOut: Number(sx.fadeOut ?? 0.08),
    muted: false,
    lane: Number(sx.lane ?? 1),
    sourceKind: 'sound-effect',
    integrity: { sha256: bin.sha256, size: bin.size, archivePath: bin.path },
  });
  media.audioSegments.push({ id, path: bin.path, name: sx.name || basename(fp), type: bin.mimeType, size: bin.size, sha256: bin.sha256 });
}

const audioDuration = audioSegments.reduce((mx, s) => Math.max(mx, s.start + s.duration), 0);

// Optional Background Music
const musicSegments = [];
let musicName = '', musicDuration = 0, musicStart = 0, musicVolume = 0.16;
if (plan.music && plan.music.file) {
  const fp = resolveFile(plan.music.file);
  if (!existsSync(fp)) throw new Error(`Music file missing: ${fp}`);
  const bin = embedBinary(fp, 'audio', plan.music.name || basename(fp));
  const probe = probeMedia(fp);
  const dur = Math.min(Number(plan.music.duration) || timelineCursor, probe.duration);
  musicName = plan.music.name || basename(fp);
  musicDuration = Number(probe.duration.toFixed(3));
  musicStart = Math.max(0, Number(plan.music.start) || 0);
  musicVolume = Number(plan.music.volume ?? 0.16);
  musicSegments.push({
    id: 'music-01',
    name: musicName,
    start: musicStart,
    duration: Number(dur.toFixed(3)),
    sourceStart: 0,
    sourceDuration: musicDuration,
    playbackRate: 1,
    volume: musicVolume,
    fadeIn: Number(plan.music.fadeIn ?? 0.8),
    fadeOut: Number(plan.music.fadeOut ?? 1.5),
    muted: false,
    integrity: { sha256: bin.sha256, size: bin.size, archivePath: bin.path },
  });
  media.music = { path: bin.path, name: musicName, type: bin.mimeType, size: bin.size, sha256: bin.sha256 };
}

// Optional Captions (off by default unless plan.captionsEnabled === true)
const captionSegments = [];
const captionsEnabled = plan.captionsEnabled === true;
if (captionsEnabled && Array.isArray(plan.captions)) {
  for (let i = 0; i < plan.captions.length; i++) {
    const c = plan.captions[i];
    if (!c.text || !(Number(c.end) > Number(c.start))) continue;
    captionSegments.push({
      id: c.id || `cap-${String(i + 1).padStart(3, '0')}`,
      text: String(c.text),
      start: Number(Number(c.start).toFixed(3)),
      end: Number(Number(c.end).toFixed(3)),
      fontId: c.fontId || 'default',
      ...(primaryVoiceId ? { audioSegmentId: primaryVoiceId } : {}),
    });
  }
}

// Timeline Effect Clips (vignette, glow, chromatic, ink-print, etc. + auto YouTube filter effects)
const effectClips = [];
const rawEffects = [...(Array.isArray(plan.effectClips) ? plan.effectClips : []), ...autoEffectClips];
for (let i = 0; i < rawEffects.length; i++) {
  const fx = rawEffects[i];
  if (!fx || !ALLOWED_EFFECT_IDS.has(fx.effect)) {
    throw new Error(`Unsupported effectClips[${i}].effect: ${fx?.effect}`);
  }
  const bound = fx.clipId ? visualRangesById.get(fx.clipId) : null;
  if (fx.clipId && !bound) throw new Error(`effectClips[${i}].clipId not found in visuals: ${fx.clipId}`);
  const start = bound ? bound.start : Math.max(0, Number(fx.start) || 0);
  const duration = bound && !(Number(fx.duration) > 0) ? bound.duration : Math.max(0.1, Number(fx.duration) || 3);
  const intensity = Math.max(0, Math.min(1, Number.isFinite(Number(fx.intensity)) ? Number(fx.intensity) : 0.4));
  const color = /^#[0-9a-f]{6}$/i.test(fx.color || '') ? fx.color : '#35ead9';
  let lane = Number.isInteger(fx.lane) && fx.lane >= 0 ? fx.lane : 0;
  while (effectClips.some(e => e.lane === lane && start < e.start + e.duration - 1e-5 && start + duration > e.start + 1e-5)) {
    lane += 1;
  }
  effectClips.push({
    id: fx.id || `fx-${String(i + 1).padStart(2, '0')}`,
    effect: fx.effect,
    ...(fx.name ? { name: String(fx.name) } : {}),
    start: Number(start.toFixed(3)),
    duration: Number(duration.toFixed(3)),
    sourceOffset: Math.max(0, Number(fx.sourceOffset) || 0),
    alignmentYaw: 0,
    alignmentPitch: 0,
    alignmentRoll: 0,
    intensity: Number(intensity.toFixed(3)),
    color,
    lane,
  });
}

// Timeline Markers / Chapters
const timelineMarkers = (plan.markers || []).map((m, idx) => ({
  id: m.id || `marker-${String(idx + 1).padStart(2, '0')}`,
  type: m.type || 'chapter',
  time: Number(Number(m.time || 0).toFixed(3)),
  ...(m.type === 'range' && Number(m.endTime) > Number(m.time) ? { endTime: Number(Number(m.endTime).toFixed(3)) } : {}),
  title: String(m.title || `Beat ${idx + 1}`),
  notes: String(m.notes || ''),
  color: m.color || '#35ead9',
}));

const ratioId = ['16:9', '9:16', '1:1', '4:5', '4:3', '3:4'].includes(plan.ratioId) ? plan.ratioId : '16:9';
const project = {
  ratioId,
  fitMode: plan.fitMode || 'cover',
  script: captionSegments.map(c => c.text).join('\n'),
  captionsEnabled,
  captionPosition: 'bottom',
  captionPlacement: { x: 50, y: 84 },
  captionSize: 22,
  captionStylePresetId: 'classic',
  captionStylePresets: [],
  captionSegments,
  visualSegments,
  visualOverlaySegments,
  audioSegments,
  audioDuration: Number(audioDuration.toFixed(3)),
  musicSegments,
  musicName,
  musicDuration,
  musicStart,
  musicVolume,
  stickerSegments: [],
  effectClips,
  timelineMarkers,
  selectedTransitionId: 'none',
  selectedFilterId: typeof plan.selectedFilterId === 'string' && plan.selectedFilterId ? plan.selectedFilterId : 'none',
  selectedStickerId: 'none',
  trackVisibility: { visuals: true, overlays: true, audio: true, music: true, captions: captionsEnabled, stickers: true, effects: true },
  trackLocks: {},
  timelineZoom: 1,
  volume: 1,
  speed: 1,
  commandState: { schemaVersion: 1, revision: 0, appliedOperationIds: [] },
};

const payload = {
  format: 'timeline-studio-archive',
  version: 3,
  exportedAt: new Date().toISOString(),
  project,
  media,
};
files['project.json'] = strToU8(JSON.stringify(payload));

const safeSlug = safeName(plan.title || basename(projectDir), 'project').toLowerCase();
const outPath = resolve(opt('out', join(projectDir, `${safeSlug}.timeline`)));
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, zipSync(files, { level: 6 }));

// 4. Native Timeline Studio CLI verification (`project.inspect`)
const inspect = spawnSync('node', [TS_CLI, 'project.inspect', outPath], { cwd: TS_DIR, encoding: 'utf8' });
if (inspect.status !== 0) {
  console.error('[TIMELINE_INSPECT FAIL]\n' + inspect.stdout + '\n' + inspect.stderr);
  process.exit(1);
}
const inspected = JSON.parse(inspect.stdout);
if (!inspected.ok) {
  console.error('[TIMELINE_INSPECT NOT OK]', inspected);
  process.exit(1);
}

// 5. Optional creator memory recording
if (has('record-memory')) {
  spawnSync(PYTHON_BIN, ['-B', join(SCRIPT_DIR, 'creator_memory.py'), '--record-plan', planAbs], { stdio: 'pipe' });
}

const gradedClips = visualSegments.filter(s => Boolean(s.colorGrade));
console.log(JSON.stringify({
  ok: true,
  timeline_file: outPath,
  size_bytes: statSync(outPath).size,
  ratioId,
  duration_s: Number(timelineCursor.toFixed(2)),
  visuals: visualSegments.length,
  transitions: transitionsApplied,
  photo_motion_keyframes: photoMotionCount,
  graded_clips: gradedClips.length,
  auto_yt_graded: autoGradedCount,
  overlays: visualOverlaySegments.length,
  effect_clips: effectClips.length,
  audio_clips: audioSegments.length,
  sfx_clips: sfxItems.length,
  markers: timelineMarkers.length,
  native_inspect_ok: inspected.ok,
  archiveVersion: inspected.archiveVersion,
}, null, 2));
