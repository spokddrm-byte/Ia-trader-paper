import os
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from indicators import sma, ema, rsi, volatility
from risk_manager import risk_check
from database import (
    initialize_database,
    log_event,
    get_today_trade_count,
    get_today_loss
)


def main():

    # =========================
    # BASE DE DATOS
    # =========================

    initialize_database()

    # =========================
    # CREDENCIALES
    # =========================

    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not secret_key:
        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY EN RAILWAY"
        )

    # =========================
    # CONEXION CON ALPACA
    # =========================

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

    print("==============================================")
    print("          AI TRADER — PAPER ANALYSIS")
    print("==============================================")
    print()
    print("CONEXION CON ALPACA: OK")
    print(f"Cuenta: {account.status}")
    print(f"Capital: ${account_value:,.2f}")
    print("MODO: PAPER")
    print("ORDENES: DESACTIVADAS")
    print()

    # =========================
    # ESTADO DEL BOT
    # =========================

    trades_today = get_today_trade_count()
    daily_loss = get_today_loss()

    print("=== ESTADO DEL BOT ===")
    print(f"Fecha UTC: {datetime.now(timezone.utc).date()}")
    print(f"Operaciones ejecutadas hoy: {trades_today}")
    print(f"Perdida diaria: ${daily_loss:.2f}")
    print()

    # =========================
    # MERCADO
    # =========================

    clock = trading_client.get_clock()

    print("=== ESTADO DEL MERCADO ===")
    print(f"Mercado abierto: {clock.is_open}")

    if not clock.is_open:
        print(f"Proxima apertura: {clock.next_open}")
        print(f"Proximo cierre: {clock.next_close}")

    print()

    # =========================
    # DATOS AAPL
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

    print("=== DATOS DEL MERCADO ===")
    print("Simbolo: AAPL")
    print("Feed: IEX")
    print(f"Velas recibidas: {len(closes)}")
    print()

    if len(closes) < 20:
        print("DATOS INSUFICIENTES")
        print("NO SE GENERA SEÑAL")
        return

    # =========================
    # INDICADORES
    # =========================

    current_price = closes[-1]

    sma20 = sma(closes, 20)
    ema20 = ema(closes, 20)
    rsi14 = rsi(closes, 14)
    vol20 = volatility(closes, 20)

    print("=== AAPL — ANALISIS ===")
    print(f"Precio: ${current_price:.2f}")
    print(f"SMA 20: ${sma20:.2f}")
    print(f"EMA 20: ${ema20:.2f}")
    print(f"RSI 14: {rsi14:.2f}")
    print(f"Volatilidad 20: {vol20:.4f}")
    print()

    # =========================
    # ESTRATEGIA
    # =========================

    print("=== ESTRATEGIA ===")

    if current_price > ema20 and rsi14 < 70:
        signal = "COMPRAR"

    elif current_price < ema20 and rsi14 > 30:
        signal = "VENDER"

    else:
        signal = "ESPERAR"

    print(f"Señal generada: {signal}")
    print()

    # =========================
    # STOP LOSS
    # =========================

    if signal == "COMPRAR":
        stop_price = current_price * 0.97

    elif signal == "VENDER":
        stop_price = current_price * 1.03

    else:
        stop_price = current_price

    print("=== GESTION DE RIESGO ===")
    print(f"Entrada de referencia: ${current_price:.2f}")
    print(f"Stop de referencia: ${stop_price:.2f}")

    # =========================
    # RISK MANAGER
    # =========================

    approved, message = risk_check(
        signal=signal,
        account_value=account_value,
        entry_price=current_price,
        stop_price=stop_price,
        daily_loss=daily_loss,
        trades_today=trades_today
    )

    print(f"Autorizacion: {approved}")
    print(message)
    print()

    # =========================
    # REGISTRO
    # =========================

    position_size = 0

    if approved:
        try:
            position_size = int(message.split("—")[1].split()[0])
        except (IndexError, ValueError):
            position_size = 0

    event_id = log_event(
        symbol="AAPL",
        signal=signal,
        entry_price=current_price,
        stop_price=stop_price,
        position_size=position_size,
        status="SIGNAL_ONLY",
        profit_loss=0.0
    )

    print("=== DATABASE ===")
    print(f"Analisis registrado: #{event_id}")
    print(f"Tamaño calculado: {position_size}")
    print("Estado: SIGNAL_ONLY")
    print()

    # =========================
    # SEGURIDAD
    # =========================

    print("=== SEGURIDAD ===")

    if approved:
        print("RIESGO APROBADO")
        print("ORDEN NO ENVIADA")
        print("ESTE ARCHIVO SOLO ANALIZA")
    else:
        print("OPERACION NO AUTORIZADA")
        print("ORDEN NO ENVIADA")

    print()
    print("==============================================")
    print("          ANALISIS COMPLETADO")
    print("==============================================")


if __name__ == "__main__":
    main()
