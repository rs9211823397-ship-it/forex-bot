class PaperAccount:

    def __init__(self, starting_balance=1000.0):

        self.starting_balance = float(starting_balance)

        self.balance = float(starting_balance)

        self.equity = float(starting_balance)

        self.floating_pnl = 0.0

        self.highest_balance = float(starting_balance)

        self.max_drawdown = 0.0

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

    def update_equity(self, floating_pnl):

        self.floating_pnl = round(floating_pnl, 4)

        self.equity = round(
            self.balance + self.floating_pnl,
            4
        )

    def get_account_info(self):

        return {

            "starting_balance": self.starting_balance,

            "balance": self.balance,

            "equity": self.equity,

            "floating_pnl": self.floating_pnl,

            "max_drawdown": self.max_drawdown
        }