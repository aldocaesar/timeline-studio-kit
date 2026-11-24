#!/usr/bin/env python3
"""
audit_visuals.py (v4.0) — Deterministic Sync, Cartography, Anti-Duplicate, Anti-Clone, Anti-Warm-Bias & Human-First QA Gate
============================================================================================================================
Hard-fails / audits any edit_plan.json / motion HTML / transparent overlay that violates craft standards:
  1. AUDIO_SYNC_LOCK:
     - Loads word-level timestamps from `words.json` (or `subtitles.srt`).
     - Enforces zero cumulative drift (`|cursor - v.start| <= 0.25s`) when `start`/`end` are provided.
     - Verifies every scene's `anchor_phrase` actually occurs in the spoken audio inside `[start-0.8s .. end+1.0s]`.
     - Verifies every Motion Graphics clip (`cue_words` or extracted terms from `name`) matches what is spoken inside
       `[start-0.8s .. end+1.2s]` (only `S01` with `"is_hook_tease": true` may tease later facts).
  2. NO_HAND_DRAWN_MAP:
     - Hard-fails any map/geography motion HTML that hand-draws filled SVG landmass polygons instead of real cartography.
  3. EDGE_ALPHA_CLIP:
     - Scans the 2px outer border of every transparent overlay PNG; HARD FAILS if any edge pixel has alpha > 2.
  4. NO_DUPLICATE_MEDIA:
     - Hard-fails reused photos, near-duplicate photos (dHash Hamming <= 8), or reused/overlapping video clips.
  5. NO_LAZY_CAM_ZOOM (Motion Graphics ONLY — static photos ARE allowed native zoom-in/zoom-out/pan keyframes!):
     - Hard-fails continuous whole-canvas zoom-in inside motion HTML or zoom animation on motion clips.
  6. MOTION_10_15_RESTRAINT & BANNED_ARTIFACT_EFFECT:
     - Default target 10-15% informational motion (hard cap 20% in docs/general), blocks `grain`/`halo` artifacts.
  7. NEW v4.0 — ANTI-WARM-SEPIA TRAP, CLONED PORTRAIT TEMPLATE, HUMAN-OVER-BUILDING & TRANSITION/PHOTO-MOTION CHECKS:
     - Flags `COLOR_GRADE_SEPIA_TRAP` if explicit `colorGrade` sets wheel saturation > 0 with negative temperature
       (which triggers accidental `sepia()` / warm shift in Timeline Studio `colorGrade.js`) or if > 40% of graded clips lean warm.
     - Hard-fails `CLONED_PORTRAIT_TEMPLATE` when >= 4 staged/framed photos share the exact same top-bar/border pixel frame.
     - Flags `HUMAN_ACTION_BUILDING_MISMATCH` when `anchor_phrase` describes people/clothing/crowds/ministers/tears/strikes
       but the visual is an empty building/parliament/courthouse/skyline exterior (hard-fail with `--strict-human`).
     - Verifies transitions and organic static-photo motion (`keyframes` / `autoPhotoMotion`) are not disabled flat in docs.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import _runtime_env  # noqa: E402

_runtime_env.init()

from PIL import Image  # noqa: E402

BANNED_CANNED_PATTERNS = (
    "renderUIFeed3D",
    "renderDossierDesk",
    "renderOdometerCounter",
    "renderVersusSplit",
    "renderWaffleScale",
    "renderCameraJourney",
    "renderNetworkGraph",
    "renderDataCurve",
    "renderKineticManifesto",
    "MotionKit.PALETTES",
    "legacy-hud-card",
    "rostrumTransform",
)

LAZY_CAM_ZOOM_PATTERNS = (
    re.compile(
        r"""\.(?:to|fromTo)\(\s*['"]#?(?:cam|camera|stage|viewport|scene|world|canvas-wrap|root)['"]\s*,\s*(?:\{[^}]*\}\s*,\s*)?\{[^}]*\bscale\s*:\s*1\.\d+""",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"""(?:cam|camera|stage|viewport)\.style\.transform\s*=\s*[^;\n]*scale\s*\(\s*\$\{?\s*1\s*\+""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""@keyframes[^{]*\{[^}]*scale\s*\(\s*1\.0\d""",
        re.IGNORECASE | re.DOTALL,
    ),
)

REAL_CARTOGRAPHY_MARKERS = (
    "world-atlas",
    "d3-geo",
    "topojson",
    "maplibre",
    "map_kit.mjs",
    "countries-10m",
    "countries-50m",
    "countries-110m",
    "land-50m",
    "geojson",
)

PT_EN_STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
    "um", "uma", "uns", "umas", "para", "por", "com", "sem", "que", "se", "ao", "aos",
    "as", "os", "mais", "mas", "como", "sua", "seu", "suas", "seus", "ele", "ela",
    "eles", "elas", "foi", "era", "ser", "tem", "ate", "entre", "sobre", "tudo", "todo",
    "toda", "todos", "todas", "isso", "este", "esta", "esse", "essa", "aquele", "aquela",
    "the", "and", "for", "with", "from", "into", "over", "under", "that", "this", "motion",
    "hook", "pico", "real", "video", "photo", "pixabay", "youtube", "visual", "cena", "3d",
    "2d", "hd", "yt", "em", "depois", "antes", "hoje", "agora", "aqui", "ali",
}

HUMAN_ACTION_KEYWORDS = (
    "vestir", "vestiram", "roupa", "camisa", "branco da cabeca", "ministr", "multid",
    "povo ", "chorou", "lagrim", "greve", "protest", "passeat", "trabalhador",
    "operari", "soldad", "prisioneir", "refugiad", "favela", "famint", "fome",
    "funeral", "discurs", "comicio", "aplaus", "wearing", "crowd", "protest", "strike", "crying",
)

BUILDING_EXTERIOR_KEYWORDS = (
    "parliament", "supreme_court", "old_supreme_court", "courthouse", "building",
    "skyscraper", "skyline", "tower", "office_glass", "facade", "hotel", "city_hall",
    "campus", "aerial_city", "night_aerial", "city_highway",
)


def _norm_text(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(s or ""))
    ascii_s = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_s.lower()).strip()


def _key_tokens(s: str) -> list[str]:
    toks = [t for t in _norm_text(s).split() if len(t) >= 3 and t not in PT_EN_STOPWORDS]
    nums = [t for t in _norm_text(s).split() if t.isdigit() and len(t) >= 2]
    out = []
    for t in toks + nums:
        if t not in out:
            out.append(t)
    return out


def _load_audio_words(project_dir: str) -> list[dict]:
    wp = os.path.join(project_dir, "words.json")
    if os.path.isfile(wp):
        try:
            raw = json.load(open(wp, "r", encoding="utf-8"))
            if isinstance(raw, list) and raw:
                return [
                    {
                        "word": str(w.get("word") or ""),
                        "norm": _norm_text(w.get("word") or ""),
                        "start": float(w.get("start_ms", 0)) / 1000.0,
                        "end": float(w.get("end_ms", 0)) / 1000.0,
                    }
                    for w in raw
                    if str(w.get("word") or "").strip()
                ]
        except Exception:
            pass
    srt_p = os.path.join(project_dir, "subtitles.srt")
    if not os.path.isfile(srt_p):
        return []

    def _ts(ts: str) -> float:
        h, m, rest = ts.strip().replace(".", ",").split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms[:3].ljust(3, "0")) / 1000.0

    words = []
    raw = open(srt_p, "r", encoding="utf-8-sig", errors="ignore").read()
    for blk in re.split(r"\n\s*\n", raw.strip()):
        ls = [x.strip() for x in blk.splitlines() if x.strip()]
        if len(ls) >= 3 and "-->" in ls[1]:
            a, b = [_ts(x) for x in ls[1].split("-->")[:2]]
            toks = " ".join(ls[2:]).split()
            if not toks:
                continue
            step = max(0.02, (b - a) / len(toks))
            for idx, tok in enumerate(toks):
                ws = a + idx * step
                words.append({"word": tok, "norm": _norm_text(tok), "start": ws, "end": ws + step})
    return words


def _spoken_window_text(words: list[dict], t0: float, t1: float) -> str:
    return " ".join(w["norm"] for w in words if w["end"] >= t0 and w["start"] <= t1)


def _find_token_times(words: list[dict], token: str) -> list[float]:
    hits = []
    for w in words:
        wn = w["norm"]
        if not wn:
            continue
        if wn == token or (len(token) >= 4 and len(wn) >= 4 and (wn.startswith(token[:5]) or token.startswith(wn[:5]))):
            hits.append(round(w["start"], 1))
    return hits


def _token_in_window(token: str, win_words: list[str]) -> bool:
    for wn in win_words:
        if wn == token:
            return True
        if len(token) >= 4 and len(wn) >= 4 and (wn.startswith(token[:5]) or token.startswith(wn[:5])):
            return True
    return False


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dhash_image(path: str) -> int | None:
    try:
        im = Image.open(path).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = list(im.getdata())
        h = 0
        for r in range(8):
            for c in range(8):
                if px[r * 9 + c] > px[r * 9 + c + 1]:
                    h |= 1 << (r * 8 + c)
        return h
    except Exception:
        return None


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _portrait_frame_signature(path: str) -> str | None:
    """Detects identical cloned top accent bar / white-box frame geometry across staged 16:9 photos."""
    try:
        im = Image.open(path).convert("RGB")
        w, h = im.size
        if w < 640 or h < 360:
            return None
        cx = w // 2
        # Check for a saturated uniform horizontal bar or crisp white border along center vertical strip y=30..210
        bands = []
        run_col = None
        run_len = 0
        for y in range(25, min(220, h)):
            r, g, b = im.getpixel((cx, y))
            # Check horizontal uniformity +-80px around center
            l_px = im.getpixel((max(0, cx - 80), y))
            r_px = im.getpixel((min(w - 1, cx + 80), y))
            uniform = max(abs(r - l_px[0]), abs(g - l_px[1]), abs(b - l_px[2]), abs(r - r_px[0]), abs(g - r_px[1]), abs(b - r_px[2])) < 14
            is_accent = uniform and (max(r, g, b) - min(r, g, b) > 75)
            is_white = uniform and r > 238 and g > 238 and b > 238
            if is_accent or is_white:
                tag = f"{'A' if is_accent else 'W'}:{(r//24)*24},{(g//24)*24},{(b//24)*24}"
                if tag == run_col:
                    run_len += 1
                else:
                    if run_col and run_len >= 4:
                        bands.append((y - run_len, run_len, run_col))
                    run_col = tag
                    run_len = 1
            else:
                if run_col and run_len >= 4:
                    bands.append((y - run_len, run_len, run_col))
                run_col = None
                run_len = 0
        if run_col and run_len >= 4:
            bands.append((220 - run_len, run_len, run_col))
        accent_bands = [b for b in bands if b[2].startswith("A:") and 4 <= b[1] <= 24]
        if accent_bands:
            y0, ln, col = accent_bands[0]
            return f"bar@{y0//6*6}:{col}"
        return None
    except Exception:
        return None


def check_overlay_alpha_edges(png_path: str, border_px: int = 2, alpha_thresh: int = 2) -> tuple[bool, dict]:
    im = Image.open(png_path)
    if im.mode != "RGBA":
        return False, {"file": os.path.basename(png_path), "reason": f"Non-RGBA overlay ({im.mode}); overlays must be RGBA with >=64px transparent margin."}
    w, h = im.size
    alpha = im.getchannel("A")
    px = alpha.load()
    clipped = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    max_edge_alpha = 0
    for y in range(min(border_px, h)):
        for x in range(w):
            a = px[x, y]
            if a > alpha_thresh:
                clipped["top"] += 1
                max_edge_alpha = max(max_edge_alpha, a)
    for y in range(max(0, h - border_px), h):
        for x in range(w):
            a = px[x, y]
            if a > alpha_thresh:
                clipped["bottom"] += 1
                max_edge_alpha = max(max_edge_alpha, a)
    for x in range(min(border_px, w)):
        for y in range(h):
            a = px[x, y]
            if a > alpha_thresh:
                clipped["left"] += 1
                max_edge_alpha = max(max_edge_alpha, a)
    for x in range(max(0, w - border_px), w):
        for y in range(h):
            a = px[x, y]
            if a > alpha_thresh:
                clipped["right"] += 1
                max_edge_alpha = max(max_edge_alpha, a)
    ok = sum(clipped.values()) == 0
    return ok, {"file": os.path.basename(png_path), "size": [w, h], "max_edge_alpha": max_edge_alpha, "clipped_pixels": clipped}


def _probe_duration(path: str) -> float:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15,
        )
        return float((res.stdout or "0").strip() or 0.0)
    except Exception:
        return 0.0


def _grab_rgb_thumb(mp4_path: str, t_sec: float) -> bytes | None:
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t_sec:.3f}", "-i", mp4_path, "-frames:v", "1", "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=20,
    )
    if res.returncode != 0 or len(res.stdout) < 160 * 90 * 3:
        return None
    return res.stdout


def check_motion_alive(mp4_path: str) -> tuple[bool, float]:
    dur = _probe_duration(mp4_path)
    if dur <= 0.4:
        return False, 0.0
    thumbs = [_grab_rgb_thumb(mp4_path, dur * p) for p in (0.05, 0.35, 0.70)]
    if any(x is None for x in thumbs):
        return False, 0.0
    max_delta = max(
        sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))
        for a, b in ((thumbs[0], thumbs[1]), (thumbs[1], thumbs[2]), (thumbs[0], thumbs[2]))
    )
    return max_delta >= 0.5, round(max_delta, 3)


def check_lazy_cam_zoom(html_text: str) -> list[str]:
    hits = []
    for rx in LAZY_CAM_ZOOM_PATTERNS:
        m = rx.search(html_text)
        if m:
            hits.append(" ".join(m.group(0).split())[:110])
    return hits


def check_hand_drawn_map(bname: str, html_text: str) -> str | None:
    low = html_text.lower()
    if any(marker in low for marker in REAL_CARTOGRAPHY_MARKERS):
        return None
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    title_txt = title_m.group(1) if title_m else ""
    map_header_hit = bool(re.search(r"\b(mapa|map|strait|estreito|peninsula|pen[íi]nsula|continent|continente|landmass|geografia|geography|atlas)\b", f"{bname} {title_txt}", re.IGNORECASE))
    if map_header_hit or re.search(r"<!--[^>]*(landmass|continent|peninsula|island|mapa)[^>]*-->", html_text, re.IGNORECASE):
        poly_paths = re.findall(
            r"""<path[^>]+d=["'][^"']*M\s*[\d.\-]+\s+[\d.\-]+(?:\s+L\s*[\d.\-]+\s+[\d.\-]+){3,}[^"']*Z["'][^>]*>""",
            html_text,
            re.IGNORECASE,
        )
        filled_polys = [p for p in poly_paths if not re.search(r"""fill\s*=\s*["']none["']""", p, re.IGNORECASE)]
        if len(filled_polys) >= 1:
            return (
                f"NO_HAND_DRAWN_MAP in {bname}: detected {len(filled_polys)} hand-drawn SVG landmass polygon(s) without real cartography. "
                f"Use `/__kit/map_kit.mjs` + `/__runtime/world-atlas/countries-10m.json` (Natural Earth real GeoJSON) or `maplibre-gl`!"
            )
    return None


def _color_grade_sepia_trap(cg: dict) -> bool:
    """Returns True if colorGrade triggers Timeline Studio's accidental warm/sepia quirk."""
    if not isinstance(cg, dict):
        return False
    temp = float(cg.get("temperature") or 0)
    wheel_sat = sum(
        float((cg.get(w) or {}).get("saturation") or 0)
        for w in ("shadows", "midtones", "highlights", "offset")
        if isinstance(cg.get(w), dict)
    )
    return (temp < -2) or (temp <= 0 and wheel_sat > 6)


def audit_project(project_dir: str, plan_path: str = "", max_motion_ratio: float = 0.20, strict_human: bool = False) -> dict:
    errors = []
    warnings = []
    stats = {
        "overlays_checked": 0,
        "overlays_clipped": 0,
        "motion_htmls": 0,
        "motion_mp4s": 0,
        "lazy_zoom_violations": 0,
        "hand_drawn_map_violations": 0,
        "audio_sync_violations": 0,
        "duplicate_media_violations": 0,
        "frozen_clips": 0,
        "scenes_total": 0,
        "unique_visual_files": 0,
        "motion_scenes": 0,
        "motion_pct": 0.0,
        "youtube_clips": 0,
        "human_building_mismatches": 0,
        "cloned_portrait_frames": 0,
        "warm_or_sepia_trap_grades": 0,
    }

    # 1. Check all transparent PNG overlays for EDGE_ALPHA_CLIP
    ov_dir = os.path.join(project_dir, "overlays")
    if os.path.isdir(ov_dir):
        for png in sorted(glob.glob(os.path.join(ov_dir, "*.png"))):
            stats["overlays_checked"] += 1
            ok, info = check_overlay_alpha_edges(png)
            if not ok:
                stats["overlays_clipped"] += 1
                errors.append(
                    f"EDGE_ALPHA_CLIP on {info['file']}: shadow/element touches PNG edge "
                    f"({info.get('clipped_pixels') or info.get('reason')}). Add >=64px transparent padding around element!"
                )

    # 2. Check motion HTML files for contract, banned widgets, lazy cam zoom, and hand-drawn maps
    mot_dir = os.path.join(project_dir, "motion")
    if os.path.isdir(mot_dir):
        for html_p in sorted(glob.glob(os.path.join(mot_dir, "*.html"))):
            stats["motion_htmls"] += 1
            raw = open(html_p, "r", encoding="utf-8", errors="ignore").read()
            bname = os.path.basename(html_p)
            if "drawframe" not in raw.lower() and "__setframe" not in raw.lower():
                errors.append(f"MOTION_CONTRACT_FAIL in {bname}: missing deterministic window.drawFrame(t) or window.__setFrame(f, fps).")
            for pat in BANNED_CANNED_PATTERNS:
                if pat in raw:
                    errors.append(f"BANNED_CANNED_WIDGET in {bname}: found deprecated `{pat}`.")
            lazy_hits = check_lazy_cam_zoom(raw)
            if lazy_hits:
                stats["lazy_zoom_violations"] += len(lazy_hits)
                errors.append(
                    f"NO_LAZY_CAM_ZOOM in {bname}: whole-canvas zoom-in detected (`{lazy_hits[0]}`). "
                    f"Keep camera locked at scale(1)! Animate elements, beats, typography, or real 3D instead of zooming the stage."
                )
            map_err = check_hand_drawn_map(bname, raw)
            if map_err:
                stats["hand_drawn_map_violations"] += 1
                errors.append(map_err)
            if re.search(r"backdrop-filter\s*:", raw, re.IGNORECASE) and re.search(r"border-radius\s*:\s*\d+px", raw, re.IGNORECASE):
                warnings.append(f"HUD_GLASS_WARNING in {bname}: verify this isn't a generic dark HUD card.")

        for mp4_p in sorted(glob.glob(os.path.join(mot_dir, "*.mp4"))):
            stats["motion_mp4s"] += 1
            ok, delta = check_motion_alive(mp4_p)
            if not ok:
                errors.append(f"DEAD_MOTION_RENDER in {os.path.basename(mp4_p)}: clip appears static across 5%->35%->70% (max delta={delta}).")

    # 3. Check edit_plan.json + Audio-to-Visual Sync + v4.0 Editorial Polish Gates
    ep_path = plan_path or os.path.join(project_dir, "edit_plan.json")
    audio_words = _load_audio_words(project_dir)

    if os.path.isfile(ep_path):
        plan = json.load(open(ep_path, "r", encoding="utf-8"))
        visuals = plan.get("visuals") or []
        stats["scenes_total"] = len(visuals)
        motion_cnt = sum(1 for v in visuals if v.get("kind") == "motion" or "motion/" in str(v.get("file", "")).replace("\\", "/"))
        stats["motion_scenes"] = motion_cnt
        stats["motion_pct"] = round((motion_cnt / float(len(visuals))) * 100.0, 1) if visuals else 0.0
        video_type = str(plan.get("video_type") or "documentary").lower()
        is_pure_motion = video_type in ("motion_showcase", "saas_promo", "kinetic_reel")
        if not is_pure_motion and len(visuals) >= 6:
            ratio = motion_cnt / float(len(visuals))
            if ratio > max_motion_ratio:
                errors.append(
                    f"MOTION_OVERUSE_10_15: {motion_cnt}/{len(visuals)} ({ratio*100:.0f}%) scenes are motion graphics "
                    f"(target 10-15%, hard cap {int(max_motion_ratio*100)}% for {video_type}). Keep motion focused on Hook + key informational peaks!"
                )
            elif ratio < 0.08:
                warnings.append(
                    f"MOTION_UNDER_10_PCT: {motion_cnt}/{len(visuals)} ({ratio*100:.0f}%) scenes are motion graphics "
                    f"(default target 10-15% illustrating key informational beats)."
                )

        # Block buggy Timeline Studio native effects proven to cause banding / lifted blacks
        for fx_i, fx in enumerate(plan.get("effectClips") or []):
            eff = str((fx or {}).get("effect") or "").lower()
            if eff in ("grain", "halo"):
                errors.append(
                    f"BANNED_ARTIFACT_EFFECT on effectClips[{fx_i}] (`{eff}`): Timeline Studio native `{eff}` causes "
                    f"vertical banding or lifted blacks. Use `colorGrade` + clean `vignette` / `glow` instead."
                )

        seen_hashes: dict[str, list[dict]] = {}
        photo_dhashes: list[tuple[str, str, int]] = []
        frame_sigs: dict[str, list[str]] = {}
        graded_total = 0
        warm_grades = 0
        sepia_traps = 0
        explicit_transitions = 0
        static_photos_total = 0
        static_photos_with_kf = 0
        building_scenes = 0
        cursor = 0.0

        for idx, v in enumerate(visuals):
            vid = str(v.get("id") or f"visual-{idx+1:02d}")
            fp = v.get("file", "")
            if not os.path.isabs(fp):
                fp = os.path.join(project_dir, fp)
            if not os.path.isfile(fp) or os.path.getsize(fp) == 0:
                errors.append(f"MISSING_OR_EMPTY_MEDIA: {vid} -> {fp}")
                continue

            b_low = os.path.basename(fp).lower()
            nm_low = str(v.get("name") or "").lower()
            if str(v.get("source") or "").lower() == "youtube" or b_low.startswith("yt_") or "(yt" in nm_low or "youtube" in nm_low:
                stats["youtube_clips"] += 1

            is_motion = v.get("kind") == "motion" or "motion/" in str(v.get("file", "")).replace("\\", "/")
            ext = os.path.splitext(fp)[1].lower()
            is_video = ext in (".mp4", ".mov", ".webm")

            if not is_video and not is_motion:
                static_photos_total += 1
                if v.get("keyframes") or (isinstance(v.get("photoMotion"), str) and v.get("photoMotion") not in ("none", "hold")):
                    static_photos_with_kf += 1

            tr = v.get("transition")
            if tr and ((isinstance(tr, str) and tr != "none") or (isinstance(tr, dict) and tr.get("id") not in (None, "", "none"))):
                explicit_transitions += 1

            # Color grade warm/sepia trap inspection
            cg = v.get("colorGrade")
            if isinstance(cg, dict):
                graded_total += 1
                if float(cg.get("temperature") or 0) > 2:
                    warm_grades += 1
                if _color_grade_sepia_trap(cg):
                    sepia_traps += 1

            anim = v.get("animation") or {}
            anim_in = (anim.get("in") or {}).get("id") if isinstance(anim.get("in"), dict) else ""
            anim_out = (anim.get("out") or {}).get("id") if isinstance(anim.get("out"), dict) else ""
            if is_motion and ("zoom" in str(anim_in).lower() or "zoom" in str(anim_out).lower()):
                stats["lazy_zoom_violations"] += 1
                errors.append(f"NO_ZOOM_ON_MOTION on {vid}: never attach Timeline Studio zoom animation to a rendered motion clip.")

            # Timing & Audio Sync checks
            has_start = v.get("start") is not None
            has_end = v.get("end") is not None
            if has_start:
                req_start = float(v["start"])
                if abs(cursor - req_start) > 0.25:
                    stats["audio_sync_violations"] += 1
                    errors.append(
                        f"TIMELINE_DRIFT_FAIL on {vid}: declared start={req_start:.2f}s != cumulative cursor={cursor:.2f}s "
                        f"(drift={cursor - req_start:+.2f}s). Lock every scene's start/end continuously to words_compact.txt!"
                    )
            req_dur = (float(v["end"]) - float(v["start"])) if (has_start and has_end and float(v["end"]) > float(v["start"])) else float(v.get("duration") or 0.0)
            seg_start, seg_end = cursor, cursor + req_dur
            cursor = seg_end

            anchor = str(v.get("anchor_phrase") or "").strip()
            anchor_norm = _norm_text(anchor)

            # v4.0 People/Action First — Anti-Building-Fallback check
            if not is_motion:
                is_bldg = any(k in b_low or k in nm_low for k in BUILDING_EXTERIOR_KEYWORDS)
                if is_bldg:
                    building_scenes += 1
                if is_bldg and anchor_norm and any(hk in anchor_norm for hk in HUMAN_ACTION_KEYWORDS):
                    stats["human_building_mismatches"] += 1
                    msg = (
                        f"HUMAN_ACTION_BUILDING_MISMATCH on {vid}: narration mentions people/clothing/action "
                        f"('{anchor[:72]}') but visual is a generic building exterior (`{os.path.basename(fp)}`). "
                        f"Source real human/event archival photo or footage instead!"
                    )
                    if strict_human:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

            if audio_words and req_dur > 0:
                win_txt = _spoken_window_text(audio_words, max(0.0, seg_start - 0.8), seg_end + 1.0)
                win_toks = win_txt.split()

                if anchor:
                    a_toks = _key_tokens(anchor)
                    if a_toks:
                        matched = [t for t in a_toks if _token_in_window(t, win_toks)]
                        if len(matched) / float(len(a_toks)) < 0.45:
                            stats["audio_sync_violations"] += 1
                            actual_hits = {t: _find_token_times(audio_words, t)[:2] for t in a_toks if _find_token_times(audio_words, t)}
                            errors.append(
                                f"AUDIO_DESYNC_FAIL on {vid} [{seg_start:.1f}s..{seg_end:.1f}s]: anchor_phrase='{anchor[:70]}' "
                                f"does not match spoken audio in this window (matched {len(matched)}/{len(a_toks)}; "
                                f"actual audio times: {actual_hits})."
                            )

                is_hook_tease = bool(v.get("is_hook_tease", False)) and idx == 0
                if is_motion and not is_hook_tease:
                    cue_list = v.get("cue_words") if isinstance(v.get("cue_words"), list) else []
                    check_tokens = _key_tokens(" ".join(str(x) for x in cue_list)) if cue_list else _key_tokens(str(v.get("name") or ""))
                    if check_tokens:
                        m_win = _spoken_window_text(audio_words, max(0.0, seg_start - 0.8), seg_end + 1.2).split()
                        matched_m = [t for t in check_tokens if _token_in_window(t, m_win)]
                        if len(matched_m) == 0 or (len(check_tokens) >= 3 and len(matched_m) / float(len(check_tokens)) < 0.34):
                            stats["audio_sync_violations"] += 1
                            real_times = {t: _find_token_times(audio_words, t)[:2] for t in check_tokens if _find_token_times(audio_words, t)}
                            errors.append(
                                f"MOTION_PREMATURE_OR_DESYNC on {vid} [{seg_start:.1f}s..{seg_end:.1f}s] (`{v.get('name')}`): "
                                f"motion topic/cues {check_tokens} not spoken in this window (spoken at: {real_times}). "
                                f"Align motion start/end strictly to when the narrator actually speaks the topic!"
                            )

            # Media uniqueness, cloned-frame detection & zero-freeze checks
            sha = _sha256_file(fp)
            src_in = float(v.get("sourceStart") or 0.0)
            src_end = src_in + req_dur
            allow_disjoint = bool(v.get("allow_disjoint_cut", False))

            if sha in seen_hashes:
                prev_uses = seen_hashes[sha]
                if not is_video:
                    stats["duplicate_media_violations"] += 1
                    errors.append(f"NO_DUPLICATE_MEDIA on {vid}: image `{os.path.basename(fp)}` already used in `{prev_uses[0]['id']}`.")
                else:
                    if not allow_disjoint:
                        stats["duplicate_media_violations"] += 1
                        errors.append(f"NO_DUPLICATE_MEDIA on {vid}: video `{os.path.basename(fp)}` already used in `{prev_uses[0]['id']}`.")
                    else:
                        if len(prev_uses) >= 2:
                            stats["duplicate_media_violations"] += 1
                            errors.append(f"NO_DUPLICATE_MEDIA on {vid}: video `{os.path.basename(fp)}` exceeded max 2 disjoint cuts.")
                        for prev in prev_uses:
                            if abs(idx - prev["idx"]) <= 1:
                                stats["duplicate_media_violations"] += 1
                                errors.append(f"NO_DUPLICATE_MEDIA on {vid}: consecutive reuse of `{os.path.basename(fp)}` right after `{prev['id']}`.")
                            overlap = not (src_end <= prev["start"] - 2.0 or src_in >= prev["end"] + 2.0)
                            if overlap or abs(src_in - prev["start"]) < 8.0:
                                stats["duplicate_media_violations"] += 1
                                errors.append(
                                    f"OVERLAPPING_VIDEO_REUSE on {vid} [{src_in:.1f}s..{src_end:.1f}s] overlaps or is <8s from "
                                    f"`{prev['id']}` [{prev['start']:.1f}s..{prev['end']:.1f}s] in `{os.path.basename(fp)}`!"
                                )
            seen_hashes.setdefault(sha, []).append({"id": vid, "idx": idx, "start": src_in, "end": src_end, "file": os.path.basename(fp)})

            if not is_video:
                dh = _dhash_image(fp)
                if dh is not None:
                    for p_id, p_name, p_dh in photo_dhashes:
                        if _hamming(dh, p_dh) <= 8:
                            stats["duplicate_media_violations"] += 1
                            errors.append(f"NEAR_DUPLICATE_PHOTO on {vid} (`{os.path.basename(fp)}`): near-identical to `{p_id}` (`{p_name}`).")
                            break
                    photo_dhashes.append((vid, os.path.basename(fp), dh))
                if not is_motion:
                    sig = _portrait_frame_signature(fp)
                    if sig:
                        frame_sigs.setdefault(sig, []).append(f"{vid}:{os.path.basename(fp)}")
            else:
                src_dur = _probe_duration(fp)
                if req_dur > 0 and src_dur > 0 and (src_in + req_dur) > (src_dur + 0.08):
                    stats["frozen_clips"] += 1
                    errors.append(f"ZERO_FREEZE_FAIL on {vid}: requested [{src_in:.2f}s..{src_in+req_dur:.2f}s] exceeds source duration {src_dur:.2f}s!")

        stats["unique_visual_files"] = len(seen_hashes)
        stats["warm_or_sepia_trap_grades"] = warm_grades + sepia_traps

        # v4.0 Project-level checks
        for sig, items in frame_sigs.items():
            if len(items) >= 4:
                stats["cloned_portrait_frames"] += len(items)
                errors.append(
                    f"CLONED_PORTRAIT_TEMPLATE ({len(items)} scenes share identical `{sig}` frame: {', '.join(items[:5])}): "
                    f"Use `stage_photo.py --style auto` to vary portrait treatments (smart_fullbleed, editorial_split, archival_matte, newspaper_sheet, diptych_side)!"
                )

        if sepia_traps > 0:
            warnings.append(
                f"COLOR_GRADE_SEPIA_TRAP ({sepia_traps} clip(s)): negative `temperature` or wheel `saturation > 0` triggers "
                f"accidental sepia/warm hue-rotate in Timeline Studio `colorGrade.js`. Omit `colorGrade` (auto v4.0 non-warm presets) "
                f"or use `gradePreset` (`crisp_cool_slate`, `steel_cyan_doc`, `neutral_high_contrast`, `muted_desat_film`, `deep_emerald_moody`, `vivid_editorial_clean`, `silver_noir_archival`)."
            )
        if graded_total >= 4 and (warm_grades / float(graded_total)) > 0.35:
            warnings.append(
                f"WARM_FILTER_BIAS: {warm_grades}/{graded_total} graded clips lean warm (>35%). Diversify with cool/neutral/moody/vivid presets!"
            )

        if len(visuals) >= 8 and plan.get("autoTransitions") is False and explicit_transitions == 0:
            warnings.append("ZERO_TRANSITIONS_WARNING: `autoTransitions` is disabled and 0 explicit transitions were set.")
        if static_photos_total >= 6 and plan.get("autoPhotoMotion") is False and static_photos_with_kf == 0:
            warnings.append("FLAT_STATIC_PHOTOS_WARNING: `autoPhotoMotion` is disabled and 0 static photos have Ken Burns keyframes.")
        if len(visuals) >= 12 and (building_scenes / float(len(visuals))) > 0.28:
            warnings.append(
                f"BUILDING_OVERUSE_WARNING: {building_scenes}/{len(visuals)} ({building_scenes*100/len(visuals):.0f}%) scenes appear to be building/skyline exteriors (>28%). Balance with people, actions, archival moments, and close-ups!"
            )

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "stats": stats}


def main():
    ap = argparse.ArgumentParser(description="Deterministic Sync, Cartography, Anti-Duplicate, Anti-Clone & Human-First QA Gate v4.0")
    ap.add_argument("--project-dir", help="Project folder containing edit_plan.json, overlays/, motion/")
    ap.add_argument("--overlay", help="Check a single transparent overlay PNG for EDGE_ALPHA_CLIP")
    ap.add_argument("--plan", default="", help="Optional explicit path to edit_plan.json")
    ap.add_argument("--max-motion-ratio", type=float, default=0.20)
    ap.add_argument("--strict-human", action="store_true", help="Treat HUMAN_ACTION_BUILDING_MISMATCH as hard error")
    args = ap.parse_args()

    if args.overlay:
        ok, info = check_overlay_alpha_edges(args.overlay)
        print(json.dumps({"ok": ok, **info}, ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)

    if not args.project_dir:
        ap.error("Provide --project-dir or --overlay")

    res = audit_project(args.project_dir, plan_path=args.plan, max_motion_ratio=args.max_motion_ratio, strict_human=args.strict_human)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
