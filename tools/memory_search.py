#!/usr/bin/env python3
"""Search local memory files for a keyword and print a few short snippets.

Usage:
    python -X utf8 memory_search.py "触觉传感器"
    python -X utf8 memory_search.py "小主人 原神" --limit 3
"""
import argparse
import glob
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED_FILES = [
    os.path.join(c.MEMORY_DIR, "MEMORY.md"),
    os.path.join(c.MEMORY_DIR, "EVENTS.md"),
    os.path.join(c.MEMORY_DIR, "STATE.md"),
    os.path.join(c.MEMORY_DIR, "THREADS.md"),
]
SKIP_PREFIXES = ("#", ">", "- [表情包:", "[表情包:")


def _files():
    files = [p for p in FIXED_FILES if os.path.isfile(p)]
    for pattern in (
        os.path.join(c.MEMORY_DIR, "notes", "s1", "*.md"),
        os.path.join(c.MEMORY_DIR, "notes", "s2", "*.md"),
        os.path.join(c.MEMORY_DIR, "raw", "s1", "*.md"),
        os.path.join(c.MEMORY_DIR, "raw", "s2", "*.md"),
    ):
        files.extend(sorted(glob.glob(pattern)))
    return files


def _date_of(path):
    match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    if match:
        return match.group(1)
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def _blocks(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return
    if os.sep + "raw" + os.sep in path or "/raw/" in path.replace("\\", "/"):
        parts = re.split(r"(?m)^##\s+", text)
        for part in parts:
            part = part.strip()
            if part:
                yield part
        return
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(SKIP_PREFIXES):
            yield line


def _score(text, query):
    low = text.lower()
    q = query.lower().strip()
    if not q:
        return 0
    score = 0
    if q in low:
        score += 10 + low.count(q) * 3
    for term in re.split(r"\s+", q):
        if term and term != q and term in low:
            score += 4
    if len(q) > 2:
        for i in range(len(q) - 1):
            chunk = q[i:i + 2]
            if chunk.strip() and chunk in low:
                score += 1
    return score


def main():
    parser = argparse.ArgumentParser(description="检索本地记忆")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-chars", type=int, default=1000)
    args = parser.parse_args()
    query = args.query.strip()
    if not query:
        print("关键词为空")
        return 1

    results = []
    seen = set()
    for path in _files():
        rel = os.path.relpath(path, c.WORK_DIR).replace("\\", "/")
        date = _date_of(path)
        for block in _blocks(path):
            text = re.sub(r"\s+", " ", block).strip()
            if not text or text in seen:
                continue
            score = _score(text, query)
            if score <= 0:
                continue
            seen.add(text)
            results.append((score, date, rel, text))

    results.sort(key=lambda item: (item[0], item[1]), reverse=True)
    output = []
    used = 0
    for score, date, rel, text in results:
        snippet = c.redact(text)[:220]
        line = f"[{date}] {rel}: {snippet}"
        if used + len(line) > args.max_chars and output:
            break
        output.append(line)
        used += len(line) + 1
        if len(output) >= args.limit:
            break

    if not output:
        print("没有找到相关记忆。")
        return 2
    for index, line in enumerate(output, 1):
        print(f"{index}. {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
