#!/usr/bin/env python3
"""Fail if the repository contains secrets or personal identifiers.

Run locally before committing, and in CI. It prints only the file, line, and
rule name — never the matched value.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}
SKIP_FILES = {os.path.abspath(__file__)}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".tgz",
              ".exe", ".dll", ".so", ".dylib", ".pdf", ".sqlite", ".db"}

RULES = [
    ("openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("ilink-bot-token", re.compile(r"[A-Za-z0-9_-]+@im\.bot:[0-9a-fA-F]{8,}")),
    ("weixin-openid", re.compile(r"o[0-9A-Za-z_-]{20,}@im\.wechat")),
    ("windows-user-path", re.compile(r"C:\\\\Users\\\\[^\\\s\"']+")),
    ("personal-username", re.compile(r"\b20251\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

TEXT_EXT = {
    ".py", ".ps1", ".psm1", ".md", ".toml", ".json", ".yaml", ".yml",
    ".txt", ".bat", ".cmd", ".vbs", ".c", ".h", ".example", ".env",
}


def iter_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = os.path.join(base, name)
            if path in SKIP_FILES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in BINARY_EXT:
                continue
            if ext and ext not in TEXT_EXT and name not in ("LICENSE", ".gitignore", "CHANGELOG.md"):
                if not name.startswith("."):
                    continue
            yield path


def main():
    findings = 0
    for path in iter_files():
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    for rule, pattern in RULES:
                        if pattern.search(line):
                            rel = os.path.relpath(path, ROOT)
                            print(f"{rel}:{lineno}: {rule}")
                            findings += 1
                            break
        except OSError:
            continue
    if findings:
        print(f"SECRET_SCAN_FAILED findings={findings}")
        return 1
    print("SECRET_SCAN_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
