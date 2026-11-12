#!/usr/bin/env python3
"""Maintain semantic tags for the local sticker library.

`sticker_admin.py scan` rebuilds the base manifest from filenames. This tool
keeps a separate `sticker_tags.json` overlay for meanings that are not obvious
from a filename (comfort, hug, head-pat, praise, teasing, ...). The send path
merges the overlay when matching `--sticker-prefer`.

Usage:
    python -X utf8 tools/sticker_tag.py --list
    python -X utf8 tools/sticker_tag.py --show <id>
    python -X utf8 tools/sticker_tag.py --add <id> --tags "comfort,抱抱,贴贴"
    python -X utf8 tools/sticker_tag.py --set <id> --tags "comfort,安慰"
    python -X utf8 tools/sticker_tag.py --auto
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

MANIFEST = os.path.join(c.STICKER_DIR, "manifest.json")
TAGS_FILE = os.path.join(c.STICKER_DIR, "sticker_tags.json")

HINTS = [
    ("抱", ["comfort", "抱抱"]),
    ("贴", ["comfort", "贴贴"]),
    ("摸", ["comfort", "摸摸"]),
    ("合十", ["comfort", "合十", "安慰"]),
    ("击掌", ["comfort", "击掌", "鼓励"]),
    ("亲", ["comfort", "亲亲"]),
    ("安慰", ["comfort", "安慰"]),
    ("拍", ["拍拍"]),
    ("爱", ["喜欢"]),
    ("笑", ["开心"]),
    ("哭", ["难过"]),
    ("困", ["困"]),
    ("睡", ["困", "晚安"]),
    ("吃", ["吃饭"]),
    ("猫", ["猫猫"]),
    ("猪", ["猪猪"]),
    ("鱼", ["大肥鱼"]),
]


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def load_tags():
    try:
        with open(TAGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def save_tags(data):
    c.save_json_atomic(TAGS_FILE, data)


def normalize(tags):
    out = []
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def auto_tags(entries):
    data = load_tags()
    added = 0
    for entry in entries:
        haystack = entry.get("label", "")
        wanted = []
        for needle, tags in HINTS:
            if needle in haystack:
                if needle == "抱" and ("不抱" in haystack or "没抱" in haystack):
                    continue
                wanted.extend(tags)
        if not wanted:
            continue
        current = data.setdefault(entry["id"], [])
        for tag in normalize(wanted):
            if tag not in current:
                current.append(tag)
                added += 1
    save_tags(data)
    print(f"AUTO_OK added={added} stickers={len(data)}")


def main():
    parser = argparse.ArgumentParser(description="给表情包打语义标签")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--show")
    parser.add_argument("--add")
    parser.add_argument("--set")
    parser.add_argument("--tags", default="")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest()
    entries = manifest.get("stickers", [])
    by_id = {e["id"]: e for e in entries}

    if args.auto:
        auto_tags(entries)
        return 0
    if args.show:
        entry = by_id.get(args.show)
        if not entry:
            print(f"找不到 {args.show}", file=sys.stderr)
            return 2
        print(json.dumps({"id": entry["id"], "label": entry.get("label", ""),
                          "category": entry.get("category", ""),
                          "style": entry.get("style", ""),
                          "base_tags": entry.get("tags", []),
                          "extra_tags": load_tags().get(entry["id"], [])},
                         ensure_ascii=False))
        return 0
    if args.add or args.set:
        sid = args.add or args.set
        if sid not in by_id:
            print(f"找不到 {sid}", file=sys.stderr)
            return 2
        new_tags = normalize([t for t in args.tags.replace("，", ",").split(",")])
        data = load_tags()
        if args.set:
            data[sid] = new_tags
        else:
            current = data.setdefault(sid, [])
            for tag in new_tags:
                if tag not in current:
                    current.append(tag)
        save_tags(data)
        print(f"TAGS_OK {sid} = {data.get(sid, [])}")
        return 0
    if args.list:
        data = load_tags()
        for entry in entries:
            print(f"{entry['id']}\t{entry['category']}/{entry['style']}\t{entry.get('label', '')}\t{data.get(entry['id'], [])}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())