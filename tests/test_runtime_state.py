import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import runtime_state
from runtime_state import EngineInstanceLock


def _use_temporary_runtime(monkeypatch, tmp_path):
    state_file = tmp_path / "aaqts_status.json"
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime_state, "STATE_FILE", state_file)
    return state_file


def test_runtime_state_writes_are_thread_safe(monkeypatch, tmp_path):
    state_file = _use_temporary_runtime(monkeypatch, tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda value: runtime_state.write_runtime_state(value=value), range(80)))

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["value"] in range(80)
    assert state["heartbeat_utc"]
    assert not list(tmp_path.glob("aaqts_status_*.json"))


def test_runtime_state_retries_transient_windows_replace_error(
    monkeypatch,
    tmp_path,
):
    state_file = _use_temporary_runtime(monkeypatch, tmp_path)
    real_replace = runtime_state.os.replace
    calls = 0

    def flaky_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("temporarily locked")
        return real_replace(source, destination)

    monkeypatch.setattr(runtime_state.os, "replace", flaky_replace)

    runtime_state.write_runtime_state(status="RUNNING")

    assert calls == 3
    assert json.loads(state_file.read_text(encoding="utf-8"))["status"] == "RUNNING"


def test_engine_instance_lock_rejects_duplicate_worker(tmp_path):
    first = EngineInstanceLock("primary", tmp_path).acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            EngineInstanceLock("primary", tmp_path).acquire()
    finally:
        first.release()

    second = EngineInstanceLock("primary", tmp_path).acquire()
    second.release()
