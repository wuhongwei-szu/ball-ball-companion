#!/usr/bin/env python3
"""Inspect and maintain the local reminder index.

The cc-connect timer delivers reminders, but the JSON index only records that
a timer was created. This tool adds a small lifecycle so past reminders do not
stay "scheduled" forever and block a future reminder with the same title.

Usage:
    python -X utf8 tools/reminder_admin.py --list
    python -X utf8 tools/reminder_admin.py --mark <id> --status sent
    python -X utf8 tools/reminder_admin.py --mark <id> --status cancelled
    python -X utf8 tools/reminder_admin.py --gc
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

STATUSES = {"scheduled", "sent", "expired", "cancelled"}


def load():
    try:
        with open(c.REMINDERS_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []


def save(items):
    c.save_json_atomic(c.REMINDERS_INDEX, items)


def parse_at(item):
    try:
        return datetime.datetime.strptime(
            str(item.get("date", "")) + " " + str(item.get("time", "")),
            "%Y-%m-%d %H:%M",
        )
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description="提醒索引维护")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--mark")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--gc", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = load()
    if args.list:
        for item in items:
            print(f"{item.get('id')}\t{item.get('owner')}\t{item.get('date')} {item.get('time')}\t"
                  f"{item.get('status')}\t{item.get('title')}")
        return 0

    if args.mark:
        if not args.status:
            print("--mark 需要同时给 --status", file=sys.stderr)
            return 2
        found = False
        for item in items:
            if item.get("id") == args.mark:
                item["status"] = args.status
                item["updated_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
                found = True
                break
        if not found:
            print(f"找不到提醒 {args.mark}", file=sys.stderr)
            return 2
        if not args.dry_run:
            save(items)
        print(f"REMINDER_MARK id={args.mark} status={args.status}")
        return 0

    if args.gc:
        now = datetime.datetime.now()
        changed = []
        for item in items:
            if item.get("status") != "scheduled":
                continue
            when = parse_at(item)
            if when is not None and when < now:
                item["status"] = "expired"
                item["updated_at"] = now.astimezone().isoformat(timespec="seconds")
                changed.append(item.get("id"))
        if changed and not args.dry_run:
            save(items)
        print(f"REMINDER_GC {'DRY-RUN ' if args.dry_run else ''}expired={len(changed)} ids={changed}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())