"""Cross-process serialization for access to one local MT5 terminal.

The MetaTrader5 Python binding owns process-local IPC state, while AAQTS runs
the engine and Telegram manager as separate processes.  A shared file lock
prevents an initialize/read/shutdown sequence in one process from overlapping
an order, history, or candle operation in another.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from runtime_state import RUNTIME_DIR


_THREAD_GATE = threading.Lock()
_LOCAL = threading.local()


class MT5IPCLockTimeout(RuntimeError):
    """Raised when another AAQTS process holds MT5 IPC too long."""


def _try_lock(handle) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError, OSError):
        return False
    return True


def _unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def mt5_ipc_lock(
    timeout_seconds: float | None = None,
    *,
    lock_path: str | Path | None = None,
):
    """Acquire the shared MT5 lock, with same-thread reentrancy."""

    timeout = (
        float(os.getenv("AAQTS_MT5_IPC_LOCK_TIMEOUT_SECONDS", "30"))
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if timeout <= 0:
        raise ValueError("MT5 IPC lock timeout must be positive")
    path = Path(lock_path) if lock_path is not None else RUNTIME_DIR / "aaqts_mt5_ipc.lock"

    depth = int(getattr(_LOCAL, "depth", 0))
    if depth:
        _LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
        return

    deadline = time.monotonic() + timeout
    if not _THREAD_GATE.acquire(timeout=timeout):
        raise MT5IPCLockTimeout(
            f"Timed out waiting {timeout:.1f}s for in-process MT5 access"
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise MT5IPCLockTimeout(
                    f"Timed out waiting {timeout:.1f}s for serialized MT5 access"
                )
            time.sleep(0.05)

        _LOCAL.depth = 1
        try:
            yield
        finally:
            _LOCAL.depth = 0
            try:
                _unlock(handle)
            finally:
                handle.close()
    finally:
        _THREAD_GATE.release()


def serialized_mt5_call(function):
    """Decorate an entire logical MT5 operation, including nested calls."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with mt5_ipc_lock():
            return function(*args, **kwargs)

    return wrapped


__all__ = ["MT5IPCLockTimeout", "mt5_ipc_lock", "serialized_mt5_call"]
