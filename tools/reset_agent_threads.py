#!/usr/bin/env python3
"""Clear active Codex agent thread IDs without deleting chat history.

Codex reads AGENTS.md/PERSONA.md when a thread starts. After changing those
files, run this with cc-connect stopped; the next message starts a fresh thread
and loads the new rules. Chat history in the cc-connect session file is kept.
"""
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c


def main():
    if not c.SESSION_FILE or not os.path.isfile(c.SESSION_FILE):
        print("session file not found")
        return 1
    backup = c.SESSION_FILE + ".bak-rules-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(c.SESSION_FILE, backup)
    with open(c.SESSION_FILE, encoding="utf-8") as f:
        data = json.load(f)
    changed = []
    for sid, session in data.get("sessions", {}).items():
        if not isinstance(session, dict):
            continue
        name = str(session.get("name", ""))
        # Keep cron/timer side sessions; reset interactive chat threads.
        if name.startswith(("cron-", "timer-", "relay")):
            continue
        agent_id = session.get("agent_session_id", "")
        if not agent_id:
            continue
        past = session.get("past_agent_session_ids")
        if not isinstance(past, list):
            past = []
        past.append(agent_id)
        session["past_agent_session_ids"] = past[-10:]
        session["agent_session_id"] = ""
        changed.append((sid, name or "default", agent_id[:8]))
    if not changed:
        print("NO_ACTIVE_AGENT_THREADS")
        return 0
    tmp = c.SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, c.SESSION_FILE)
    print(f"RESET_OK backup={backup}")
    for sid, name, aid in changed:
        print(f"  {sid} ({name}) cleared agent {aid}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
