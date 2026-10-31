#!/usr/bin/env python3
"""Capture new cc-connect conversation messages into raw memory transcripts.

Runs every few minutes. It never copies the bot token or openids; it only
reads the session file and appends redacted text to memory/raw/.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_state():
    try:
        with open(c.CAPTURE_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = c.CAPTURE_STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, c.CAPTURE_STATE_FILE)


def main():
    if not c.SESSION_FILE:
        print("capture: session_file 未配置")
        return 1
    try:
        with open(c.SESSION_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"capture: cannot read session file: {exc}")
        return 1

    os.makedirs(os.path.dirname(c.CAPTURE_STATE_FILE), exist_ok=True)
    state = load_state()
    total = 0

    for sid in ("s1", "s2"):
        history = data.get("sessions", {}).get(sid, {}).get("history", [])
        last = int(state.get(sid, 0))
        if last > len(history):
            last = 0
        new_items = history[last:]
        if not new_items:
            state[sid] = len(history)
            continue

        skip_next_assistant = False
        for item in new_items:
            role = item.get("role", "")
            content = (item.get("content") or "").strip()
            if not content:
                continue

            if skip_next_assistant and role == "assistant":
                skip_next_assistant = False
                continue
            skip_next_assistant = False

            # Skip synthetic/system conversations.
            if role == "user" and (
                "每日要闻" in content
                or "静默记忆整理任务" in content
                or "主动关心任务" in content
                or "【系统通知】" in content
            ):
                skip_next_assistant = True
                continue

            # NO_REPLY is a control marker, not a real assistant message.
            if role == "assistant" and content.upper() == "NO_REPLY":
                continue

            ts = item.get("timestamp", "")
            c.append_raw(sid, content, role, ts)
            if role == "assistant":
                c.append_recent(content, ts)
            total += 1

        state[sid] = len(history)

    save_state(state)
    print(f"captured {total} new messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
