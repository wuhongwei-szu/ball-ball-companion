#!/usr/bin/env python3
"""Shared configuration and helpers for the companion bot.

Private values live in config/bot.config.json (gitignored). The bot token and
openids are never stored there: they are read at runtime from the existing
cc-connect config and session files.
"""
import datetime
import json
import os
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get("BOT_CONFIG") or os.path.join(ROOT, "config", "bot.config.json")

DEFAULTS = {
    "work_dir": ROOT,
    "cc_data_dir": os.path.expanduser("~/.cc-connect"),
    "cc_project": "my-project",
    "cc_bin": "",
    "cc_config_file": "",
    "session_file": "",
    "master_session_id": "s1",
    "xi_session_id": "s2",
    "xi_platform_index": 2,
    "weixin_api_url": "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage",
    "weixin_cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",
    "sticker_dir": os.path.join(ROOT, "assets", "stickers"),
    "sticker_daily_limit": 12,
    "sticker_proactive_daily_limit": 0,
    "sticker_cooldown_seconds": 30,
    "proactive_daily_limit": 4,
    "proactive_min_gap_seconds": 300,
    "edge_tts_python": "",
    "edge_tts_voice": "zh-CN-XiaoxiaoNeural",
    "edge_tts_rate": "-8%",
    "edge_tts_pitch": "+5Hz",
    "edge_tts_volume": "-5%",
    "voice_dir": os.path.join(ROOT, "artifacts", "voice"),
    "proxy": "",
    "codex_home": os.path.join(ROOT, ".codex"),
    "codex_wrapper": os.path.join(ROOT, "bin", "codex.exe"),
    "bot_name": "Companion",
    "labels": {"master": "Owner", "xi": "Partner"},
}

PATH_KEYS = {
    "work_dir", "cc_data_dir", "cc_bin", "cc_config_file", "session_file",
    "sticker_dir", "edge_tts_python", "voice_dir", "codex_home", "codex_wrapper",
}


def _expand(value):
    if not isinstance(value, str):
        return value
    return os.path.expanduser(os.path.expandvars(value))


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_cfg = json.load(f)
    except FileNotFoundError:
        user_cfg = {}
    except Exception as exc:
        print(f"config error: {exc}")
        user_cfg = {}
    cfg.update(user_cfg)
    for key in PATH_KEYS:
        cfg[key] = _expand(cfg.get(key, ""))
    cfg["labels"] = {**DEFAULTS["labels"], **cfg.get("labels", {})}
    return cfg


def _derive_session_key(session_file, session_id):
    """Find the full weixin:dm:... key for an internal session id (s1/s2)."""
    try:
        with open(session_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    mapping = data.get("user_sessions", {})
    for key, ids in mapping.items():
        if isinstance(ids, list) and session_id in ids:
            return key
        if ids == session_id:
            return key
    return ""


def _parse_weixin_platforms(cc_config_file):
    """Return [(account_id, token), ...] for weixin platform blocks."""
    try:
        with open(cc_config_file, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return []
    blocks = text.split("[[projects.platforms]]")[1:]
    out = []
    for block in blocks:
        if not re.search(r'^\s*type\s*=\s*"weixin"', block, re.M):
            continue
        token = re.search(r'^\s*token\s*=\s*"([^"]+)"', block, re.M)
        account = re.search(r'^\s*account_id\s*=\s*"([^"]+)"', block, re.M)
        out.append((
            account.group(1) if account else "",
            token.group(1) if token else "",
        ))
    return out


CFG = load_config()
WORK_DIR = CFG["work_dir"]
DATA_DIR = CFG["cc_data_dir"]
PROJECT = CFG["cc_project"]
CC_BIN = CFG["cc_bin"]
CC_CONFIG_FILE = CFG["cc_config_file"]
SESSION_FILE = CFG["session_file"]
LABELS = CFG["labels"]
BOT_NAME = CFG.get("bot_name", "Companion")

MASTER_SESSION = _derive_session_key(SESSION_FILE, CFG.get("master_session_id", "s1"))
XI_SESSION = _derive_session_key(SESSION_FILE, CFG.get("xi_session_id", "s2"))

_weixin_platforms = _parse_weixin_platforms(CC_CONFIG_FILE)
_xi_index = int(CFG.get("xi_platform_index", 2))
if not (1 <= _xi_index <= len(_weixin_platforms)):
    _xi_index = 1
if _weixin_platforms:
    MASTER_BOT_ACCOUNT, MASTER_BOT_TOKEN = _weixin_platforms[0]
    XI_BOT_ACCOUNT, XI_BOT_TOKEN = _weixin_platforms[_xi_index - 1]
else:
    MASTER_BOT_ACCOUNT, MASTER_BOT_TOKEN = "", ""
    XI_BOT_ACCOUNT, XI_BOT_TOKEN = "", ""
MASTER_CONTEXT_TOKENS = (
    os.path.join(DATA_DIR, "weixin", PROJECT, MASTER_BOT_ACCOUNT, "context_tokens.json")
    if MASTER_BOT_ACCOUNT else ""
)
XI_CONTEXT_TOKENS = (
    os.path.join(DATA_DIR, "weixin", PROJECT, XI_BOT_ACCOUNT, "context_tokens.json")
    if XI_BOT_ACCOUNT else ""
)
WEIXIN_API_URL = CFG["weixin_api_url"]
WEIXIN_API_BASE = WEIXIN_API_URL.split("/ilink/bot/", 1)[0]
WEIXIN_CDN_BASE_URL = CFG["weixin_cdn_base_url"].rstrip("/")
STICKER_DIR = CFG["sticker_dir"]
EDGE_TTS_PYTHON = CFG["edge_tts_python"]
EDGE_TTS_VOICE = CFG["edge_tts_voice"]
EDGE_TTS_RATE = CFG["edge_tts_rate"]
EDGE_TTS_PITCH = CFG["edge_tts_pitch"]
EDGE_TTS_VOLUME = CFG["edge_tts_volume"]
VOICE_DIR = CFG["voice_dir"]
STICKER_DAILY_LIMIT = int(CFG.get("sticker_daily_limit", 12))
STICKER_PROACTIVE_DAILY_LIMIT = int(CFG.get("sticker_proactive_daily_limit", 0))
STICKER_COOLDOWN_SECONDS = int(CFG.get("sticker_cooldown_seconds", 30))
PROACTIVE_DAILY_LIMIT = int(CFG.get("proactive_daily_limit", 4))
PROACTIVE_MIN_GAP_SECONDS = int(CFG.get("proactive_min_gap_seconds", 300))
PROXY = CFG["proxy"]
CODEX_HOME = CFG["codex_home"]
CODEX_WRAPPER = CFG["codex_wrapper"]

MEMORY_DIR = os.path.join(WORK_DIR, "memory")
RAW_DIR = os.path.join(MEMORY_DIR, "raw")
RECENT_FILE = os.path.join(MEMORY_DIR, "recent_replies.md")
REMINDERS_INDEX = os.path.join(MEMORY_DIR, "reminders.json")
CARE_PLAN_FILE = os.path.join(MEMORY_DIR, ".care_plan.json")
CAPTURE_STATE_FILE = os.path.join(MEMORY_DIR, ".capture_state.json")
STICKER_USAGE_FILE = os.path.join(MEMORY_DIR, "sticker_usage.json")
OUTBOUND_STATE_FILE = os.path.join(MEMORY_DIR, "outbound_state.json")
THREADS_FILE = os.path.join(MEMORY_DIR, "THREADS.md")

RECENT_HEADER = (
    "# 最近说过的话（避免重复）\n\n"
    "> 最近 20 条回复，开新线程时读一遍，避免重复开头、句式和颜文字。\n"
)

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{20,}"),
    re.compile(r"(?i)(password|passwd|pwd|密码|口令)\s*[:=：]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}['\"]?"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


def redact(text):
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def load_json(path, default=None):
    """Load JSON, returning default on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_atomic(path, data):
    """Write JSON via a temp file + os.replace so a crash cannot truncate it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def session_peer(session):
    """Return the peer user id from a weixin:dm:<peer> session key."""
    if not session:
        return ""
    marker = "weixin:dm:"
    return session.split(marker, 1)[1] if marker in session else session


def read_context_token(path, peer):
    """Read a peer's cached ilink context token; empty when absent/expired."""
    data = load_json(path, {}) or {}
    token = data.get(peer, "") if isinstance(data, dict) else ""
    return token if isinstance(token, str) else ""


def _local_now():
    return datetime.datetime.now().astimezone()


def _outbound_entry(target):
    """Load/create today's outbound counters for one bot."""
    state = load_json(OUTBOUND_STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    today = _local_now().date().isoformat()
    target_state = state.get(target)
    if not isinstance(target_state, dict):
        target_state = {}
        state[target] = target_state
    entry = target_state.get(today)
    if not isinstance(entry, dict):
        entry = {"proactive": 0, "replies": 0, "last_proactive": ""}
        target_state[today] = entry
    cutoff = (_local_now().date() - datetime.timedelta(days=7)).isoformat()
    for key in list(target_state):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", key) or key < cutoff:
            del target_state[key]
    return state, entry


def proactive_remaining(target):
    """Return (remaining_messages, reason). 0 means wait; a huge number = unlimited."""
    if PROACTIVE_DAILY_LIMIT <= 0:
        return 10**9, ""
    _, entry = _outbound_entry(target)
    count = int(entry.get("proactive", 0) or 0)
    if count >= PROACTIVE_DAILY_LIMIT:
        return 0, f"今天主动消息已达本地安全上限 {PROACTIVE_DAILY_LIMIT} 条"
    if PROACTIVE_MIN_GAP_SECONDS > 0:
        last = entry.get("last_proactive", "")
        try:
            when = datetime.datetime.fromisoformat(last)
            if when.tzinfo is None:
                when = when.replace(tzinfo=_local_now().tzinfo)
        except Exception:
            when = None
        if when:
            elapsed = (_local_now() - when).total_seconds()
            if elapsed < PROACTIVE_MIN_GAP_SECONDS:
                return 0, (
                    f"距上条主动消息 {int(elapsed)} 秒，"
                    f"至少间隔 {PROACTIVE_MIN_GAP_SECONDS} 秒"
                )
    return PROACTIVE_DAILY_LIMIT - count, ""


def record_outbound(target, proactive=False, count=1):
    """Persist a successful outbound message count."""
    state, entry = _outbound_entry(target)
    if proactive:
        entry["proactive"] = int(entry.get("proactive", 0) or 0) + count
        entry["last_proactive"] = _local_now().isoformat(timespec="seconds")
    else:
        entry["replies"] = int(entry.get("replies", 0) or 0) + count
    save_json_atomic(OUTBOUND_STATE_FILE, state)


def append_raw(sid, text, role="assistant", ts=None):
    """Append one message to memory/raw/{sid}/YYYY-MM-DD.md."""
    text = redact(text)
    now = datetime.datetime.now()
    if ts and len(ts) >= 16:
        date = ts[:10]
        hm = ts[11:16]
    else:
        date = now.strftime("%Y-%m-%d")
        hm = now.strftime("%H:%M")
    outdir = os.path.join(RAW_DIR, sid)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, date + ".md")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n## {date} {hm} [{role}]\n{text}\n")


def append_recent(text, ts=None):
    """Keep the last 20 assistant messages for cross-session anti-repetition."""
    text = redact(text)
    snippet = " ".join(text.split())[:120]
    if ts and len(ts) >= 16:
        stamp = ts[5:10] + " " + ts[11:16]
    else:
        stamp = datetime.datetime.now().strftime("%m-%d %H:%M")
    line = f"- [{stamp}] {snippet}"
    try:
        with open(RECENT_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    items = [l for l in lines if l.startswith("- ")]
    items = [l for l in items if snippet not in l]
    items.append(line)
    items = items[-20:]
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(RECENT_FILE, "w", encoding="utf-8") as f:
        f.write(RECENT_HEADER + "\n" + "\n".join(items) + "\n")


def require(value, name):
    if not value:
        raise SystemExit(f"缺少配置项 {name}，请检查 config/bot.config.json 和 cc-connect 配置。")


def run_cc(args, timeout=30):
    """Run the cc-connect CLI with --data-dir appended."""
    require(CC_BIN, "cc_bin")
    cmd = [CC_BIN] + list(args) + ["--data-dir", DATA_DIR]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
