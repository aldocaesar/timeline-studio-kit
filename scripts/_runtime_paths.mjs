#!/usr/bin/env node
/**
 * _runtime_paths.mjs (v4.1 Portable) — Dynamic Cross-Platform Runtime Resolver
 * Zero hardcoded usernames or agent IDs. Works across Windows, macOS, and Linux.
 */
import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

export function detectAgentWorkspace(scriptDir) {
  const envWs = (process.env.TIMELINE_WORKSPACE || '').trim();
  if (envWs && existsSync(envWs)) return resolve(envWs);
  let cur = resolve(scriptDir);
  for (let i = 0; i < 8; i++) {
    const b = basename(cur).toLowerCase();
    if (b === '.agents' || b === '.claude' || b === '.runtime') {
      const parent = dirname(cur);
      if (existsSync(parent)) return parent;
    }
    const nxt = dirname(cur);
    if (nxt === cur) break;
    cur = nxt;
  }
  return resolve(process.cwd());
}

export function detectTimelineStudioDir(workspace, scriptDir) {
  const home = homedir();
  const candidates = [
    (process.env.TIMELINE_STUDIO_DIR || '').trim(),
    join(workspace, '.runtime', 'timeline-studio'),
    join(home, 'OpenBot', 'Shared', 'timeline-studio'),
    join(dirname(scriptDir), 'timeline-studio'),
    join(home, '.timeline-studio-kit', 'timeline-studio'),
  ];
  for (const c of candidates) {
    if (c && existsSync(join(c, 'scripts', 'timeline-command.mjs'))) return resolve(c);
  }
  return join(workspace, '.runtime', 'timeline-studio');
}

export function detectMotionRuntimeDir(workspace, scriptDir) {
  const home = homedir();
  const candidates = [
    (process.env.MOTION_RUNTIME_DIR || '').trim(),
    (process.env.MOTION_LAB_RUNTIME_DIR || '').trim(),
    join(workspace, '.runtime'),
    join(workspace, '.runtime', 'motion-runtime'),
    join(home, 'OpenBot', 'Shared', 'motion-video-lab', 'runtime'),
    join(dirname(scriptDir), 'motion-runtime'),
    join(home, '.timeline-studio-kit', 'motion-runtime'),
  ];
  for (const c of candidates) {
    if (c && existsSync(join(c, 'node_modules', 'playwright'))) return resolve(c);
  }
  return join(workspace, '.runtime');
}

export function detectSfxDir(scriptDir) {
  const candidates = [
    join(dirname(scriptDir), 'assets', 'sfx'),
    join(scriptDir, 'sfx'),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return resolve(c);
  }
  return join(dirname(scriptDir), 'assets', 'sfx');
}

export function augmentEnvPath(workspace) {
  const sep = process.platform === 'win32' ? ';' : ':';
  const extras = [];
  const venvBin = join(workspace, '.runtime', '.venv', process.platform === 'win32' ? 'Scripts' : 'bin');
  if (existsSync(venvBin)) extras.push(venvBin);

  if (process.platform === 'win32') {
    const localApp = process.env.LOCALAPPDATA || '';
    const progFiles = process.env.ProgramFiles || 'C:\\Program Files';
    if (localApp) {
      extras.push(join(localApp, 'Microsoft', 'WinGet', 'Links'));
      const pkgRoot = join(localApp, 'Microsoft', 'WinGet', 'Packages');
      if (existsSync(pkgRoot)) {
        try {
          for (const d of readdirSync(pkgRoot)) {
            if (/ffmpeg|nodejs|git\.git/i.test(d)) {
              const p1 = join(pkgRoot, d);
              extras.push(p1);
              try {
                for (const sub of readdirSync(p1)) {
                  const binD = join(p1, sub, 'bin');
                  if (existsSync(binD)) extras.push(binD);
                }
              } catch {}
            }
          }
        } catch {}
      }
    }
    extras.push('C:\\ffmpeg\\bin', join(progFiles, 'nodejs'), join(progFiles, 'Git', 'cmd'));
  } else {
    const home = homedir();
    extras.push('/opt/homebrew/bin', '/usr/local/bin', join(home, '.local', 'bin'));
  }

  const cur = process.env.PATH || '';
  const curLower = new Set(cur.split(sep).map(s => s.toLowerCase()));
  const add = extras.filter(d => d && existsSync(d) && !curLower.has(d.toLowerCase()));
  if (add.length) process.env.PATH = add.join(sep) + (cur ? sep + cur : '');
}

export function findPythonBin(workspace) {
  const envPy = (process.env.TIMELINE_PYTHON || '').trim();
  if (envPy && existsSync(envPy)) return envPy;
  const venvPy = join(
    workspace,
    '.runtime',
    '.venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python',
  );
  if (existsSync(venvPy)) return venvPy;
  for (const cmd of process.platform === 'win32' ? ['python', 'python3'] : ['python3', 'python']) {
    const r = spawnSync(cmd, ['--version'], { stdio: 'ignore' });
    if (r.status === 0) return cmd;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

export function findChromeExecutable() {
  const envChrome = (process.env.CHROME_PATH || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '').trim();
  if (envChrome && existsSync(envChrome)) return envChrome;

  let candidates = [];
  if (process.platform === 'win32') {
    const pf = process.env.ProgramFiles || 'C:\\Program Files';
    const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
    const la = process.env.LOCALAPPDATA || '';
    candidates = [
      join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      la ? join(la, 'Google', 'Chrome', 'Application', 'chrome.exe') : '',
      join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
      join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    ];
  } else if (process.platform === 'darwin') {
    candidates = [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ];
  } else {
    candidates = [
      '/usr/bin/google-chrome',
      '/usr/bin/google-chrome-stable',
      '/usr/bin/chromium',
      '/usr/bin/chromium-browser',
      '/usr/bin/microsoft-edge',
    ];
  }
  return candidates.find(p => p && existsSync(p)) || '';
}

export function resolveRuntime(scriptDir) {
  const workspace = detectAgentWorkspace(scriptDir);
  augmentEnvPath(workspace);
  const tsDir = detectTimelineStudioDir(workspace, scriptDir);
  const motionRuntimeDir = detectMotionRuntimeDir(workspace, scriptDir);
  const sfxDir = detectSfxDir(scriptDir);
  const pythonBin = findPythonBin(workspace);
  return {
    workspace,
    tsDir,
    tsCli: join(tsDir, 'scripts', 'timeline-command.mjs'),
    tsSfxDir: join(tsDir, 'public', 'assets', 'sound-effects'),
    motionRuntimeDir,
    motionRuntimePkg: join(motionRuntimeDir, 'package.json'),
    motionRuntimeNm: join(motionRuntimeDir, 'node_modules'),
    sfxDir,
    pythonBin,
  };
}
