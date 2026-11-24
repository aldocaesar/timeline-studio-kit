#!/usr/bin/env node
/**
 * motion_runner.mjs — Deterministic Chrome Headless D3D11 Motion & Transparent Overlay Renderer
 * Bridges `mattypark/Motion-graphics-skill` (GSAP / Three.js / Canvas / SVG / p5.brush) directly
 * into Timeline Studio, with automatic EDGE_ALPHA_CLIP validation on transparent PNG overlays!
 *
 * Usage:
 *   MP4 clip:     node motion_runner.mjs --html motion/S01_hook.html --mp4 motion/S01_hook.mp4 --duration 4.5 --fps 30 --width 1920 --height 1080
 *   Frames (jpg): node motion_runner.mjs --html motion/S01_hook.html --from 0 --to 4.5 --fps 8 --scale 0.25 --out cache/preview --jpg --width 1920 --height 1080
 *   PNG overlay:  node motion_runner.mjs --html overlays/badge.html --png overlays/badge.png --time 1.0 --width 1200 --height 400 --transparent
 */
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, normalize, relative, resolve } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

import { findChromeExecutable, resolveRuntime } from './_runtime_paths.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const RT = resolveRuntime(SCRIPT_DIR);
const LAB_RUNTIME_PKG = RT.motionRuntimePkg;
const LAB_RUNTIME_NM = RT.motionRuntimeNm;
const PYTHON_BIN = RT.pythonBin;
const reqRuntime = createRequire(existsSync(LAB_RUNTIME_PKG) ? LAB_RUNTIME_PKG : import.meta.url);
const { chromium } = reqRuntime('playwright');

const argv = process.argv.slice(2);
const has = k => argv.includes('--' + k);
const opt = (k, d) => { const i = argv.indexOf('--' + k); return i >= 0 ? argv[i + 1] : d; };

const htmlArg = opt('html', '');
if (!htmlArg) {
  console.error('Missing --html <path>');
  process.exit(2);
}
const htmlAbs = resolve(htmlArg);
if (!existsSync(htmlAbs)) {
  console.error(`HTML not found: ${htmlAbs}`);
  process.exit(2);
}
const rootDir = resolve(opt('root', dirname(dirname(htmlAbs))));
const relEntry = relative(rootDir, htmlAbs).replace(/\\/g, '/');

const duration = parseFloat(opt('duration', '5'));
const fromSec = parseFloat(opt('from', '0'));
const toSec = parseFloat(opt('to', String(fromSec + duration)));
const fps = parseFloat(opt('fps', '30'));
const scale = parseFloat(opt('scale', '1'));
const width = parseInt(opt('width', '1920'), 10);
const height = parseInt(opt('height', '1080'), 10);
const outDir = opt('out', '');
const mp4Path = opt('mp4', '');
const pngPath = opt('png', '');
const audioPath = opt('audio', '');
const transparent = has('transparent') || Boolean(pngPath);
const useJpg = (has('jpg') || Boolean(mp4Path)) && !transparent;
const pngTime = parseFloat(opt('time', '1.0'));

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
  '.otf': 'font/otf',
};

function startServer(baseDir) {
  return new Promise(resPromise => {
    const srv = createServer((req, res) => {
      const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
      let filePath;
      if (urlPath.startsWith('/__runtime/')) {
        const rel = normalize(urlPath.slice('/__runtime/'.length)).replace(/^(\.\.(\/|\\|$))+/, '');
        filePath = resolve(LAB_RUNTIME_NM, rel);
      } else if (urlPath.startsWith('/__kit/')) {
        const rel = normalize(urlPath.slice('/__kit/'.length)).replace(/^(\.\.(\/|\\|$))+/, '');
        filePath = resolve(SCRIPT_DIR, rel);
      } else {
        const rel = urlPath === '/' ? relEntry : normalize(urlPath.slice(1)).replace(/^(\.\.(\/|\\|$))+/, '');
        filePath = resolve(baseDir, rel);
      }
      if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
        res.writeHead(404);
        res.end('Not found');
        return;
      }
      const st = statSync(filePath);
      const mime = MIME[extname(filePath).toLowerCase()] || 'application/octet-stream';
      const range = req.headers.range;
      if (range) {
        const m = /bytes=(\d*)-(\d*)/.exec(range);
        const start = m && m[1] ? parseInt(m[1], 10) : 0;
        const end = m && m[2] ? parseInt(m[2], 10) : st.size - 1;
        res.writeHead(206, {
          'Content-Range': `bytes ${start}-${end}/${st.size}`,
          'Accept-Ranges': 'bytes',
          'Content-Length': end - start + 1,
          'Content-Type': mime,
        });
        createReadStream(filePath, { start, end }).pipe(res);
      } else {
        res.writeHead(200, { 'Content-Length': st.size, 'Accept-Ranges': 'bytes', 'Content-Type': mime });
        createReadStream(filePath).pipe(res);
      }
    });
    srv.listen(0, '127.0.0.1', () => resPromise(srv));
  });
}

async function main() {
  const srv = await startServer(rootDir);
  const port = srv.address().port;
  if (outDir) mkdirSync(outDir, { recursive: true });
  if (mp4Path) mkdirSync(dirname(resolve(mp4Path)), { recursive: true });
  if (pngPath) mkdirSync(dirname(resolve(pngPath)), { recursive: true });

  const executablePath = findChromeExecutable();
  const launchArgs = process.platform === 'win32'
    ? ['--use-angle=d3d11', '--enable-webgl', '--ignore-gpu-blocklist']
    : ['--enable-webgl', '--ignore-gpu-blocklist'];
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
    args: launchArgs,
  });

  let ff = null;
  if (mp4Path) {
    const ffArgs = ['-v', 'error', '-y', '-f', 'image2pipe', '-vcodec', useJpg ? 'mjpeg' : 'png', '-r', String(fps), '-i', '-'];
    if (audioPath && existsSync(audioPath)) ffArgs.push('-ss', String(fromSec), '-t', String(toSec - fromSec), '-i', audioPath);
    ffArgs.push('-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart');
    if (audioPath && existsSync(audioPath)) ffArgs.push('-c:a', 'aac', '-ar', '48000', '-b:a', '192k', '-shortest');
    else ffArgs.push('-an');
    ffArgs.push(resolve(mp4Path));
    ff = spawn('ffmpeg', ffArgs, { stdio: ['pipe', 'inherit', 'inherit'] });
  }

  try {
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale });
    const page = await ctx.newPage();
    page.on('pageerror', err => console.error('[pageerror]', err.message));
    await page.goto(`http://127.0.0.1:${port}/${relEntry}?w=${width}&h=${height}`, { waitUntil: 'networkidle' });
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      if (window.__sceneReady) await window.__sceneReady;
    });

    if (pngPath) {
      await page.evaluate(async ({ t, f }) => {
        if (typeof window.drawFrame === 'function') await window.drawFrame(t);
        else if (typeof window.__setFrame === 'function') await window.__setFrame(Math.round(t * f), f);
      }, { t: pngTime, f: fps });
      const buf = await page.screenshot({ type: 'png', omitBackground: transparent });
      const absPng = resolve(pngPath);
      writeFileSync(absPng, buf);
      // Automatic Anti-Shadow-Clip Gate (EDGE_ALPHA_CLIP)
      if (transparent) {
        const auditScript = join(SCRIPT_DIR, 'audit_visuals.py');
        const check = spawnSync(PYTHON_BIN, ['-B', auditScript, '--overlay', absPng], { encoding: 'utf8' });
        if (check.status !== 0) {
          console.error(`[EDGE_ALPHA_CLIP FAIL] ${absPng}\n${check.stdout}\n${check.stderr}`);
          process.exitCode = 1;
        } else {
          console.log(JSON.stringify({ ok: true, png: absPng, width, height, edge_alpha_clip: 'PASS' }));
        }
      }
      return;
    }

    const totalFrames = Math.max(1, Math.round((toSec - fromSec) * fps));
    for (let i = 0; i < totalFrames; i++) {
      const t = fromSec + i / fps;
      await page.evaluate(async ({ curT, idx, f }) => {
        if (typeof window.drawFrame === 'function') await window.drawFrame(curT);
        else if (typeof window.__setFrame === 'function') await window.__setFrame(idx, f);
      }, { curT: t, idx: Math.round(t * fps), f: fps });
      const buf = await page.screenshot({
        type: useJpg ? 'jpeg' : 'png',
        quality: useJpg ? (mp4Path ? 95 : 85) : undefined,
        omitBackground: transparent,
      });
      if (outDir) {
        writeFileSync(join(outDir, `${String(i).padStart(5, '0')}.${useJpg ? 'jpg' : 'png'}`), buf);
      }
      if (ff) {
        if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      }
    }
  } finally {
    await browser.close();
    srv.close();
  }

  if (ff) {
    ff.stdin.end();
    const code = await new Promise(r => ff.on('close', r));
    if (code !== 0) process.exit(code || 1);
    console.log(JSON.stringify({ ok: true, mp4: resolve(mp4Path), duration_s: Number((toSec - fromSec).toFixed(2)), fps, width, height }));
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
