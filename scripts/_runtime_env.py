#!/usr/bin/env python3
"""
_runtime_env.py (v4.1 Portable) — Cross-Platform PATH, Workspace & Key Loader
Zero hardcoded usernames or agent IDs. Works identically across Windows, macOS,
Linux, OpenBot (any shared copy), Claude Code, Codex, and Cursor.
Loads optional keys (PIXABAY_API_KEY, GROQ_API_KEY, etc.) into RAM from OpenBot
Vault or local .env without ever printing or copying secret values.
"""
import glob
import os
import re
import shutil
import site
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

KNOWN_KEYS = (
    "PIXABAY_API_KEY",
    "PEXELS_API_KEY",
    "FREESOUND_API_KEY",
    "TMDB_API_KEY",
    "GROQ_API_KEY",
    "ASSEMBLYAI_API_KEY",
    "ELEVENLABS_API_KEY",
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def detect_agent_workspace(script_dir: str = SCRIPT_DIR) -> str:
    env_ws = os.environ.get("TIMELINE_WORKSPACE", "").strip()
    if env_ws and os.path.isdir(env_ws):
        return os.path.abspath(env_ws)
    cur = os.path.abspath(script_dir)
    for _ in range(8):
        base = os.path.basename(cur).lower()
        if base in (".agents", ".claude", ".runtime"):
            parent = os.path.dirname(cur)
            if os.path.isdir(parent):
                return parent
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return os.path.abspath(os.getcwd())


def detect_timeline_studio_dir(workspace: str = "", script_dir: str = SCRIPT_DIR) -> str:
    ws = workspace or detect_agent_workspace(script_dir)
    home = os.path.expanduser("~")
    candidates = [
        os.environ.get("TIMELINE_STUDIO_DIR", "").strip(),
        os.path.join(ws, ".runtime", "timeline-studio"),
        os.path.join(home, "OpenBot", "Shared", "timeline-studio"),
        os.path.join(os.path.dirname(script_dir), "timeline-studio"),
        os.path.join(home, ".timeline-studio-kit", "timeline-studio"),
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "scripts", "timeline-command.mjs")):
            return os.path.abspath(c)
    return os.path.join(ws, ".runtime", "timeline-studio")


def detect_motion_runtime_dir(workspace: str = "", script_dir: str = SCRIPT_DIR) -> str:
    ws = workspace or detect_agent_workspace(script_dir)
    home = os.path.expanduser("~")
    candidates = [
        os.environ.get("MOTION_RUNTIME_DIR", "").strip(),
        os.environ.get("MOTION_LAB_RUNTIME_DIR", "").strip(),
        os.path.join(ws, ".runtime"),
        os.path.join(ws, ".runtime", "motion-runtime"),
        os.path.join(home, "OpenBot", "Shared", "motion-video-lab", "runtime"),
        os.path.join(os.path.dirname(script_dir), "motion-runtime"),
        os.path.join(home, ".timeline-studio-kit", "motion-runtime"),
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "node_modules", "playwright")):
            return os.path.abspath(c)
    return os.path.join(ws, ".runtime")


def detect_sfx_dir(script_dir: str = SCRIPT_DIR) -> str:
    for cand in (
        os.path.join(os.path.dirname(script_dir), "assets", "sfx"),
        os.path.join(script_dir, "sfx"),
    ):
        if os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.path.join(os.path.dirname(script_dir), "assets", "sfx")


AGENT_WORKSPACE = detect_agent_workspace(SCRIPT_DIR)
TIMELINE_STUDIO_DIR = detect_timeline_studio_dir(AGENT_WORKSPACE, SCRIPT_DIR)
MOTION_LAB_RUNTIME_DIR = detect_motion_runtime_dir(AGENT_WORKSPACE, SCRIPT_DIR)
KIT_SFX_DIR = detect_sfx_dir(SCRIPT_DIR)


def ensure_user_site():
    try:
        user_site = site.getusersitepackages()
        if user_site and os.path.isdir(user_site) and user_site not in sys.path:
            sys.path.append(user_site)
    except Exception:
        pass
    venv_dir = os.path.join(AGENT_WORKSPACE, ".runtime", ".venv")
    if os.path.isdir(venv_dir):
        for pat in (
            os.path.join(venv_dir, "Lib", "site-packages"),
            os.path.join(venv_dir, "lib", "python*", "site-packages"),
        ):
            for sp in glob.glob(pat):
                if os.path.isdir(sp) and sp not in sys.path:
                    sys.path.insert(0, sp)


def ensure_runtime_paths():
    ensure_user_site()
    extra_dirs = []
    venv_bin = os.path.join(
        AGENT_WORKSPACE, ".runtime", ".venv", "Scripts" if os.name == "nt" else "bin"
    )
    if os.path.isdir(venv_bin):
        extra_dirs.append(venv_bin)

    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        if local_app:
            extra_dirs.append(os.path.join(local_app, "Microsoft", "WinGet", "Links"))
            for pattern in ("Gyan.FFmpeg*", "FFmpeg*", "BtbN.FFmpeg*", "OpenJS.NodeJS*", "Git.Git*"):
                for pkg_dir in glob.glob(os.path.join(local_app, "Microsoft", "WinGet", "Packages", pattern)):
                    for root_d, _, files_d in os.walk(pkg_dir):
                        low = {f.lower() for f in files_d}
                        if low & {"ffmpeg.exe", "ffprobe.exe", "node.exe", "git.exe"}:
                            extra_dirs.append(root_d)
            for py_scripts in glob.glob(os.path.join(local_app, "Programs", "Python", "Python*", "Scripts")):
                extra_dirs.append(py_scripts)
        if appdata:
            for py_scripts in glob.glob(os.path.join(appdata, "Python", "Python*", "Scripts")):
                extra_dirs.append(py_scripts)
        extra_dirs.extend([
            r"C:\ffmpeg\bin",
            os.path.join(prog_files, "nodejs"),
            os.path.join(prog_files, "Git", "cmd"),
        ])
    else:
        home = os.path.expanduser("~")
        extra_dirs.extend([
            "/opt/homebrew/bin",
            "/usr/local/bin",
            os.path.join(home, ".local", "bin"),
            os.path.join(home, ".nvm", "current", "bin"),
        ])

    cur_path = os.environ.get("PATH", "")
    cur_set = {os.path.normcase(os.path.normpath(p)) for p in cur_path.split(os.pathsep) if p}
    to_add = []
    for d in extra_dirs:
        if d and os.path.isdir(d):
            norm = os.path.normcase(os.path.normpath(d))
            if norm not in cur_set:
                cur_set.add(norm)
                to_add.append(d)
    if to_add:
        os.environ["PATH"] = os.pathsep.join(to_add) + (os.pathsep + cur_path if cur_path else "")


def _detect_agent_ids(extra_agent_id: str = "") -> list:
    agent_ids = []
    rx = re.compile(r"[\\/]Agents[\\/](agent-[0-9a-fA-F-]+)(?:[\\/]|$)")
    for src in (extra_agent_id, os.environ.get("OPENBOT_AGENT_ID", ""), os.getcwd(), SCRIPT_DIR, AGENT_WORKSPACE):
        if not src:
            continue
        if src.startswith("agent-") and "/" not in src and "\\" not in src:
            aid = src
        else:
            m = rx.search(src)
            aid = m.group(1) if m else ""
        if aid and aid not in agent_ids:
            agent_ids.append(aid)
    return agent_ids


def _openbot_key_dirs(extra_agent_id: str = "") -> list:
    dirs = []
    custom = os.environ.get("OPENBOT_VAULT_DIR", "").strip()
    if custom:
        dirs.append(custom)

    bases = []
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        bases.append(os.path.join(appdata, "OpenBot", "agent-api-keys"))
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        bases.append(os.path.join(home, "Library", "Application Support", "OpenBot", "agent-api-keys"))
    bases.append(os.path.join(home, ".config", "OpenBot", "agent-api-keys"))

    agent_ids = _detect_agent_ids(extra_agent_id)
    for b in bases:
        for aid in agent_ids:
            dirs.append(os.path.join(b, ".vault", aid))
            dirs.append(os.path.join(b, aid))
        dirs.append(os.path.join(b, ".vault"))
        dirs.append(b)
    return dirs


def autoload_known_keys(agent_id: str = ""):
    env_candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(AGENT_WORKSPACE, ".env"),
        os.path.join(TIMELINE_STUDIO_DIR, ".env"),
    ]
    for env_p in env_candidates:
        if os.path.isfile(env_p):
            try:
                with open(env_p, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        ln = line.strip()
                        if ln and not ln.startswith("#") and "=" in ln:
                            k, v = ln.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k in KNOWN_KEYS and v and not os.environ.get(k):
                                os.environ[k] = v
            except Exception:
                pass

    for vd in _openbot_key_dirs(agent_id):
        if os.path.isdir(vd):
            for k in KNOWN_KEYS:
                if os.environ.get(k):
                    continue
                kp = os.path.join(vd, k)
                if os.path.isfile(kp):
                    try:
                        with open(kp, "r", encoding="utf-8", errors="ignore") as fh:
                            val = fh.read().strip()
                        if val:
                            os.environ[k] = val
                    except Exception:
                        pass


def apply_vault_key_args():
    argv = sys.argv
    cleaned = [argv[0]]
    i = 1
    while i < len(argv):
        if argv[i] == "--vault-key" and i + 2 < len(argv):
            var_name = argv[i + 1].strip()
            file_path = argv[i + 2].strip()
            if var_name and file_path and os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    secret_val = fh.read().strip()
                if secret_val:
                    os.environ[var_name] = secret_val
            i += 3
            continue
        cleaned.append(argv[i])
        i += 1
    sys.argv[:] = cleaned


def find_python_executable() -> str:
    venv_py = os.path.join(
        AGENT_WORKSPACE,
        ".runtime",
        ".venv",
        "Scripts" if os.name == "nt" else "bin",
        "python.exe" if os.name == "nt" else "python",
    )
    if os.path.isfile(venv_py):
        return venv_py
    return sys.executable or shutil.which("python3") or shutil.which("python") or "python"


def init(agent_id: str = ""):
    ensure_runtime_paths()
    autoload_known_keys(agent_id)
    apply_vault_key_args()
