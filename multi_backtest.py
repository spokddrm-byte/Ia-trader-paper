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

SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL"
]

PERIODS = {
    "1 AÑO": 365,
    "3 AÑOS": 1095,
    "5 AÑOS": 1825
}

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
# FUNCIÓN DE BACKTEST
# =========================

def run_backtest(closes):

    if len(closes) < 50:
        return None

    capital = INITIAL_CAPITAL

    position = 0

    entry_price = 0.0

    stop_price = 0.0

    trades = []

    equity_curve = []

    wins = 0

    losses = 0


    # =========================
    # RECORRER DATOS
    # =========================

    for i in range(20, len(closes)):

        price = closes[i]

        history = closes[:i + 1]

        ema20 = ema(history, 20)

        rsi14 = rsi(history, 14)

        if ema20 is None or rsi14 is None:
            continue


        # =========================
        # ENTRADA
        # =========================

        if position == 0:

            if price > ema20 and rsi14 < 70:

                risk_amount = (
                    capital * RISK_PER_TRADE
                )

                risk_per_share = (
                    price * STOP_PERCENT
                )

                shares = int(
                    risk_amount / risk_per_share
                )

                if shares > 0:

                    position = shares

                    entry_price = price

                    stop_price = (
                        price * (1 - STOP_PERCENT)
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

                position = 0

                entry_price = 0.0

                stop_price = 0.0


            # SALIDA EMA

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

                position = 0

                entry_price = 0.0

                stop_price = 0.0


        # =========================
        # EQUITY
        # =========================

        if position > 0:

            unrealized = (
                price - entry_price
            ) * position

            equity = capital + unrealized

        else:

            equity = capital

        equity_curve.append(equity)


    # =========================
    # CERRAR POSICIÓN
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


    # =========================
    # ESTADÍSTICAS
    # =========================

    total_trades = len(trades)

    total_profit = (
        capital - INITIAL_CAPITAL
    )

    if total_trades > 0:

        win_rate = (
            wins / total_trades
        ) * 100

    else:

        win_rate = 0.0


    # =========================
    # PROFIT FACTOR
    # =========================

    gross_profit = sum(
        trade
        for trade in trades
        if trade > 0
    )

    gross_loss = abs(
        sum(
            trade
            for trade in trades
            if trade < 0
        )
    )

    if gross_loss > 0:

        profit_factor = (
            gross_profit / gross_loss
        )

    else:

        profit_factor = 0.0


    # =========================
    # DRAWDOWN
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


    # =========================
    # RESULTADO
    # =========================

    strategy_return = (
        total_profit
        / INITIAL_CAPITAL
    ) * 100


    return {
        "return": strategy_return,
        "buy_hold": buy_hold_return,
        "trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "drawdown": max_drawdown_percent
    }


# =========================
# EJECUTAR PRUEBAS
# =========================

print("========================================")
print("       AI TRADER — MULTI BACKTEST")
print("========================================")
print()

results = []


for symbol in SYMBOLS:

    print(f"Analizando {symbol}...")

    for period_name, days in PERIODS.items():

        end = datetime.now(timezone.utc)

        start = end - timedelta(days=days)

        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=DataFeed.IEX
        )

        try:

            bars = data_client.get_stock_bars(
                request
            )

            symbol_bars = bars[symbol]

            closes = [
                float(bar.close)
                for bar in symbol_bars
            ]

            result = run_backtest(closes)

            if result is None:

                print(
                    f"  {period_name}: "
                    f"DATOS INSUFICIENTES"
                )

                continue


            results.append({
                "symbol": symbol,
                "period": period_name,
                **result
            })


            print(
                f"  {period_name}: "
                f"{result['return']:.2f}% | "
                f"Buy&Hold "
                f"{result['buy_hold']:.2f}% | "
                f"DD "
                f"{result['drawdown']:.2f}%"
            )


        except Exception as error:

            print(
                f"  {period_name}: ERROR"
            )

            print(error)


    print()


# =========================
# TABLA FINAL
# =========================

print()
print("========================================")
print("             RESULTADOS")
print("========================================")

print()

print(
    "ACTIVO | PERIODO | ESTRATEGIA | "
    "BUY&HOLD | TRADES | WINRATE | "
    "PF | DRAWDOWN"
)

print("-" * 85)


for result in results:

    print(
        f"{result['symbol']:6} | "
        f"{result['period']:7} | "
        f"{result['return']:9.2f}% | "
        f"{result['buy_hold']:8.2f}% | "
        f"{result['trades']:6} | "
        f"{result['win_rate']:7.2f}% | "
        f"{result['profit_factor']:4.2f} | "
        f"{result['drawdown']:7.2f}%"
    )


# =========================
# SEGURIDAD
# =========================

print()
print("========================================")
print("             SEGURIDAD")
print("========================================")
print()
print("MULTI BACKTEST SOLAMENTE")
print("NO SE ENVIARON ÓRDENES")
