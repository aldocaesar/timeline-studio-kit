#!/usr/bin/env python3
"""
stage_photo.py (v1.0) — Anti-Clone Multi-Style Editorial Staging for Vertical/Archival Photos
==============================================================================================
Replaces repetitive cookie-cutter portrait frames (same white box + top accent stripe over blur)
with 6 distinct documentary staging treatments rotated automatically per scene and adapted to
each video's palette:

  1. `smart_fullbleed`  : Upper-third / portrait-aware 16:9 full-bleed cinema crop (zero boxes!)
  2. `editorial_split`  : Asymmetric left/right full-height photo strip + matte color stage + caption
  3. `archival_matte`   : Frameless grounded studio matte backdrop with soft ambient shadow
  4. `newspaper_sheet`  : Tactile newsprint / dossier sheet slightly tilted over dark desk
  5. `diptych_side`     : Clean 2-photo side-by-side comparison (`--file2` required)
  6. `clean_backdrop`   : Dark desaturated depth blur with frameless edge feather (NO white box!)

Tracks `<out_dir>/_photo_staging_log.json` so consecutive photos NEVER repeat the same style.
"""
import argparse
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import _runtime_env  # noqa: E402

_runtime_env.init()

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps  # noqa: E402

AUTO_STYLES = [
    "smart_fullbleed",
    "editorial_split",
    "archival_matte",
    "newspaper_sheet",
    "clean_backdrop",
]


def _hex_rgb(h: str, fb=(20, 24, 30)) -> tuple[int, int, int]:
    h = str(h or "").strip().lstrip("#")
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except Exception:
            pass
    return fb


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["segoeuib.ttf", "arialbd.ttf", "georgia.ttf", "consolab.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf", "georgia.ttf", "consola.ttf"]
    )
    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in candidates:
        p = os.path.join(win_fonts, name)
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        box = draw.textbbox((0, 0), cand, font=font)
        if box[2] - box[0] <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:4]


def _add_soft_shadow(canvas: Image.Image, box: tuple[int, int, int, int], radius: int = 34, offset=(0, 18), alpha: int = 125):
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.rectangle([x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]], fill=(0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(radius))
    canvas.alpha_composite(sh)


def style_smart_fullbleed(im: Image.Image, w: int, h: int) -> Image.Image:
    # Center-top biased crop (0.5, 0.24) preserves faces/heads on portraits without letterbox bars
    return ImageOps.fit(im.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.24))


def style_editorial_split(
    im: Image.Image,
    w: int,
    h: int,
    bg_rgb: tuple[int, int, int],
    accent_rgb: tuple[int, int, int],
    caption: str,
    year: str,
    side: str = "left",
) -> Image.Image:
    canvas = Image.new("RGB", (w, h), bg_rgb)
    photo_w = int(w * 0.56)
    cropped = ImageOps.fit(im.convert("RGB"), (photo_w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.25))
    px = 0 if side == "left" else (w - photo_w)
    canvas.paste(cropped, (px, 0))

    # Subtle 1px tonal hairline separating photo and editorial column
    draw = ImageDraw.Draw(canvas)
    sep_x = photo_w if side == "left" else (w - photo_w)
    luma = 0.2126 * bg_rgb[0] + 0.7152 * bg_rgb[1] + 0.0722 * bg_rgb[2]
    ink = (22, 24, 28) if luma > 128 else (238, 240, 244)
    muted = (96, 100, 110) if luma > 128 else (160, 168, 178)
    draw.line([(sep_x, 0), (sep_x, h)], fill=muted, width=2)

    tx = (photo_w + 72) if side == "left" else 72
    max_tw = w - photo_w - 144
    y_cur = int(h * 0.34)
    if year:
        draw.rectangle([tx, y_cur - 22, tx + 64, y_cur - 17], fill=accent_rgb)
        f_yr = _load_font(56, bold=True)
        draw.text((tx, y_cur), year, fill=accent_rgb, font=f_yr)
        y_cur += 86
    if caption:
        f_cap = _load_font(40, bold=False)
        for line in _wrap_text(draw, caption, f_cap, max_tw):
            draw.text((tx, y_cur), line, fill=ink, font=f_cap)
            y_cur += 54
    return canvas


def style_archival_matte(
    im: Image.Image,
    w: int,
    h: int,
    bg_rgb: tuple[int, int, int],
    caption: str,
    year: str,
) -> Image.Image:
    # Frameless museum matte stage with subtle radial vignette (ZERO white box, ZERO top stripe)
    base = Image.new("RGBA", (w, h), (*bg_rgb, 255))
    # Subtle radial lighting falloff
    vig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    for r in range(6):
        inset = r * 45
        vd.rectangle([inset, inset, w - inset, h - inset], outline=(0, 0, 0, 14), width=45)
    vig = vig.filter(ImageFilter.GaussianBlur(70))
    base.alpha_composite(vig)

    max_h = int(h * (0.78 if caption or year else 0.84))
    max_w = int(w * 0.72)
    fg = im.convert("RGBA")
    fg.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    fw, fh = fg.size
    x0 = (w - fw) // 2
    y0 = (h - fh) // 2 - (24 if (caption or year) else 0)
    _add_soft_shadow(base, (x0, y0, x0 + fw, y0 + fh), radius=40, offset=(0, 22), alpha=145)
    base.alpha_composite(fg, (x0, y0))

    if caption or year:
        draw = ImageDraw.Draw(base)
        luma = 0.2126 * bg_rgb[0] + 0.7152 * bg_rgb[1] + 0.0722 * bg_rgb[2]
        txt_col = (40, 42, 48, 220) if luma > 128 else (210, 214, 222, 220)
        label = "  ·  ".join(x for x in [year, caption] if x)
        f_sub = _load_font(28, bold=False)
        bb = draw.textbbox((0, 0), label, font=f_sub)
        tw = bb[2] - bb[0]
        draw.text(((w - tw) // 2, y0 + fh + 34), label, fill=txt_col, font=f_sub)
    return base.convert("RGB")


def style_newspaper_sheet(
    im: Image.Image,
    w: int,
    h: int,
    bg_rgb: tuple[int, int, int],
    tilt_deg: float = -1.6,
) -> Image.Image:
    # Tactile archival sheet lightly angled over matte studio desk
    base = Image.new("RGBA", (w, h), (*bg_rgb, 255))
    fg = im.convert("RGB")
    fg.thumbnail((int(w * 0.68), int(h * 0.80)), Image.Resampling.LANCZOS)
    pad = 22
    sheet = Image.new("RGBA", (fg.width + pad * 2, fg.height + pad * 2), (242, 237, 226, 255))
    sheet.paste(fg, (pad, pad))
    # Very thin archival hairline around image
    sd = ImageDraw.Draw(sheet)
    sd.rectangle([pad - 1, pad - 1, pad + fg.width, pad + fg.height], outline=(185, 178, 165, 255), width=1)
    rot = sheet.rotate(tilt_deg, resample=Image.Resampling.BICUBIC, expand=True)
    x0 = (w - rot.width) // 2
    y0 = (h - rot.height) // 2

    # Soft rotated shadow matching sheet alpha
    sh_alpha = rot.getchannel("A").point(lambda a: int(a * 0.48))
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sh_patch = Image.new("RGBA", rot.size, (0, 0, 0, 255))
    sh_patch.putalpha(sh_alpha)
    sh.paste(sh_patch, (x0 + 12, y0 + 20))
    sh = sh.filter(ImageFilter.GaussianBlur(28))
    base.alpha_composite(sh)
    base.alpha_composite(rot, (x0, y0))
    return base.convert("RGB")


def style_diptych_side(im1: Image.Image, im2: Image.Image, w: int, h: int, bg_rgb: tuple[int, int, int]) -> Image.Image:
    canvas = Image.new("RGB", (w, h), bg_rgb)
    gutter = 14
    half = (w - gutter) // 2
    left = ImageOps.fit(im1.convert("RGB"), (half, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.28))
    right = ImageOps.fit(im2.convert("RGB"), (w - half - gutter, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.28))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (half + gutter, 0))
    return canvas


def style_clean_backdrop(im: Image.Image, w: int, h: int) -> Image.Image:
    # Dark desaturated atmospheric backdrop + FRAMELESS clean shadow (NO white border, NO red top bar!)
    bg = ImageOps.fit(im.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS)
    bg = ImageEnhance.Color(bg).enhance(0.35)
    bg = ImageEnhance.Brightness(bg).enhance(0.28)
    bg = bg.filter(ImageFilter.GaussianBlur(42)).convert("RGBA")

    fg = im.convert("RGBA")
    fg.thumbnail((int(w * 0.74), int(h * 0.88)), Image.Resampling.LANCZOS)
    x0 = (w - fg.width) // 2
    y0 = (h - fg.height) // 2
    _add_soft_shadow(bg, (x0, y0, x0 + fg.width, y0 + fg.height), radius=42, offset=(0, 20), alpha=165)
    bg.alpha_composite(fg, (x0, y0))
    return bg.convert("RGB")


def _pick_auto_style(in_path: str, im: Image.Image, log_path: str, has_second: bool) -> str:
    if has_second:
        return "diptych_side"
    history = []
    if os.path.isfile(log_path):
        try:
            history = json.load(open(log_path, "r", encoding="utf-8"))
        except Exception:
            history = []
    last_style = history[-1]["style"] if history else ""
    counts = {s: sum(1 for h in history if h.get("style") == s) for s in AUTO_STYLES}

    # Prefer smart_fullbleed only when aspect isn't ultra-narrow (avoid excessive vertical crop)
    aspect = im.width / max(1.0, float(im.height))
    candidates = [s for s in AUTO_STYLES if s != last_style]
    if aspect < 0.72 and "smart_fullbleed" in candidates:
        candidates.remove("smart_fullbleed")

    # Pick least-used style with deterministic tie-breaker
    seed = int(hashlib.sha256(os.path.basename(in_path).encode("utf-8")).hexdigest()[:8], 16)
    candidates.sort(key=lambda s: (counts.get(s, 0), (seed + AUTO_STYLES.index(s)) % 97))
    return candidates[0] if candidates else "archival_matte"


def main():
    ap = argparse.ArgumentParser(description="Anti-Clone Multi-Style Editorial Photo Staging (v1.0)")
    ap.add_argument("--in", dest="in_path", required=True, help="Source image path")
    ap.add_argument("--file2", default="", help="Optional second image for `diptych_side`")
    ap.add_argument("--out", required=True, help="Output 16:9 JPG/PNG path")
    ap.add_argument("--style", default="auto", choices=["auto", "smart_fullbleed", "editorial_split", "archival_matte", "newspaper_sheet", "diptych_side", "clean_backdrop"])
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--bg", default="#14181F", help="Matte stage background hex color (vary per video!)")
    ap.add_argument("--accent", default="#38BDF8", help="Accent hex color for editorial split (vary per video!)")
    ap.add_argument("--caption", default="", help="Optional short factual caption")
    ap.add_argument("--year", default="", help="Optional year/date stamp")
    ap.add_argument("--side", default="auto", choices=["auto", "left", "right"])
    args = ap.parse_args()

    im = Image.open(args.in_path)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "_photo_staging_log.json")

    style = _pick_auto_style(args.in_path, im, log_path, bool(args.file2)) if args.style == "auto" else args.style
    bg_rgb = _hex_rgb(args.bg, (20, 24, 31))
    accent_rgb = _hex_rgb(args.accent, (56, 189, 248))

    history = []
    if os.path.isfile(log_path):
        try:
            history = json.load(open(log_path, "r", encoding="utf-8"))
        except Exception:
            history = []

    side = args.side
    if side == "auto":
        side = "right" if (len(history) % 2 == 1) else "left"

    if style == "smart_fullbleed":
        res = style_smart_fullbleed(im, args.width, args.height)
    elif style == "editorial_split":
        res = style_editorial_split(im, args.width, args.height, bg_rgb, accent_rgb, args.caption, args.year, side=side)
    elif style == "archival_matte":
        res = style_archival_matte(im, args.width, args.height, bg_rgb, args.caption, args.year)
    elif style == "newspaper_sheet":
        tilt = -1.6 if (len(history) % 2 == 0) else 1.5
        res = style_newspaper_sheet(im, args.width, args.height, bg_rgb, tilt_deg=tilt)
    elif style == "diptych_side":
        if not args.file2 or not os.path.isfile(args.file2):
            raise SystemExit("diptych_side requires --file2 <second_image>")
        res = style_diptych_side(im, Image.open(args.file2), args.width, args.height, bg_rgb)
    else:
        res = style_clean_backdrop(im, args.width, args.height)

    ext = os.path.splitext(args.out)[1].lower()
    if ext == ".png":
        res.save(args.out, format="PNG")
    else:
        res.save(args.out, format="JPEG", quality=93, subsampling=0)

    history.append({"file": os.path.basename(args.out), "style": style, "bg": args.bg, "accent": args.accent})
    with open(log_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(history[-50:], fh, ensure_ascii=False, indent=2)

    print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "style": style, "size": [res.width, res.height]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
