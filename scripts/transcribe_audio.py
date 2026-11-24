#!/usr/bin/env python3
"""
transcribe_audio.py — Standalone Free Word-Level Transcriber (Timeline Studio Kit v1.0)
Generates `words.json`, `subtitles.srt`, and token-lean `words_compact.txt` (~75 lines / 10 min)
using 100% free local `faster-whisper` (auto CUDA->CPU fallback) or instant `--from-srt`.
"""
import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import _runtime_env  # noqa: E402

_runtime_env.init()
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
import requests  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
VOICE_MEMO_EXTS = {".opus", ".oga", ".ogg", ".aac", ".amr", ".3gp", ".wma", ".caf", ".flac"}


def ensure_audio_file(input_path: str, out_dir: str) -> str:
    ext = os.path.splitext(input_path)[1].lower()
    if ext not in VIDEO_EXTS and ext not in VOICE_MEMO_EXTS:
        return input_path
    os.makedirs(out_dir, exist_ok=True)
    wav_out = os.path.join(out_dir, "extracted_audio.wav")
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", input_path, "-vn", "-ar", "44100", "-c:a", "pcm_s16le", wav_out]
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.isfile(wav_out):
        raise RuntimeError(f"FFmpeg audio extraction failed: {res.stderr[-400:]}")
    return wav_out


def _ts_to_ms(ts: str) -> int:
    ts = ts.strip().replace(".", ",")
    hms, ms = ts.split(",")
    h, m, s = [int(x) for x in hms.split(":")]
    return ((h * 3600 + m * 60 + s) * 1000) + int(ms[:3].ljust(3, "0"))


def _ms_to_srt_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, rem = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def parse_srt_to_words(srt_path: str) -> list:
    raw = open(srt_path, "r", encoding="utf-8-sig", errors="ignore").read()
    words = []
    for b in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln.strip() for ln in b.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        ts_line = lines[1] if "-->" in lines[1] else (lines[0] if "-->" in lines[0] else None)
        if not ts_line:
            continue
        txt_start = 2 if ts_line == lines[1] else 1
        text = re.sub(r"<[^>]+>", "", " ".join(lines[txt_start:])).strip()
        if not text:
            continue
        p0, p1 = [x.strip() for x in ts_line.split("-->")[:2]]
        s_ms, e_ms = _ts_to_ms(p0), _ts_to_ms(p1)
        tokens = text.split()
        dur = max(1, e_ms - s_ms)
        total_chars = max(1, sum(len(t) for t in tokens))
        cur = s_ms
        for idx, tok in enumerate(tokens):
            share = int(round(dur * (len(tok) / total_chars)))
            w_end = e_ms if idx == len(tokens) - 1 else min(e_ms, cur + max(20, share))
            words.append({"word": tok, "start_ms": cur, "end_ms": max(cur + 15, w_end), "confidence": 1.0})
            cur = w_end
    return words


def write_srt_from_words(words: list, srt_path: str, max_words_per_cue: int = 5):
    if not words:
        return
    cues, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= 2 and (w["start_ms"] - buf[-2]["end_ms"] > 450):
            last = buf.pop()
            cues.append(buf)
            buf = [last]
            continue
        if len(buf) >= max_words_per_cue or w["word"].endswith((".", "!", "?", ":", ";")):
            cues.append(buf)
            buf = []
    if buf:
        cues.append(buf)
    lines = []
    for idx, chunk in enumerate(cues, 1):
        s_ms = chunk[0]["start_ms"]
        e_ms = max(s_ms + 120, chunk[-1]["end_ms"])
        lines.append(f"{idx}\n{_ms_to_srt_ts(s_ms)} --> {_ms_to_srt_ts(e_ms)}\n{' '.join(x['word'] for x in chunk)}\n")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_compact_words(words: list, compact_path: str, window_ms: int = 8000):
    if not words:
        return
    lines = ["# Compact Word-Timestamp Index (word@start_s) — Read THIS instead of words.json or raw audio!"]
    chunk, win_start = [], words[0]["start_ms"]
    for w in words:
        chunk.append(w)
        elapsed = w["end_ms"] - win_start
        if elapsed >= window_ms or (elapsed >= 4500 and str(w.get("word", "")).endswith((".", "!", "?", ";"))):
            s0, e0 = chunk[0]["start_ms"], chunk[-1]["end_ms"]
            lines.append(f"[{s0}ms..{e0}ms] " + " ".join(f"{x['word']}@{x['start_ms']/1000.0:.2f}" for x in chunk))
            chunk, win_start = [], e0
    if chunk:
        s0, e0 = chunk[0]["start_ms"], chunk[-1]["end_ms"]
        lines.append(f"[{s0}ms..{e0}ms] " + " ".join(f"{x['word']}@{x['start_ms']/1000.0:.2f}" for x in chunk))
    with open(compact_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _prepare_windows_cuda_dlls() -> bool:
    if os.name != "nt":
        return True
    site_dirs = [p for p in sys.path if "site-packages" in p.lower() and os.path.isdir(p)]
    for sd in site_dirs:
        for rel in (os.path.join("nvidia", "cublas", "bin"), os.path.join("nvidia", "cudnn", "bin"), os.path.join("torch", "lib")):
            d = os.path.join(sd, rel)
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    for dll in ("cublas64_12.dll", "cublas64_11.dll"):
        try:
            ctypes.WinDLL(dll)
            return True
        except OSError:
            continue
    return False


def transcribe_local(audio_path: str, lang: str = "auto", model_size: str = "small", prompt: str | None = None) -> list:
    from faster_whisper import WhisperModel
    lang_arg = None if (not lang or lang.lower() == "auto") else lang.split("-")[0].lower()
    device, compute = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0 and _prepare_windows_cuda_dlls():
            device, compute = "cuda", "float16"
    except Exception:
        pass

    def _pass(dev, comp):
        kw = {"device": dev, "compute_type": comp}
        if dev == "cpu":
            kw["cpu_threads"] = max(2, min(12, os.cpu_count() or 4))
        try:
            model = WhisperModel(model_size, local_files_only=True, **kw)
        except Exception:
            model = WhisperModel(model_size, **kw)
        segs_gen, _ = model.transcribe(
            audio_path, language=lang_arg, initial_prompt=prompt or None,
            word_timestamps=True, vad_filter=True, vad_parameters={"min_silence_duration_ms": 280},
        )
        words = []
        for seg in list(segs_gen):
            if getattr(seg, "words", None):
                for w in seg.words:
                    tok = (w.word or "").strip()
                    if tok:
                        s_ms = int(round(w.start * 1000))
                        e_ms = max(s_ms + 20, int(round(w.end * 1000)))
                        words.append({"word": tok, "start_ms": s_ms, "end_ms": e_ms, "confidence": round(float(getattr(w, "probability", 0.95)), 4)})
            else:
                toks = (seg.text or "").strip().split()
                if toks:
                    s_ms, e_ms = int(round(seg.start * 1000)), max(int(round(seg.start * 1000)) + 50, int(round(seg.end * 1000)))
                    step = max(20, (e_ms - s_ms) // len(toks))
                    for i, tok in enumerate(toks):
                        ws = s_ms + i * step
                        words.append({"word": tok, "start_ms": ws, "end_ms": e_ms if i == len(toks) - 1 else ws + step, "confidence": 0.9})
        return words

    if device == "cuda":
        try:
            return _pass("cuda", "float16")
        except Exception:
            pass
    return _pass("cpu", "int8")


def transcribe_groq(audio_path: str, api_key: str, lang: str = "auto", prompt: str | None = None) -> list:
    send_path, tmp_mp3 = audio_path, None
    if os.path.getsize(audio_path) > 16 * 1024 * 1024:
        fd, tmp_mp3 = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", tmp_mp3], capture_output=True, check=True)
        send_path = tmp_mp3
    try:
        data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "timestamp_granularities[]": "word"}
        if lang and lang.lower() != "auto":
            data["language"] = lang.split("-")[0].lower()
        if prompt:
            data["prompt"] = prompt[:800]
        with open(send_path, "rb") as f:
            r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", headers={"Authorization": f"Bearer {api_key}"}, data=data, files={"file": (os.path.basename(send_path), f)}, timeout=180)
        r.raise_for_status()
        return [{"word": (w.get("word") or "").strip(), "start_ms": int(round(float(w["start"]) * 1000)), "end_ms": max(int(round(float(w["start"]) * 1000)) + 20, int(round(float(w["end"]) * 1000))), "confidence": 0.98} for w in r.json().get("words", []) if (w.get("word") or "").strip()]
    finally:
        if tmp_mp3 and os.path.isfile(tmp_mp3):
            os.remove(tmp_mp3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--from-srt", default=None)
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--prompt", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.audio):
        sys.exit(f"[ERROR] Input not found: {args.audio}")
    os.makedirs(args.out_dir, exist_ok=True)
    words_p = os.path.join(args.out_dir, "words.json")
    srt_p = os.path.join(args.out_dir, "subtitles.srt")
    compact_p = os.path.join(args.out_dir, "words_compact.txt")

    if args.from_srt and os.path.isfile(args.from_srt):
        words = parse_srt_to_words(args.from_srt)
        engine = "srt"
    else:
        audio_f = ensure_audio_file(args.audio, args.out_dir)
        groq_k = os.environ.get("GROQ_API_KEY", "").strip()
        words, engine = None, "local:faster-whisper"
        if groq_k:
            try:
                words = transcribe_groq(audio_f, groq_k, args.lang, args.prompt)
                engine = "cloud:groq"
            except Exception:
                words = None
        if not words:
            words = transcribe_local(audio_f, args.lang, args.whisper_model, args.prompt)

    with open(words_p, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
    write_srt_from_words(words, srt_p)
    write_compact_words(words, compact_p)
    dur = (words[-1]["end_ms"] / 1000.0) if words else 0.0
    print(json.dumps({"ok": True, "engine": engine, "words": len(words), "duration_s": round(dur, 2), "compact_path": os.path.abspath(compact_p), "srt_path": os.path.abspath(srt_p)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
