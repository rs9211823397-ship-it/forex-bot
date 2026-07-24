class BotController:

    def __init__(self):
        self.running = False
        self.paused = False


    def start_bot(self):
        self.running = True
        self.paused = False
        return "BOT STARTED"


    def stop_bot(self):
        self.running = False
        self.paused = False
        return "BOT STOPPED"


    def pause_bot(self):
        if self.running:
            self.paused = True
            return "BOT PAUSED"

        return "BOT IS NOT RUNNING"


    def resume_bot(self):
        if self.running and self.paused:
            self.paused = False
            return "BOT RESUMED"

        return "BOT IS NOT PAUSED"


    def status(self):

        if not self.running:
            return "STOPPED"

        if self.paused:
            return "PAUSED"

        return "RUNNING"