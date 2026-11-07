#!/usr/bin/env python3
"""Record like/dislike feedback for the last sticker sent to a chat.

Usage:
    python -X utf8 sticker_feedback.py --target xi --like
    python -X utf8 sticker_feedback.py --target master --dislike --note "太土"
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

FEEDBACK_FILE = os.path.join(c.STICKER_DIR, "feedback.json")


def _last_sticker_id(target):
    usage = c.load_json(c.STICKER_USAGE_FILE, {}) or {}
    sent = (usage.get(target, {}) or {}).get("sent", [])
    if isinstance(sent, list) and sent:
        last = sent[-1]
        if isinstance(last, dict) and last.get("id"):
            return last["id"]
    try:
        with open(c.RECENT_FILE, encoding="utf-8") as f:
            lines = [l for l in f if "[表情包:" in l]
        if lines:
            match = re.search(r"\[表情包:([^\]]+)\]", lines[-1])
            if match:
                return match.group(1)
    except Exception:
        pass
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["master", "xi"], default=None)
    parser.add_argument("--id", dest="sticker_id", default="")
    parser.add_argument("--like", action="store_true")
    parser.add_argument("--dislike", action="store_true")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    target = args.target or c.current_target()
    if target not in {"master", "xi"}:
        raise SystemExit("请用 --target master|xi")
    c.assert_target(target)
    if args.like == args.dislike:
        raise SystemExit("请选择 --like 或 --dislike 其中一个")
    sticker_id = args.sticker_id or _last_sticker_id(target)
    if not sticker_id:
        raise SystemExit("找不到最近的表情包 ID；请用 --id 指定")
    data = c.load_json(FEEDBACK_FILE, {})
    if not isinstance(data, dict):
        data = {}
    entry = data.get(sticker_id)
    if not isinstance(entry, dict):
        entry = {"likes": 0, "dislikes": 0, "banned": False, "owner": target, "note": ""}
    if args.like:
        entry["likes"] = int(entry.get("likes", 0)) + 1
        entry["banned"] = False
    else:
        entry["dislikes"] = int(entry.get("dislikes", 0)) + 1
        entry["banned"] = True
    entry["owner"] = target
    entry["last"] = "like" if args.like else "dislike"
    entry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if args.note:
        entry["note"] = args.note[:120]
    data[sticker_id] = entry
    c.save_json_atomic(FEEDBACK_FILE, data)

    label = "喜欢" if args.like else "不喜欢/禁用"
    line = f"- {datetime.now().strftime('%Y-%m-%d')} {target} {label}表情 `{sticker_id}`"
    if args.note:
        line += f"：{args.note[:80]}"
    with open(os.path.join(c.MEMORY_DIR, "STICKER_PREFS.md"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"FEEDBACK_OK {sticker_id} {entry['last']} banned={entry['banned']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
