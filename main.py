import os

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest


def main():
    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]

    # Conexión a Alpaca Paper
    trading_client = TradingClient(
        api_key,
        secret_key,
        paper=True
    )

    # Datos del mercado
    data_client = StockHistoricalDataClient(
        api_key,
        secret_key
    )

    # Cuenta
    account = trading_client.get_account()

    print("=== AI TRADER — PAPER TRADING ===")
    print(f"Estado de cuenta: {account.status}")
    print(f"Saldo: ${account.cash}")
    print(f"Valor de la cuenta: ${account.portfolio_value}")
    print("Modo: PAPER")
    print("ÓRDENES: DESACTIVADAS")

    # Cotización de AAPL
    request = StockLatestQuoteRequest(
        symbol_or_symbols=["AAPL"]
    )

    quotes = data_client.get_stock_latest_quote(request)
    quote = quotes["AAPL"]

    print()
    print("=== DATOS DEL MERCADO ===")
    print("Activo: AAPL")
    print(f"Bid: ${quote.bid_price}")
    print(f"Ask: ${quote.ask_price}")
    print(f"Tamaño Bid: {quote.bid_size}")
    print(f"Tamaño Ask: {quote.ask_size}")


if __name__ == "__main__":
    main()
