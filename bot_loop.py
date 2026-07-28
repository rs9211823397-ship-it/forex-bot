import time


class BotLoop:
    def __init__(self, interval=300, controller=None, logger=None):
        if interval <= 0:
            raise ValueError("interval must be greater than zero")
        self.interval = interval
        self.controller = controller
        self.logger = logger
        self.active = False

    def start(self, callback):
        self.active = True
        if self.logger:
            self.logger.log_event("bot_loop_started", interval=self.interval)

        while self.active:
            if self.controller and self.controller.is_stopped:
                break

            if self.controller and not self.controller.should_run:
                time.sleep(min(self.interval, 1))
                continue

            started_at = time.monotonic()
            try:
                callback()
            except Exception as exc:
                if self.logger:
                    self.logger.log_exception("bot_cycle_failed", exc)
                else:
                    print("BOT ERROR:", exc)

            elapsed = time.monotonic() - started_at
            time.sleep(max(0, self.interval - elapsed))

        self.active = False
        if self.logger:
            self.logger.log_event("bot_loop_stopped")

    def stop(self):
        self.active = False
        if self.controller:
            self.controller.stop_bot()
