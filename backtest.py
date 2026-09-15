import os
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
# VARIABLES
# =========================

capital = INITIAL_CAPITAL

position = 0

entry_price = 0.0

stop_price = 0.0

trades = []

equity_curve = []

wins = 0

losses = 0


# =========================
# BACKTEST
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

        # =========================
        # STOP LOSS
        # =========================

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


        # =========================
        # SALIDA EMA
        # =========================

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
    # EQUITY CURVE
    # =========================

    if position > 0:

        unrealized = (
            price - entry_price
        ) * position

        current_equity = capital + unrealized

    else:

        current_equity = capital

    equity_curve.append(current_equity)


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
# ESTADÍSTICAS BÁSICAS
# =========================

total_trades = len(trades)

total_profit = capital - INITIAL_CAPITAL

if total_trades > 0:

    win_rate = (
        wins / total_trades
    ) * 100

else:

    win_rate = 0.0


# =========================
# MEJOR / PEOR OPERACIÓN
# =========================

if trades:

    best_trade = max(trades)

    worst_trade = min(trades)

else:

    best_trade = 0.0

    worst_trade = 0.0


# =========================
# PROFIT FACTOR
# =========================

gross_profit = sum(
    trade for trade in trades
    if trade > 0
)

gross_loss = abs(
    sum(
        trade for trade in trades
        if trade < 0
    )
)

if gross_loss > 0:

    profit_factor = (
        gross_profit / gross_loss
    )

else:

    profit_factor = float("inf")


# =========================
# Racha máxima de pérdidas
# =========================

max_losing_streak = 0

current_losing_streak = 0

for trade in trades:

    if trade < 0:

        current_losing_streak += 1

        max_losing_streak = max(
            max_losing_streak,
            current_losing_streak
        )

    else:

        current_losing_streak = 0


# =========================
# DRAWDOWN MÁXIMO
# =========================

peak = INITIAL_CAPITAL

max_drawdown = 0.0

max_drawdown_percent = 0.0

for equity in equity_curve:

    if equity > peak:

        peak = equity

    drawdown = peak - equity

    if drawdown > max_drawdown:

        max_drawdown = drawdown

        if peak > 0:

            max_drawdown_percent = (
                drawdown / peak
            ) * 100


# =========================
# BUY & HOLD
# =========================

first_price = closes[0]

last_price = closes[-1]

buy_hold_return = (
    (last_price - first_price)
    / first_price
) * 100

buy_hold_capital = (
    INITIAL_CAPITAL
    * (1 + buy_hold_return / 100)
)

strategy_return = (
    total_profit
    / INITIAL_CAPITAL
) * 100


# =========================
# RESULTADOS
# =========================

print()

print("================================")
print("     RESULTADOS DEL BACKTEST")
print("================================")

print()

print(f"Capital inicial: ${INITIAL_CAPITAL:.2f}")

print(f"Capital final:   ${capital:.2f}")

print(f"Resultado:       ${total_profit:.2f}")

print(f"Rendimiento:     {strategy_return:.2f}%")

print()

print(f"Operaciones:     {total_trades}")

print(f"Ganadoras:       {wins}")

print(f"Perdedoras:      {losses}")

print(f"Win rate:        {win_rate:.2f}%")

print()

print(f"Mejor operación: ${best_trade:.2f}")

print(f"Peor operación:  ${worst_trade:.2f}")

print()

print(f"Profit Factor:   {profit_factor:.2f}")

print(
    f"Racha máx. pérdidas: "
    f"{max_losing_streak}"
)

print()

print(
    f"Drawdown máximo: "
    f"${max_drawdown:.2f}"
)

print(
    f"Drawdown máximo: "
    f"{max_drawdown_percent:.2f}%"
)

print()

print("================================")
print("       BUY & HOLD")
print("================================")

print()

print(
    f"Rendimiento AAPL: "
    f"{buy_hold_return:.2f}%"
)

print(
    f"Capital final: "
    f"${buy_hold_capital:.2f}"
)

print()

print("================================")
print("        COMPARACIÓN")
print("================================")

print()

print(
    f"Estrategia: "
    f"{strategy_return:.2f}%"
)

print(
    f"Buy & Hold: "
    f"{buy_hold_return:.2f}%"
)

print(
    f"Diferencia: "
    f"{strategy_return - buy_hold_return:.2f}%"
)

print()

print("================================")
print("          SEGURIDAD")
print("================================")

print()

print("BACKTEST SOLAMENTE")
print("NO SE ENVIARON ÓRDENES")
