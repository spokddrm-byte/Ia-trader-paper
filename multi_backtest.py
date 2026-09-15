import os
import math
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# AI TRADER — MULTI BACKTEST V2
# ============================================================
#
# SOLO BACKTEST
# NO ENVÍA ÓRDENES
#
# Mejoras:
# - Datos ordenados cronológicamente
# - Validación de precios
# - Capital realmente disponible
# - Position sizing por riesgo
# - Stop loss
# - Salida por EMA
# - Slippage
# - Comisiones simuladas
# - Equity curve
# - Drawdown
# - Profit factor
# - Win rate
# - Rachas de pérdidas
# - CAGR
# - Sharpe aproximado
# - Buy & Hold corregido
# ============================================================


# ============================================================
# CONFIGURACIÓN
# ============================================================

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


# Riesgo máximo teórico por operación
RISK_PER_TRADE = 0.01


# Stop loss
STOP_PERCENT = 0.03


# Costos simulados
# 0.05% por entrada y 0.05% por salida
SLIPPAGE_PERCENT = 0.0005


# Comisión simulada
# Alpaca puede tener comisión $0 para acciones,
# pero agregamos un pequeño costo para no hacer
# el backtest demasiado optimista.
COMMISSION_PER_SHARE = 0.01


# ============================================================
# CONEXIÓN ALPACA
# ============================================================

api_key = os.environ["ALPACA_API_KEY"]
secret_key = os.environ["ALPACA_SECRET_KEY"]


data_client = StockHistoricalDataClient(
    api_key,
    secret_key
)


# ============================================================
# INDICADORES
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    average = sum(values[:period]) / period

    for price in values[period:]:
        average = (
            (price - average) * multiplier
        ) + average

    return average


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)

        else:
            gains.append(0)
            losses.append(abs(change))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        average_gain = (
            (average_gain * (period - 1))
            + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1))
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    relative_strength = (
        average_gain / average_loss
    )

    return 100 - (
        100 / (1 + relative_strength)
    )


# ============================================================
# DATOS
# ============================================================

def clean_bars(symbol_bars):

    data = []

    for bar in symbol_bars:

        timestamp = bar.timestamp
        close = float(bar.close)

        if close <= 0:
            continue

        data.append(
            (
                timestamp,
                close
            )
        )

    # IMPORTANTE:
    # Ordenamos explícitamente por fecha.
    data.sort(
        key=lambda item: item[0]
    )

    return data


# ============================================================
# ESTADÍSTICAS
# ============================================================

def calculate_max_drawdown(equity_curve):

    if not equity_curve:
        return 0.0, 0.0

    peak = equity_curve[0]

    max_drawdown = 0.0
    max_drawdown_percent = 0.0

    for equity in equity_curve:

        if equity > peak:
            peak = equity

        if peak <= 0:
            continue

        drawdown = peak - equity

        drawdown_percent = (
            drawdown / peak
        ) * 100

        if drawdown > max_drawdown:
            max_drawdown = drawdown

        if drawdown_percent > max_drawdown_percent:
            max_drawdown_percent = drawdown_percent

    return (
        max_drawdown,
        max_drawdown_percent
    )


def calculate_sharpe(equity_curve):

    if len(equity_curve) < 2:
        return 0.0

    returns = []

    for i in range(1, len(equity_curve)):

        previous = equity_curve[i - 1]
        current = equity_curve[i]

        if previous <= 0:
            continue

        daily_return = (
            current - previous
        ) / previous

        returns.append(daily_return)

    if len(returns) < 2:
        return 0.0

    average = (
        sum(returns)
        / len(returns)
    )

    variance = sum(
        (value - average) ** 2
        for value in returns
    ) / (
        len(returns) - 1
    )

    standard_deviation = math.sqrt(
        variance
    )

    if standard_deviation == 0:
        return 0.0

    # Aproximación anualizada
    return (
        average
        / standard_deviation
    ) * math.sqrt(252)


def calculate_max_losing_streak(trades):

    current = 0
    maximum = 0

    for trade in trades:

        if trade < 0:

            current += 1

            if current > maximum:
                maximum = current

        else:

            current = 0

    return maximum


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(data):

    if len(data) < 50:
        return None

    dates = [
        item[0]
        for item in data
    ]

    closes = [
        item[1]
        for item in data
    ]

    capital = INITIAL_CAPITAL

    position = 0

    entry_price = 0.0
    stop_price = 0.0

    entry_cost = 0.0

    trades = []

    equity_curve = []

    wins = 0
    losses = 0

    total_commissions = 0.0

    # ========================================================
    # RECORRER MERCADO
    # ========================================================

    for i in range(20, len(closes)):

        price = closes[i]

        history = closes[:i + 1]

        ema20 = ema(
            history,
            20
        )

        rsi14 = rsi(
            history,
            14
        )

        if ema20 is None or rsi14 is None:

            equity_curve.append(
                capital
            )

            continue

        # ====================================================
        # ENTRADA
        # ====================================================

        if position == 0:

            signal = (
                price > ema20
                and rsi14 < 70
            )

            if signal:

                stop_distance = (
                    price * STOP_PERCENT
                )

                if stop_distance <= 0:
                    continue

                # Riesgo monetario máximo
                risk_amount = (
                    capital
                    * RISK_PER_TRADE
                )

                shares_by_risk = int(
                    risk_amount
                    / stop_distance
                )

                # Precio real de entrada
                entry_execution_price = (
                    price
                    * (1 + SLIPPAGE_PERCENT)
                )

                # Nunca podemos comprar más
                # acciones de las que podemos pagar.
                shares_by_capital = int(
                    capital
                    / (
                        entry_execution_price
                        + COMMISSION_PER_SHARE
                    )
                )

                shares = min(
                    shares_by_risk,
                    shares_by_capital
                )

                if shares > 0:

                    entry_price = (
                        entry_execution_price
                    )

                    stop_price = (
                        entry_price
                        * (1 - STOP_PERCENT)
                    )

                    entry_cost = (
                        entry_price
                        * shares
                    )

                    commission = (
                        shares
                        * COMMISSION_PER_SHARE
                    )

                    total_cost = (
                        entry_cost
                        + commission
                    )

                    if total_cost <= capital:

                        capital -= total_cost

                        position = shares

                        total_commissions += (
                            commission
                        )

        # ====================================================
        # POSICIÓN ABIERTA
        # ====================================================

        else:

            exit_reason = None

            execution_price = price

            # ------------------------------------------------
            # STOP LOSS
            # ------------------------------------------------

            if price <= stop_price:

                exit_reason = "STOP"

                execution_price = (
                    stop_price
                    * (1 - SLIPPAGE_PERCENT)
                )

            # ------------------------------------------------
            # SALIDA POR EMA
            # ------------------------------------------------

            elif price < ema20:

                exit_reason = "EMA"

                execution_price = (
                    price
                    * (1 - SLIPPAGE_PERCENT)
                )

            # ------------------------------------------------
            # CERRAR
            # ------------------------------------------------

            if exit_reason is not None:

                gross_result = (
                    execution_price
                    - entry_price
                ) * position

                commission = (
                    position
                    * COMMISSION_PER_SHARE
                )

                profit_loss = (
                    gross_result
                    - commission
                )

                capital += (
                    execution_price
                    * position
                )

                capital -= commission

                trades.append(
                    profit_loss
                )

                total_commissions += (
                    commission
                )

                if profit_loss >= 0:
                    wins += 1
                else:
                    losses += 1

                position = 0

                entry_price = 0.0
                stop_price = 0.0
                entry_cost = 0.0

        # ====================================================
        # EQUITY
        # ====================================================

        if position > 0:

            unrealized = (
                price - entry_price
            ) * position

            equity = (
                capital
                + (
                    entry_price
                    * position
                )
                + unrealized
            )

        else:

            equity = capital

        equity_curve.append(
            equity
        )

    # ========================================================
    # CERRAR POSICIÓN FINAL
    # ========================================================

    if position > 0:

        final_price = closes[-1]

        execution_price = (
            final_price
            * (1 - SLIPPAGE_PERCENT)
        )

        gross_result = (
            execution_price
            - entry_price
        ) * position

        commission = (
            position
            * COMMISSION_PER_SHARE
        )

        profit_loss = (
            gross_result
            - commission
        )

        capital += (
            execution_price
            * position
        )

        capital -= commission

        trades.append(
            profit_loss
        )

        total_commissions += (
            commission
        )

        if profit_loss >= 0:
            wins += 1
        else:
            losses += 1

        position = 0

    # ========================================================
    # RESULTADOS
    # ========================================================

    total_trades = len(trades)

    final_capital = capital

    total_profit = (
        final_capital
        - INITIAL_CAPITAL
    )

    strategy_return = (
        total_profit
        / INITIAL_CAPITAL
    ) * 100

    # --------------------------------------------------------
    # WIN RATE
    # --------------------------------------------------------

    if total_trades > 0:

        win_rate = (
            wins
            / total_trades
        ) * 100

    else:

        win_rate = 0.0

    # --------------------------------------------------------
    # PROFIT FACTOR
    # --------------------------------------------------------

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
            gross_profit
            / gross_loss
        )

    else:

        profit_factor = float("inf")

    # --------------------------------------------------------
    # DRAWDOWN
    # --------------------------------------------------------

    max_drawdown, max_drawdown_percent = (
        calculate_max_drawdown(
            equity_curve
        )
    )

    # --------------------------------------------------------
    # BUY & HOLD
    # --------------------------------------------------------

    first_price = closes[0]
    last_price = closes[-1]

    buy_hold_return = (
        (
            last_price
            - first_price
        )
        / first_price
    ) * 100

    buy_hold_final = (
        INITIAL_CAPITAL
        * (
            last_price
            / first_price
        )
    )

    # --------------------------------------------------------
    # CAGR
    # --------------------------------------------------------

    total_days = (
        dates[-1]
        - dates[0]
    ).total_seconds() / 86400

    years = max(
        total_days / 365.25,
        0.01
    )

    if final_capital > 0:

        cagr = (
            (
                final_capital
                / INITIAL_CAPITAL
            ) ** (
                1 / years
            )
            - 1
        ) * 100

    else:

        cagr = -100.0

    # --------------------------------------------------------
    # SHARPE
    # --------------------------------------------------------

    sharpe = calculate_sharpe(
        equity_curve
    )

    # --------------------------------------------------------
    # RACHAS
    # --------------------------------------------------------

    max_losing_streak = (
        calculate_max_losing_streak(
            trades
        )
    )

    # --------------------------------------------------------
    # MEJOR / PEOR OPERACIÓN
    # --------------------------------------------------------

    if trades:

        best_trade = max(trades)
        worst_trade = min(trades)

    else:

        best_trade = 0.0
        worst_trade = 0.0

    # --------------------------------------------------------
    # DIFERENCIA CONTRA BUY & HOLD
    # --------------------------------------------------------

    vs_buy_hold = (
        strategy_return
        - buy_hold_return
    )

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    return {

        "start_date": dates[0].strftime(
            "%Y-%m-%d"
        ),

        "end_date": dates[-1].strftime(
            "%Y-%m-%d"
        ),

        "start_price": first_price,

        "end_price": last_price,

        "final_capital": final_capital,

        "return": strategy_return,

        "buy_hold": buy_hold_return,

        "buy_hold_final": buy_hold_final,

        "vs_buy_hold": vs_buy_hold,

        "cagr": cagr,

        "trades": total_trades,

        "wins": wins,

        "losses": losses,

        "win_rate": win_rate,

        "profit_factor": profit_factor,

        "drawdown": max_drawdown_percent,

        "drawdown_dollars": max_drawdown,

        "sharpe": sharpe,

        "max_losing_streak": max_losing_streak,

        "best_trade": best_trade,

        "worst_trade": worst_trade,

        "commissions": total_commissions
    }


# ============================================================
# EJECUCIÓN
# ============================================================

print()
print("==============================================")
print("       AI TRADER — MULTI BACKTEST V2")
print("==============================================")
print()

results = []


for symbol in SYMBOLS:

    print(
        f"Analizando {symbol}..."
    )

    for period_name, days in PERIODS.items():

        end = datetime.now(
            timezone.utc
        )

        start = (
            end
            - timedelta(days=days)
        )

        request = StockBarsRequest(
            symbol_or_symbols=[
                symbol
            ],
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

            data = clean_bars(
                symbol_bars
            )

            if len(data) < 50:

                print(
                    f"  {period_name}: "
                    f"DATOS INSUFICIENTES"
                )

                continue

            result = run_backtest(
                data
            )

            if result is None:

                print(
                    f"  {period_name}: "
                    f"BACKTEST NO DISPONIBLE"
                )

                continue

            results.append({

                "symbol": symbol,

                "period": period_name,

                **result

            })

            pf = result["profit_factor"]

            if math.isinf(pf):
                pf_text = "INF"
            else:
                pf_text = f"{pf:.2f}"

            print(
                f"  {period_name}: "
                f"{result['return']:.2f}% | "
                f"B&H "
                f"{result['buy_hold']:.2f}% | "
                f"DD "
                f"{result['drawdown']:.2f}% | "
                f"PF "
                f"{pf_text}"
            )

            print(
                f"      Datos: "
                f"{result['start_date']} → "
                f"{result['end_date']} | "
                f"{result['trades']} trades"
            )

        except Exception as error:

            print(
                f"  {period_name}: ERROR"
            )

            print(
                f"      {error}"
            )

    print()


# ============================================================
# TABLA PRINCIPAL
# ============================================================

print()
print("==============================================")
print("                 RESULTADOS")
print("==============================================")
print()

print(
    "ACTIVO | PERIODO | "
    "ESTRATEGIA | B&H | "
    "TRADES | WIN% | PF | "
    "DD | CAGR | SHARPE"
)

print("-" * 105)


for result in results:

    pf = result["profit_factor"]

    if math.isinf(pf):
        pf_text = "INF"
    else:
        pf_text = f"{pf:.2f}"

    print(
        f"{result['symbol']:6} | "
        f"{result['period']:7} | "
        f"{result['return']:9.2f}% | "
        f"{result['buy_hold']:6.2f}% | "
        f"{result['trades']:6} | "
        f"{result['win_rate']:5.1f}% | "
        f"{pf_text:>4} | "
        f"{result['drawdown']:5.2f}% | "
        f"{result['cagr']:5.2f}% | "
        f"{result['sharpe']:6.2f}"
    )


# ============================================================
# DETALLE
# ============================================================

print()
print("==============================================")
print("              DETALLE DE RIESGO")
print("==============================================")
print()


for result in results:

    print(
        f"{result['symbol']} — "
        f"{result['period']}"
    )

    print(
        f"  Capital final: "
        f"${result['final_capital']:,.2f}"
    )

    print(
        f"  Rendimiento: "
        f"{result['return']:.2f}%"
    )

    print(
        f"  Diferencia vs B&H: "
        f"{result['vs_buy_hold']:+.2f}%"
    )

    print(
        f"  Drawdown máximo: "
        f"{result['drawdown']:.2f}% "
        f"(${result['drawdown_dollars']:,.2f})"
    )

    print(
        f"  Mejor operación: "
        f"${result['best_trade']:,.2f}"
    )

    print(
        f"  Peor operación: "
        f"${result['worst_trade']:,.2f}"
    )

    print(
        f"  Racha máxima de pérdidas: "
        f"{result['max_losing_streak']}"
    )

    print(
        f"  Costos simulados: "
        f"${result['commissions']:,.2f}"
    )

    print()


# ============================================================
# RESUMEN GLOBAL
# ============================================================

print("==============================================")
print("                 SEGURIDAD")
print("==============================================")
print()

print("BACKTEST V2 SOLAMENTE")
print("NO SE ENVIARON ÓRDENES")
print()
print("SIN DINERO REAL")
print("SIN PAPER ORDERS")
print("SIN LIVE ORDERS")
print()
print("==============================================")
# ============================================================
# GUARDAR RESULTADOS EN ARCHIVO
# ============================================================

with open("backtest_results.txt", "w", encoding="utf-8") as file:

    file.write("AI TRADER — MULTI BACKTEST V2\n")
    file.write("=" * 60 + "\n\n")

    file.write(
        "ACTIVO | PERIODO | ESTRATEGIA | B&H | "
        "TRADES | WIN% | PF | DD | CAGR | SHARPE\n"
    )

    file.write("-" * 100 + "\n")

    for result in results:

        pf = result["profit_factor"]

        if math.isinf(pf):
            pf_text = "INF"
        else:
            pf_text = f"{pf:.2f}"

        file.write(
            f"{result['symbol']:6} | "
            f"{result['period']:7} | "
            f"{result['return']:9.2f}% | "
            f"{result['buy_hold']:6.2f}% | "
            f"{result['trades']:6} | "
            f"{result['win_rate']:5.1f}% | "
            f"{pf_text:>4} | "
            f"{result['drawdown']:5.2f}% | "
            f"{result['cagr']:5.2f}% | "
            f"{result['sharpe']:6.2f}\n"
        )

    file.write("\n")
    file.write("=" * 60 + "\n")
    file.write("DETALLE DE CADA PRUEBA\n")
    file.write("=" * 60 + "\n\n")

    for result in results:

        file.write(
            f"{result['symbol']} — {result['period']}\n"
        )

        file.write(
            f"Capital final: ${result['final_capital']:,.2f}\n"
        )

        file.write(
            f"Rendimiento: {result['return']:.2f}%\n"
        )

        file.write(
            f"Buy & Hold: {result['buy_hold']:.2f}%\n"
        )

        file.write(
            f"Vs Buy & Hold: {result['vs_buy_hold']:+.2f}%\n"
        )

        file.write(
            f"Trades: {result['trades']}\n"
        )

        file.write(
            f"Win rate: {result['win_rate']:.2f}%\n"
        )

        file.write(
            f"Profit Factor: {result['profit_factor']:.2f}\n"
            if not math.isinf(result["profit_factor"])
            else "Profit Factor: INF\n"
        )

        file.write(
            f"Drawdown máximo: {result['drawdown']:.2f}% "
            f"(${result['drawdown_dollars']:,.2f})\n"
        )

        file.write(
            f"CAGR: {result['cagr']:.2f}%\n"
        )

        file.write(
            f"Sharpe: {result['sharpe']:.2f}\n"
        )

        file.write(
            f"Racha máxima de pérdidas: "
            f"{result['max_losing_streak']}\n"
        )

        file.write(
            f"Mejor operación: "
            f"${result['best_trade']:,.2f}\n"
        )

        file.write(
            f"Peor operación: "
            f"${result['worst_trade']:,.2f}\n"
        )

        file.write(
            f"Costos simulados: "
            f"${result['commissions']:,.2f}\n"
        )

        file.write(
            f"Periodo: "
            f"{result['start_date']} → {result['end_date']}\n"
        )

        file.write("\n" + "-" * 60 + "\n\n")

    file.write("BACKTEST V2 SOLAMENTE\n")
    file.write("NO SE ENVIARON ÓRDENES\n")
    file.write("SIN DINERO REAL\n")
    file.write("SIN PAPER ORDERS\n")
    file.write("SIN LIVE ORDERS\n")


print()
print("==============================================")
print("RESULTADOS GUARDADOS EN backtest_results.txt")
print("==============================================")
