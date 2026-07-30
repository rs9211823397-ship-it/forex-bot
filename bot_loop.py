import logging
import threading
import time
from typing import Callable


logger = logging.getLogger(__name__)


class BotLoop:
    """
    Production-grade bot execution loop.

    Features:
    - Immediate shutdown
    - Stable execution interval
    - Exception isolation
    - Consecutive failure protection
    - Execution time monitoring
    """

    def __init__(
        self,
        interval: int = 300,
        max_consecutive_failures: int = 5,
    ):
        self.interval = interval
        self.max_consecutive_failures = max_consecutive_failures

        self.active = False
        self._stop_event = threading.Event()

    def start(self, callback: Callable[[], None]) -> None:
        """
        Starts the execution loop.

        Parameters
        ----------
        callback : Callable
            Function executed every interval.
        """

        if self.active:
            raise RuntimeError("BotLoop is already running.")

        self.active = True
        self._stop_event.clear()

        consecutive_failures = 0

        logger.info("========================================")
        logger.info("AAQTS Bot Loop Started")
        logger.info("Execution Interval: %s seconds", self.interval)
        logger.info("========================================")

        while self.active:

            cycle_start = time.perf_counter()

            try:
                callback()

                consecutive_failures = 0

            except Exception:
                consecutive_failures += 1

                logger.exception(
                    "Bot iteration failed (%s/%s)",
                    consecutive_failures,
                    self.max_consecutive_failures,
                )

                if consecutive_failures >= self.max_consecutive_failures:
                    logger.critical(
                        "Maximum consecutive failures reached. Stopping bot loop."
                    )
                    self.stop()
                    break

            execution_time = time.perf_counter() - cycle_start

            if execution_time > self.interval:
                logger.warning(
                    "Execution took %.2f sec (greater than interval %s sec).",
                    execution_time,
                    self.interval,
                )

            remaining = max(0.0, self.interval - execution_time)

            if self._stop_event.wait(remaining):
                break

        self.active = False

        logger.info("========================================")
        logger.info("AAQTS Bot Loop Stopped")
        logger.info("========================================")

    def stop(self) -> None:
        """
        Stops the bot immediately.
        """

        self.active = False
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        """
        Returns True if the loop is currently active.
        """
        return self.active