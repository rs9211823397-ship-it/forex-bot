import json
import os


class PaperAccount:

    FILE = "account.json"

    def __init__(self, starting_balance=1000.0):

        if os.path.exists(self.FILE):

            self.load()

        else:

            self.starting_balance = float(starting_balance)
            self.balance = float(starting_balance)
            self.equity = float(starting_balance)
            self.floating_pnl = 0.0
            self.highest_balance = float(starting_balance)
            self.max_drawdown = 0.0

            self.save()


    def save(self):

        data = {

            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "equity": self.equity,
            "floating_pnl": self.floating_pnl,
            "highest_balance": self.highest_balance,
            "max_drawdown": self.max_drawdown

        }

        with open(self.FILE, "w") as f:
            json.dump(data, f, indent=4)



    def load(self):

        with open(self.FILE, "r") as f:
            data = json.load(f)


        self.starting_balance = data["starting_balance"]
        self.balance = data["balance"]
        self.equity = data["equity"]
        self.floating_pnl = data["floating_pnl"]
        self.highest_balance = data["highest_balance"]
        self.max_drawdown = data["max_drawdown"]



    def update_balance(self, pnl):

        self.balance = round(
            self.balance + pnl,
            4
        )

        if self.balance > self.highest_balance:
            self.highest_balance = self.balance

        drawdown = self.highest_balance - self.balance

        if drawdown > self.max_drawdown:
            self.max_drawdown = round(drawdown, 4)

        self.save()



    def update_equity(self, floating_pnl):

        self.floating_pnl = round(floating_pnl, 4)

        self.equity = round(
            self.balance + self.floating_pnl,
            4
        )

        self.save()



    def get_account_info(self):

        return {

            "starting_balance": self.starting_balance,

            "balance": self.balance,

            "equity": self.equity,

            "floating_pnl": self.floating_pnl,

            "max_drawdown": self.max_drawdown
        }