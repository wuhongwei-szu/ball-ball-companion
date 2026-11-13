#!/usr/bin/env python3
"""Archive attributable generated replies; session history is not delivery proof.

Only assistant_unverified ranges are eligible. Baselines and boundary warnings
remain untouched. A durable pending marker blocks capture after any uncertain
append outcome; repeated message text is never treated as an event identifier.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_runtime as runtime

GENERATED = "[会话生成记录，送达未核实]\n"


def _prepare(common, state, data, all_sessions=False, channel=None):
    runtime.validate_state(state)
    if any(entry["pending"] is not None for record in state["channels"].values()
           for entry in record["sessions"].values()):
        runtime.fail("append_outcome_uncertain")
    channels = runtime.resolve_channels(data, common.CFG)
    prepared = []
    for name, record in state["channels"].items():
        if channel and channel != name:
            continue
        owner, active, _ = channels[name]
        if (record["owner"] != runtime.digest(state["salt"], owner, b"capture-owner\0")
                or record["active"] != active):
            runtime.fail("channel_owner_changed")
        candidates = list(record["sessions"]) if all_sessions else [active]
        for sid in candidates:
            entry = record["sessions"][sid]
            ranges = [item for item in entry["review"]
                      if item["reason"] == "assistant_unverified"]
            if not ranges:
                continue
            memberships = [key for key, ids in data["user_sessions"].items()
                           if sid in (ids if isinstance(ids, list) else [ids])]
            session = data["sessions"].get(sid)
            if (memberships != [owner] or not isinstance(session, dict)
                    or session.get("id") != sid):
                runtime.fail("session_owner_changed")
            history = session.get("history")
            cursor = entry["cursor"]
            if (not isinstance(history, list) or cursor > len(history)
                    or entry["prefix"] != runtime.prefix(state["salt"], history, cursor)):
                runtime.fail("history_continuity_unproven")
            for review in ranges:
                for index in range(review["start"], review["end"]):
                    role, text, stamp = runtime.item_fields(history[index])
                    if role != "assistant" or not text or text.upper() == "NO_REPLY" or not stamp:
                        runtime.fail("review_item_unproven")
                    prepared.append((name, entry, index, text, stamp))
    return prepared


def _remove_review_index(entry, index):
    remaining = []
    for review in entry["review"]:
        if review["reason"] != "assistant_unverified" or not review["start"] <= index < review["end"]:
            remaining.append(review)
            continue
        if review["start"] < index:
            remaining.append({**review, "end": index})
        if index + 1 < review["end"]:
            remaining.append({**review, "start": index + 1})
    entry["review"] = remaining


def review(common, *, dry_run=False, all_sessions=False, channel=None):
    path = common.CAPTURE_STATE_FILE + ".v2"
    def load():
        state = runtime.read_json(path)
        return state, _prepare(common, state, runtime.read_json(common.SESSION_FILE),
                               all_sessions, channel)
    if dry_run:
        _, prepared = load()
        return len(prepared)
    with runtime.locked(path):
        state, prepared = load()
        for name, entry, index, text, stamp in prepared:
            # Keep the existing pending schema so ordinary capture also blocks.
            entry["pending"] = {"index": entry["cursor"]}
            entry["review_append_index"] = index
            runtime.save_state(path, state)
            try:
                common.append_raw(name, GENERATED + text, "assistant", stamp)
            except Exception:
                runtime.fail("append_outcome_uncertain")
            _remove_review_index(entry, index)
            entry["pending"] = None
            entry.pop("review_append_index", None)
            # Failure here leaves the durable pre-append pending marker intact.
            runtime.save_state(path, state)
        return len(prepared)


def main(argv=None):
    parser = argparse.ArgumentParser(description="归档有来源的助手生成记录（送达未核实）")
    parser.add_argument("--dry-run", action="store_true")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--active", action="store_true")
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--channel", choices=["s1", "s2"])
    args = parser.parse_args(argv)
    # Importing common loads deployment configuration; tests inject a fixture.
    import common
    try:
        count = review(common, dry_run=args.dry_run, all_sessions=args.all,
                       channel=args.channel)
        print(f"review_status={'dry_run' if args.dry_run else 'ok'} generated_records={count}")
        return 0
    except runtime.CaptureError as exc:
        print(f"review_status=blocked reason={exc.args[0]}", file=sys.stderr)
    except Exception:
        print("review_status=blocked reason=io_or_internal_failure", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
