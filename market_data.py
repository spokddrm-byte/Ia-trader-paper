from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
import os


def main():
    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]

    client = StockHistoricalDataClient(
        api_key,
        secret_key
    )

    request = StockLatestQuoteRequest(
        symbol_or_symbols=["AAPL"]
    )

    quotes = client.get_stock_latest_quote(request)

    quote = quotes["AAPL"]

    print("=== AI TRADER — MARKET DATA ===")
    print(f"Activo: AAPL")
    print(f"Bid: ${quote.bid_price}")
    print(f"Ask: ${quote.ask_price}")
    print(f"Último tamaño Bid: {quote.bid_size}")
    print(f"Último tamaño Ask: {quote.ask_size}")


if __name__ == "__main__":
    main()
