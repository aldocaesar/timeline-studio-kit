#!/usr/bin/env python3
"""
youtube_hunter.py — 100% Local Visually-Validated YouTube B-Roll & Scene Clipper (Zero Paid API)
================================================================================================
Implements the exact visual-first workflow:
  1. `search`     — yt-dlp flat-playlist search (parallel across queries, zero video downloads).
  2. `subs`       — download auto/manual subtitles only to find spoken topic timestamps.
  3. `storyboard` — download YouTube sb0/sb1/sb2 thumbnail storyboards (a few KB!) and stitch a
                    timestamped contact sheet so a Vision subagent can scan the entire video fast.
  4. `preview`    — download ONLY a short 360p range and generate timestamped contact sheet or
                    scene-change frames (`gt(scene,0.3)`) before touching high-res media.
  5. `clip`       — surgical high-quality download ONLY for the confirmed range using
                    `--download-sections "*MM:SS-MM:SS" --force-keyframes-at-cuts`, optional
                    FFmpeg edge trim & aspect crop, mandatory `check_final.jpg` (1fps) + `ffprobe`.
  6. `cleanup`    — clean temporary preview/contact-sheet files while preserving final clips.
"""
import argparse
import concurrent.futures
import glob
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import _runtime_env  # noqa: E402

_runtime_env.init()

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ASPECT_DIMS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
}


def _parse_ts(ts: str) -> float:
    ts = ts.strip()
    parts = [float(p) for p in ts.split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60.0 + parts[1]
    return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]


def _fmt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def _ffmpeg_font_path() -> str:
    if os.name == "nt":
        return "C\\:/Windows/Fonts/arial.ttf"
    for cand in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    ):
        if os.path.isfile(cand):
            return cand
    return ""


def _run(cmd: list, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def _search_one(query: str, limit: int, cc_only: bool) -> dict:
    q = f"{query} creative commons" if cc_only and "creative commons" not in query.lower() else query
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--no-warnings",
        "--print",
        "%(id)s\t%(duration_string)s\t%(webpage_url)s\t%(title)s",
        f"ytsearch{limit}:{q}",
    ]
    res = _run(cmd, timeout=45)
    rows = []
    for line in (res.stdout or "").splitlines():
        parts = [p.strip() for p in line.split("\t", 3)]
        if len(parts) == 4:
            rows.append({
                "id": parts[0],
                "duration": parts[1],
                "url": parts[2],
                "title": parts[3],
            })
    return {"query": query, "ok": res.returncode == 0, "count": len(rows), "results": rows, "stderr": res.stderr.strip()[:300]}


def cmd_search(args):
    queries = args.query if isinstance(args.query, list) else [args.query]
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(queries)))) as ex:
        futs = [ex.submit(_search_one, q, args.limit, args.cc) for q in queries]
        for f in futs:
            out.append(f.result())
    print(json.dumps({"ok": True, "searches": out}, ensure_ascii=False, indent=2))


def cmd_subs(args):
    os.makedirs(args.out_dir, exist_ok=True)
    tpl = os.path.join(args.out_dir, "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        args.langs,
        "--convert-subs",
        "srt",
        "-o",
        tpl,
        args.url,
    ]
    res = _run(cmd, timeout=60)
    srts = sorted(glob.glob(os.path.join(args.out_dir, "*.srt")))
    print(json.dumps({"ok": res.returncode == 0 and bool(srts), "srt_files": srts, "stderr": res.stderr.strip()[:300]}, ensure_ascii=False, indent=2))


def _fetch_bytes(url: str, timeout: int = 15) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def cmd_storyboard(args):
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    res = _run(["yt-dlp", "-J", "--no-warnings", args.url], timeout=45)
    if res.returncode != 0 or not res.stdout.strip():
        print(json.dumps({"ok": False, "error": f"yt-dlp -J failed: {res.stderr.strip()[:300]}"}))
        sys.exit(1)
    info = json.loads(res.stdout)
    duration = float(info.get("duration") or 0.0)
    sb_formats = [
        f for f in (info.get("formats") or [])
        if f.get("ext") == "mhtml" and f.get("fragments")
    ]
    if not sb_formats:
        print(json.dumps({"ok": False, "error": "No YouTube storyboard (mhtml) formats available; use `preview` subcommand."}))
        sys.exit(1)
    # Pick highest-resolution storyboard (usually sb0 or largest width*height)
    sb_formats.sort(key=lambda f: (int(f.get("width") or 0) * int(f.get("height") or 0), len(f.get("fragments") or [])), reverse=True)
    chosen = sb_formats[0]
    frags = chosen.get("fragments") or []
    max_sheets = max(1, min(len(frags), args.max_sheets))
    # Sample evenly across the video if there are many sheets
    if len(frags) > max_sheets:
        idxs = [round(i * (len(frags) - 1) / (max_sheets - 1)) for i in range(max_sheets)]
        picked = [(idx, frags[idx]) for idx in sorted(set(idxs))]
    else:
        picked = list(enumerate(frags))

    # Compute start time of each fragment
    cum_t = 0.0
    frag_times = {}
    for idx, fr in enumerate(frags):
        d = float(fr.get("duration") or (duration / max(1, len(frags))))
        frag_times[idx] = (cum_t, cum_t + d)
        cum_t += d

    def _dl(item):
        idx, fr = item
        data = _fetch_bytes(fr.get("url", ""))
        return idx, data

    imgs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for idx, data in ex.map(_dl, picked):
            if not data:
                continue
            try:
                im = Image.open(io.BytesIO(data)).convert("RGB")
                t0, t1 = frag_times[idx]
                imgs.append((idx, t0, t1, im))
            except Exception:
                pass
    imgs.sort(key=lambda x: x[0])
    if not imgs:
        print(json.dumps({"ok": False, "error": "Failed to download storyboard fragment images."}))
        sys.exit(1)

    target_w = min(1400, max(im.width for _, _, _, im in imgs))
    header_h = 34
    blocks = []
    total_h = 44
    for idx, t0, t1, im in imgs:
        scale = target_w / float(im.width)
        nh = int(round(im.height * scale))
        resized = im.resize((target_w, nh), Image.Resampling.LANCZOS)
        blocks.append((idx, t0, t1, resized))
        total_h += header_h + nh + 10

    canvas = Image.new("RGB", (target_w + 20, total_h), (18, 20, 26))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    title = str(info.get("title") or "")[:90]
    draw.text((12, 10), f"YOUTUBE STORYBOARD | {title} | Duration: {_fmt_ts(duration)} | {chosen.get('format_id')}", fill=(240, 244, 250), font=font)
    y = 44
    for idx, t0, t1, im in blocks:
        draw.rectangle([10, y, target_w + 10, y + header_h - 4], fill=(32, 38, 52))
        draw.text((18, y + 6), f"Sheet #{idx+1}/{len(frags)}  •  Range: {_fmt_ts(t0)} -> {_fmt_ts(t1)}  (rows read left-to-right, top-to-bottom)", fill=(125, 226, 255), font=font)
        canvas.paste(im, (10, y + header_h))
        y += header_h + im.height + 10

    canvas.save(args.out, "JPEG", quality=88)
    print(json.dumps({
        "ok": True,
        "storyboard_path": os.path.abspath(args.out),
        "title": info.get("title"),
        "duration_s": round(duration, 2),
        "sheets_rendered": len(blocks),
        "total_sheets": len(frags),
    }, ensure_ascii=False, indent=2))


def cmd_preview(args):
    os.makedirs(args.out_dir, exist_ok=True)
    preview_mp4 = os.path.join(args.out_dir, "preview.mp4")
    if os.path.exists(preview_mp4):
        os.remove(preview_mp4)
    start_s, end_s = [_parse_ts(p) for p in args.range.split("-", 1)]
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--download-sections",
        f"*{args.range}",
        "-f",
        "bv*[height<=360]/b[height<=360]",
        "--merge-output-format",
        "mp4",
        "-o",
        preview_mp4,
        args.url,
    ]
    res = _run(cmd, timeout=90)
    if res.returncode != 0 or not os.path.isfile(preview_mp4):
        print(json.dumps({"ok": False, "error": f"360p preview download failed: {res.stderr.strip()[:300]}"}))
        sys.exit(1)

    font = _ffmpeg_font_path()
    font_opt = f"fontfile='{font}':" if font else ""
    pts_shift = f"setpts=PTS+{start_s}/TB,"
    outputs = []
    if args.mode == "scene":
        pattern = os.path.join(args.out_dir, "cena_%03d.jpg")
        vf = (
            f"select='gt(scene,{args.scene_thresh})',{pts_shift}scale=640:-1,"
            f"drawtext={font_opt}text='%{{pts\\:hms}}':x=10:y=10:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7"
        )
        ff = _run(["ffmpeg", "-v", "error", "-y", "-i", preview_mp4, "-vf", vf, "-vsync", "vfr", "-q:v", "3", pattern], timeout=60)
        outputs = sorted(glob.glob(os.path.join(args.out_dir, "cena_*.jpg")))
        if not outputs:
            # Fallback to interval if no hard cuts found
            args.mode = "interval"
    if args.mode == "interval":
        sheet = os.path.join(args.out_dir, "contact_sheet.jpg")
        step = max(0.5, float(args.step))
        dur = max(1.0, end_s - start_s)
        n_frames = max(1, int(math.ceil(dur / step)))
        cols = 4
        rows = max(1, min(8, int(math.ceil(n_frames / cols))))
        vf = (
            f"fps=1/{step},{pts_shift}scale=480:-1,"
            f"drawtext={font_opt}text='%{{pts\\:hms}}':x=10:y=10:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.75,"
            f"tile={cols}x{rows}:padding=4:margin=4:color=0x16181f"
        )
        ff = _run(["ffmpeg", "-v", "error", "-y", "-i", preview_mp4, "-vf", vf, "-frames:v", "1", "-update", "1", "-q:v", "3", sheet], timeout=60)
        if ff.returncode != 0 or not os.path.isfile(sheet):
            # Fallback without drawtext
            vf2 = f"fps=1/{step},scale=480:-1,tile={cols}x{rows}:padding=4:margin=4:color=0x16181f"
            _run(["ffmpeg", "-v", "error", "-y", "-i", preview_mp4, "-vf", vf2, "-frames:v", "1", "-update", "1", "-q:v", "3", sheet], timeout=60)
        outputs = [sheet] if os.path.isfile(sheet) else []

    print(json.dumps({
        "ok": bool(outputs),
        "preview_mp4": os.path.abspath(preview_mp4),
        "range": args.range,
        "outputs": [os.path.abspath(p) for p in outputs],
    }, ensure_ascii=False, indent=2))


def _ffprobe(path: str) -> dict:
    res = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
        "-show_entries", "format=duration,size",
        "-of", "json", path,
    ], timeout=20)
    if res.returncode != 0:
        return {}
    data = json.loads(res.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    return {
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "video_codec": v.get("codec_name"),
        "fps": v.get("r_frame_rate"),
        "has_audio": a is not None,
        "duration_s": round(float(fmt.get("duration") or 0.0), 3),
        "size_bytes": int(fmt.get("size") or 0),
    }


def cmd_clip(args):
    out_abs = os.path.abspath(args.out)
    out_dir = os.path.dirname(out_abs)
    os.makedirs(out_dir, exist_ok=True)
    raw_mp4 = os.path.join(out_dir, f"_raw_{os.path.basename(out_abs)}")
    if os.path.exists(raw_mp4):
        os.remove(raw_mp4)

    fmt_sel = (
        f"bv*[height<={args.max_height}]+ba/b[height<={args.max_height}]/bv*+ba/b"
        if args.keep_audio
        else f"bv*[height<={args.max_height}]/b[height<={args.max_height}]/bv*/b"
    )
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--download-sections",
        f"*{args.range}",
        "--force-keyframes-at-cuts",
        "-f",
        fmt_sel,
        "--merge-output-format",
        "mp4",
        "-o",
        raw_mp4,
        args.url,
    ]
    res = _run(cmd, timeout=180)
    if res.returncode != 0 or not os.path.isfile(raw_mp4) or os.path.getsize(raw_mp4) == 0:
        print(json.dumps({"ok": False, "error": f"yt-dlp clip download failed: {res.stderr.strip()[:400]}"}))
        sys.exit(1)

    # Fine edge trim + normalize to crisp 30fps H.264 yuv420p (and optional crop)
    ff_cmd = ["ffmpeg", "-v", "error", "-y"]
    if args.trim_start > 0:
        ff_cmd += ["-ss", str(args.trim_start)]
    ff_cmd += ["-i", raw_mp4]
    if args.duration > 0:
        ff_cmd += ["-t", str(args.duration)]

    vf_parts = []
    if args.aspect and args.aspect in ASPECT_DIMS:
        tw, th = ASPECT_DIMS[args.aspect]
        vf_parts.append(f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}")
    vf_parts.append("fps=30,format=yuv420p")
    ff_cmd += ["-vf", ",".join(vf_parts)]
    if args.keep_audio:
        ff_cmd += ["-c:a", "aac", "-ar", "48000", "-b:a", "192k"]
    else:
        ff_cmd += ["-an"]
    ff_cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-movflags", "+faststart", out_abs]

    ff = _run(ff_cmd, timeout=120)
    try:
        os.remove(raw_mp4)
    except OSError:
        pass
    if ff.returncode != 0 or not os.path.isfile(out_abs) or os.path.getsize(out_abs) == 0:
        print(json.dumps({"ok": False, "error": f"ffmpeg finalize failed: {ff.stderr.strip()[:300]}"}))
        sys.exit(1)

    probe = _ffprobe(out_abs)
    check_path = os.path.abspath(args.check_out) if args.check_out else os.path.splitext(out_abs)[0] + "_check_final.jpg"
    dur = max(1.0, float(probe.get("duration_s") or 4.0))
    cols = 4
    rows = max(1, min(4, int(math.ceil(dur / cols))))
    _run([
        "ffmpeg", "-v", "error", "-y", "-i", out_abs,
        "-vf", f"fps=1,scale=480:-1,tile={cols}x{rows}:padding=4:margin=4:color=0x16181f",
        "-frames:v", "1", "-update", "1", "-q:v", "3", check_path,
    ], timeout=45)

    print(json.dumps({
        "ok": True,
        "clip_path": out_abs,
        "check_final_jpg": check_path if os.path.isfile(check_path) else "",
        "range": args.range,
        "probe": probe,
    }, ensure_ascii=False, indent=2))


def cmd_cleanup(args):
    removed = []
    patterns = ["preview*.mp4", "*contact_sheet*.jpg", "*storyboard*.jpg", "*_check_final.jpg", "cena_*.jpg", "_raw_*.mp4"]
    for pat in patterns:
        for p in glob.glob(os.path.join(args.dir, pat)):
            try:
                os.remove(p)
                removed.append(os.path.basename(p))
            except OSError:
                pass
    print(json.dumps({"ok": True, "removed_count": len(removed), "removed": removed}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="100% local visual-first YouTube B-roll clipper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("search")
    p_s.add_argument("--query", action="append", required=True)
    p_s.add_argument("--limit", type=int, default=8)
    p_s.add_argument("--cc", action="store_true")
    p_s.set_defaults(func=cmd_search)

    p_sub = sub.add_parser("subs")
    p_sub.add_argument("--url", required=True)
    p_sub.add_argument("--out-dir", required=True)
    p_sub.add_argument("--langs", default="pt,en")
    p_sub.set_defaults(func=cmd_subs)

    p_sb = sub.add_parser("storyboard")
    p_sb.add_argument("--url", required=True)
    p_sb.add_argument("--out", required=True)
    p_sb.add_argument("--max-sheets", type=int, default=4)
    p_sb.set_defaults(func=cmd_storyboard)

    p_pv = sub.add_parser("preview")
    p_pv.add_argument("--url", required=True)
    p_pv.add_argument("--range", required=True, help="MM:SS-MM:SS")
    p_pv.add_argument("--out-dir", required=True)
    p_pv.add_argument("--mode", choices=["interval", "scene"], default="interval")
    p_pv.add_argument("--step", type=float, default=2.0)
    p_pv.add_argument("--scene-thresh", type=float, default=0.3)
    p_pv.set_defaults(func=cmd_preview)

    p_cl = sub.add_parser("clip")
    p_cl.add_argument("--url", required=True)
    p_cl.add_argument("--range", required=True, help="MM:SS-MM:SS")
    p_cl.add_argument("--out", required=True)
    p_cl.add_argument("--trim-start", type=float, default=0.0)
    p_cl.add_argument("--duration", type=float, default=0.0)
    p_cl.add_argument("--aspect", choices=["16:9", "9:16", "4:5", "1:1", "keep"], default="16:9")
    p_cl.add_argument("--max-height", type=int, default=1080)
    p_cl.add_argument("--keep-audio", action="store_true")
    p_cl.add_argument("--check-out", default="")
    p_cl.set_defaults(func=cmd_clip)

    p_cu = sub.add_parser("cleanup")
    p_cu.add_argument("--dir", required=True)
    p_cu.set_defaults(func=cmd_cleanup)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
