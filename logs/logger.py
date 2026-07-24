import logging


class TradeLogger:

    def __init__(self):

        logging.basicConfig(
            filename="logs/trading.log",
            level=logging.INFO,
            format="%(asctime)s | %(message)s"
        )


    def log_signal(self, symbol, signal, confidence):

        message = (
            f"{symbol} | "
            f"Signal: {signal} | "
            f"Confidence: {confidence}%"
        )

        logging.info(message)


    def log_trade(self, symbol, trade, position):

        message = (
            f"{symbol} | "
            f"ENTRY: {trade['entry']} | "
            f"SL: {trade['stop_loss']} | "
            f"TP: {trade['take_profit']} | "
            f"RR: {trade['risk_reward']} | "
            f"POSITION: {position}"
        )

        logging.info(message)