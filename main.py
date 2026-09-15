import os
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from indicators import sma, ema, rsi, volatility
from risk_manager import risk_check
from bot_state import BotState
from trade_log import log_event


def main():
    # =========================
    # ESTADO DEL BOT
    # =========================

    state = BotState()
    state.reset_if_new_day()

    # =========================
    # CONEXION CON ALPACA
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
    print("ORDENES: DESACTIVADAS")

    # =========================
    # ESTADO ACTUAL
    # =========================

    status = state.get_status()

    print()
    print("=== ESTADO DEL BOT ===")
    print(f"Fecha: {status['date']}")
    print(f"Operaciones hoy: {status['trades_today']}")
    print(f"Perdida diaria: ${status['daily_loss']:.2f}")

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
    print("Simbolo: AAPL")
    print("Feed: IEX")
    print(f"Velas recibidas: {len(closes)}")

    if len(closes) < 20:
        print("DATOS INSUFICIENTES - NO SE ANALIZA")
        return

    current_price = closes[-1]

    # =========================
    # INDICADORES
    # =========================

    sma20 = sma(closes, 20)
    ema20 = ema(closes, 20)
    rsi14 = rsi(closes, 14)
   
