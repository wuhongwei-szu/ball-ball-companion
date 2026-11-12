#!/usr/bin/env python3
"""Show the most recently active cc-connect session for master or xi.

Active internal session ids rotate (s9/s10/...), so documentation must not
hard-code s1/s2. This helper resolves the subject's platform dm key from
config/shared_memory.json, finds the newest matching internal session in the
cc-connect session file, then delegates to `cc-connect sessions show`.

Usage:
    python -X utf8 tools/view_session.py master -n 10
    python -X utf8 tools/view_session.py xi -n 10
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c


def _load_subject(target):
    path = Path(c.WORK_DIR) / "config" / "shared_memory.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    subject = data.get("subjects", {}).get(target)
    if not isinstance(subject, dict):
        raise SystemExit(f"找不到 {target} 的身份配置")
    return subject


def _session_activity(session):
    """Return a sortable activity stamp for one internal session."""
    if not isinstance(session, dict):
        return ""
    stamps = []
    for key in ("updated_at", "last_user_activity", "created_at"):
        value = session.get(key)
        if isinstance(value, str) and value:
            stamps.append(value)
    for item in session.get("history") or []:
        if isinstance(item, dict):
            value = item.get("timestamp")
            if isinstance(value, str) and value:
                stamps.append(value)
    return max(stamps) if stamps else ""


def resolve_ids(target):
    subject = _load_subject(target)
    platform_key = str(subject.get("session_key", "")).strip()
    data = json.loads(Path(c.SESSION_FILE).read_text(encoding="utf-8"))
    mapping = data.get("user_sessions") or {}
    ids = []
    for key, value in mapping.items():
        if key != platform_key and not key.startswith(platform_key + "#account:"):
            continue
        if isinstance(value, list):
            ids.extend(str(x) for x in value)
        elif value:
            ids.append(str(value))
    # Newest first; ignore timer/cron side sessions when looking for the chat.
    sessions = data.get("sessions") or {}
    ids = [
        sid for sid in ids
        if sid in sessions
        and not str(sessions.get(sid, {}).get("name", "")).startswith(("timer-", "cron-", "relay"))
    ]
    ids.sort(key=lambda sid: _session_activity(sessions.get(sid)), reverse=True)
    return ids, data


def main():
    parser = argparse.ArgumentParser(description="按身份查看最近活跃的微信会话")
    parser.add_argument("target", choices=["master", "xi"])
    parser.add_argument("-n", type=int, default=10, help="显示最近 N 条")
    parser.add_argument("--id", help="指定内部 session id（默认取最近活跃）")
    args = parser.parse_args()

    ids, data = resolve_ids(args.target)
    if args.id:
        sid = args.id
    elif ids:
        sid = ids[0]
    else:
        print(f"没有找到 {args.target} 的会话", file=sys.stderr)
        return 2

    project = Path(c.SESSION_FILE).stem
    result = c.run_cc([
        "sessions", "show", f"{project}:{sid}", "-n", str(max(1, args.n)),
    ], timeout=60)
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        print(err or out or "cc-connect sessions show 失败", file=sys.stderr)
        return result.returncode or 1
    print(out)
    # A short machine-readable hint is useful for the agent; keep stdout clean.
    if os.environ.get("CC_VIEW_SESSION_VERBOSE"):
        session = (data.get("sessions") or {}).get(sid, {})
        print(json.dumps({
            "target": args.target,
            "session_id": sid,
            "activity": _session_activity(session),
            "candidates": ids[:5],
        }, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())