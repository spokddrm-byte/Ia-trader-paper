from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from indicators import ema, rsi


# =========================
# CONFIGURACIÓN
# =========================

SYMBOL = "AAPL"

INITIAL_CAPITAL = 100000.0

RISK_PER_TRADE = 0.01

STOP_PERCENT = 0.03


# =========================
# CONEXIÓN CON ALPACA
# =========================

import os

api_key = os.environ["ALPACA_API_KEY"]
secret_key = os.environ["ALPACA_SECRET_KEY"]

data_client = StockHistoricalDataClient(
    api_key,
    secret_key
)


# =========================
# OBTENER DATOS
# =========================

end = datetime.now(timezone.utc)

start = end - timedelta(days=365)


request = StockBarsRequest(
    symbol_or_symbols=[SYMBOL],
    timeframe=TimeFrame.Day,
    start=start,
    end=end,
    feed=DataFeed.IEX
)


bars = data_client.get_stock_bars(request)

symbol_bars = bars[SYMBOL]


closes = [
    float(bar.close)
    for bar in symbol_bars
]


print("=== AI TRADER — BACKTEST ===")
print(f"Símbolo: {SYMBOL}")
print(f"Velas históricas: {len(closes)}")
print(f"Capital inicial: ${INITIAL_CAPITAL:.2f}")
print()


# =========================
# VALIDACIÓN
# =========================

if len(closes) < 50:
    print("DATOS INSUFICIENTES")
    raise SystemExit


# =========================
# VARIABLES DEL BACKTEST
# =========================

capital = INITIAL_CAPITAL

position = 0

entry_price = 0.0

stop_price = 0.0

trades = []

wins = 0

losses = 0


# =========================
# RECORRER HISTÓRICO
# =========================

for i in range(20, len(closes)):

    price = closes[i]

    history = closes[:i + 1]


    # =========================
    # INDICADORES
    # =========================

    ema20 = ema(history, 20)

    rsi14 = rsi(history, 14)


    if ema20 is None or rsi14 is None:
        continue


    # =========================
    # SEÑAL
    # =========================

    if position == 0:

        if price > ema20 and rsi14 < 70:

            signal = "COMPRAR"

        else:

            signal = "ESPERAR"


        # =========================
        # ENTRADA
        # =========================

        if signal == "COMPRAR":

            risk_amount = capital * RISK_PER_TRADE

            risk_per_share = price * STOP_PERCENT

            shares = int(
                risk_amount / risk_per_share
            )


            if shares > 0:

                position = shares

                entry_price = price

                stop_price = price * (1 - STOP_PERCENT)

                print(
                    f"ENTRADA | Día {i} | "
                    f"Precio ${price:.2f} | "
                    f"Acciones {shares} | "
                    f"Stop ${stop_price:.2f}"
                )


    # =========================
    # POSICIÓN ABIERTA
    # =========================

    else:

        # STOP LOSS

        if price <= stop_price:

            profit_loss = (
                price - entry_price
            ) * position


            capital += profit_loss


            trades.append(profit_loss)


            if profit_loss >= 0:
                wins += 1
            else:
                losses += 1


            print(
                f"SALIDA STOP | Día {i} | "
                f"Precio ${price:.2f} | "
                f"P/L ${profit_loss:.2f}"
            )


            position = 0

            entry_price = 0.0

            stop_price = 0.0


        # SALIDA POR CAMBIO DE TENDENCIA

        elif price < ema20:

            profit_loss = (
                price - entry_price
            ) * position


            capital += profit_loss


            trades.append(profit_loss)


            if profit_loss >= 0:
                wins += 1
            else:
                losses += 1


            print(
                f"SALIDA EMA | Día {i} | "
                f"Precio ${price:.2f} | "
                f"P/L ${profit_loss:.2f}"
            )


            position = 0

            entry_price = 0.0

            stop_price = 0.0


# =========================
# CERRAR POSICIÓN FINAL
# =========================

if position > 0:

    final_price = closes[-1]

    profit_loss = (
        final_price - entry_price
    ) * position


    capital += profit_loss

    trades.append(profit_loss)


    if profit_loss >= 0:
        wins += 1
    else:
        losses += 1


    print(
        f"SALIDA FINAL | "
        f"Precio ${final_price:.2f} | "
        f"P/L ${profit_loss:.2f}"
    )


# =========================
# ESTADÍSTICAS
# =========================

total_trades = len(trades)

if total_trades > 0:

    win_rate = (
        wins / total_trades
    ) * 100

else:

    win_rate = 0


total_profit = capital - INITIAL_CAPITAL


print()
print("=== RESULTADOS DEL BACKTEST ===")

print(
    f"Capital inicial: "
    f"${INITIAL_CAPITAL:.2f}"
)

print(
    f"Capital final: "
    f"${capital:.2f}"
)

print(
    f"Resultado: "
    f"${total_profit:.2f}"
)

print(
    f"Operaciones: "
    f"{total_trades}"
)

print(
    f"Ganadoras: "
    f"{wins}"
)

print(
    f"Perdedoras: "
    f"{losses}"
)

print(
    f"Win rate: "
    f"{win_rate:.2f}%"
)

print()
print("=== SEGURIDAD ===")
print("BACKTEST SOLAMENTE")
print("NO SE ENVIARON ÓRDENES")
