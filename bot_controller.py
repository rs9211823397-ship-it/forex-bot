from enum import Enum
from threading import RLock


class BotState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class BotController:
    def __init__(self):
        self._state = BotState.STOPPED
        self._lock = RLock()

    def start_bot(self):
        with self._lock:
            self._state = BotState.RUNNING
        return "BOT STARTED"

    def stop_bot(self):
        with self._lock:
            self._state = BotState.STOPPED
        return "BOT STOPPED"

    def pause_bot(self):
        with self._lock:
            if self._state == BotState.RUNNING:
                self._state = BotState.PAUSED
                return "BOT PAUSED"
        return "BOT IS NOT RUNNING"

    def resume_bot(self):
        with self._lock:
            if self._state == BotState.PAUSED:
                self._state = BotState.RUNNING
                return "BOT RESUMED"
        return "BOT IS NOT PAUSED"

    def status(self):
        with self._lock:
            return self._state.value

    @property
    def should_run(self):
        return self.status() == BotState.RUNNING.value

    @property
    def is_stopped(self):
        return self.status() == BotState.STOPPED.value
