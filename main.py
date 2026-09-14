import os
from alpaca.trading.client import TradingClient


def main():
    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]

    client = TradingClient(
        api_key,
        secret_key,
        paper=True
    )

    account = client.get_account()

    print("=== AI TRADER — PAPER TRADING ===")
    print(f"Estado de cuenta: {account.status}")
    print(f"Saldo: ${account.cash}")
    print(f"Valor de la cuenta: ${account.portfolio_value}")
    print("Modo: PAPER")
    print("ÓRDENES: DESACTIVADAS")


if __name__ == "__main__":
    main()
