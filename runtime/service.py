import threading

from bot_loop import BotLoop
from runtime.runner import run_bot
from runtime.bot_runtime import runtime


class BotService:

    def __init__(self):
        self.loop = BotLoop(interval=10)
        self.thread = None


    def start(self):

        if self.thread and self.thread.is_alive():
            return "BOT ALREADY RUNNING"

        runtime.bot.start_bot()

        self.thread = threading.Thread(
            target=self.loop.start,
            args=(run_bot,),
            daemon=True
        )

        self.thread.start()

        return "BOT SERVICE STARTED"


    def stop(self):

        self.loop.stop()
        runtime.bot.stop_bot()

        return "BOT SERVICE STOPPED"


service = BotService()
