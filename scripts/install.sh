#!/usr/bin/env bash
# ============================================================================
# Timeline Studio Kit v4.2 — Portable Automatic macOS & Linux Installer
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve agent workspace root (walks up from .runtime/kit/scripts, .agents/skills/..., or .claude/skills/...)
WORKSPACE="$SCRIPT_DIR"
for _ in 1 2 3 4 5 6 7 8; do
  LEAF="$(basename "$WORKSPACE")"
  if [[ "$LEAF" == ".agents" || "$LEAF" == ".claude" || "$LEAF" == ".runtime" ]]; then
    WORKSPACE="$(dirname "$WORKSPACE")"
    break
  fi
  PARENT="$(dirname "$WORKSPACE")"
  if [[ "$PARENT" == "$WORKSPACE" ]]; then
    WORKSPACE="$(pwd)"
    break
  fi
  WORKSPACE="$PARENT"
done

RUNTIME_DIR="$WORKSPACE/.runtime"
mkdir -p "$RUNTIME_DIR"

echo "======================================================================"
echo " Timeline Studio Kit v4.2 — macOS / Linux Automatic Setup"
echo " Workspace: $WORKSPACE"
echo "======================================================================"

install_pkg() {
  local cmd_name="$1"
  local brew_pkg="$2"
  local apt_pkg="$3"
  local optional="${4:-0}"
  if command -v "$cmd_name" >/dev/null 2>&1; then
    echo "  [OK] $cmd_name found: $(command -v "$cmd_name")"
    return
  fi
  echo "  [INSTALL] Installing $cmd_name..."
  if command -v brew >/dev/null 2>&1; then
    brew install "$brew_pkg" || [[ "$optional" == "1" ]]
  elif command -v apt-get >/dev/null 2>&1; then
    (sudo apt-get update -y && sudo apt-get install -y $apt_pkg) || [[ "$optional" == "1" ]]
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y $apt_pkg || [[ "$optional" == "1" ]]
  else
    if [[ "$optional" == "1" ]]; then
      echo "  [WARN] Optional $cmd_name unavailable; continuing with fallback."
      return
    fi
    echo "  [ERROR] Please install '$cmd_name' manually and re-run install.sh"
    exit 1
  fi
}

echo ""
echo "[1/5] Checking System Binaries (Python 3, Node.js, FFmpeg, Git)..."
install_pkg python3 python "python3 python3-venv python3-pip"
install_pkg node node "nodejs npm"
install_pkg ffmpeg ffmpeg "ffmpeg"
install_pkg git git "git" 1

echo ""
echo "[2/5] Setting up Python Virtual Environment (.runtime/.venv)..."
VENV_PY="$RUNTIME_DIR/.venv/bin/python"
if python3 -B -c "import PIL, requests, faster_whisper, shutil, sys; sys.exit(0 if shutil.which('yt-dlp') else 1)" 2>/dev/null; then
  echo "  [OK] Existing Python 3 already has all required packages + yt-dlp."
  PY_EXE="python3"
else
  if [[ ! -x "$VENV_PY" ]]; then
    python3 -m venv "$RUNTIME_DIR/.venv"
  fi
  "$VENV_PY" -B -m pip install --upgrade pip --quiet
  "$VENV_PY" -B -m pip install -r "$SCRIPT_DIR/requirements.txt"
  PY_EXE="$VENV_PY"
fi

echo ""
echo "[3/5] Setting up Timeline Studio CLI & CC0 SFX (MartinDelophy/ai-video-editor)..."
SHARED_TS="$HOME/OpenBot/Shared/timeline-studio"
LOCAL_TS="$RUNTIME_DIR/timeline-studio"
if [[ -f "$SHARED_TS/scripts/timeline-command.mjs" ]]; then
  echo "  [OK] Reusing existing Timeline Studio at $SHARED_TS"
elif [[ -f "$LOCAL_TS/scripts/timeline-command.mjs" ]]; then
  echo "  [OK] Timeline Studio already present at $LOCAL_TS"
else
  if command -v git >/dev/null 2>&1 && git clone --depth 1 "https://github.com/MartinDelophy/ai-video-editor.git" "$LOCAL_TS"; then
    echo "  [OK] Timeline Studio cloned to $LOCAL_TS"
  else
    echo "  [ZIP] Downloading MartinDelophy/ai-video-editor ZIP fallback..."
    rm -rf "$RUNTIME_DIR/_ts_extract" "$LOCAL_TS"
    curl -fsSL "https://github.com/MartinDelophy/ai-video-editor/archive/refs/heads/main.zip" -o "$RUNTIME_DIR/_ts_tmp.zip"
    unzip -qo "$RUNTIME_DIR/_ts_tmp.zip" -d "$RUNTIME_DIR/_ts_extract"
    mv "$RUNTIME_DIR/_ts_extract"/* "$LOCAL_TS"
    rm -rf "$RUNTIME_DIR/_ts_extract" "$RUNTIME_DIR/_ts_tmp.zip"
    echo "  [OK] Timeline Studio extracted to $LOCAL_TS"
  fi
fi

echo ""
echo "[4/5] Setting up Motion Graphics, Natural Earth Maps & CLI Node Runtime..."
if [[ ! -d "$RUNTIME_DIR/node_modules/playwright" || ! -d "$RUNTIME_DIR/node_modules/world-atlas" || ! -d "$RUNTIME_DIR/node_modules/fflate" ]]; then
  cp "$SCRIPT_DIR/runtime-package.json" "$RUNTIME_DIR/package.json"
  (cd "$RUNTIME_DIR" && npm install --no-audit --no-fund)
else
  echo "  [OK] Local Node runtime already installed at $RUNTIME_DIR"
fi

HAS_BROWSER=0
for b in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
         "/Applications/Chromium.app/Contents/MacOS/Chromium" \
         "/usr/bin/google-chrome" "/usr/bin/chromium" "/usr/bin/chromium-browser"; do
  if [[ -x "$b" ]]; then
    HAS_BROWSER=1
    echo "  [OK] System browser detected: $b"
    break
  fi
done
if [[ "$HAS_BROWSER" -eq 0 ]]; then
  echo "  [BROWSER] Installing Playwright Chromium..."
  (cd "$RUNTIME_DIR" && npx playwright install chromium)
fi

echo ""
echo "[5/5] Warming up local offline Whisper model & running final Doctor check..."
"$PY_EXE" -B -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); print('  [OK] faster-whisper small model cached.')" || \
  echo "  [WARN] Could not pre-cache Whisper model right now (will download automatically on first audio)."

"$PY_EXE" -B "$SCRIPT_DIR/doctor.py"
echo ""
echo "[DONE] Timeline Studio Kit v4.2 is READY!"
