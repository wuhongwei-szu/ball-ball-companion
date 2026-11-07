"""Local timer safety: serialize writers and distinguish launch from outcome.

A lock protects local journals, not the remote timer API. Once a process starts,
any error or unrecognized reply is uncertain and must not be retried blindly.
"""
import contextlib
import json
import os
import re
import subprocess

import common as c


class StateError(RuntimeError):
    pass


class StateBusy(StateError):
    pass


class NotStarted(RuntimeError):
    """The timer command definitely did not start; a later retry is safe."""


@contextlib.contextmanager
def locked(path):
    """Nonblocking cross-process lock, automatically released after a crash.

    Never unlink the lock file: replacing its inode permits two lock owners.
    Only scripts using this protocol are protected; external/manual writers
    must be stopped before repairing state.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(str(path) + ".lock", "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise StateBusy("another timer writer is active") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateBusy("another timer writer is active") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def read_json(path, absent):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return absent
    except (OSError, ValueError) as exc:
        raise StateError("cannot read timer state; preserve it and reconcile timers") from exc


def add_timer(args):
    """Return (id, output); classify failure only at the process launch boundary."""
    if not c.CC_BIN:
        raise NotStarted("missing cc_bin configuration")
    binder = getattr(c, "_cc_account_args", None)
    if not callable(binder):
        raise NotStarted("account routing helper is unavailable; no process started")
    try:
        bound_args = binder(list(args))
    except Exception as exc:
        # The production binding helper is pure argument validation. No process
        # has started, so a fixed binding may safely retry this same intent.
        raise NotStarted("account binding failed before timer launch") from exc
    if (not isinstance(bound_args, list) or bound_args.count("--account") != 1
            or bound_args.index("--account") + 1 >= len(bound_args)
            or not isinstance(bound_args[bound_args.index("--account") + 1], str)
            or not bound_args[bound_args.index("--account") + 1].strip()):
        raise NotStarted("timer requires one explicit account; no process started")
    cmd = [c.CC_BIN] + bound_args + ["--data-dir", c.DATA_DIR]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        # This catch surrounds only Popen, never communicate()/response parsing.
        raise NotStarted(f"timer executable could not start: {exc}") from exc
    with process:
        try:
            output, error = process.communicate(timeout=30)
        except BaseException:
            process.kill()
            process.communicate()
            raise
    output, error = (output or "").strip(), (error or "").strip()
    if process.returncode != 0:
        raise StateError("timer outcome uncertain: " + (error or output or f"exit {process.returncode}")[:200])
    ids = re.findall(r"^Timer created:[ \t]*(\S+)[ \t]*$", output, re.M)
    if len(ids) != 1:
        raise StateError("timer outcome uncertain: unrecognized creation response")
    return ids[0], output


def validate_care_plan(plan, allow_next_day=False):
    """Validate both legacy complete plans and the retry-aware journal format."""
    import datetime
    if not isinstance(plan, dict):
        raise StateError("invalid care plan object")
    try:
        day = datetime.date.fromisoformat(plan.get("date", ""))
    except (ValueError, TypeError) as exc:
        raise StateError("invalid care plan date") from exc
    if day.isoformat() != plan["date"]:
        raise StateError("noncanonical care plan date")
    n, timers = plan.get("n"), plan.get("timers")
    failed = plan.get("failed", 0)
    if (type(n) is not int or n < 0 or not isinstance(timers, list)
            or len(timers) > n or type(failed) is not int or not 0 <= failed <= n):
        raise StateError("invalid care plan counts")
    for timer in timers:
        if (not isinstance(timer, dict) or not isinstance(timer.get("id"), str)
                or not timer["id"] or not isinstance(timer.get("at"), str)):
            raise StateError("invalid care timer record")
    if len({timer["id"] for timer in timers}) != len(timers):
        raise StateError("duplicate care timer ids")
    if "attempts" in plan:
        attempts = plan["attempts"]
        if not isinstance(attempts, list) or len(attempts) != n:
            raise StateError("invalid care attempts")
        expected = []
        for item in attempts:
            if (not isinstance(item, dict) or not isinstance(item.get("status"), str)
                    or item["status"] not in
                    {"ready", "creating", "scheduled", "uncertain", "expired"}):
                raise StateError("invalid care attempt status")
            try:
                when = datetime.datetime.strptime(item.get("at", ""), "%Y-%m-%d %H:%M")
            except (ValueError, TypeError) as exc:
                raise StateError("invalid care attempt time") from exc
            allowed_days = {day, day + datetime.timedelta(days=1)} if allow_next_day else {day}
            if when.date() not in allowed_days or when.strftime("%Y-%m-%d %H:%M") != item["at"]:
                raise StateError("inconsistent care attempt date")
            if item["status"] == "scheduled":
                expected.append({"id": item.get("id"), "at": item["at"]})
        if timers != expected or failed != n - len(expected):
            raise StateError("inconsistent care attempt results")
    return plan
