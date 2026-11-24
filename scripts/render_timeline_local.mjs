#!/usr/bin/env node
/**
 * render_timeline_local.mjs — Pixel-Identical Chunked Local MP4 Renderer for Timeline Studio (.timeline v3)
 *
 * Uses the ACTUAL local Timeline Studio engine (`offlineVideoExport.js`, `editorComposition.js`,
 * `audioExport.js`, `colorGrade.js`, `maskTransitions.js`, captions, stickers, overlays, effectClips)
 * inside Chrome WebCodecs, rendering frame-exact chunks on disk so even 30-120+ min / 4K projects
 * render with 100% visual & audio fidelity and flat RAM usage (~200-500 MB per chunk).
 *
 * Usage:
 *   node render_timeline_local.mjs --timeline <project.timeline> --out <video.mp4>
 *        [--resolution 1080] [--fps 30] [--quality high] [--chunk-seconds 120]
 *        [--bitrate <bps>] [--audio-bitrate 192000] [--captions burned|none] [--keep-temp]
 */
import {
  createReadStream,
  createWriteStream,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, extname, join, normalize, resolve } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { findChromeExecutable, resolveRuntime } from './_runtime_paths.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const RT = resolveRuntime(SCRIPT_DIR);
const PYTHON_BIN = RT.pythonBin;
const TS_DIR = RT.tsDir;

const reqRuntime = createRequire(existsSync(RT.motionRuntimePkg) ? RT.motionRuntimePkg : import.meta.url);
const { chromium } = reqRuntime('playwright');

const argv = process.argv.slice(2);
const has = (k) => argv.includes('--' + k);
const opt = (k, d) => {
  const i = argv.indexOf('--' + k);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};

const timelineArg = opt('timeline', '');
const outArg = opt('out', '');
if (!timelineArg || !outArg) {
  console.error(
    'Usage: node render_timeline_local.mjs --timeline <file.timeline> --out <output.mp4> ' +
      '[--resolution 720|1080|1440|2160] [--fps 24|30|60] [--quality standard|high|ultra] ' +
      '[--chunk-seconds 120] [--bitrate <bps>] [--audio-bitrate 192000] [--captions burned|none] [--keep-temp]',
  );
  process.exit(2);
}

const timelinePath = resolve(timelineArg);
const outPath = resolve(outArg);
if (!existsSync(timelinePath)) {
  console.error(`Timeline archive not found: ${timelinePath}`);
  process.exit(2);
}
if (!existsSync(join(TS_DIR, 'src', 'lib', 'offlineVideoExport.js'))) {
  console.error(`Local Timeline Studio engine not found in: ${TS_DIR}`);
  process.exit(2);
}

const resolution = String(opt('resolution', '1080'));
const fps = Math.max(24, Math.min(60, Math.round(Number(opt('fps', '30')) || 30)));
const quality = String(opt('quality', 'high'));
const customBitrate = opt('bitrate', '') ? Number(opt('bitrate', '0')) : 0;
const audioBitrate = Math.max(96_000, Number(opt('audio-bitrate', '192000')) || 192_000);
const captionsMode = String(opt('captions', 'burned'));
const defaultChunkSec = Number(resolution) >= 2160 ? 60 : 120;
const chunkSeconds = Math.max(15, Number(opt('chunk-seconds', String(defaultChunkSec))) || defaultChunkSec);
const keepTemp = has('keep-temp');

const MIME = {
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mov': 'video/quicktime',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.m4a': 'audio/mp4',
  '.ogg': 'audio/ogg',
  '.json': 'application/json; charset=utf-8',
};

function getExportFrameCount(duration, frameRate) {
  const frames = duration * frameRate;
  const integer = Math.round(frames);
  return Math.abs(frames - integer) < 1e-8 ? integer : Math.ceil(frames);
}

function computeContentDuration(project) {
  const visuals = Array.isArray(project.visualSegments) ? project.visualSegments : [];
  const visualDuration = visuals.reduce((sum, s) => sum + Math.max(0, Number(s?.duration) || 0), 0);
  const voiceDuration = (Array.isArray(project.audioSegments) ? project.audioSegments : []).reduce(
    (max, s) => Math.max(max, Math.max(0, Number(s?.start) || 0) + Math.max(0, Number(s?.duration) || 0)),
    0,
  );
  const overlayDuration = (Array.isArray(project.visualOverlaySegments) ? project.visualOverlaySegments : []).reduce(
    (max, s) =>
      Math.max(
        max,
        Number(s?.end) || Math.max(0, Number(s?.start) || 0) + Math.max(0, Number(s?.duration) || 0),
      ),
    0,
  );
  const stickerDuration = (Array.isArray(project.stickerSegments) ? project.stickerSegments : []).reduce(
    (max, s) => Math.max(max, Math.max(0, Number(s?.start) || 0) + Math.max(0, Number(s?.duration) || 0)),
    0,
  );
  const captionDuration = Number(project.captionDuration) || 0;
  const sourceAudioDuration = Number(project.sourceAudioDuration)
    ? (Number(project.sourceAudioStart) || 0) + Number(project.sourceAudioDuration)
    : 0;
  const musicDuration = (Array.isArray(project.musicSegments) ? project.musicSegments : []).reduce(
    (max, s) => Math.max(max, Math.max(0, Number(s?.start) || 0) + Math.max(0, Number(s?.duration) || 0)),
    Number(project.musicDuration) ? (Number(project.musicStart) || 0) + Number(project.musicDuration) : 0,
  );
  return Math.max(
    visualDuration,
    voiceDuration,
    overlayDuration,
    stickerDuration,
    captionDuration,
    sourceAudioDuration,
    musicDuration,
  );
}

function buildChunkPlan(project, totalFrames, frameRate, targetSeconds) {
  const targetFrames = Math.max(frameRate * 10, Math.round(targetSeconds * frameRate));
  const minTailFrames = Math.round(Math.min(targetFrames * 0.25, frameRate * 15));

  // Collect clean visual cut frames (where the ending clip has NO transition)
  const cleanCutFrames = [];
  let cursor = 0;
  for (const seg of project.visualSegments || []) {
    cursor += Math.max(0, Number(seg?.duration) || 0);
    const hasTransition = Boolean(seg?.transition?.id && seg.transition.id !== 'none');
    if (!hasTransition) {
      const f = Math.round(cursor * frameRate);
      if (f > 0 && f < totalFrames) cleanCutFrames.push(f);
    }
  }

  const chunks = [];
  let startFrame = 0;
  let index = 0;
  while (startFrame < totalFrames) {
    const remaining = totalFrames - startFrame;
    if (remaining <= targetFrames + minTailFrames) {
      chunks.push({
        index,
        startFrame,
        endFrame: totalFrames,
        frameCount: totalFrames - startFrame,
        startSec: startFrame / frameRate,
        endSec: totalFrames / frameRate,
        durationSec: (totalFrames - startFrame) / frameRate,
        snappedToCleanCut: false,
      });
      break;
    }

    const idealEnd = startFrame + targetFrames;
    const searchRadius = Math.round(Math.min(targetFrames * 0.2, frameRate * 15));
    let chosenEnd = idealEnd;
    let snapped = false;
    let bestDist = Infinity;
    for (const cutFrame of cleanCutFrames) {
      if (cutFrame <= startFrame + frameRate * 5) continue;
      if (cutFrame >= totalFrames - frameRate * 5) continue;
      const dist = Math.abs(cutFrame - idealEnd);
      if (dist <= searchRadius && dist < bestDist) {
        bestDist = dist;
        chosenEnd = cutFrame;
        snapped = true;
      }
    }

    chunks.push({
      index,
      startFrame,
      endFrame: chosenEnd,
      frameCount: chosenEnd - startFrame,
      startSec: startFrame / frameRate,
      endSec: chosenEnd / frameRate,
      durationSec: (chosenEnd - startFrame) / frameRate,
      snappedToCleanCut: snapped,
    });
    startFrame = chosenEnd;
    index += 1;
  }
  return chunks;
}

function buildBrowserHarnessSource() {
  return `
import { RATIO_OPTIONS, FILTER_OPTIONS } from "/src/config/editor.js";
import {
  normalizeExportSettings,
  getExportDimensions,
  getEffectiveExportBitrate,
} from "/src/lib/exportSettings.js";
import { prepareEditorComposition } from "/src/lib/editorComposition.js";
import { exportOfflineVideo } from "/src/lib/offlineVideoExport.js";
import { exportAudioMix } from "/src/lib/audioExport.js";
import { ensureCaptionFontLoaded, resolveCaptionStyleForSegment } from "/src/lib/captionFonts.js";
import { createCaptionSegments, getVisualSegmentsTotal } from "/src/lib/timeline.js";
import { normalizeEffectClips } from "/src/lib/timelineEffects.js";
import { normalizeTimelineMarkers } from "/src/lib/timelineMarkers.js";
import { normalizeTrackLocks, normalizeTrackVisibility } from "/src/lib/projectTrackState.js";
import { normalizeSmartFrame } from "/src/lib/smartFrame.js";

function encodeMediaUrl(relPath) {
  return "/__local_render/media/" + relPath.split("/").map(encodeURIComponent).join("/");
}

async function fetchBlob(url, fallbackType = "application/octet-stream") {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch media (" + res.status + "): " + url);
  const blob = await res.blob();
  return fallbackType && !blob.type ? blob.slice(0, blob.size, fallbackType) : blob;
}

async function reportProgress(chunkIndex, kind, info) {
  try {
    await fetch("/__local_render/progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chunkIndex, kind, ...info }),
    });
  } catch {}
}

async function uploadChunk(chunkIndex, ext, blob) {
  const res = await fetch("/__local_render/upload?index=" + chunkIndex + "&ext=" + encodeURIComponent(ext), {
    method: "POST",
    headers: { "Content-Type": blob.type || "application/octet-stream" },
    body: blob,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => "");
    throw new Error("Chunk upload failed (" + res.status + "): " + msg);
  }
  return res.json();
}

function buildVisualMediaMap(media) {
  const map = new Map();
  for (const entry of media?.visuals || []) {
    if (entry?.id) map.set(entry.id, entry);
  }
  return map;
}

function resolveVisualEntry(map, seg) {
  return map.get(seg?.id) || map.get(seg?.archiveMediaId) || map.get(seg?.assetId) || null;
}

async function hydrateForChunk(manifest, chunk, includeAudio) {
  const { payload, settings, totalDuration } = manifest;
  const data = payload.project || {};
  const media = payload.media || {};
  const visualMap = buildVisualMediaMap(media);
  const audioSegMap = new Map((media.audioSegments || []).map((e) => [e.id, e]));

  const restoreVisual = (seg) => {
    const entry = resolveVisualEntry(visualMap, seg);
    if (!entry?.path) return seg?.src ? { ...seg } : null;
    const restored = { ...seg, src: encodeMediaUrl(entry.path) };
    const sf = normalizeSmartFrame(restored.smartFrame);
    if (!sf) delete restored.smartFrame;
    else restored.smartFrame = sf;
    return restored;
  };

  const renderedVisualSegments = (Array.isArray(data.visualSegments) ? data.visualSegments : [])
    .map(restoreVisual)
    .filter(Boolean);
  const visualOverlaySegments = (Array.isArray(data.visualOverlaySegments) ? data.visualOverlaySegments : [])
    .map(restoreVisual)
    .filter(Boolean);

  const ratio = RATIO_OPTIONS.find((o) => o.id === data.ratioId) || RATIO_OPTIONS[0];
  const selectedFilter = FILTER_OPTIONS.find((f) => f.id === (data.selectedFilterId || "none")) || FILTER_OPTIONS[0];
  const trackVisibility = normalizeTrackVisibility(data.trackVisibility);
  const trackLocks = normalizeTrackLocks(data.trackLocks);
  const timelineMarkers = normalizeTimelineMarkers(data.timelineMarkers);
  const effectClips = normalizeEffectClips(data.effectClips);

  const legacyFontId = data.captionStyle?.fontId || "default";
  let inheritedFont = legacyFontId;
  const captionSegments = (Array.isArray(data.captionSegments) ? data.captionSegments : createCaptionSegments(data.script || ""))
    .map((seg) => {
      inheritedFont = seg.fontId || inheritedFont;
      return seg.fontId ? seg : { ...seg, fontId: inheritedFont };
    });

  const rangeStart = chunk.startSec;
  const rangeEnd = chunk.endSec;

  // Only fetch audio blobs overlapping this chunk (and slice continuous tracks > 600s on server!)
  let audioSegments = [];
  let sourceAudioBlob = null;
  let musicBlob = null;
  let hasAnyAudioOverlap = false;

  if (includeAudio) {
    const rawAudioSegs = Array.isArray(data.audioSegments) && data.audioSegments.length
      ? data.audioSegments
      : media.audio?.path
        ? [{ id: "__standalone_audio__", start: 0, duration: Number(data.audioDuration) || totalDuration, volume: Number(data.volume) || 1 }]
        : [];

    const blobCache = new Map();
    for (const seg of rawAudioSegs) {
      if (seg.muted === true) continue;
      const segStart = Math.max(0, Number(seg.start) || 0);
      const segDur = Math.max(0, Number(seg.duration) || 0);
      if (segStart >= rangeEnd || (segDur > 0 && segStart + segDur <= rangeStart)) continue;

      const entry = seg.id === "__standalone_audio__" ? media.audio : (audioSegMap.get(seg.id) || media.audio);
      if (!entry?.path) continue;
      hasAnyAudioOverlap = true;

      const canServerSlice =
        segDur > 600 &&
        !seg.speedCurve?.enabled &&
        Math.abs((Number(seg.playbackRate) || 1) - 1) < 1e-4 &&
        !(Number(seg.fadeIn) > 0) &&
        !(Number(seg.fadeOut) > 0);

      if (canServerSlice) {
        const visStart = Math.max(segStart, rangeStart);
        const visEnd = Math.min(segStart + segDur, rangeEnd);
        const sliceSourceStart = Math.max(0, Number(seg.sourceStart) || 0) + (visStart - segStart);
        const sliceDur = Math.max(0.01, visEnd - visStart);
        const sliceUrl =
          "/__local_render/audio-slice?rel=" + encodeURIComponent(entry.path) +
          "&start=" + sliceSourceStart.toFixed(6) +
          "&dur=" + (sliceDur + 0.1).toFixed(6);
        const blob = await fetchBlob(sliceUrl, "audio/wav");
        audioSegments.push({
          ...seg,
          start: visStart,
          duration: sliceDur,
          sourceStart: 0,
          sourceDuration: sliceDur,
          blob,
        });
      } else {
        if (!blobCache.has(entry.path)) {
          blobCache.set(entry.path, await fetchBlob(encodeMediaUrl(entry.path), entry.type || "audio/mpeg"));
        }
        audioSegments.push({ ...seg, blob: blobCache.get(entry.path) });
      }
    }

    if (media.sourceAudio?.path && trackVisibility.source !== false) {
      hasAnyAudioOverlap = true;
      sourceAudioBlob = await fetchBlob(encodeMediaUrl(media.sourceAudio.path), media.sourceAudio.type || "audio/wav");
    }
    if (media.music?.path && trackVisibility.music !== false) {
      hasAnyAudioOverlap = true;
      musicBlob = await fetchBlob(encodeMediaUrl(media.music.path), media.music.type || "audio/mpeg");
    }
  }

  const d = {
    t: (k) => k,
    imageSrc: renderedVisualSegments[0]?.src || "",
    visualType: renderedVisualSegments[0]?.type || "image",
    renderedVisualSegments,
    visualOverlaySegments,
    sourceAudioBlob,
    sourceAudioAssetId: data.sourceAudioAssetId || "",
    sourceAudioLinked: data.sourceAudioLinked !== false,
    linkedSourceAudioSegments: Array.isArray(data.sourceAudioSegments) ? data.sourceAudioSegments : [],
    sourceAudioStart: Number(data.sourceAudioStart) || 0,
    sourceAudioDuration: Number(data.sourceAudioDuration) || 0,
    sourceAudioFades: data.sourceAudioFades || {},
    sourceAudioVolume: Number(data.sourceAudioVolume) || 1,
    sourceAudioSpatialEffect: data.sourceAudioSpatialEffect || "original",
    sourceAudioSpatialAmount: Number.isFinite(Number(data.sourceAudioSpatialAmount)) ? Number(data.sourceAudioSpatialAmount) : 1,
    trackVisibility,
    trackLocks,
    visionRecords: {},
    depthRecords: {},
    audioSegments,
    volume: Number(data.volume) || 1,
    musicBlob,
    musicVolume: Number(data.musicVolume) || 0.35,
    musicStart: Math.max(0, Number(data.musicStart) || 0),
    musicSegments: Array.isArray(data.musicSegments) ? data.musicSegments : [],
    timelineMarkers,
    effectClips,
    script: typeof data.script === "string" ? data.script : "",
    captionSegments,
    captionTargetDuration: Number(data.captionTargetDuration) || Number(data.captionDuration) || totalDuration,
    captionDuration: Number(data.captionDuration) || totalDuration,
    ratio,
    fitMode: data.fitMode || "contain",
    selectedFilter,
    captionPosition: data.captionPosition || "bottom",
    captionPlacement: data.captionPlacement || { x: 50, y: 78 },
    captionSize: Number(data.captionSize) || 14,
    captionStyle: data.captionStyle || {},
    captionsEnabled: data.captionsEnabled !== false,
    previewFrameSize: { width: 0, height: 0 },
    stickerSegments: Array.isArray(data.stickerSegments) ? data.stickerSegments : [],
  };

  const requested = normalizeExportSettings({
    resolution: settings.resolution,
    frameRate: settings.fps,
    codec: "h264",
    quality: settings.quality,
    pipeline: "deterministic",
    audio: includeAudio ? "mix" : "none",
    audioBitsPerSecond: settings.audioBitrate,
    captions: settings.captionsMode,
    range: "custom",
    rangeStart: chunk.startSec,
    rangeEnd: chunk.endSec,
    bitrateMode: settings.customBitrate > 0 ? "custom" : "auto",
    customVideoBitsPerSecond: settings.customBitrate > 0 ? settings.customBitrate : 12_000_000,
    keyFrameInterval: 2,
  });

  const exportSettings = {
    ...requested,
    ...getExportDimensions(ratio, Number(requested.resolution)),
    videoBitsPerSecond: getEffectiveExportBitrate(requested),
  };

  const exportRange = {
    start: chunk.startSec,
    end: chunk.endSec,
    duration: chunk.durationSec,
  };

  const burnCaptions =
    settings.captionsMode !== "none" &&
    d.captionsEnabled &&
    d.trackVisibility.caption !== false &&
    d.captionSegments.some((s) => !s.hidden && String(s.text || "").trim());

  if (burnCaptions) {
    const captionsByFont = new Map();
    d.captionSegments.forEach((seg) => {
      const fontId = resolveCaptionStyleForSegment(d.captionStyle, seg).fontId;
      captionsByFont.set(fontId, ((captionsByFont.get(fontId) || "") + " " + (seg.text || "")).trim());
    });
    await Promise.all([...captionsByFont].map(([fontId, text]) => ensureCaptionFontLoaded(fontId, text)));
  }

  return { d, exportSettings, exportRange, burnCaptions, hasAnyAudioOverlap };
}

window.__renderChunk = async (chunkIndex) => {
  const t0 = performance.now();
  const manifest = await fetch("/__local_render/manifest.json").then((r) => r.json());
  const chunk = manifest.chunks[chunkIndex];
  if (!chunk) throw new Error("Invalid chunkIndex: " + chunkIndex);

  // 1) VIDEO PASS (pure deterministic WebCodecs H.264, zero audio encoding overhead)
  const vHydrated = await hydrateForChunk(manifest, chunk, false);
  let lastPct = -1;
  const videoOptions = await prepareEditorComposition(vHydrated.d, {
    exportSettings: vHydrated.exportSettings,
    exportRange: vHydrated.exportRange,
    exportAudio: false,
    burnCaptions: vHydrated.burnCaptions,
    onProgress: (u) => {
      const p = Math.round(Number(u?.progress) || 0);
      if (p >= lastPct + 10 || p >= 98) {
        lastPct = p;
        void reportProgress(chunkIndex, "video", { progress: p, phaseKey: u?.phaseKey || "" });
      }
    },
  });
  const videoResult = await exportOfflineVideo(videoOptions);
  const vUpload = await uploadChunk(chunkIndex, "mp4", videoResult.blob);

  // 2) AUDIO PASS (exact Timeline Studio mix -> lossless 48kHz stereo WAV for zero-click concat)
  const aHydrated = await hydrateForChunk(manifest, chunk, true);
  const audioOptions = await prepareEditorComposition(aHydrated.d, {
    exportSettings: aHydrated.exportSettings,
    exportRange: aHydrated.exportRange,
    exportAudio: true,
    burnCaptions: false,
  });
  const wavResult = await exportAudioMix({
    ...audioOptions,
    format: "wav",
    audioBitsPerSecond: manifest.settings.audioBitrate,
  });
  const aUpload = await uploadChunk(chunkIndex, "wav", wavResult.blob);

  return {
    chunkIndex,
    elapsedMs: Math.round(performance.now() - t0),
    videoBytes: vUpload.bytes,
    wavBytes: aUpload.bytes,
    diagnostics: videoResult.diagnostics,
    hasAudioOverlap: aHydrated.hasAnyAudioOverlap,
  };
};

window.__LOCAL_RENDER_READY__ = true;
`;
}

async function main() {
  const tStart = Date.now();
  const workDir = mkdtempSync(join(tmpdir(), 'ts-local-render-'));
  const extractDir = join(workDir, 'unpacked');
  const chunksDir = join(workDir, 'chunks');
  mkdirSync(extractDir, { recursive: true });
  mkdirSync(chunksDir, { recursive: true });

  let viteServer = null;
  let browser = null;

  try {
    console.log(`[1/4] Unpacking .timeline archive to disk...`);
    const entryMapPath = join(workDir, 'entry_map.json');
    const pyUnzip = spawnSync(
      PYTHON_BIN,
      [
        '-B',
        '-c',
        `import sys, os, json, zipfile
src, out_dir, map_path = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out_dir, exist_ok=True)
mapping = {}
with zipfile.ZipFile(src, 'r') as z:
    for idx, info in enumerate(z.infolist()):
        if info.is_dir():
            continue
        safe_name = f"entry_{idx:05d}.bin"
        dst = os.path.join(out_dir, safe_name)
        with z.open(info, 'r') as rf, open(dst, 'wb') as wf:
            while True:
                buf = rf.read(1024 * 1024)
                if not buf:
                    break
                wf.write(buf)
        mapping[info.filename] = safe_name
with open(map_path, 'w', encoding='utf-8') as f:
    json.dump(mapping, f, ensure_ascii=False)
`,
        timelinePath,
        extractDir,
        entryMapPath,
      ],
      { encoding: 'utf8' },
    );
    if (pyUnzip.status !== 0) {
      throw new Error(`Failed to unpack .timeline: ${pyUnzip.stderr || pyUnzip.stdout}`);
    }

    const entryMap = JSON.parse(readFileSync(entryMapPath, 'utf8'));
    const resolveArchiveEntry = (relPath) => {
      const safe = entryMap[relPath];
      return safe ? join(extractDir, safe) : null;
    };

    const projectJsonPath = resolveArchiveEntry('project.json');
    if (!projectJsonPath || !existsSync(projectJsonPath)) {
      throw new Error('Invalid .timeline archive: project.json missing');
    }
    const payload = JSON.parse(readFileSync(projectJsonPath, 'utf8'));
    const project = payload.project || {};

    // Build exact MIME lookup from payload.media so extensionless entries get proper Content-Type
    const mediaMimeMap = new Map();
    const registerMime = (entry) => {
      if (entry?.path && entry?.type) mediaMimeMap.set(entry.path, entry.type);
      if (entry?.originalPath && entry?.originalType) mediaMimeMap.set(entry.originalPath, entry.originalType);
    };
    for (const e of payload.media?.visuals || []) registerMime(e);
    for (const e of payload.media?.audioSegments || []) registerMime(e);
    registerMime(payload.media?.audio);
    registerMime(payload.media?.sourceAudio);
    registerMime(payload.media?.music);
    const totalDuration = computeContentDuration(project);
    if (!(totalDuration > 0)) {
      throw new Error('Project has zero duration');
    }

    const totalFrames = getExportFrameCount(totalDuration, fps);
    const chunks = buildChunkPlan(project, totalFrames, fps, chunkSeconds);
    const manifest = {
      payload,
      chunks,
      totalDuration,
      totalFrames,
      settings: {
        resolution,
        fps,
        quality,
        customBitrate,
        audioBitrate,
        captionsMode,
      },
    };

    console.log(
      `      Project: ${project.ratioId || '16:9'} | ${totalDuration.toFixed(2)}s (${totalFrames} frames @ ${fps}fps) | ` +
        `${(project.visualSegments || []).length} visuals | ${(project.effectClips || []).length} effects | ` +
        `${(project.audioSegments || []).length} audio clips`,
    );
    console.log(`      Chunk plan (${chunks.length} chunks, target ${chunkSeconds}s):`);
    for (const c of chunks) {
      console.log(
        `        Chunk ${c.index}: ${c.startSec.toFixed(3)}s -> ${c.endSec.toFixed(3)}s ` +
          `(${c.frameCount} frames, ${c.durationSec.toFixed(2)}s${c.snappedToCleanCut ? ', clean-cut' : ''})`,
      );
    }

    console.log(`[2/4] Starting local Timeline Studio engine bridge...`);
    const viteCandidates = [
      join(TS_DIR, 'node_modules', 'vite', 'dist', 'node', 'index.js'),
      join(RT.motionRuntimeNm, 'vite', 'dist', 'node', 'index.js'),
      join(dirname(TS_DIR), 'node_modules', 'vite', 'dist', 'node', 'index.js'),
    ];
    const viteEntry = viteCandidates.find((p) => existsSync(p));
    if (!viteEntry) {
      throw new Error(
        `Vite not found in ${TS_DIR}/node_modules or ${RT.motionRuntimeNm}. Run install.ps1 / install.sh to install local render dependencies.`,
      );
    }
    const viteModUrl = pathToFileURL(viteEntry).href;
    const { createServer } = await import(viteModUrl);

    const HARNESS_URL = '/__local_render/harness.js';
    const HARNESS_RESOLVED = '\0local-render-harness.js';
    const harnessSource = buildBrowserHarnessSource();
    const hasTsNodeModules = existsSync(join(TS_DIR, 'node_modules', 'mediabunny'));
    const needsFallbackResolve =
      !hasTsNodeModules &&
      existsSync(RT.motionRuntimeNm) &&
      resolve(dirname(TS_DIR), 'node_modules') !== resolve(RT.motionRuntimeNm);
    const fallbackImporter = join(RT.motionRuntimeDir, '__virtual_importer__.js');

    const bridgePlugin = {
      name: 'local-timeline-render-bridge',
      async resolveId(id, importer, options) {
        if (id === HARNESS_URL) return HARNESS_RESOLVED;
        if (
          needsFallbackResolve &&
          id &&
          !id.startsWith('.') &&
          !id.startsWith('/') &&
          !id.startsWith('\0') &&
          !id.startsWith('http:') &&
          !id.startsWith('https:') &&
          !id.startsWith('data:') &&
          importer !== fallbackImporter
        ) {
          const normal = await this.resolve(id, importer, { ...options, skipSelf: true });
          if (normal) return normal;
          return this.resolve(id, fallbackImporter, { ...options, skipSelf: true });
        }
        return null;
      },
      load(id) {
        if (id === HARNESS_RESOLVED) return harnessSource;
        return null;
      },
      configureServer(server) {
        server.middlewares.use(async (req, res, next) => {
          try {
            const urlObj = new URL(req.url || '/', 'http://127.0.0.1');
            const pathname = urlObj.pathname;

            if (pathname === '/__local_render/harness.html') {
              const rawHtml =
                '<!doctype html><html><head><meta charset="utf-8"><title>Local Render</title></head>' +
                `<body><script type="module" src="${HARNESS_URL}"></script></body></html>`;
              const html = await server.transformIndexHtml(pathname, rawHtml);
              res.statusCode = 200;
              res.setHeader('Content-Type', 'text/html; charset=utf-8');
              res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
              res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
              res.end(html);
              return;
            }

            if (pathname === '/__local_render/manifest.json') {
              res.statusCode = 200;
              res.setHeader('Content-Type', 'application/json; charset=utf-8');
              res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
              res.end(JSON.stringify(manifest));
              return;
            }

            if (pathname.startsWith('/__local_render/media/')) {
              const rel = pathname
                .slice('/__local_render/media/'.length)
                .split('/')
                .map(decodeURIComponent)
                .join('/');
              const abs = resolveArchiveEntry(rel);
              if (!abs || !existsSync(abs)) {
                console.error(`[404] Media entry not found in archive: ${rel}`);
                res.statusCode = 404;
                res.end('Not found');
                return;
              }
              const stat = statSync(abs);
              const contentType =
                mediaMimeMap.get(rel) || MIME[extname(rel).toLowerCase()] || 'application/octet-stream';
              res.setHeader('Content-Type', contentType);
              res.setHeader('Accept-Ranges', 'bytes');
              res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');

              const rangeHeader = req.headers.range;
              if (rangeHeader) {
                const match = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader);
                if (match) {
                  const start = match[1] ? parseInt(match[1], 10) : 0;
                  const end = match[2] ? Math.min(stat.size - 1, parseInt(match[2], 10)) : stat.size - 1;
                  res.statusCode = 206;
                  res.setHeader('Content-Range', `bytes ${start}-${end}/${stat.size}`);
                  res.setHeader('Content-Length', String(end - start + 1));
                  createReadStream(abs, { start, end }).pipe(res);
                  return;
                }
              }
              res.statusCode = 200;
              res.setHeader('Content-Length', String(stat.size));
              createReadStream(abs).pipe(res);
              return;
            }

            if (pathname === '/__local_render/audio-slice') {
              const rel = urlObj.searchParams.get('rel') || '';
              const start = Math.max(0, Number(urlObj.searchParams.get('start')) || 0);
              const dur = Math.max(0.05, Number(urlObj.searchParams.get('dur')) || 1);
              const abs = resolveArchiveEntry(rel);
              if (!abs || !existsSync(abs)) {
                console.error(`[404] Audio entry not found in archive: ${rel}`);
                res.statusCode = 404;
                res.end('Not found');
                return;
              }
              res.statusCode = 200;
              res.setHeader('Content-Type', 'audio/wav');
              res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
              const ff = spawn(
                'ffmpeg',
                [
                  '-v', 'error',
                  '-ss', start.toFixed(6),
                  '-t', dur.toFixed(6),
                  '-i', abs,
                  '-vn',
                  '-c:a', 'pcm_s16le',
                  '-ar', '48000',
                  '-ac', '2',
                  '-f', 'wav',
                  'pipe:1',
                ],
                { stdio: ['ignore', 'pipe', 'pipe'] },
              );
              ff.stdout.pipe(res);
              ff.on('error', (err) => {
                if (!res.headersSent) res.statusCode = 500;
                res.end(String(err));
              });
              return;
            }

            if (pathname === '/__local_render/upload' && req.method === 'POST') {
              const idx = Number(urlObj.searchParams.get('index'));
              const ext = String(urlObj.searchParams.get('ext') || 'bin').replace(/[^a-z0-9]/gi, '');
              const fileName = `chunk_${String(idx).padStart(4, '0')}.${ext}`;
              const dest = join(chunksDir, fileName);
              const ws = createWriteStream(dest);
              let bytes = 0;
              req.on('data', (chunk) => {
                bytes += chunk.length;
              });
              req.pipe(ws);
              ws.on('finish', () => {
                res.statusCode = 200;
                res.setHeader('Content-Type', 'application/json');
                res.end(JSON.stringify({ ok: true, fileName, bytes }));
              });
              ws.on('error', (err) => {
                res.statusCode = 500;
                res.end(String(err));
              });
              return;
            }

            if (pathname === '/__local_render/progress' && req.method === 'POST') {
              let body = '';
              req.on('data', (c) => (body += c));
              req.on('end', () => {
                try {
                  const info = JSON.parse(body);
                  console.log(`        [chunk ${info.chunkIndex}] ${info.kind} ${info.progress}% (${info.phaseKey || ''})`);
                } catch {}
                res.statusCode = 200;
                res.end('ok');
              });
              return;
            }

            next();
          } catch (err) {
            res.statusCode = 500;
            res.end(String(err?.stack || err));
          }
        });
      },
    };

    viteServer = await createServer({
      root: TS_DIR,
      configFile: false,
      cacheDir: join(workDir, '.vite-cache'),
      logLevel: 'error',
      worker: { format: 'es' },
      server: {
        host: '127.0.0.1',
        port: 0,
        open: false,
        fs: { allow: [TS_DIR, RT.motionRuntimeDir, dirname(TS_DIR)] },
      },
      plugins: [bridgePlugin],
    });
    await viteServer.listen();
    const addr = viteServer.httpServer.address();
    const baseUrl = `http://127.0.0.1:${addr.port}`;

    const chromePath = findChromeExecutable();
    console.log(`[3/4] Rendering ${chunks.length} chunks via Chrome WebCodecs (${chromePath || 'bundled chromium'})...`);
    browser = await chromium.launch({
      ...(chromePath ? { executablePath: chromePath } : {}),
      headless: true,
      args: [
        ...(process.platform === 'win32' ? ['--use-gl=angle', '--use-angle=d3d11'] : []),
        '--enable-webgl',
        '--ignore-gpu-blocklist',
        '--enable-accelerated-video-decode',
        '--enable-accelerated-video-encode',
        '--autoplay-policy=no-user-gesture-required',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
      ],
    });

    const chunkResults = [];
    for (const chunk of chunks) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
      const pageErrors = [];
      page.on('pageerror', (e) => pageErrors.push(e.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      try {
        await page.goto(`${baseUrl}/__local_render/harness.html`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
        await page.waitForFunction(() => window.__LOCAL_RENDER_READY__ === true, null, { timeout: 60_000 });
        const result = await page.evaluate((idx) => window.__renderChunk(idx), chunk.index);
        chunkResults.push(result);
        const enc = result.diagnostics?.encoderConfig;
        console.log(
          `      Chunk ${chunk.index}/${chunks.length - 1} done in ${(result.elapsedMs / 1000).toFixed(1)}s | ` +
            `${result.diagnostics?.width}x${result.diagnostics?.height} ${result.diagnostics?.frameCount}f | ` +
            `MP4 ${(result.videoBytes / 1048576).toFixed(1)} MB + WAV ${(result.wavBytes / 1048576).toFixed(1)} MB` +
            (enc?.hardwareAcceleration ? ` | enc=${enc.codec}/${enc.hardwareAcceleration}` : ''),
        );
      } catch (err) {
        throw new Error(
          `Chunk ${chunk.index} render failed: ${err?.message || err}` +
            (pageErrors.length ? `\nBrowser errors:\n${pageErrors.join('\n')}` : ''),
        );
      } finally {
        await page.close().catch(() => {});
      }
    }

    await browser.close();
    browser = null;
    await viteServer.close();
    viteServer = null;

    console.log(`[4/4] Stitching chunks seamlessly with FFmpeg (stream-copy video + continuous AAC audio)...`);
    const videoListPath = join(chunksDir, 'video_list.txt');
    const audioListPath = join(chunksDir, 'audio_list.txt');
    const escConcat = (p) => `file '${p.replace(/\\/g, '/').replace(/'/g, "'\\''")}'`;

    const videoLines = chunks.map((c) => escConcat(join(chunksDir, `chunk_${String(c.index).padStart(4, '0')}.mp4`)));
    const audioLines = chunks.map((c) => escConcat(join(chunksDir, `chunk_${String(c.index).padStart(4, '0')}.wav`)));
    writeFileSync(videoListPath, videoLines.join('\n') + '\n', 'utf8');
    writeFileSync(audioListPath, audioLines.join('\n') + '\n', 'utf8');

    mkdirSync(dirname(outPath), { recursive: true });
    const ffArgs = [
      '-y',
      '-v', 'warning',
      '-f', 'concat', '-safe', '0', '-i', videoListPath,
      '-f', 'concat', '-safe', '0', '-i', audioListPath,
      '-map', '0:v:0',
      '-map', '1:a:0',
      '-c:v', 'copy',
      '-c:a', 'aac',
      '-b:a', String(audioBitrate),
      '-ar', '48000',
      '-ac', '2',
      '-movflags', '+faststart',
      outPath,
    ];
    const ffStitch = spawnSync('ffmpeg', ffArgs, { encoding: 'utf8' });
    if (ffStitch.status !== 0) {
      throw new Error(`FFmpeg stitch failed:\n${ffStitch.stderr || ffStitch.stdout}`);
    }

    // Probe final MP4 for physical verification
    const probe = spawnSync(
      'ffprobe',
      [
        '-v', 'error',
        '-show_entries', 'format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels',
        '-of', 'json',
        outPath,
      ],
      { encoding: 'utf8' },
    );
    const probeJson = probe.status === 0 ? JSON.parse(probe.stdout) : {};
    const vStream = (probeJson.streams || []).find((s) => s.codec_type === 'video') || {};
    const aStream = (probeJson.streams || []).find((s) => s.codec_type === 'audio') || {};
    const finalDur = Number(probeJson.format?.duration || 0);
    const finalSize = Number(probeJson.format?.size || statSync(outPath).size);
    const totalSec = (Date.now() - tStart) / 1000;

    const summary = {
      ok: true,
      input: timelinePath,
      output: outPath,
      chunks: chunks.length,
      chunkBoundariesSec: chunks.slice(1).map((c) => Number(c.startSec.toFixed(3))),
      expectedDurationSec: Number((totalFrames / fps).toFixed(3)),
      actualDurationSec: Number(finalDur.toFixed(3)),
      driftSec: Number(Math.abs(finalDur - totalFrames / fps).toFixed(4)),
      expectedFrames: totalFrames,
      actualFrames: Number(vStream.nb_frames || 0),
      width: vStream.width,
      height: vStream.height,
      videoCodec: vStream.codec_name,
      audioCodec: aStream.codec_name,
      audioSampleRate: aStream.sample_rate,
      sizeBytes: finalSize,
      sizeMB: Number((finalSize / 1048576).toFixed(2)),
      elapsedSec: Number(totalSec.toFixed(1)),
      realtimeFactor: Number((finalDur / Math.max(0.1, totalSec)).toFixed(2)),
    };
    console.log('\n=== RENDER_SUMMARY ===');
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (viteServer) await viteServer.close().catch(() => {});
    if (!keepTemp) {
      rmSync(workDir, { recursive: true, force: true });
    } else {
      console.log(`[keep-temp] Temp dir kept at: ${workDir}`);
    }
  }
}

main().catch((err) => {
  console.error('\n[RENDER_FAILED]', err?.stack || err);
  process.exit(1);
});
