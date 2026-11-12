"""Conservative transcript capture across session rotation.

No backfill and no assistant-message deduplication by text. Unknown append
outcomes remain blocked. This module does not import runtime configuration.
"""
import contextlib
import copy
import datetime
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile


ABSENT = object()


class CaptureError(RuntimeError):
    """A fixed, non-sensitive reason code, never input or exception text."""


def fail(reason):
    raise CaptureError(reason)


def read_json(path, missing=False):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if missing:
            return ABSENT
        fail("session_read_failed")
    except (OSError, ValueError):
        fail("invalid_json_or_unreadable")


def source_id(value):
    return (isinstance(value, str) and 0 < len(value) <= 128
            and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None)


def resolve_channels(data, cfg):
    """Bind legacy configured anchors to owners, then use authoritative pointers.

    `active_session` is an explicit source-schema contract, not a heuristic.
    Missing or ambiguous metadata blocks capture rather than picking a history.
    """
    if not isinstance(data, dict):
        fail("invalid_session_root")
    sessions = data.get("sessions")
    owners = data.get("user_sessions")
    active = data.get("active_session")
    if not all(isinstance(value, dict) for value in (sessions, owners, active)):
        fail("active_session_metadata_missing")
    result = {}
    for channel, config_key in (("s1", "master_session_id"), ("s2", "xi_session_id")):
        anchor = cfg.get(config_key, channel)
        if not source_id(anchor):
            fail("invalid_session_anchor")
        matches = []
        for owner, ids in owners.items():
            values = ids if isinstance(ids, list) else [ids]
            if anchor in values:
                if (not isinstance(owner, str) or not owner or not values
                        or any(not source_id(value) for value in values)
                        or len(values) != len(set(values))):
                    fail("invalid_owner_mapping")
                matches.append((owner, values))
        if len(matches) != 1:
            fail("session_owner_ambiguous")
        owner, ids = matches[0]
        current = active.get(owner)
        if not source_id(current) or current not in ids:
            fail("active_session_unproven")
        session = sessions.get(current)
        if not isinstance(session, dict) or session.get("id") != current:
            fail("active_session_missing")
        memberships = sum(current in (value if isinstance(value, list) else [value])
                          for value in owners.values())
        if memberships != 1:
            fail("active_session_owner_ambiguous")
        history = session.get("history")
        if history is None:
            fail("history_unavailable")
        if not isinstance(history, list):
            fail("invalid_history")
        result[channel] = (owner, current, history)
    if (result["s1"][0] == result["s2"][0]
            or result["s1"][1] == result["s2"][1]):
        fail("channel_identity_collision")
    return result


def digest(salt, value, domain):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(bytes.fromhex(salt) + domain + payload).hexdigest()


def prefix(salt, history, count):
    return digest(salt, history[:count], b"capture-prefix\0")


def validate_state(state):
    if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 2:
        fail("invalid_v2_state")
    if not isinstance(state.get("salt"), str) or not re.fullmatch(r"[0-9a-f]{32}", state["salt"]):
        fail("invalid_v2_state")
    flags = state.get("review_flags")
    if (not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags)
            or len(flags) != len(set(flags))
            or not set(flags) <= {"initial_boundary_unverified", "rotation_boundary_unverified"}):
        fail("invalid_v2_state")
    channels = state.get("channels")
    if not isinstance(channels, dict) or set(channels) != {"s1", "s2"}:
        fail("invalid_v2_state")
    for channel in channels.values():
        if (not isinstance(channel, dict) or not isinstance(channel.get("owner"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", channel["owner"])
                or not source_id(channel.get("active"))
                or not isinstance(channel.get("sessions"), dict)
                or channel["active"] not in channel["sessions"]):
            fail("invalid_v2_state")
        for sid, entry in channel["sessions"].items():
            if (not source_id(sid) or not isinstance(entry, dict)
                    or not {"cursor", "prefix", "synthetic_pending", "pending", "review"} <= set(entry)):
                fail("invalid_v2_state")
            cursor = entry.get("cursor")
            if (type(cursor) is not int or cursor < 0
                    or not isinstance(entry.get("prefix"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["prefix"])
                    or type(entry.get("synthetic_pending")) is not bool
                    or not isinstance(entry.get("review"), list)):
                fail("invalid_v2_state")
            pending = entry.get("pending")
            if pending is not None:
                if (not isinstance(pending, dict) or set(pending) != {"index"}
                        or type(pending["index"]) is not int or pending["index"] != cursor):
                    fail("invalid_v2_state")
            last_end = 0
            for interval in entry["review"]:
                if not isinstance(interval, dict) or set(interval) != {"start", "end", "reason"}:
                    fail("invalid_v2_state")
                start, end = interval["start"], interval["end"]
                if (type(start) is not int or type(end) is not int
                        or start < last_end or not start < end <= cursor
                        or interval["reason"] not in {"baseline_unverified", "assistant_unverified"}):
                    fail("invalid_v2_state")
                last_end = end


@contextlib.contextmanager
def locked(path):
    """Protect v2 capture writers only; never unlink the lock inode."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".lock", "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fail("capture_busy")
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("capture_busy")
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save_state(path, state):
    validate_state(state)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".capture-v2-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def timestamp(value):
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        fail("invalid_history_item")
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        fail("invalid_history_timestamp")


def item_fields(item):
    if not isinstance(item, dict):
        fail("invalid_history_item")
    role, text = item.get("role"), item.get("content")
    if not isinstance(role, str) or (text is not None and not isinstance(text, str)):
        fail("invalid_history_item")
    return role, (text or "").strip(), timestamp(item.get("timestamp"))


def add_review(entry, index, reason):
    ranges = entry["review"]
    if ranges and ranges[-1]["end"] == index and ranges[-1]["reason"] == reason:
        ranges[-1]["end"] = index + 1
    else:
        ranges.append({"start": index, "end": index + 1, "reason": reason})


def review_count(state):
    return sum(item["end"] - item["start"]
               for channel in state["channels"].values()
               for entry in channel["sessions"].values() for item in entry["review"])


def review_count_active(state):
    total = 0
    for channel in state["channels"].values():
        entry = channel.get("sessions", {}).get(channel.get("active"))
        if isinstance(entry, dict):
            total += sum(item["end"] - item["start"] for item in entry.get("review", []))
    return total


def is_synthetic_prompt(text):
    """Retain legacy filtering and recognize the generated care/reminder templates."""
    if any(marker in text for marker in (
            "每日要闻", "静默记忆整理任务", "主动关心任务", "【系统通知】")):
        return True
    return (text.startswith(("【上下文关怀】现在是 ", "【定时提醒】现在是 "))
            and "/tools/chat_burst.py " in text
            and "--proactive" in text
            and "NO_REPLY" in text)


def capture(common):
    if not common.SESSION_FILE:
        fail("session_unconfigured")
    cfg = getattr(common, "CFG", {})
    if not isinstance(cfg, dict):
        fail("invalid_config")
    # Validate current inputs before touching even the v2 lock/checkpoint.
    channels = resolve_channels(read_json(common.SESSION_FILE), cfg)
    path = common.CAPTURE_STATE_FILE + ".v2"
    with locked(path):
        old = read_json(path, missing=True)
        if old is ABSENT:
            state = {"version": 2, "salt": secrets.token_hex(16), "channels": {},
                     "review_flags": ["initial_boundary_unverified"]}
        else:
            validate_state(old)
            if any(entry["pending"] is not None for channel in old["channels"].values()
                   for entry in channel["sessions"].values()):
                fail("append_outcome_uncertain")
            state = copy.deepcopy(old)
        prepared = []
        baseline = 0
        for channel, (owner, sid, history) in channels.items():
            owner_hash = digest(state["salt"], owner, b"capture-owner\0")
            record = state["channels"].setdefault(channel, {"owner": owner_hash, "active": sid, "sessions": {}})
            if record["owner"] != owner_hash:
                fail("channel_owner_changed")
            if record["active"] != sid:
                # The previous source may have an unread/evicted tail. Do not
                # claim completeness or backfill it merely because rotation
                # has produced a new empty active history.
                if "rotation_boundary_unverified" not in state["review_flags"]:
                    state["review_flags"].append("rotation_boundary_unverified")
                record["active"] = sid
            if any(sid in other["sessions"] for name, other in state["channels"].items() if name != channel):
                fail("session_owner_changed")
            if sid not in record["sessions"]:
                count = len(history)
                record["sessions"][sid] = {
                    "cursor": count, "prefix": prefix(state["salt"], history, count),
                    "synthetic_pending": False, "pending": None,
                    "review": ([{"start": 0, "end": count, "reason": "baseline_unverified"}]
                               if count else []),
                }
                baseline += count
            entry = record["sessions"][sid]
            cursor = entry["cursor"]
            if cursor > len(history) or entry["prefix"] != prefix(state["salt"], history, cursor):
                fail("history_continuity_unproven")
            # Validate every suffix before any channel can append.
            items = [item_fields(item) for item in history[cursor:]]
            prepared.append((channel, history, entry, cursor, items))
        if state != old:
            save_state(path, state)
        captured = withheld = 0
        for channel, history, entry, cursor, items in prepared:
            for index, (role, text, ts) in enumerate(items, start=cursor):
                append = False
                if role not in {"user", "assistant"} or not text:
                    pass
                elif entry["synthetic_pending"] and role == "assistant":
                    entry["synthetic_pending"] = False
                elif role == "user":
                    entry["synthetic_pending"] = is_synthetic_prompt(text)
                    append = not entry["synthetic_pending"]
                elif text.upper() != "NO_REPLY":
                    add_review(entry, index, "assistant_unverified")
                    withheld += 1
                if append:
                    entry["pending"] = {"index": index}
                    # Cursor must describe all preceding inspected records.
                    save_state(path, state)
                    try:
                        common.append_raw(channel, text, "user", ts)
                    except Exception:
                        fail("append_outcome_uncertain")
                    captured += 1
                entry["cursor"] = index + 1
                entry["prefix"] = prefix(state["salt"], history, index + 1)
                entry["pending"] = None
                save_state(path, state)
        pending = review_count(state)
        flags = len(state["review_flags"])
        coverage = "review_required" if pending or flags else "no_recorded_gaps"
        # Exit status describes this invocation, not historical completeness.
        # Keep every review range and boundary; never mark them reconciled here.
        print(f"capture_status=ok coverage_status={coverage} captured_user={captured} "
              f"baselined={baseline} withheld_assistant={withheld} review_pending={pending} "
              f"review_boundaries={flags}")
        return 0


def main(common):
    try:
        return capture(common)
    except CaptureError as exc:
        print(f"capture_status=blocked reason={exc.args[0]}", file=sys.stderr)
        return 1
    except Exception:
        # Never echo paths, input values, raw exceptions, or traceback locals.
        print("capture_status=blocked reason=io_or_internal_failure", file=sys.stderr)
        return 1


def capture_health(state_path, job, now=None):
    """Read-only: combine last scheduled outcome with retained coverage evidence.

    A valid checkpoint alone is not a heartbeat. The scheduler's last_run and
    last_error establish the current execution result; review ranges establish
    only known coverage gaps. Never expose source IDs, hashes, or input text.
    """
    result = {"capture_status": "blocked", "reason": "state_unavailable",
              "coverage_status": "unknown", "review_pending": None,
              "review_pending_active": None, "review_pending_legacy": None,
              "review_boundaries": None}
    try:
        state = read_json(state_path)
        validate_state(state)
    except CaptureError:
        return result
    pending = review_count(state)
    active_pending = review_count_active(state)
    flags = len(state["review_flags"])
    result.update(coverage_status="review_required" if pending or flags else "no_recorded_gaps",
                  review_pending=pending, review_pending_active=active_pending,
                  review_pending_legacy=max(0, pending - active_pending),
                  review_boundaries=flags)
    if any(entry["pending"] is not None for channel in state["channels"].values()
           for entry in channel["sessions"].values()):
        result["reason"] = "append_outcome_uncertain"
        return result
    # A multi-file recovery can be interrupted between file/state commits.
    # Its durable audit must not be mistaken for a completed historical repair.
    try:
        parent = os.path.dirname(os.path.abspath(state_path))
        for name in os.listdir(parent):
            if not re.fullmatch(r"\.capture_recovery_[0-9]{8}\.json", name):
                continue
            audit = read_json(os.path.join(parent, name))
            if not isinstance(audit, dict) or audit.get("status") != "committed":
                raise CaptureError("recovery_outcome_uncertain")
            plan = audit.get("plan")
            if (not isinstance(plan, dict) or plan.get("version") != 1
                    or not isinstance(plan.get("output_hashes"), dict)
                    or not isinstance(audit.get("created"), list)
                    or set(audit["created"]) != set(plan["output_hashes"])):
                raise CaptureError("recovery_outcome_uncertain")
    except (CaptureError, OSError, TypeError):
        result["reason"] = "recovery_outcome_uncertain"
        return result
    if not isinstance(job, dict) or job.get("id") != "capture01":
        result["reason"] = "schedule_missing"
        return result
    if job.get("enabled") is not True:
        result["reason"] = "schedule_disabled"
        return result
    if job.get("last_error"):
        result["reason"] = "scheduled_run_failed"
        return result
    try:
        stamp = datetime.datetime.fromisoformat(job["last_run"].replace("Z", "+00:00"))
        current = now or datetime.datetime.now(datetime.timezone.utc)
        if stamp.tzinfo is None or current.tzinfo is None:
            raise ValueError("timezone required")
        age = (current - stamp).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        result["reason"] = "schedule_time_invalid"
        return result
    if age < -60:
        result["reason"] = "schedule_time_in_future"
        return result
    if age > 600:
        result["reason"] = "schedule_stale"
        return result
    result.update(capture_status="ok", reason=None)
    return result
