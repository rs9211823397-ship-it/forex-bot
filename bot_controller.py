import logging
import threading
from typing import Callable

from execution.execution_router import ExecutionRouter
from bot_loop import BotLoop


logger = logging.getLogger(__name__)


class BotController:
    """Lifecycle controller for the AAQTS trading engine."""

    def __init__(self):
        self.bot_loop: BotLoop | None = None
        self.execution_router: ExecutionRouter | None = None
        self.callback: Callable[[], None] | None = None
        self.running = False
        self.paused = False
        self._thread: threading.Thread | None = None

    @classmethod
    def configured(
        cls,
        bot_loop: BotLoop,
        execution_router: ExecutionRouter,
        callback: Callable[[], None],
    ) -> "BotController":
        controller = cls()
        controller.bot_loop = bot_loop
        controller.execution_router = execution_router
        controller.callback = callback
        return controller

    def start_bot(self):
        if self.status() != "STOPPED":
            return "BOT ALREADY RUNNING"
        logger.info("Starting AAQTS Bot")
        if self.execution_router is not None:
            self.execution_router.start()
        self.running = True
        self.paused = False
        if self.bot_loop is not None and self.callback is not None:
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
        if not self.running and self._thread is None:
            return "BOT ALREADY STOPPED"
        logger.info("Stopping AAQTS Bot")
        if self.bot_loop is not None:
            self.bot_loop.stop()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.error("Bot loop thread did not stop within timeout")
            self._thread = None
        if self.execution_router is not None:
            self.execution_router.shutdown()
        self.running = False
        self.paused = False
        logger.info("AAQTS Bot stopped")
        return "BOT STOPPED"

    def pause_bot(self) -> str:
        if self.status() == "STOPPED":
            return "BOT IS NOT RUNNING"
        if self.paused:
            return "BOT ALREADY PAUSED"
        logger.info("Pausing execution")
        if self.execution_router is not None:
            self.execution_router.pause()
        self.paused = True
        return "BOT PAUSED"

    def resume_bot(self) -> str:
        if self.status() == "STOPPED":
            return "BOT IS NOT RUNNING"
        if not self.paused:
            return "BOT IS NOT PAUSED"
        logger.info("Resuming execution")
        if self.execution_router is not None:
            self.execution_router.resume()
        self.paused = False
        return "BOT RESUMED"

    def emergency_stop(self):
        logger.critical("Emergency stop initiated")
        positions = []
        close_error: Exception | None = None
        try:
            if self.execution_router is not None:
                positions = self.execution_router.emergency_stop()
        except Exception as exc:
            close_error = exc
            logger.exception("Emergency position close was incomplete")
        finally:
            if self.bot_loop is not None:
                self.bot_loop.stop()
            if self._thread is not None:
                self._thread.join(timeout=10)
                if self._thread.is_alive():
                    logger.error("Bot loop thread did not stop within emergency timeout")
                self._thread = None
            if self.execution_router is not None:
                self.execution_router.shutdown()
            self.running = False
            self.paused = False
            logger.critical("Emergency stop completed")
        if close_error is not None:
            raise close_error
        return positions

    def status(self) -> str:
        if not self.running:
            return "STOPPED"
        if self._thread is not None and not self._thread.is_alive():
            return "STOPPED"
        if self.bot_loop is not None and not self.bot_loop.is_running and self._thread is not None:
            return "STOPPED"
        if self.paused:
            return "PAUSED"
        return "RUNNING"

    @property
    def is_running(self) -> bool:
        return self.status() != "STOPPED"

    @property
    def is_paused(self) -> bool:
        return self.status() == "PAUSED"
