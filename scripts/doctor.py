#!/usr/bin/env python3
"""
doctor.py (v4.1 Portable) — Cross-Platform Environment Diagnostic for Timeline Studio Kit
Verifies Node, Python, FFmpeg/ffprobe, yt-dlp, Python packages (faster-whisper, Pillow,
requests), Timeline Studio CLI + fflate, Motion Runtime (Playwright, GSAP, Three.js, p5,
p5.brush, world-atlas, d3-geo, topojson-client, maplibre-gl), headless Chromium/Chrome,
CC0 SFX pack, and optional API keys (never prints secret values!).
"""
import json
import os
import platform
import subprocess
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import _runtime_env  # noqa: E402

_runtime_env.init()


def _ver(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        out = (r.stdout or r.stderr or "").strip().splitlines()
        return (r.returncode == 0), (out[0][:90] if out else "")
    except Exception as e:
        return False, str(e)[:90]


def _find_headless_browser(motion_runtime_dir: str) -> str:
    env_p = (os.environ.get("CHROME_PATH") or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or "").strip()
    if env_p and os.path.isfile(env_p):
        return env_p
    cands = []
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        la = os.environ.get("LOCALAPPDATA", "")
        cands = [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(la, "Google", "Chrome", "Application", "chrome.exe") if la else "",
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
    elif sys.platform == "darwin":
        cands = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        cands = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge",
        ]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    # Fallback: check Playwright bundled Chromium executable
    pw_pkg = os.path.join(motion_runtime_dir, "package.json")
    if os.path.isfile(pw_pkg):
        try:
            code = (
                "import { createRequire } from 'node:module';"
                f"const r = createRequire({json.dumps(pw_pkg)});"
                "const p = r('playwright').chromium.executablePath();"
                "console.log(p || '');"
            )
            res = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=10)
            exe = (res.stdout or "").strip().splitlines()
            if exe and os.path.isfile(exe[-1]):
                return exe[-1]
        except Exception:
            pass
    return ""


def main():
    checks = []
    for name, cmd in (
        ("node", ["node", "-v"]),
        ("ffmpeg", ["ffmpeg", "-version"]),
        ("ffprobe", ["ffprobe", "-version"]),
        ("yt-dlp", ["yt-dlp", "--version"]),
    ):
        ok, info = _ver(cmd)
        checks.append({"item": name, "ok": ok, "detail": info})

    for mod in ("PIL", "requests", "faster_whisper"):
        try:
            __import__(mod)
            checks.append({"item": f"python:{mod}", "ok": True, "detail": "importable"})
        except Exception as e:
            checks.append({"item": f"python:{mod}", "ok": False, "detail": str(e)[:80]})

    ts_dir = _runtime_env.TIMELINE_STUDIO_DIR
    mvl_dir = _runtime_env.MOTION_LAB_RUNTIME_DIR
    ts_cli = os.path.join(ts_dir, "scripts", "timeline-command.mjs")
    fflate_ok = any(
        os.path.isdir(p)
        for p in (
            os.path.join(ts_dir, "node_modules", "fflate"),
            os.path.join(os.path.dirname(ts_dir), "node_modules", "fflate"),
            os.path.join(mvl_dir, "node_modules", "fflate"),
        )
    )
    checks.append({
        "item": "timeline-studio-cli",
        "ok": os.path.isfile(ts_cli) and fflate_ok,
        "detail": ts_cli if (os.path.isfile(ts_cli) and fflate_ok) else f"missing cli/fflate in {ts_dir}",
    })

    req_pkgs = ("playwright", "gsap", "three", "p5", "p5.brush", "world-atlas", "d3-geo", "topojson-client", "maplibre-gl")
    missing_pkgs = [p for p in req_pkgs if not os.path.isdir(os.path.join(mvl_dir, "node_modules", p))]
    checks.append({
        "item": "motion-runtime",
        "ok": len(missing_pkgs) == 0,
        "detail": mvl_dir if not missing_pkgs else f"missing: {', '.join(missing_pkgs)}",
    })

    render_pkgs = (
        "vite",
        "mediabunny",
        os.path.join("@mediabunny", "aac-encoder"),
        os.path.join("@ffmpeg", "ffmpeg"),
        os.path.join("@ffmpeg", "core"),
        os.path.join("@ffmpeg", "util"),
        os.path.join("@phosphor-icons", "react"),
    )
    render_roots = (
        os.path.join(ts_dir, "node_modules"),
        os.path.join(os.path.dirname(ts_dir), "node_modules"),
        os.path.join(mvl_dir, "node_modules"),
    )
    missing_render = [
        p for p in render_pkgs
        if not any(os.path.isdir(os.path.join(r, p)) for r in render_roots)
    ]
    render_script_ok = os.path.isfile(os.path.join(SCRIPT_DIR, "render_timeline_local.mjs"))
    missing_render_items = (["render_timeline_local.mjs"] if not render_script_ok else []) + missing_render
    checks.append({
        "item": "local-render-runtime",
        "ok": len(missing_render_items) == 0,
        "detail": "ready (vite + mediabunny)" if not missing_render_items else f"missing: {', '.join(missing_render_items)}",
    })

    chrome = _find_headless_browser(mvl_dir)
    checks.append({"item": "headless-browser", "ok": bool(chrome), "detail": chrome or "missing (run installer)"})

    sfx_dir = _runtime_env.KIT_SFX_DIR
    sfx_count = len([f for f in os.listdir(sfx_dir) if f.lower().endswith((".mp3", ".wav"))]) if os.path.isdir(sfx_dir) else 0
    checks.append({"item": "sfx-pack", "ok": sfx_count >= 5, "detail": f"{sfx_count} files in {sfx_dir}"})

    keys_status = {k: ("SET" if os.environ.get(k) else "EMPTY") for k in ("PIXABAY_API_KEY", "GROQ_API_KEY", "FREESOUND_API_KEY")}
    pixabay_pref = "default"
    mem_file = os.path.join(_runtime_env.AGENT_WORKSPACE, ".timeline-creator-memory.json")
    if os.path.isfile(mem_file):
        try:
            mem_data = json.load(open(mem_file, "r", encoding="utf-8"))
            pixabay_pref = str((mem_data.get("profile") or {}).get("pixabay_preference") or "default")
        except Exception:
            pass
    all_ok = all(c["ok"] for c in checks)
    print(json.dumps({
        "status": "READY" if all_ok else "MISSING_DEPS",
        "platform": f"{platform.system()} {platform.release()}",
        "workspace": _runtime_env.AGENT_WORKSPACE,
        "kit_dir": SCRIPT_DIR,
        "timeline_studio_dir": ts_dir,
        "motion_runtime_dir": mvl_dir,
        "checks": checks,
        "optional_keys": keys_status,
        "pixabay_preference": pixabay_pref,
    }, ensure_ascii=False, indent=2))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
