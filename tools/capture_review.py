#!/usr/bin/env python3
"""Backfill verified assistant replies into raw transcripts.

The conservative capture job holds assistant messages in review ranges instead
of appending them automatically. Those messages contain the bot's own long
answers, promises and explanations; without them the daily memory consolidation
only sees the user side of the conversation. This tool appends the review
ranges for sessions that are still present in the cc-connect session file and
then removes those ranges from the capture state.

Usage:
    python -X utf8 tools/capture_review.py --dry-run
    python -X utf8 tools/capture_review.py --active
    python -X utf8 tools/capture_review.py --all
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

STATE_FILE = c.CAPTURE_STATE_FILE + ".v2"


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _raw_path(channel, ts):
    date = (ts or "")[:10]
    if not date:
        return None
    return Path(c.RAW_DIR) / channel / (date + ".md")


def _exists(cache, channel, ts, text):
    path = _raw_path(channel, ts)
    if path is None:
        return False
    key = str(path)
    if key not in cache:
        try:
            cache[key] = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            cache[key] = ""
    return text and text in cache[key]


def _append_missing(cache, channel, ts, text):
    safe = c.redact(text)
    if not safe.strip() or _exists(cache, channel, ts, safe):
        return False
    c.append_raw(channel, safe, "assistant", ts)
    path = _raw_path(channel, ts)
    if path is not None:
        try:
            cache[str(path)] = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            cache[str(path)] = ""
    return True


def _process_range(history, channel, review, cache, dry_run):
    start = max(0, int(review.get("start", 0)))
    end = min(len(history), int(review.get("end", 0)))
    written = 0
    for item in history[start:end]:
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        text = (item.get("content") or "").strip()
        if not text or text.upper() == "NO_REPLY":
            continue
        if dry_run:
            written += 1
        elif _append_missing(cache, channel, item.get("timestamp", ""), text):
            written += 1
    return written


def main():
    parser = argparse.ArgumentParser(description="把待审核的助手回复回填到 raw 原文")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--active", action="store_true", help="只处理当前活跃会话（默认）")
    parser.add_argument("--all", action="store_true", help="处理 session 文件中仍存在的所有会话")
    parser.add_argument("--channel", choices=["s1", "s2"], help="只处理一个通道")
    args = parser.parse_args()

    if not os.path.isfile(c.SESSION_FILE):
        print("session file not found", file=sys.stderr)
        return 1
    if not os.path.isfile(STATE_FILE):
        print("capture state not found", file=sys.stderr)
        return 1

    sessions = _load(c.SESSION_FILE).get("sessions") or {}
    state = _load(STATE_FILE)
    cache = {}
    total = 0
    touched = 0

    for channel, record in (state.get("channels") or {}).items():
        if args.channel and channel != args.channel:
            continue
        if not isinstance(record, dict):
            continue
        active = record.get("active")
        candidates = []
        if args.all:
            candidates = list((record.get("sessions") or {}).keys())
        elif active:
            candidates = [active]
        for sid in candidates:
            entry = (record.get("sessions") or {}).get(sid)
            session = sessions.get(sid)
            if not isinstance(entry, dict) or not isinstance(session, dict):
                continue
            history = session.get("history") or []
            review = entry.get("review") or []
            if not review:
                continue
            written = 0
            for item in review:
                if isinstance(item, dict):
                    written += _process_range(history, channel, item, cache, args.dry_run)
            if written and not args.dry_run:
                entry["review"] = []
                touched += 1
            total += written
            print(f"[{channel}:{sid}] review_ranges={len(review)} messages_written={written}")

    if touched and not args.dry_run:
        c.save_json_atomic(STATE_FILE, state)
    print(f"{'DRY-RUN' if args.dry_run else 'BACKFILL_OK'} messages={total} sessions={touched}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())