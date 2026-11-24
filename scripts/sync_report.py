#!/usr/bin/env python3
"""
sync_report.py — Scene-by-Scene Speech Alignment & Media Relevance Auditor (Timeline Studio Kit v3.0)
Prints every scene's exact timeline window [start..end], asset filename, declared anchor_phrase, and
the LITERAL spoken audio inside that exact window from words.json / subtitles.srt so any mismatch or
off-topic generic stock clip is spotted immediately BEFORE building `.timeline`.
"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import audit_visuals  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Print 1-to-1 spoken audio vs visual scene alignment table")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--plan", default="")
    ap.add_argument("--only-motions", action="store_true")
    args = ap.parse_args()

    ep = args.plan or os.path.join(args.project_dir, "edit_plan.json")
    if not os.path.isfile(ep):
        sys.exit(f"[ERROR] Missing plan: {ep}")
    plan = json.load(open(ep, "r", encoding="utf-8"))
    words = audit_visuals._load_audio_words(args.project_dir)
    if not words:
        sys.exit("[ERROR] No words.json or subtitles.srt found in project_dir.")

    t = 0.0
    print(f"# SYNC REPORT — {plan.get('title', '')} | audio_end={words[-1]['end']:.2f}s | scenes={len(plan.get('visuals') or [])}")
    for i, v in enumerate(plan.get("visuals") or [], 1):
        has_se = v.get("start") is not None and v.get("end") is not None and float(v["end"]) > float(v["start"])
        dur = (float(v["end"]) - float(v["start"])) if has_se else float(v.get("duration") or 0.0)
        s0, s1 = t, t + dur
        t = s1
        is_m = v.get("kind") == "motion" or "motion/" in str(v.get("file", "")).replace("\\", "/")
        if args.only_motions and not is_m:
            continue
        spoken = " ".join(w["word"] for w in words if w["end"] > s0 + 0.15 and w["start"] < s1 - 0.15)
        drift_note = ""
        if v.get("start") is not None and abs(float(v["start"]) - s0) > 0.20:
            drift_note = f" [DRIFT {s0 - float(v['start']):+.2f}s!]"
        tag = "MOTION" if is_m else str(v.get("source") or v.get("kind") or "VISUAL").upper()
        print(f"{i:02d} [{tag:7s}] {s0:6.2f}s..{s1:6.2f}s ({dur:4.2f}s){drift_note} | {v.get('id')} | {os.path.basename(str(v.get('file','')))}")
        if v.get("anchor_phrase"):
            print(f"    ANCHOR: {v['anchor_phrase']}")
        print(f"    FALADO: {spoken}")
    print(f"# TIMELINE TOTAL: {t:.2f}s")


if __name__ == "__main__":
    main()
