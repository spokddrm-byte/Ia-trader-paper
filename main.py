import os
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from indicators import sma, ema, rsi, volatility
from risk_manager import risk_check


def main():
    # =========================
    # CONEXIÓN CON ALPACA
    # =========================

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

    account = trading_client.get_account()

    account_value = float(account.equity)

    print("=== AI TRADER ===")
    print(f"Cuenta: {account.status}")
    print(f"Saldo: ${account.cash}")
    print(f"Valor de cuenta: ${account_value:.2f}")
    print("Modo: PAPER")
    print("ÓRDENES: DESACTIVADAS")

    # =========================
    # DATOS DEL MERCADO
    # =========================

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)

    request = StockBarsRequest(
        symbol_or_symbols=["AAPL"],
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=DataFeed.IEX
    )

    bars = data_client.get_stock_bars(request)
    aapl_bars = bars["AAPL"]

    closes = [float(bar.close) for bar in aapl_bars]

    print()
    print("=== DATOS DEL MERCADO ===")
    print("Símbolo: AAPL")
    print("Feed: IEX")
    print(f"Velas recibidas: {len(closes)}")

    if len(closes) < 20:
        print("DATOS INSUFICIENTES — NO SE ANALIZA")
        return

    current_price = closes[-1]

    # =========================
    # INDICADORES
    # =========================

    sma20 = sma(closes, 20)
    ema20 = ema(closes, 20)
    rsi14 = rsi(closes, 14)
    vol20 = volatility(closes, 20)

    print()
    print("=== AAPL — ANALISIS ===")
    print(f"Precio: ${current_price:.2f}")
    print(f"SMA 20: ${sma20:.2f}")
    print(f"EMA 20: ${ema20:.2f}")
    print(f"RSI
