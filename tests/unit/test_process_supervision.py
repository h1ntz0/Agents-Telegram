"""Process liveness and stop signalling.

`process_alive` is easy to get wrong on Windows, where `os.kill(pid, 0)` maps to
TerminateProcess: a naive probe kills the process it is inspecting. These tests pin the
non-destructive behaviour.
"""

import os
import subprocess
import sys
import threading
import time

from src.interfaces.cli.main import (
    PID_FILE,
    STOP_FILE,
    process_alive,
    read_pid,
    request_stop,
    wait_for_exit,
)

SLEEPER = "import time; time.sleep(60)"


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", SLEEPER])


def test_current_process_is_alive():
    assert process_alive(os.getpid()) is True


def test_probing_a_live_process_does_not_kill_it():
    child = _spawn_sleeper()
    try:
        for _ in range(5):
            assert process_alive(child.pid) is True
            time.sleep(0.1)
        assert child.poll() is None, "the liveness probe terminated the process it inspected"
    finally:
        child.kill()
        child.wait(timeout=10)


def test_exited_process_is_not_alive():
    child = _spawn_sleeper()
    child.kill()
    child.wait(timeout=10)

    assert process_alive(child.pid) is False


def test_nonsense_pids_are_not_alive():
    assert process_alive(0) is False
    assert process_alive(-1) is False


def test_missing_pid_file_reads_as_none(tmp_path):
    assert read_pid(str(tmp_path / "absent.pid")) is None


def test_corrupt_pid_file_reads_as_none(tmp_path):
    bad = tmp_path / "agent.pid"
    bad.write_text("not-a-number", encoding="utf-8")

    assert read_pid(str(bad)) is None


def test_request_stop_drops_the_sentinel_and_the_process_exits_cleanly(tmp_path, monkeypatch):
    """A stop request must reach a process that cannot receive SIGTERM, such as on Windows."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)

    # The child stands in for the agent: it ignores SIGTERM, so the sentinel file is the
    # only thing that can stop it -- which is the behaviour this test pins on every
    # platform, not just the ones where request_stop cannot deliver a signal.
    script = (
        "import os, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({PID_FILE!r}, 'w').write(str(os.getpid()))\n"
        f"while not os.path.exists({STOP_FILE!r}):\n"
        "    time.sleep(0.1)\n"
        f"os.remove({STOP_FILE!r})\n"
        f"os.remove({PID_FILE!r})\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    # A real agent is reaped by its init parent. POSIX keeps an unreaped child alive as a
    # zombie that `process_alive` still reports as running, so reap it in the background.
    threading.Thread(target=child.wait, daemon=True).start()
    try:
        for _ in range(50):
            if os.path.exists(PID_FILE):
                break
            time.sleep(0.1)

        request_stop(child.pid)

        assert wait_for_exit(child.pid, timeout=20) is True
        assert child.wait(timeout=20) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
