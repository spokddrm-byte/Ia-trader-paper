import os

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

from strategy import calculate_signal, risk_check


def main():
    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]

    trading_client = TradingClient(
        api_key,
        secret_key,
        paper=True
    )

    data_client = StockHistoricalDataClient(
        api_key,
        secret_key
    )

    # Cuenta Paper
    account = trading_client.get_account()

    print("=== AI TRADER ===")
    print(f"Cuenta: {account.status}")
    print(f"Saldo: ${account.cash}")
    print("Modo: PAPER")
    print("ÓRDENES: DESACTIVADAS")

    # Obtener AAPL
    request = StockLatestQuoteRequest(
        symbol_or_symbols=["AAPL"]
    )

    quotes = data_client.get_stock_latest_quote(request)
    quote = quotes["AAPL"]

    bid = quote.bid_price
    ask = quote.ask_price

    print()
    print("=== MERCADO ===")
    print(f"AAPL Bid: ${bid}")
    print(f"AAPL Ask: ${ask}")

    # Protección contra datos incompletos
    if not bid or not ask or ask <= 0:
        print("DATOS INCOMPLETOS — SEÑAL DESCARTADA")
        return

    # Precio medio entre Bid y Ask
    price = (bid + ask) / 2

    # Media temporal provisional
    moving_average = price

    signal = calculate_signal(price, moving_average)
    result = risk_check(signal)

    print()
    print("=== ANALISIS ===")
    print(f"Precio: ${price:.2f}")
    print(f"Media móvil: ${moving_average:.2f}")
    print(f"Señal: {signal}")
    print(f"Filtro de riesgo: {result}")
    print("ÓRDENES: DESACTIVADAS")


if __name__ == "__main__":
    main()
