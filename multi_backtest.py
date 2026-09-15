import os
import math
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# AI TRADER — MULTI BACKTEST V5
# ROLLING OUT-OF-SAMPLE / WALK-FORWARD
# SOLO BACKTEST — NO ENVIA ORDENES
# ============================================================

SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]

PERIODS = {
    "1 AÑO": 365,
    "3 AÑOS": 1095,
    "5 AÑOS": 1825,
}

INITIAL_CAPITAL = 100000.0

RISK_PER_TRADE = 0.01
STOP_PERCENT = 0.03
SLIPPAGE_PERCENT = 0.0005
COMMISSION_PER_SHARE = 0.01

WARMUP_DAYS = 252
TEST_WINDOW_DAYS = 63


# ============================================================
# ALPACA
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
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        average_gain = (
            (
                average_gain * (period - 1)
                + gains[i]
            ) / period
        )

        average_loss = (
            (
                average_loss * (period - 1)
                + losses[i]
            ) / period
        )

    if average_loss == 0:
        return 100.0

    rs = average_gain / average_loss

    return 100.0 - (
        100.0 / (1.0 + rs)
    )


# ============================================================
# DATOS
# ============================================================

def clean_bars(symbol_bars):
    data = []

    for bar in symbol_bars:
        timestamp = bar.timestamp

        open_price = float(bar.open)
        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)

        if (
            open_price <= 0
            or high <= 0
            or low <= 0
            or close <= 0
        ):
            continue

        if high < low:
            continue

        if high < open_price:
            continue

        if high < close:
            continue

        if low > open_price:
            continue

        if low > close:
            continue

        data.append(
            (
                timestamp,
                open_price,
                high,
                low,
                close
            )
        )

    data.sort(
        key=lambda x: x[0]
    )

    return data


# ============================================================
# METRICAS
# ============================================================

def max_drawdown(equity):
    if not equity:
        return 0.0, 0.0

    peak = equity[0]
    max_dd = 0.0
    max_dd_pct = 0.0

    for value in equity:
        if value > peak:
            peak = value

        if peak <= 0:
            continue

        dd = peak - value
        dd_pct = (dd / peak) * 100.0

        max_dd = max(max_dd, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)

    return max_dd, max_dd_pct


def sharpe(equity):
    if len(equity) < 2:
        return 0.0

    returns = []

    for i in range(1, len(equity)):
        previous = equity[i - 1]
        current = equity[i]

        if previous <= 0:
            continue

        returns.append(
            (current - previous) / previous
        )

    if len(returns) < 2:
        return 0.0

    average = sum(returns) / len(returns)

    variance = sum(
        (x - average) ** 2
        for x in returns
    ) / (len(returns) - 1)

    deviation = math.sqrt(variance)

    if deviation == 0:
        return 0.0

    return (
        average / deviation
    ) * math.sqrt(252)


def profit_factor(trades):
    profit = sum(
        x for x in trades if x > 0
    )

    loss = abs(
        sum(x for x in trades if x < 0)
    )

    if loss == 0:
        if profit > 0:
            return float("inf")
        return 0.0

    return profit / loss


def losing_streak(trades):
    current = 0
    maximum = 0

    for trade in trades:
        if trade < 0:
            current += 1
            maximum = max(
                maximum,
                current
            )
        else:
            current = 0

    return maximum


def format_pf(value):
    if math.isinf(value):
        return "INF"

    return f"{value:.2f}"


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(data):

    if len(data) < WARMUP_DAYS + 50:
        return None

    dates = [
        x[0] for x in data
    ]

    opens = [
        x[1] for x in data
    ]

    highs = [
        x[2] for x in data
    ]

    lows = [
        x[3] for x in data
    ]

    closes = [
        x[4] for x in data
    ]

    capital = INITIAL_CAPITAL

    position = 0
    entry_price = 0.0
    stop_price = 0.0

    pending_entry = False

    trades = []
    oos_trades = []

    equity_curve = []
    oos_equity_curve = []

    total_commissions = 0.0
    oos_commissions = 0.0

    wins = 0
    losses = 0

    oos_wins = 0
    oos_losses = 0

    oos_start = min(
        WARMUP_DAYS,
        len(data) - 1
    )

    # ========================================================
    # HISTORIAL
    # ========================================================

    for i in range(
        20,
        len(closes)
    ):

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

        if (
            ema20 is None
            or rsi14 is None
        ):
            equity_curve.append(
                capital
            )

            if i >= oos_start:
                oos_equity_curve.append(
                    capital
                )

            continue

        # ====================================================
        # ENTRADA AL OPEN
        # ====================================================

        if (
            position == 0
            and pending_entry
        ):

            entry_price_execution = (
                opens[i]
                * (1 + SLIPPAGE_PERCENT)
            )

            stop_distance = (
                entry_price_execution
                * STOP_PERCENT
            )

            risk_amount = (
                capital
                * RISK_PER_TRADE
            )

            shares_risk = int(
                risk_amount
                / stop_distance
            )

            shares_capital = int(
                capital
                / (
                    entry_price_execution
                    + COMMISSION_PER_SHARE
                )
            )

            shares = min(
                shares_risk,
                shares_capital
            )

            if shares > 0:

                entry_commission = (
                    shares
                    * COMMISSION_PER_SHARE
                )

                total_cost = (
                    entry_price_execution
                    * shares
                    + entry_commission
                )

                if total_cost <= capital:

                    capital -= total_cost

                    position = shares

                    entry_price = (
                        entry_price_execution
                    )

                    stop_price = (
                        entry_price
                        * (1 - STOP_PERCENT)
                    )

                    total_commissions += (
                        entry_commission
                    )

                    if i >= oos_start:
                        oos_commissions += (
                            entry_commission
                        )

            pending_entry = False

        # ====================================================
        # GESTION DE POSICION
        # ====================================================

        if position > 0:

            exit_reason = None
            execution_price = None

            # STOP POR GAP
            if opens[i] <= stop_price:

                exit_reason = "STOP_GAP"

                execution_price = (
                    opens[i]
                    * (1 - SLIPPAGE_PERCENT)
                )

            # STOP NORMAL
            elif lows[i] <= stop_price:

                exit_reason = "STOP"

                execution_price = (
                    stop_price
                    * (1 - SLIPPAGE_PERCENT)
                )

            # SALIDA EMA
            elif price < ema20:

                exit_reason = "EMA"

                execution_price = (
                    price
                    * (1 - SLIPPAGE_PERCENT)
                )

            if exit_reason is not None:

                gross_result = (
                    execution_price
                    - entry_price
                ) * position

                exit_commission = (
                    position
                    * COMMISSION_PER_SHARE
                )

                pnl = (
                    gross_result
                    - exit_commission
                )

                capital += (
                    execution_price
                    * position
                )

                capital -= (
                    exit_commission
                )

                trades.append(
                    pnl
                )

                total_commissions += (
                    exit_commission
                )

                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1

                if i >= oos_start:

                    oos_trades.append(
                        pnl
                    )

                    oos_commissions += (
                        exit_commission
                    )

                    if pnl >= 0:
                        oos_wins += 1
                    else:
                        oos_losses += 1

                position = 0
                entry_price = 0.0
                stop_price = 0.0

        # ====================================================
        # NUEVA SEÑAL AL CIERRE
        # ====================================================

        if (
            position == 0
            and not pending_entry
        ):

            signal = (
                price > ema20
                and rsi14 < 70
            )

            if signal:
                pending_entry = True

        # ====================================================
        # EQUITY
        # ====================================================

        if position > 0:

            market_value = (
                closes[i]
                * position
            )

            equity = (
                capital
                + market_value
            )

        else:

            equity = capital

        equity_curve.append(
            equity
        )

        if i >= oos_start:

            oos_equity_curve.append(
                equity
            )

    # ========================================================
    # CIERRE FINAL
    # ========================================================

    if position > 0:

        final_price = (
            closes[-1]
            * (1 - SLIPPAGE_PERCENT)
        )

        gross_result = (
            final_price
            - entry_price
        ) * position

        exit_commission = (
            position
            * COMMISSION_PER_SHARE
        )

        pnl = (
            gross_result
            - exit_commission
        )

        capital += (
            final_price
            * position
        )

        capital -= (
            exit_commission
        )

        trades.append(
            pnl
        )

        total_commissions += (
            exit_commission
        )

        if pnl >= 0:
            wins += 1
        else:
            losses += 1

        if (
            len(data) - 1
            >= oos_start
        ):

            oos_trades.append(
                pnl
            )

            oos_commissions += (
                exit_commission
            )

            if pnl >= 0:
                oos_wins += 1
            else:
                oos_losses += 1

        position = 0

        equity_curve.append(
            capital
        )

        oos_equity_curve.append(
            capital
        )

    # ========================================================
    # METRICAS TOTALES
    # ========================================================

    final_capital = capital

    total_return = (
        (
            final_capital
            / INITIAL_CAPITAL
        ) - 1
    ) * 100

    total_trades = len(trades)

    win_rate = (
        wins / total_trades * 100
        if total_trades
        else 0.0
    )

    pf = profit_factor(
        trades
    )

    dd_dollars, dd_percent = (
        max_drawdown(
            equity_curve
        )
    )

    total_sharpe = sharpe(
        equity_curve
    )

    streak = losing_streak(
        trades
    )

    # ========================================================
    # BUY & HOLD
    # ========================================================

    buy_hold = (
        (
            closes[-1]
            / closes[0]
        ) - 1
    ) * 100

    # ========================================================
    # CAGR
    # ========================================================

    total_days = (
        dates[-1]
        - dates[0]
    ).total_seconds() / 86400

    years = max(
        total_days / 365.25,
        0.01
    )

    cagr = (
        (
            final_capital
            / INITIAL_CAPITAL
        )
        ** (1 / years)
        - 1
    ) * 100

    # ========================================================
    # OOS
    # ========================================================

    if oos_equity_curve:

        oos_initial = (
            oos_equity_curve[0]
        )

        oos_final = (
            oos_equity_curve[-1]
        )

    else:

        oos_initial = INITIAL_CAPITAL
        oos_final = INITIAL_CAPITAL

    if oos_initial > 0:

        oos_return = (
            (
                oos_final
                / oos_initial
            ) - 1
        ) * 100

    else:

        oos_return = 0.0

    oos_count = len(
        oos_trades
    )

    oos_win_rate = (
        oos_wins
        / oos_count
        * 100
        if oos_count
        else 0.0
    )

    oos_pf = profit_factor(
        oos_trades
    )

    oos_dd_dollars, oos_dd_percent = (
        max_drawdown(
            oos_equity_curve
        )
    )

    oos_sharpe = sharpe(
        oos_equity_curve
    )

    oos_streak = losing_streak(
        oos_trades
    )

    return {
        "start_date":
            dates[0].strftime("%Y-%m-%d"),

        "end_date":
            dates[-1].strftime("%Y-%m-%d"),

        "final_capital":
            final_capital,

        "return":
            total_return,

        "buy_hold":
            buy_hold,

        "vs_buy_hold":
            total_return - buy_hold,

        "cagr":
            cagr,

        "trades":
            total_trades,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            win_rate,

        "profit_factor":
            pf,

        "drawdown":
            dd_percent,

        "drawdown_dollars":
            dd_dollars,

        "sharpe":
            total_sharpe,

        "losing_streak":
            streak,

        "commissions":
            total_commissions,

        "oos_start_date":
            dates[oos_start].strftime(
                "%Y-%m-%d"
            ),

        "oos_end_date":
            dates[-1].strftime(
                "%Y-%m-%d"
            ),

        "oos_initial":
            oos_initial,

        "oos_final":
            oos_final,

        "oos_return":
            oos_return,

        "oos_trades":
            oos_count,

        "oos_wins":
            oos_wins,

        "oos_losses":
            oos_losses,

        "oos_win_rate":
            oos_win_rate,

        "oos_profit_factor":
            oos_pf,

        "oos_drawdown":
            oos_dd_percent,

        "oos_drawdown_dollars":
            oos_dd_dollars,

        "oos_sharpe":
            oos_sharpe,

        "oos_losing_streak":
            oos_streak,

        "oos_commissions":
            oos_commissions
    }


# ============================================================
# EJECUCION
# ============================================================

print()
print("==============================================")
print("       AI TRADER — MULTI BACKTEST V5")
print("==============================================")
print()
print("ROLLING OUT-OF-SAMPLE / WALK-FORWARD")
print(f"WARMUP: {WARMUP_DAYS} días")
print(f"VENTANA OOS: {TEST_WINDOW_DAYS} días")
print()
print("DATOS AJUSTADOS: SPLITS + DIVIDENDOS")
print("ENTRADA: OPEN DEL DÍA SIGUIENTE")
print("STOP: LOW REAL + PROTECCION GAP")
print("SLIPPAGE + COMISIONES ACTIVOS")
print()
print("IMPORTANTE: SOLO BACKTEST")
print("NO SE ENVIAN ORDENES")
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
            - timedelta(
                days=days
            )
        )

        request = StockBarsRequest(
            symbol_or_symbols=[
                symbol
            ],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=DataFeed.IEX,
            adjustment="all"
        )

        try:

            bars = (
                data_client
                .get_stock_bars(
                    request
                )
            )

            data = clean_bars(
                bars[symbol]
            )

            if len(data) < (
                WARMUP_DAYS + 50
            ):

                print(
                    f"  {period_name}: "
                    "DATOS INSUFICIENTES"
                )

                continue

            result = run_backtest(
                data
            )

            if result is None:

                print(
                    f"  {period_name}: "
                    "NO DISPONIBLE"
                )

                continue

            result["symbol"] = symbol
            result["period"] = period_name

            results.append(
                result
            )

            print(
                f"  {period_name}: "
                f"TOTAL {result['return']:.2f}% | "
                f"B&H {result['buy_hold']:.2f}% | "
                f"OOS {result['oos_return']:.2f}% | "
                f"OOS trades "
                f"{result['oos_trades']} | "
                f"OOS PF "
                f"{format_pf(result['oos_profit_factor'])} | "
                f"OOS DD "
                f"{result['oos_drawdown']:.2f}%"
            )

            print(
                f"      OOS: "
                f"{result['oos_start_date']} -> "
                f"{result['oos_end_date']}"
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
# RESUMEN
# ============================================================

print()
print("==============================================")
print("             RESULTADOS V5")
print("==============================================")
print()

print(
    "ACTIVO | PERIODO | TOTAL | B&H | OOS | "
    "OOS TRADES | WIN% | PF | DD | SHARPE"
)

print("-" * 110)

for result in results:

    print(
        f"{result['symbol']:6} | "
        f"{result['period']:7} | "
        f"{result['return']:6.2f}% | "
        f"{result['buy_hold']:6.2f}% | "
        f"{result['oos_return']:6.2f}% | "
        f"{result['oos_trades']:10} | "
        f"{result['oos_win_rate']:5.1f}% | "
        f"{format_pf(result['oos_profit_factor']):>4} | "
        f"{result['oos_drawdown']:5.2f}% | "
        f"{result['oos_sharpe']:6.2f}"
    )


# ============================================================
# DETALLE OOS
# ============================================================

print()
print("==============================================")
print("              DETALLE OOS")
print("==============================================")
print()

for result in results:

    print(
        f"{result['symbol']} — "
        f"{result['period']}"
    )

    print(
        f"  Periodo OOS: "
        f"{result['oos_start_date']} -> "
        f"{result['oos_end_date']}"
    )

    print(
        f"  Capital inicial: "
        f"${result['oos_initial']:,.2f}"
    )

    print(
        f"  Capital final: "
        f"${result['oos_final']:,.2f}"
    )

    print(
        f"  Rendimiento OOS: "
        f"{result['oos_return']:.2f}%"
    )

    print(
        f"  Trades OOS: "
        f"{result['oos_trades']}"
    )

    print(
        f"  Win Rate OOS: "
        f"{result['oos_win_rate']:.1f}%"
    )

    print(
        f"  Profit Factor OOS: "
        f"{format_pf(result['oos_profit_factor'])}"
    )

    print(
        f"  Drawdown OOS: "
        f"{result['oos_drawdown']:.2f}% "
        f"(${result['oos_drawdown_dollars']:,.2f})"
    )

    print(
        f"  Sharpe OOS: "
        f"{result['oos_sharpe']:.2f}"
    )

    print(
        f"  Racha perdedora OOS: "
        f"{result['oos_losing_streak']}"
    )

    print(
        f"  Comisiones OOS: "
        f"${result['oos_commissions']:,.2f}"
    )

    print()


# ============================================================
# EXPORTAR
# ============================================================

output = []

output.append(
    "AI TRADER — MULTI BACKTEST V5"
)

output.append(
    "=============================================="
)

output.append(
    "ROLLING OUT-OF-SAMPLE / WALK-FORWARD"
)

output.append(
    f"WARMUP: {WARMUP_DAYS} días"
)

output.append(
    f"VENTANA OOS: {TEST_WINDOW_DAYS} días"
)

output.append(
    "SOLO BACKTEST — NO SE ENVIAN ORDENES"
)

output.append("")

output.append(
    "ACTIVO | PERIODO | TOTAL | B&H | OOS | "
    "OOS TRADES | WIN% | PF | DD | SHARPE"
)

output.append(
    "-" * 110
)

for result in results:

    output.append(
        f"{result['symbol']:6} | "
        f"{result['period']:7} | "
        f"{result['return']:6.2f}% | "
        f"{result['buy_hold']:6.2f}% | "
        f"{result['oos_return']:6.2f}% | "
        f"{result['oos_trades']:10} | "
        f"{result['oos_win_rate']:5.1f}% | "
        f"{format_pf(result['oos_profit_factor']):>4} | "
        f"{result['oos_drawdown']:5.2f}% | "
        f"{result['oos_sharpe']:6.2f}"
    )

output.append("")
output.append("DETALLE OOS")
output.append("==============================================")
output.append("")

for result in results:

    output.append(
        f"{result['symbol']} — "
        f"{result['period']}"
    )

    output.append(
        f"OOS: "
        f"{result['oos_start_date']} -> "
        f"{result['oos_end_date']}"
    )

    output.append(
        f"Capital inicial: "
        f"${result['oos_initial']:,.2f}"
    )

    output.append(
        f"Capital final: "
        f"${result['oos_final']:,.2f}"
    )

    output.append(
        f"Rendimiento OOS: "
        f"{result['oos_return']:.2f}%"
    )

    output.append(
        f"Trades OOS: "
        f"{result['oos_trades']}"
    )

    output.append(
        f"Win Rate OOS: "
        f"{result['oos_win_rate']:.1f}%"
    )

    output.append(
        f"Profit Factor OOS: "
        f"{format_pf(result['oos_profit_factor'])}"
    )

    output.append(
        f"Drawdown OOS: "
        f"{result['oos_drawdown']:.2f}% "
        f"(${result['oos_drawdown_dollars']:,.2f})"
    )

    output.append(
        f"Sharpe OOS: "
        f"{result['oos_sharpe']:.2f}"
    )

    output.append(
        f"Racha perdedora OOS: "
        f"{result['oos_losing_streak']}"
    )

    output.append(
        f"Comisiones OOS: "
        f"${result['oos_commissions']:,.2f}"
    )

    output.append("")


try:

    with open(
        "backtest_results_v5.txt",
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "\n".join(output)
        )

    print(
        "=============================================="
    )

    print(
        "RESULTADOS V5 EXPORTADOS"
    )

    print(
        "Archivo: backtest_results_v5.txt"
    )

    print(
        "=============================================="
    )

except Exception as error:

    print(
        "ERROR AL EXPORTAR RESULTADOS"
    )

    print(
        error
    )


print()
print("==============================================")
print("       BACKTEST V5 FINALIZADO")
print("       NO SE ENVIARON ORDENES")
print("==============================================")
