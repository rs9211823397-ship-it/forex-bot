import time


class BotLoop:

    def __init__(self, interval=300):
        self.interval = interval
        self.active = False


    def start(self, callback):

        self.active = True

        print("LIVE BOT LOOP STARTED")


        while self.active:

            try:
                callback()

            except Exception as e:
                print("BOT ERROR:", e)


            time.sleep(self.interval)



    def stop(self):

        self.active = False
        print("LIVE BOT LOOP STOPPED")