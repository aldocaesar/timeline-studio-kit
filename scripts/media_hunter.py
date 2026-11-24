#!/usr/bin/env python3
"""
media_hunter.py (v2.0) — Pixabay API HD + Parallel Free HD Web Scraper (Project-Wide Anti-Duplicate!)
=====================================================================================================
Handles 2 clean sourcing tracks (YouTube footage MUST go through `youtube_hunter.py`!):
  1. Pixabay API (`PIXABAY_API_KEY` — single free API, auto-loaded from OpenBot Vault):
     - HD 1080p stock videos (`--type video`) & HD photos (`--type photo`) for atmospheric B-roll.
     - Tracks every downloaded Pixabay ID & URL in `<out_dir>/_used_media_registry.json` so two
       scenes NEVER download or reuse the same clip/photo even on similar queries!
     - Generates `<id>_check.jpg` (3-frame visual strip) for every downloaded video so a Vision
       subagent can verify framing and relevance before assembly.
  2. Parallel Free HD Web Scraping (`--specific` or zero-key fallback, `< 8s`):
     - Bing Images (`murl` JSON), Wikimedia Commons, Openverse, and Bing News RSS (`og:image`).
     - Filters watermarks, stock-preview domains, tiny/blurry images, Cyrillic spam, and
       cross-scene dHash duplicates (stored in `_used_media_registry.json`).
     - Outputs a clean 4-column `contact_sheet.jpg` (labels OUTSIDE image thumbnails) so an
       isolated Vision subagent can pick the best candidate cleanly (`--select`).
"""
import argparse
import concurrent.futures
import html as html_lib
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import _runtime_env  # noqa: E402

_runtime_env.init()

import requests  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ASPECT_DIMS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}
WATERMARK_DOMAINS = (
    "shutterstock", "gettyimages", "istockphoto", "alamy", "dreamstime", "123rf",
    "depositphotos", "vecteezy", "freepik", "adobe.com/stock", "pond5", "storyblocks",
    "stockcake", "canstockphoto", "bigstockphoto", "dissolve", "agefotostock", "bridgemanimages",
)
STOPWORDS = {"the", "and", "for", "with", "from", "into", "over", "under", "about", "that", "this", "cinematic", "4k", "8k", "hd", "ultra", "photo", "image", "video", "footage", "b-roll", "broll"}


def _registry_path(out_dir: str) -> str:
    return os.path.join(out_dir, "_used_media_registry.json")


def _load_registry(out_dir: str) -> dict:
    p = _registry_path(out_dir)
    base = {"used_ids": [], "used_urls": [], "used_dhashes": []}
    if os.path.isfile(p):
        try:
            raw = json.load(open(p, "r", encoding="utf-8"))
            if isinstance(raw, dict):
                for k in base:
                    if isinstance(raw.get(k), list):
                        base[k] = raw[k]
        except Exception:
            pass
    return base


def _save_registry(out_dir: str, reg: dict):
    os.makedirs(out_dir, exist_ok=True)
    with open(_registry_path(out_dir), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2)


def _has_cyrillic(s: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", s or ""))


def _is_bad_url(url: str) -> bool:
    u = (url or "").lower()
    if not u.startswith(("http://", "https://")):
        return True
    if any(bad in u for bad in WATERMARK_DOMAINS):
        return True
    if any(ext in u.split("?")[0] for ext in (".svg", ".gif", ".ico", ".bmp")):
        return True
    return False


def _dhash(im: Image.Image) -> int:
    g = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = list(g.getdata())
    h = 0
    for r in range(8):
        for c in range(8):
            if px[r * 9 + c] > px[r * 9 + c + 1]:
                h |= 1 << (r * 8 + c)
    return h


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _pixabay_short_queries(q: str) -> list:
    clean = re.sub(r"[^a-zA-Z0-9\s\-áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]", " ", q).strip()
    words = [w for w in clean.split() if len(w) > 2 and w.lower() not in STOPWORDS]
    out = []
    if len(clean) <= 95:
        out.append(clean)
    if len(words) >= 3:
        out.append(" ".join(words[:3]))
    if len(words) >= 2:
        out.append(" ".join(words[:2]))
    if len(words) >= 1:
        out.append(words[0])
    return list(dict.fromkeys([x for x in out if x]))


def search_pixabay_videos(query: str, api_key: str, min_dur: float = 4.0, used_ids: set | None = None, used_urls: set | None = None) -> list:
    if not api_key:
        return []
    used_ids = used_ids or set()
    used_urls = used_urls or set()
    hits_out = []
    seen = set()
    for pq in _pixabay_short_queries(query):
        try:
            r = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": api_key, "q": pq, "safesearch": "true", "per_page": 30},
                timeout=12,
            )
            if r.status_code != 200:
                continue
            for h in r.json().get("hits") or []:
                pid = f"pixabay_video:{h.get('id')}"
                vids = h.get("videos") or {}
                dur = float(h.get("duration") or 0.0)
                best = vids.get("large") or vids.get("medium") or vids.get("small") or {}
                u = best.get("url") or ""
                page_u = h.get("pageURL") or ""
                if not u or u in seen or pid in used_ids or u in used_urls or page_u in used_urls:
                    continue
                seen.add(u)
                w = int(best.get("width") or 0)
                ht = int(best.get("height") or 0)
                hits_out.append({
                    "source": "pixabay_video",
                    "asset_id": pid,
                    "url": u,
                    "page_url": page_u,
                    "author": h.get("user") or "Pixabay",
                    "duration": dur,
                    "width": w,
                    "height": ht,
                    "tags": h.get("tags") or "",
                    "score": (25 if dur >= min_dur else 0) + (15 if w >= 1920 else (10 if w >= 1280 else 0)) + (5 if w > ht else 0),
                })
            if len(hits_out) >= 4:
                break
        except Exception:
            continue
    hits_out.sort(key=lambda x: (x["score"], x["width"], x["duration"]), reverse=True)
    return hits_out


def search_pixabay_photos(query: str, api_key: str, aspect: str = "16:9", used_ids: set | None = None, used_urls: set | None = None) -> list:
    if not api_key:
        return []
    used_ids = used_ids or set()
    used_urls = used_urls or set()
    orient = "vertical" if aspect in ("9:16", "4:5") else "horizontal"
    out, seen = [], set()
    for pq in _pixabay_short_queries(query):
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={"key": api_key, "q": pq, "image_type": "photo", "orientation": orient, "safesearch": "true", "per_page": 25},
                timeout=10,
            )
            if r.status_code != 200:
                continue
            for h in r.json().get("hits") or []:
                pid = f"pixabay_photo:{h.get('id')}"
                u = h.get("largeImageURL") or h.get("webformatURL") or ""
                page_u = h.get("pageURL") or ""
                if not u or u in seen or pid in used_ids or u in used_urls or page_u in used_urls:
                    continue
                seen.add(u)
                out.append({
                    "source": "pixabay_photo",
                    "asset_id": pid,
                    "url": u,
                    "page_url": page_u,
                    "title": h.get("tags") or "",
                    "width": int(h.get("imageWidth") or 0),
                    "height": int(h.get("imageHeight") or 0),
                })
            if len(out) >= 5:
                break
        except Exception:
            continue
    return out


def search_bing_images(query: str, limit: int = 16) -> list:
    out = []
    try:
        r = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": "1"},
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=9,
        )
        if r.status_code != 200:
            return out
        for m in re.finditer(r'm="(\{[^"]*?murl[^"]*?\})"', r.text):
            try:
                obj = json.loads(html_lib.unescape(m.group(1)))
                u = obj.get("murl") or ""
                t = obj.get("t") or ""
                if u and not _is_bad_url(u):
                    out.append({"source": "bing", "url": u, "title": t, "page_url": obj.get("purl") or ""})
                if len(out) >= limit:
                    break
            except Exception:
                continue
    except Exception:
        pass
    return out


def search_wikimedia_images(query: str, limit: int = 12) -> list:
    out = []
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "generator": "search", "gsrsearch": query,
                "gsrnamespace": "6", "gsrlimit": str(limit), "prop": "imageinfo",
                "iiprop": "url|size|mime", "format": "json",
            },
            headers={"User-Agent": "TimelineStudioKit/2.0 (https://github.com/MartinDelophy/ai-video-editor)"},
            timeout=9,
        )
        if r.status_code != 200:
            return out
        pages = (r.json().get("query") or {}).get("pages") or {}
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            u = ii.get("url") or ""
            mime = str(ii.get("mime") or "")
            w, h = int(ii.get("width") or 0), int(ii.get("height") or 0)
            if u and mime.startswith("image/") and w >= 700 and h >= 450 and not _is_bad_url(u):
                out.append({"source": "wikimedia", "url": u, "title": p.get("title") or "", "width": w, "height": h, "page_url": ii.get("descriptionurl") or ""})
    except Exception:
        pass
    return out


def _relevance_score(cand: dict, query: str, aspect: str = "16:9") -> float:
    tokens = [w.lower() for w in re.findall(r"[a-zA-Z0-9áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]{3,}", query) if w.lower() not in STOPWORDS]
    hay = f"{cand.get('title', '')} {cand.get('url', '')} {cand.get('page_url', '')}".lower()
    hits = sum(1 for t in set(tokens) if t in hay)
    score = hits * 10.0
    if cand.get("source") == "wikimedia":
        score += 6.0
    elif cand.get("source") == "pixabay_photo":
        score += 5.0
    if "pinterest." in hay:
        score -= 4.0
    w, h = int(cand.get("width") or 0), int(cand.get("height") or 0)
    if w > 0 and h > 0:
        if aspect == "16:9" and w > h:
            score += 4.0
        elif aspect == "9:16" and h > w:
            score += 4.0
    return score


def search_openverse_images(query: str, limit: int = 10) -> list:
    out = []
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": str(limit)},
            headers={"User-Agent": "TimelineStudioKit/2.0"},
            timeout=9,
        )
        if r.status_code != 200:
            return out
        for it in r.json().get("results") or []:
            u = it.get("url") or ""
            if u and not _is_bad_url(u):
                out.append({"source": "openverse", "url": u, "title": it.get("title") or "", "width": int(it.get("width") or 0), "height": int(it.get("height") or 0), "page_url": it.get("foreign_landing_url") or ""})
    except Exception:
        pass
    return out


def search_news_og_images(query: str, limit: int = 6) -> list:
    out = []
    try:
        r = requests.get(f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&format=rss", headers={"User-Agent": UA}, timeout=8)
        if r.status_code != 200:
            return out
        root = ET.fromstring(r.text)
        links = [el.text.strip() for el in root.findall(".//item/link") if el.text][:limit]

        def _grab(url):
            try:
                pg = requests.get(url, headers={"User-Agent": UA}, timeout=6)
                m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', pg.text, re.I)
                if m and not _is_bad_url(m.group(1)):
                    return {"source": "news_og", "url": html_lib.unescape(m.group(1)), "title": query, "page_url": url}
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            for item in ex.map(_grab, links):
                if item:
                    out.append(item)
    except Exception:
        pass
    return out


def _download_valid_image(cand: dict, out_path: str, aspect: str = "16:9") -> dict | None:
    try:
        r = requests.get(cand["url"], headers={"User-Agent": UA, "Referer": cand.get("page_url") or "https://www.bing.com/"}, timeout=10)
        if r.status_code != 200 or len(r.content) < 12000:
            return None
        im = Image.open(io.BytesIO(r.content))
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        w, h = im.size
        if w < 640 or h < 360:
            return None
        ar = w / float(h)
        if ar > 3.2 or ar < 0.32:
            return None
        dh = _dhash(im)
        im.convert("RGB").save(out_path, "JPEG", quality=92)
        return {**cand, "local_path": os.path.abspath(out_path), "width": w, "height": h, "dhash": dh}
    except Exception:
        return None


def _build_contact_sheet(cands: list, out_jpg: str, title: str):
    if not cands:
        return
    cols = min(4, len(cands))
    rows = int(math.ceil(len(cands) / float(cols)))
    tw, th = 420, 236
    lbl_h = 34
    pad = 12
    canvas = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + lbl_h + pad) + pad + 38), (20, 22, 28))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    draw.text((pad, 10), title[:110], fill=(240, 245, 255), font=font)
    for idx, c in enumerate(cands):
        r, col = divmod(idx, cols)
        x = pad + col * (tw + pad)
        y = 38 + pad + r * (th + lbl_h + pad)
        draw.rectangle([x, y, x + tw, y + lbl_h - 2], fill=(35, 41, 56))
        draw.text((x + 8, y + 7), f"#{idx+1} [{c['source']}] {c['width']}x{c['height']}", fill=(140, 225, 255), font=font)
        try:
            im = Image.open(c["local_path"]).convert("RGB")
            im.thumbnail((tw, th), Image.Resampling.LANCZOS)
            ox = x + (tw - im.width) // 2
            oy = y + lbl_h + (th - im.height) // 2
            canvas.paste(im, (ox, oy))
        except Exception:
            pass
    canvas.save(out_jpg, "JPEG", quality=88)


def _make_video_check_strip(mp4_path: str, out_jpg: str):
    """Build a fast 3-frame horizontal verification strip (10%, 50%, 88%) for visual QA."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", mp4_path,
                "-vf", "fps=0.6,scale=420:-2,tile=3x1:padding=4:color=0x16181f",
                "-frames:v", "1", "-update", "1", "-q:v", "4", out_jpg,
            ],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def normalize_video(raw_mp4: str, out_mp4: str, target_dur: float, aspect: str = "16:9") -> bool:
    tw, th = ASPECT_DIMS.get(aspect, (1920, 1080))
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", raw_mp4,
        "-an",
        "-vf", f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},fps=30,format=yuv420p",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-movflags", "+faststart",
    ]
    if target_dur > 0:
        cmd += ["-t", f"{target_dur + 0.6:.2f}"]
    cmd.append(out_mp4)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return res.returncode == 0 and os.path.isfile(out_mp4) and os.path.getsize(out_mp4) > 10000


def hunt_photo(scene_id: str, query: str, out_dir: str, specific: bool, aspect: str, exclude_terms: list, max_cands: int = 8) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    reg = _load_registry(out_dir)
    used_ids = set(reg["used_ids"])
    used_urls = set(reg["used_urls"])
    used_dhashes = [int(x) for x in reg["used_dhashes"]]

    pix_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    tasks = []
    if not specific and pix_key:
        tasks.append(lambda: search_pixabay_photos(query, pix_key, aspect, used_ids=used_ids, used_urls=used_urls))
    tasks.append(lambda: search_bing_images(query, limit=14))
    tasks.append(lambda: search_wikimedia_images(query, limit=8))
    tasks.append(lambda: search_openverse_images(query, limit=8))
    if specific:
        tasks.append(lambda: search_news_og_images(query, limit=5))

    raw_cands = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        for res in ex.map(lambda fn: fn(), tasks):
            raw_cands.extend(res or [])

    want_cyr = _has_cyrillic(query)
    excl = [e.lower() for e in (exclude_terms or []) if e]
    filtered, seen_u = [], set()
    for c in raw_cands:
        u = c.get("url", "")
        if not u or u in seen_u or u in used_urls or c.get("page_url") in used_urls:
            continue
        txt = f"{c.get('title', '')} {u}".lower()
        if any(e in txt for e in excl):
            continue
        if not want_cyr and _has_cyrillic(c.get("title", "")):
            continue
        seen_u.add(u)
        c["_score"] = _relevance_score(c, query, aspect)
        if c["_score"] > 0:
            filtered.append(c)

    filtered.sort(key=lambda x: x.get("_score", 0.0), reverse=True)

    cand_dir = os.path.join(out_dir, f"{scene_id}_cands")
    os.makedirs(cand_dir, exist_ok=True)
    downloaded = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [
            ex.submit(_download_valid_image, c, os.path.join(cand_dir, f"{scene_id}_{i+1:02d}.jpg"), aspect)
            for i, c in enumerate(filtered[: max_cands * 2])
        ]
        for f in futs:
            r = f.result()
            if not r:
                continue
            if any(_hamming(r["dhash"], prev_dh) <= 8 for prev_dh in used_dhashes):
                continue
            if any(_hamming(r["dhash"], prev["dhash"]) <= 6 for prev in downloaded):
                continue
            downloaded.append(r)
            if len(downloaded) >= max_cands:
                break
    downloaded.sort(key=lambda x: _relevance_score(x, query, aspect), reverse=True)

    sheet = os.path.join(out_dir, f"{scene_id}_contact_sheet.jpg")
    _build_contact_sheet(downloaded, sheet, f"{scene_id} | {'SPECIFIC SCRAPE' if specific else 'STOCK/SCRAPE'} | {query}")
    chosen = ""
    if downloaded:
        chosen = os.path.join(out_dir, f"{scene_id}.jpg")
        top = downloaded[0]
        with open(top["local_path"], "rb") as src, open(chosen, "wb") as dst:
            dst.write(src.read())
        if top.get("asset_id") and top["asset_id"] not in reg["used_ids"]:
            reg["used_ids"].append(top["asset_id"])
        if top.get("url") and top["url"] not in reg["used_urls"]:
            reg["used_urls"].append(top["url"])
        if top.get("dhash") is not None:
            reg["used_dhashes"].append(int(top["dhash"]))
        _save_registry(out_dir, reg)
    return {
        "ok": bool(downloaded),
        "scene_id": scene_id,
        "mode": "photo",
        "pixabay_active": bool(pix_key),
        "candidates": len(downloaded),
        "selected": os.path.abspath(chosen) if chosen else "",
        "contact_sheet": os.path.abspath(sheet) if os.path.isfile(sheet) else "",
        "items": [{"index": i + 1, "source": c["source"], "size": [c["width"], c["height"]], "path": c["local_path"], "page_url": c.get("page_url", "")} for i, c in enumerate(downloaded)],
    }


def hunt_video(scene_id: str, query: str, out_dir: str, duration: float, aspect: str, pick_index: int = 1) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    pix_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not pix_key:
        return {
            "ok": False,
            "scene_id": scene_id,
            "mode": "video",
            "pixabay_active": False,
            "error": "PIXABAY_API_KEY not set — use `youtube_hunter.py` (visual YouTube clip) or `--type photo` HD scrape, or save PIXABAY_API_KEY in Vault.",
        }
    reg = _load_registry(out_dir)
    used_ids = set(reg["used_ids"])
    used_urls = set(reg["used_urls"])

    hits = search_pixabay_videos(query, pix_key, min_dur=duration + 0.5, used_ids=used_ids, used_urls=used_urls)
    if not hits:
        return {"ok": False, "scene_id": scene_id, "mode": "video", "pixabay_active": True, "error": f"No unused Pixabay HD videos matched '{query}'."}

    start_idx = max(0, min(len(hits) - 1, pick_index - 1))
    raw_p = os.path.join(out_dir, f"_raw_{scene_id}.mp4")
    out_p = os.path.join(out_dir, f"{scene_id}.mp4")
    check_jpg = os.path.join(out_dir, f"{scene_id}_check_final.jpg")

    for h in hits[start_idx : start_idx + 4]:
        try:
            with requests.get(h["url"], stream=True, timeout=35) as r:
                r.raise_for_status()
                with open(raw_p, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
            if normalize_video(raw_p, out_p, duration, aspect):
                try:
                    os.remove(raw_p)
                except OSError:
                    pass
                _make_video_check_strip(out_p, check_jpg)
                # Register asset so no future scene in this project can ever download the same clip!
                for k, val in (("used_ids", h["asset_id"]), ("used_urls", h["url"]), ("used_urls", h["page_url"])):
                    if val and val not in reg[k]:
                        reg[k].append(val)
                _save_registry(out_dir, reg)
                return {
                    "ok": True,
                    "scene_id": scene_id,
                    "mode": "video",
                    "source": "pixabay_video",
                    "asset_id": h["asset_id"],
                    "selected": os.path.abspath(out_p),
                    "check_strip": os.path.abspath(check_jpg) if os.path.isfile(check_jpg) else "",
                    "source_duration": h["duration"],
                    "tags": h["tags"],
                    "page_url": h["page_url"],
                    "author": h["author"],
                }
        except Exception:
            continue
    return {"ok": False, "scene_id": scene_id, "mode": "video", "error": "Pixabay video download/normalize failed."}


def main():
    ap = argparse.ArgumentParser(description="Pixabay HD (Anti-Duplicate) + Parallel Free HD Web Scraper v2.0")
    ap.add_argument("--id", required=True, help="Scene ID (e.g., S02)")
    ap.add_argument("--query", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--type", choices=["photo", "video"], default="photo")
    ap.add_argument("--specific", action="store_true", help="Block generic stock; use real web/press/Wikimedia photos")
    ap.add_argument("--aspect", choices=["16:9", "9:16", "4:5", "1:1"], default="16:9")
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--pick-index", type=int, default=1, help="1-based candidate index for Pixabay video")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--select", type=int, default=0, help="Copy candidate #N into <id>.jpg after Vision QA")
    args = ap.parse_args()

    if args.select > 0:
        cand = os.path.join(args.out_dir, f"{args.id}_cands", f"{args.id}_{args.select:02d}.jpg")
        dst = os.path.join(args.out_dir, f"{args.id}.jpg")
        if not os.path.isfile(cand):
            sys.exit(f"[ERROR] Candidate not found: {cand}")
        with open(cand, "rb") as s, open(dst, "wb") as d:
            d.write(s.read())
        try:
            reg = _load_registry(args.out_dir)
            dh = _dhash(Image.open(dst))
            if dh not in reg["used_dhashes"]:
                reg["used_dhashes"].append(int(dh))
                _save_registry(args.out_dir, reg)
        except Exception:
            pass
        print(json.dumps({"ok": True, "scene_id": args.id, "selected_index": args.select, "selected": os.path.abspath(dst)}))
        return

    res = (
        hunt_video(args.id, args.query, args.out_dir, args.duration, args.aspect, pick_index=args.pick_index)
        if args.type == "video"
        else hunt_photo(args.id, args.query, args.out_dir, args.specific, args.aspect, args.exclude)
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
