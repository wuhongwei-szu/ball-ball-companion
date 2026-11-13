#!/usr/bin/env python3
"""Fail if the repository contains secrets or personal identifiers.

Run locally before committing, and in CI. It prints only the file, line, and
rule name — never the matched value.
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RULES = [
    ("openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("ilink-bot-token", re.compile(r"[A-Za-z0-9_-]+@im\.bot:[0-9a-fA-F]{8,}")),
    ("weixin-openid", re.compile(r"o[0-9A-Za-z_-]{20,}@im\.wechat")),
    ("windows-user-path", re.compile(r"[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.IGNORECASE)),
    ("personal-username", re.compile(r"\b20" r"251\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

def _git(*args):
    result = subprocess.run(["git", "-C", ROOT, *args], capture_output=True)
    if result.returncode:
        raise RuntimeError("cannot inspect Git publication files")
    return result.stdout


def private_path(path):
    path = path.replace("\\", "/").lower()
    parts = path.split("/")
    name = parts[-1]
    if parts[0] in {"memory", "logs", "sessions", "backups", "assets", "artifacts", ".codex", ".cc-connect"}:
        return True
    if path in {"agents.md", "persona.md"} or name in {"auth.json", "config.toml", "bot.config.json", "shared_memory.json", "core_memory.json"}:
        return True
    if parts[0] == "config" and ".example" not in name:
        return True
    if name.startswith(".env") and name != ".env.example":
        return True
    if name.endswith((".log", ".jsonl", ".sqlite", ".sqlite3", ".db", ".zip", ".bak", ".exe")):
        return True
    return False


def iter_files(staged=False):
    args = ["ls-files", "-z", "--cached"]
    if not staged:
        args.extend(["--others", "--exclude-standard"])
    paths = sorted(set(os.fsdecode(path) for path in _git(*args).split(b"\0") if path))
    for relative in paths:
        path = os.path.join(ROOT, relative)
        # A normal scan reads the work tree; --staged reads the exact commit snapshot.
        if staged:
            content = _git("show", ":" + relative)
        else:
            if not os.path.exists(path):
                continue  # tracked deletion
            with open(path, "rb") as source:
                content = source.read()
        yield relative, content


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="scan the Git index instead of working files")
    args = parser.parse_args([] if argv is None else argv)
    findings = 0
    try:
        for relative, content in iter_files(args.staged):
            if private_path(relative):
                print(f"{relative}:1: private-path")
                findings += 1
                continue
            if b"\0" in content:
                continue
            for lineno, line in enumerate(content.decode("utf-8", "replace").splitlines(), 1):
                for rule, pattern in RULES:
                    if pattern.search(line):
                        print(f"{relative}:{lineno}: {rule}")
                        findings += 1
                        break
    except (OSError, RuntimeError):
        print("SECRET_SCAN_ERROR cannot inspect all publication files")
        return 2
    if findings:
        print(f"SECRET_SCAN_FAILED findings={findings}")
        return 1
    print("SECRET_SCAN_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
