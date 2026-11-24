#!/usr/bin/env node
/**
 * preview_motion.mjs — Fast Preview Loop (~2s timestamped contact sheet before any full render!)
 * Usage: node preview_motion.mjs --html motion/S01_hook.html --duration 4.5 --out previews/S01_sheet.jpg [--fps 8 --scale 0.25 --cols 6 --width 1920 --height 1080]
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveRuntime } from './_runtime_paths.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
resolveRuntime(SCRIPT_DIR);
const argv = process.argv.slice(2);
const opt = (k, d) => { const i = argv.indexOf('--' + k); return i >= 0 ? argv[i + 1] : d; };

const htmlPath = opt('html', '');
const duration = parseFloat(opt('duration', '4.5'));
const from = parseFloat(opt('from', '0'));
const to = parseFloat(opt('to', String(from + duration)));
const fps = parseFloat(opt('fps', '8'));
const scale = parseFloat(opt('scale', '0.25'));
const cols = parseInt(opt('cols', '6'), 10);
const width = opt('width', '1920');
const height = opt('height', '1080');
const outSheet = resolve(opt('out', 'preview_sheet.jpg'));
if (!htmlPath || !(to > from)) {
  console.error('Usage: node preview_motion.mjs --html <file.html> --duration <sec> --out <sheet.jpg>');
  process.exit(2);
}

const framesDir = resolve(dirname(outSheet), `_tmp_frames_${Date.now()}`);
mkdirSync(framesDir, { recursive: true });
mkdirSync(dirname(outSheet), { recursive: true });

const t0 = Date.now();
const r1 = spawnSync('node', [
  join(SCRIPT_DIR, 'motion_runner.mjs'),
  '--html', resolve(htmlPath),
  '--from', String(from),
  '--to', String(to),
  '--fps', String(fps),
  '--scale', String(scale),
  '--width', String(width),
  '--height', String(height),
  '--out', framesDir,
  '--jpg',
], { stdio: 'inherit' });

if (r1.status !== 0) {
  rmSync(framesDir, { recursive: true, force: true });
  process.exit(r1.status || 1);
}

const n = readdirSync(framesDir).filter(f => /^\d{5}\.jpg$/.test(f)).length;
const rows = Math.max(1, Math.ceil(n / cols));
const font = process.platform === 'win32'
  ? "C\\:/Windows/Fonts/arial.ttf"
  : ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/System/Library/Fonts/Helvetica.ttc'].find(existsSync);
const label = font
  ? `setpts=PTS+${from}/TB,drawtext=fontfile='${font}':text='%{pts\\:hms}':x=6:y=h-th-6:fontsize=16:fontcolor=white:box=1:boxcolor=black@0.7:boxborderw=4,`
  : '';
const tile = `tile=${cols}x${rows}:padding=4:margin=4:color=0x181a20`;

let r2 = spawnSync('ffmpeg', [
  '-v', 'error', '-y', '-framerate', String(fps), '-i', join(framesDir, '%05d.jpg'),
  '-vf', label + tile, '-frames:v', '1', '-update', '1', '-q:v', '3', outSheet,
], { stdio: 'pipe' });
if (r2.status !== 0) {
  r2 = spawnSync('ffmpeg', [
    '-v', 'error', '-y', '-framerate', String(fps), '-i', join(framesDir, '%05d.jpg'),
    '-vf', tile, '-frames:v', '1', '-update', '1', '-q:v', '3', outSheet,
  ], { stdio: 'inherit' });
}
rmSync(framesDir, { recursive: true, force: true });
if (r2.status !== 0 || !existsSync(outSheet)) {
  console.error('Failed to build preview contact sheet');
  process.exit(1);
}
console.log(JSON.stringify({
  ok: true,
  sheet: outSheet,
  frames: n,
  grid: `${cols}x${rows}`,
  elapsed_s: Number(((Date.now() - t0) / 1000).toFixed(2)),
}));
