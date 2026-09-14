from datetime import datetime, timezone


class BotState:
    def __init__(self):
        self.date = self.current_date()
        self.trades_today = 0
        self.daily_loss = 0.0

    def current_date(self):
        return datetime.now(timezone.utc).date()

    def reset_if_new_day(self):
        today = self.current_date()

        if today != self.date:
            self.date = today
            self.trades_today = 0
            self.daily_loss = 0.0

    def register_trade(self):
        self.reset_if_new_day()
        self.trades_today += 1

    def register_loss(self, loss):
        self.reset_if_new_day()

        if loss > 0:
            self.daily_loss += loss

    def get_status(self):
        self.reset_if_new_day()

        return {
            "date": str(self.date),
            "trades_today": self.trades_today,
            "daily_loss": self.daily_loss
        }


if __name__ == "__main__":
    print("=== AI TRADER — BOT STATE ===")

    state = BotState()

    print(state.get_status())

    state.register_trade()
    state.register_loss(100)

    print()
    print("Después de una operación:")
    print(state.get_status())
