import os

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from indicators import sma, ema, rsi, volatility


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

    account = trading_client.get_account()

    print("=== AI TRADER ===")
    print(f"Cuenta: {account.status}")
    print(f"Saldo: ${account.cash}")
    print("Modo: PAPER")
    print("ÓRDENES: DESACTIVADAS")

    # Obtener velas de AAPL
    request = StockBarsRequest(
        symbol_or_symbols=["AAPL"],
        timeframe=TimeFrame.Day,
        limit=100
    )

    bars = data_client.get_stock_bars(request)

    aapl_bars = bars["AAPL"]

    closes = [float(bar.close) for bar in aapl_bars]

    print()
    print("=== DIAGNOSTICO DE DATOS ===")
    print(f"Velas recibidas: {len(closes)}")

    if len(closes) > 0:
        print(f"Primera vela: {closes[0]}")
        print(f"Última vela: {closes[-1]}")
    else:
        print("No se recibieron velas.")

    if len(closes) < 20:
        print("DATOS INSUFICIENTES — NO SE ANALIZA")
        return

    current_price = closes[-1]

    sma20 = sma(closes, 20)
    ema20 = ema(closes, 20)
    rsi14 = rsi(closes, 14)
    vol20 = volatility(closes, 20)

    print()
    print("=== AAPL — ANALISIS ===")
    print(f"Velas recibidas: {len(closes)}")
    print(f"Precio: ${current_price:.2f}")
    print(f"SMA 20: ${sma20:.2f}")
    print(f"EMA 20: ${ema20:.2f}")
    print(f"RSI 14: {rsi14:.2f}")
    print(f"Volatilidad 20: {vol20:.4f}")

    print()
    print("=== DECISIÓN ===")

    if current_price > ema20 and rsi14 < 70:
        signal = "COMPRAR"

    elif current_price < ema20 and rsi14 > 30:
        signal = "VENDER"

    else:
        signal = "ESPERAR"

    print(f"Señal: {signal}")
    print("ÓRDENES: DESACTIVADAS")


if __name__ == "__main__":
    main()
