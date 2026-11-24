# Timeline Studio Kit (v4.2 Portable)

Portable, self-installing video editing & code-drawn motion graphics engine for **[Timeline Studio](https://github.com/MartinDelophy/ai-video-editor)** (`.timeline` v3), designed to work seamlessly with the **Editor-Timeline-Studio** AI agent on Windows, macOS, and Linux.

## What Is Included
- **`scripts/install.ps1` & `scripts/install.sh`** — One-command automatic environment installers (Python 3, Node.js LTS, FFmpeg, `yt-dlp`, offline `faster-whisper`, Playwright headless renderer, GSAP, Three.js, p5.brush, Natural Earth maps, and Timeline Studio CLI).
- **`scripts/doctor.py`** — Cross-platform readiness check (`READY` / `MISSING_DEPS`).
- **`scripts/transcribe_audio.py`** — Offline word-level audio transcription (`words_compact.txt` + `subtitles.srt`).
- **`scripts/media_hunter.py` & `scripts/youtube_hunter.py`** — Visual-first YouTube clipping, parallel HD photo sourcing, and optional free Pixabay HD stock API with anti-duplicate tracking.
- **`scripts/stage_photo.py`** — 6-style editorial framing engine for vertical/archival photos.
- **`scripts/motion_runner.mjs`, `scripts/preview_motion.mjs`, `scripts/map_kit.mjs`** — Deterministic 1080p code-drawn motion graphics & real Natural Earth cartography renderer.
- **`scripts/audit_visuals.py`, `scripts/sync_report.py`, `scripts/build_timeline.mjs`** — Strict editorial QA gate and native `.timeline` v3 archive builder (transitions, organic photo keyframes, sepia-free color grades, CC0 SFX, chapter markers).
- **`assets/sfx/`** — Curated CC0 editorial sound effects.
- **`references/motion-craft-recipes.md`** — Reference motion craft patterns.

## Quick Setup (Automatic)
When using the shared **Editor-Timeline-Studio** agent in OpenBot, the agent downloads and installs this kit automatically on first use — no manual setup required.

## Optional Free API Key
- `PIXABAY_API_KEY` (100% free at https://pixabay.com/api/docs/) — Optional; enables Pixabay HD stock videos alongside YouTube clipping and HD photo search. Without any key, the kit still runs 100% free.

## License
MIT License. Bundled sound effects in `assets/sfx/` are CC0 (Public Domain).
