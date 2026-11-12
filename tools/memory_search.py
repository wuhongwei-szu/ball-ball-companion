#!/usr/bin/env python3
"""Search the companion's current attributed memory, then labeled old evidence."""
import argparse
from pathlib import Path
import re
import sys

import companion_memory as memory


def legacy(query, viewer, root=memory.ROOT, limit=4):
    root = Path(root)
    with memory.database(root) as db:
        obsolete = [r[0] for r in db.execute("SELECT value FROM facts WHERE active=0")]
    paths = list((root / "memory").glob("*.md"))
    for kind in ("notes", "raw"):
        for sid in ("s1", "s2"):
            paths.extend((root / "memory" / kind / sid).glob("*.md"))
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        entries = []
        if path.name == "MEMORY.md":
            # MEMORY.md is a shared document with per-person sections; label
            # each line with the section it came from instead of calling the
            # whole file "shared".
            section = "shared"
            for line in text.splitlines():
                if line.startswith("## "):
                    title = line[3:].strip()
                    if title.startswith("主人"):
                        section = "master"
                    elif title.startswith("小主人"):
                        section = "xi"
                    else:
                        section = "shared"
                    continue
                entries.append((section, line))
        else:
            subject = "master" if "s1" in path.parts else "xi" if "s2" in path.parts else "shared"
            blocks = re.split(r"(?m)^##\s+", text) if "raw" in path.parts else text.splitlines()
            entries = [(subject, block) for block in blocks]
        for subject, block in entries:
            block = re.sub(r"\s+", " ", block).strip()
            if not block or block.startswith(("#", ">")) or memory.SECRET.search(block):
                continue
            if memory.PRIVATE.search(block) and subject != viewer:
                continue
            if any(value and value in block for value in obsolete):
                continue
            relevance = memory.score(block, query)
            if relevance > 1:
                found.append((relevance, subject == viewer, {
                    "kind": "legacy_evidence_not_current_fact", "subject": subject,
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "text": block[:320]}))
    found.sort(key=lambda row: row[:2], reverse=True)
    return [row[2] for row in found[:limit]]


def main(argv=None):
    parser = argparse.ArgumentParser(description="共同记忆检索，保留人物归属与来源")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-chars", type=int, default=3000)
    args = parser.parse_args(argv)
    try:
        who = memory.env_caller(memory.config())
        entries = memory.search(args.query, viewer=who, limit=max(1, min(args.limit, 20)))
        entries += legacy(args.query, who)
        import json
        output = json.dumps(entries, ensure_ascii=False)
        # Keep complete JSON records rather than truncating fields mid-character.
        while len(output) > max(500, args.max_chars) and len(entries) > 1:
            entries.pop();output = json.dumps(entries, ensure_ascii=False)
        print(output if entries else "没有找到相关记忆。")
        return 0 if entries else 2
    except Exception:
        print("记忆暂不可用，不能确认当前对话身份或读取状态。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
