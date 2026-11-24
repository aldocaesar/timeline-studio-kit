#!/usr/bin/env python3
"""
creator_memory.py (v2.0) — Persistent Anti-Clone Style & Channel Memory (Timeline Studio Kit)
Remembers channel preferences (aspect, captions, tone, durable rules) and logs the last 5 videos'
full visual identity (palette, bg_mood, motion_paradigm, portrait_staging_mix, fonts, hook_concept)
so consecutive videos NEVER repeat the same motion design or photo-framing aesthetic.
"""
import argparse
import datetime
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import _runtime_env  # noqa: E402

DEFAULT_MEM_FILE = os.path.join(_runtime_env.AGENT_WORKSPACE, ".timeline-creator-memory.json")


def _default() -> dict:
    return {
        "version": "2.1",
        "updated_at": "",
        "profile": {"default_aspect_ratio": "16:9", "language": "auto", "captions_default": False, "accent_color": "", "pixabay_preference": "default"},
        "style_rules": [],
        "recent_projects": [],
    }


def load_mem(path: str) -> dict:
    base = _default()
    if os.path.isfile(path):
        try:
            raw = json.load(open(path, "r", encoding="utf-8"))
            if isinstance(raw, dict):
                base["profile"].update(raw.get("profile") or {})
                for k in ("style_rules", "recent_projects"):
                    if isinstance(raw.get(k), list):
                        base[k] = raw[k]
                base["updated_at"] = str(raw.get("updated_at") or "")
        except Exception:
            pass
    return base


def save_mem(path: str, data: dict):
    data["version"] = "2.0"
    data["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_MEM_FILE)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--remember", action="append", default=[])
    ap.add_argument("--aspect-ratio", choices=["16:9", "9:16", "4:5", "1:1"])
    ap.add_argument("--captions", choices=["on", "off"])
    ap.add_argument("--set-pixabay-skipped", action="store_true", help="Remember that the user chose to skip optional Pixabay API setup")
    ap.add_argument("--clear-pixabay-skipped", action="store_true", help="Reset Pixabay onboarding preference to default")
    ap.add_argument("--record-plan", default="", help="Path to edit_plan.json to record into anti-clone history")
    args = ap.parse_args()

    mem = load_mem(args.file)
    changed = False
    if args.aspect_ratio:
        mem["profile"]["default_aspect_ratio"] = args.aspect_ratio
        changed = True
    if args.captions:
        mem["profile"]["captions_default"] = args.captions == "on"
        changed = True
    if args.set_pixabay_skipped:
        mem["profile"]["pixabay_preference"] = "skipped"
        changed = True
    if args.clear_pixabay_skipped:
        mem["profile"]["pixabay_preference"] = "default"
        changed = True
    for r in args.remember:
        rc = " ".join(r.strip().split())
        if rc and rc.lower() not in {x.lower() for x in mem["style_rules"]}:
            mem["style_rules"].append(rc[:220])
            mem["style_rules"] = mem["style_rules"][-20:]
            changed = True
    if args.record_plan and os.path.isfile(args.record_plan):
        p = json.load(open(args.record_plan, "r", encoding="utf-8"))
        dna = p.get("style_dna") or {}
        entry = {
            "title": str(p.get("title") or os.path.basename(os.path.dirname(args.record_plan)))[:80],
            "video_type": str(p.get("video_type") or "documentary"),
            "ratio": str(p.get("ratioId") or "16:9"),
            "accent": str(dna.get("accent") or ""),
            "palette": dna.get("palette") or [],
            "bg_mood": str(dna.get("bg_mood") or ""),
            "motion_paradigm": str(dna.get("motion_paradigm") or ""),
            "portrait_staging_mix": dna.get("portrait_staging_mix") or [],
            "fonts": dna.get("fonts") or [],
            "hook_concept": str(dna.get("hook_concept") or "")[:120],
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        }
        mem["recent_projects"] = [x for x in mem["recent_projects"] if x.get("title") != entry["title"]]
        mem["recent_projects"].insert(0, entry)
        mem["recent_projects"] = mem["recent_projects"][:8]
        changed = True

    if changed:
        save_mem(args.file, mem)

    prof = mem["profile"]
    lines = [
        f"[CREATOR MEMORY v2.0] aspect={prof['default_aspect_ratio']} | captions={'on' if prof['captions_default'] else 'off'}"
        + (f" | locked_accent={prof['accent_color']}" if prof.get("accent_color") else " | palette=fresh_per_video")
    ]
    if mem["style_rules"]:
        lines.append("  Rules: " + " ; ".join(mem["style_rules"][-8:]))
    recent = mem["recent_projects"][:3]
    if recent:
        lines.append("  ANTI-CLONE BLOCKLIST (Last 3 Videos — DO NOT repeat palette, bg_mood, motion_paradigm, font pair, or portrait frame style!):")
        for idx, item in enumerate(recent, 1):
            lines.append(
                f"    #{idx} {item.get('title')} ({item.get('video_type')}, {item.get('ratio')}) | "
                f"accent={item.get('accent')} | bg_mood={item.get('bg_mood') or 'unspecified'} | "
                f"paradigm={item.get('motion_paradigm') or 'unspecified'} | fonts={item.get('fonts')} | "
                f"staging={item.get('portrait_staging_mix') or []} | hook={item.get('hook_concept')}"
            )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
