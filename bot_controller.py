import logging
import threading
from typing import Callable

from execution.execution_router import ExecutionRouter
from runtime.bot_loop import BotLoop


logger = logging.getLogger(__name__)


class BotController:
    """
    Production-grade controller for the AAQTS trading bot.

    Responsibilities:
    - Start/stop the bot
    - Pause/resume execution
    - Manage MT5 lifecycle
    - Run BotLoop in a background thread
    """

    def __init__(
        self,
        bot_loop: BotLoop,
        execution_router: ExecutionRouter,
        callback: Callable[[], None],
    ) -> None:

        self.bot_loop = bot_loop
        self.execution_router = execution_router
        self.callback = callback

        self.running = False
        self.paused = False

        self._thread: threading.Thread | None = None

    def start_bot(self) -> str:

        if self.running:
            return "BOT ALREADY RUNNING"

        logger.info("Starting AAQTS Bot")

        self.execution_router.start()

        self.running = True
        self.paused = False

        self._thread = threading.Thread(
            target=self.bot_loop.start,
            args=(self.callback,),
            daemon=True,
            name="AAQTS-BotLoop",
        )

        self._thread.start()

        logger.info("AAQTS Bot started successfully")

        return "BOT STARTED"

    def stop_bot(self) -> str:

        if not self.running:
            return "BOT ALREADY STOPPED"

        logger.info("Stopping AAQTS Bot")

        self.bot_loop.stop()

        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

        self.execution_router.shutdown()

        self.running = False
        self.paused = False

        logger.info("AAQTS Bot stopped")

        return "BOT STOPPED"

    def pause_bot(self) -> str:

        if not self.running:
            return "BOT IS NOT RUNNING"

        if self.paused:
            return "BOT ALREADY PAUSED"

        logger.info("Pausing execution")

        self.execution_router.pause()

        self.paused = True

        return "BOT PAUSED"

    def resume_bot(self) -> str:

        if not self.running:
            return "BOT IS NOT RUNNING"

        if not self.paused:
            return "BOT IS NOT PAUSED"

        logger.info("Resuming execution")

        self.execution_router.resume()

        self.paused = False

        return "BOT RESUMED"

    def emergency_stop(self):

        logger.critical("Emergency stop initiated")

        positions = self.execution_router.emergency_stop()

        self.bot_loop.stop()

        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

        self.execution_router.shutdown()

        self.running = False
        self.paused = False

        logger.critical("Emergency stop completed")

        return positions

    def status(self) -> str:

        if not self.running:
            return "STOPPED"

        if self.paused:
            return "PAUSED"

        return "RUNNING"

    @property
    def is_running(self) -> bool:
        return self.running

    @property
    def is_paused(self) -> bool:
        return self.paused