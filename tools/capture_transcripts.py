#!/usr/bin/env python3
"""Capture only proven-new records, with session-scoped v2 checkpoints.

This command is not a dry run. Existing histories and uncorrelated assistant
messages are held for review rather than automatically backfilled.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import capture_runtime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    return capture_runtime.main(c)


if __name__ == "__main__":
    sys.exit(main())
