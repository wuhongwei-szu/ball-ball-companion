#!/usr/bin/env python3
"""Print which WeChat channel this agent process is serving.

The two bots share one persona and one memory store, but each bot account is
bound to exactly one person. This helper makes that binding explicit so the
agent never has to guess whether it is talking to master or xi.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c


def main():
    account = os.environ.get("CC_PLATFORM_ACCOUNT", "").strip()
    session_key = os.environ.get("CC_SESSION_KEY", "").strip()
    role = c.current_target()
    payload = {
        "role": role or "unknown",
        "label": c.LABELS.get(role, ""),
        "account": account,
        "session_key": session_key,
        "master_session": c.MASTER_SESSION,
        "xi_session": c.XI_SESSION,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if role else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())