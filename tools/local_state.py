"""Cross-process locks for local state; nested operations keep the same lock."""
import contextlib
import json
import os
import threading


class StateError(RuntimeError):
    pass


class StateBusy(StateError):
    pass


_held = threading.local()
_thread_lock = threading.RLock()


@contextlib.contextmanager
def locked(path, *, reentrant=False):
    path = os.path.normcase(os.path.abspath(path))
    if not _thread_lock.acquire(blocking=False):
        raise StateBusy('another local state writer is active')
    try:
        held = getattr(_held, 'paths', set())
        _held.paths = held
        if path in held:
            if not reentrant:
                raise StateBusy('another local state writer is active')
            yield
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Do not unlink this lock inode: another process may already have it open.
        with open(path + '.lock', 'a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if not handle.tell():
                    handle.write(b'\0')
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise StateBusy('another local state writer is active') from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise StateBusy('another local state writer is active') from exc
            held.add(path)
            try:
                yield
            finally:
                held.remove(path)
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        _thread_lock.release()


def read_json(path, absent):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        return absent
    except (OSError, ValueError) as exc:
        raise StateError('cannot read local state; preserve it for inspection') from exc
