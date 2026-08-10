import threading
import time
from types import SimpleNamespace

from bot_controller import BotController
from bot_loop import BotLoop


class Execution:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def shutdown(self):
        self.stopped = True


def test_controller_runs_position_management_independently_of_slow_scan():
    execution = Execution()
    scan_entered = threading.Event()
    release_scan = threading.Event()
    management_entered = threading.Event()

    def slow_scan():
        scan_entered.set()
        release_scan.wait(1.0)

    def manage():
        management_entered.set()

    controller = BotController.configured(
        bot_loop=BotLoop(interval=60),
        execution_router=execution,
        callback=slow_scan,
        management_loop=BotLoop(interval=1),
        management_callback=manage,
    )

    controller.start_bot()
    try:
        assert scan_entered.wait(0.5)
        assert management_entered.wait(0.5)
        assert execution.started is True
    finally:
        release_scan.set()
    controller.stop_bot()

    assert execution.stopped is True
    assert controller.status() == "STOPPED"


def test_controller_reports_stopped_if_management_loop_dies():
    scan_release = threading.Event()

    def scan_callback():
        scan_release.wait(timeout=1)

    def failed_management_callback():
        raise RuntimeError("management failed")

    execution = Execution()
    controller = BotController.configured(
        bot_loop=BotLoop(interval=60),
        execution_router=execution,
        callback=scan_callback,
        management_loop=BotLoop(interval=1, max_consecutive_failures=1),
        management_callback=failed_management_callback,
    )
    controller.start_bot()

    deadline = time.time() + 2
    while controller.status() != "STOPPED" and time.time() < deadline:
        time.sleep(0.01)

    assert controller.status() == "STOPPED"
    scan_release.set()
    controller.stop_bot()
