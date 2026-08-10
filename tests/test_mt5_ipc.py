import threading
import time
import subprocess
import sys

import pytest

from mt5_ipc import MT5IPCLockTimeout, mt5_ipc_lock


def test_mt5_ipc_lock_is_same_thread_reentrant(tmp_path):
    lock_path = tmp_path / "mt5.lock"

    with mt5_ipc_lock(0.5, lock_path=lock_path):
        with mt5_ipc_lock(0.5, lock_path=lock_path):
            assert lock_path.exists()


def test_mt5_ipc_lock_serializes_threads(tmp_path):
    lock_path = tmp_path / "mt5.lock"
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with mt5_ipc_lock(1.0, lock_path=lock_path):
            entered.set()
            release.wait(1.0)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(1.0)

    started = time.monotonic()
    with pytest.raises(MT5IPCLockTimeout):
        with mt5_ipc_lock(0.1, lock_path=lock_path):
            pass
    assert time.monotonic() - started >= 0.09

    release.set()
    thread.join(1.0)
    assert not thread.is_alive()


def test_mt5_ipc_lock_serializes_processes(tmp_path):
    lock_path = tmp_path / "mt5-process.lock"
    script = (
        "import sys,time; "
        "from mt5_ipc import mt5_ipc_lock; "
        f"p={str(lock_path)!r}; "
        "ctx=mt5_ipc_lock(2.0,lock_path=p); ctx.__enter__(); "
        "print('LOCKED',flush=True); time.sleep(0.5); ctx.__exit__(None,None,None)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(MT5IPCLockTimeout):
            with mt5_ipc_lock(0.1, lock_path=lock_path):
                pass
    finally:
        child.wait(timeout=2.0)
    assert child.returncode == 0
