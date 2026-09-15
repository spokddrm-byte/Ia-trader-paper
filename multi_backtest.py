import os
import math
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# AI TRADER — MULTI BACKTEST V6
# WALK-FORWARD REAL / ROLLING OUT-OF-SAMPLE
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

# Días iniciales necesarios para que los indicadores
# tengan suficiente historial.
WARMUP_DAYS = 252

# Cada bloque OOS tendrá aproximadamente 63 días.
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

    average = sum(
        values[:period]
    ) / period

    for price in values[period:]:
        average = (
            (price - average)
            * multiplier
        ) + average

    return average


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:
            gains.append(change)
            losses.append(0.0)

        else:
            gains.append(0.0)
            losses.append(abs(change))

    average_gain = (
        sum(gains[:period])
        / period
    )

    average_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        average_gain = (
            (
                average_gain
                * (period - 1)
                + gains[i]
            )
            / period
        )

        average_loss = (
            (
                average_loss
                * (period - 1)
                + losses[i]
            )
            / period
        )

    if average_loss == 0:
        return 100.0

    relative_strength = (
        average_gain
        / average_loss
    )

    return 100.0 - (
        100.0
        / (1.0 + relative_strength)
    )


# ============================================================
# LIMPIEZA DE DATOS
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
        key=lambda item: item[0]
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
    max_dd_percent = 0.0

    for value in equity:

        if value > peak:
            peak = value

        if peak <= 0:
            continue

        drawdown = (
            peak - value
        )

        drawdown_percent = (
            drawdown
            / peak
            * 100.0
        )

        max_dd = max(
            max_dd,
            drawdown
        )

        max_dd_percent = max(
            max_dd_percent,
            drawdown_percent
        )

    return (
        max_dd,
        max_dd_percent
    )


def sharpe(equity):

    if len(equity) < 2:
        return 0.0

    returns = []

    for i in range(
        1,
        len(equity)
    ):

        previous = equity[i - 1]
        current = equity[i]

        if previous <= 0:
            continue

        daily_return = (
            current - previous
        ) / previous

        returns.append(
            daily_return
        )

    if len(returns) < 2:
        return 0.0

    average = (
        sum(returns)
        / len(returns)
    )

    variance = (
        sum(
            (value - average) ** 2
            for value in returns
        )
        / (len(returns) - 1)
    )

    deviation = math.sqrt(
        variance
    )

    if deviation == 0:
        return 0.0

    return (
        average
        / deviation
        * math.sqrt(252)
    )


def profit_factor(trades):

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

    if gross_loss == 0:

        if gross_profit > 0:
            return float("inf")

        return 0.0

    return (
        gross_profit
        / gross_loss
    )


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
# SIMULADOR DE UNA VENTANA
# ============================================================

def process_window(
    data,
    start_index,
    end_index,
    capital,
    position,
    entry_price,
    stop_price,
    pending_entry
):

    trades = []
    equity_curve = []

    commissions = 0.0

    wins = 0
    losses = 0

    closes = [
        row[4]
        for row in data
    ]

    for i in range(
        start_index,
        end_index
    ):

        timestamp = data[i][0]
        open_price = data[i][1]
        high = data[i][2]
        low = data[i][3]
        close = data[i][4]

        del timestamp
        del high

        # ====================================================
        # INDICADORES
        # ====================================================

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

            if position > 0:

                equity = (
                    capital
                    + close * position
                )

            else:

                equity = capital

            equity_curve.append(
                equity
            )

            continue

        # ====================================================
        # ENTRADA PENDIENTE
        # ====================================================

        if (
            position == 0
            and pending_entry
        ):

            execution_price = (
                open_price
                * (
                    1
                    + SLIPPAGE_PERCENT
                )
            )

            stop_distance = (
                execution_price
                * STOP_PERCENT
            )

            risk_amount = (
                capital
                * RISK_PER_TRADE
            )

            if stop_distance > 0:

                shares_risk = int(
                    risk_amount
                    / stop_distance
                )

            else:

                shares_risk = 0

            share_cost = (
                execution_price
                + COMMISSION_PER_SHARE
            )

            if share_cost > 0:

                shares_capital = int(
                    capital
                    / share_cost
                )

            else:

                shares_capital = 0

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
                    execution_price
                    * shares
                    + entry_commission
                )

                if total_cost <= capital:

                    capital -= total_cost

                    position = shares

                    entry_price = (
                        execution_price
                    )

                    stop_price = (
                        entry_price
                        * (
                            1
                            - STOP_PERCENT
                        )
                    )

                    commissions += (
                        entry_commission
                    )

            pending_entry = False

        # ====================================================
        # GESTION DE POSICION
        # ====================================================

        if position > 0:

            exit_reason = None
            exit_price = None

            # -----------------------------------------------
            # STOP POR GAP
            # -----------------------------------------------

            if open_price <= stop_price:

                exit_reason = "STOP_GAP"

                exit_price = (
                    open_price
                    * (
                        1
                        - SLIPPAGE_PERCENT
                    )
                )

            # -----------------------------------------------
            # STOP NORMAL
            # -----------------------------------------------

            elif low <= stop_price:

                exit_reason = "STOP"

                exit_price = (
                    stop_price
                    * (
                        1
                        - SLIPPAGE_PERCENT
                    )
                )

            # -----------------------------------------------
            # SALIDA POR EMA
            # -----------------------------------------------

            elif close < ema20:

                exit_reason = "EMA"

                exit_price = (
                    close
                    * (
                        1
                        - SLIPPAGE_PERCENT
                    )
                )

            # -----------------------------------------------
            # EJECUTAR SALIDA
            # -----------------------------------------------

            if exit_reason is not None:

                gross_result = (
                    exit_price
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
                    exit_price
                    * position
                )

                capital -= (
                    exit_commission
                )

                trades.append(
                    pnl
                )

                commissions += (
                    exit_commission
                )

                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1

                position = 0

                entry_price = 0.0

                stop_price = 0.0

        # ====================================================
        # NUEVA SEÑAL
        # ====================================================

        if (
            position == 0
            and not pending_entry
        ):

            signal = (
                close > ema20
                and rsi14 < 70
            )

            if signal:

                pending_entry = True

        # ====================================================
        # EQUITY
        # ====================================================

        if position > 0:

            market_value = (
                close
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

    return {
        "capital": capital,
        "position": position,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "pending_entry": pending_entry,
        "trades": trades,
        "equity": equity_curve,
        "commissions": commissions,
        "wins": wins,
        "losses": losses
    }


# ============================================================
# WALK-FORWARD REAL
# ============================================================

def run_walk_forward(data):

    minimum_required = (
        WARMUP_DAYS
        + TEST_WINDOW_DAYS
        + 20
    )

    if len(data) < minimum_required:
        return None

    dates = [
        row[0]
        for row in data
    ]

    closes = [
        row[4]
        for row in data
    ]

    # ========================================================
    # ESTADO GLOBAL
    # ========================================================

    capital = INITIAL_CAPITAL

    position = 0
    entry_price = 0.0
    stop_price = 0.0
    pending_entry = False

    all_trades = []
    all_equity = []

    total_commissions = 0.0

    total_wins = 0
    total_losses = 0

    windows = []

    # ========================================================
    # PRIMER BLOQUE OOS
    # ========================================================

    window_start = WARMUP_DAYS

    window_number = 1

    while window_start < len(data):

        window_end = min(
            window_start
            + TEST_WINDOW_DAYS,
            len(data)
        )

        # -----------------------------------------------
        # IMPORTANTE:
        # Antes de cada bloque OOS, los indicadores
        # utilizan únicamente información disponible
        # hasta ese momento.
        # -----------------------------------------------

        starting_capital = capital

        result = process_window(
            data,
            window_start,
            window_end,
            capital,
            position,
            entry_price,
            stop_price,
            pending_entry
        )

        capital = result["capital"]

        position = result["position"]

        entry_price = result["entry_price"]

        stop_price = result["stop_price"]

        pending_entry = result["pending_entry"]

        window_trades = result["trades"]

        window_equity = result["equity"]

        window_commissions = (
            result["commissions"]
        )

        window_wins = result["wins"]

        window_losses = result["losses"]

        all_trades.extend(
            window_trades
        )

        all_equity.extend(
            window_equity
        )

        total_commissions += (
            window_commissions
        )

        total_wins += (
            window_wins
        )

        total_losses += (
            window_losses
        )

        # -----------------------------------------------
        # METRICAS DE LA VENTANA
        # -----------------------------------------------

        if starting_capital > 0:

            window_return = (
                (
                    capital
                    / starting_capital
                ) - 1
            ) * 100

        else:

            window_return = 0.0

        window_pf = profit_factor(
            window_trades
        )

        _, window_dd = (
            max_drawdown(
                window_equity
            )
        )

        window_sharpe = sharpe(
            window_equity
        )

        window_win_rate = (
            window_wins
            / len(window_trades)
            * 100
            if window_trades
            else 0.0
        )

        windows.append(
            {
                "number":
                    window_number,

                "start":
                    dates[window_start]
                    .strftime(
                        "%Y-%m-%d"
                    ),

                "end":
                    dates[window_end - 1]
                    .strftime(
                        "%Y-%m-%d"
                    ),

                "starting_capital":
                    starting_capital,

                "ending_capital":
                    capital,

                "return":
                    window_return,

                "trades":
                    len(window_trades),

                "wins":
                    window_wins,

                "losses":
                    window_losses,

                "win_rate":
                    window_win_rate,

                "profit_factor":
                    window_pf,

                "drawdown":
                    window_dd,

                "sharpe":
                    window_sharpe,

                "commissions":
                    window_commissions
            }
        )

        window_number += 1

        window_start = window_end

    # ========================================================
    # CIERRE FINAL DE POSICION
    # ========================================================

    if position > 0:

        final_close = closes[-1]

        final_price = (
            final_close
            * (
                1
                - SLIPPAGE_PERCENT
            )
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

        all_trades.append(
            pnl
        )

        total_commissions += (
            exit_commission
        )

        if pnl >= 0:
            total_wins += 1
        else:
            total_losses += 1

        position = 0

    # ========================================================
    # METRICAS GLOBALES
    # ========================================================

    final_capital = capital

    total_return = (
        (
            final_capital
            / INITIAL_CAPITAL
        ) - 1
    ) * 100

    total_trades = len(
        all_trades
    )

    total_win_rate = (
        total_wins
        / total_trades
        * 100
        if total_trades
        else 0.0
    )

    total_pf = profit_factor(
        all_trades
    )

    total_dd_dollars, total_dd = (
        max_drawdown(
            all_equity
        )
    )

    total_sharpe = sharpe(
        all_equity
    )

    total_losing_streak = (
        losing_streak(
            all_trades
        )
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
    # CONSISTENCIA DE VENTANAS
    # ========================================================

    positive_windows = sum(
        1
        for window in windows
        if window["return"] > 0
    )

    negative_windows = sum(
        1
        for window in windows
        if window["return"] < 0
    )

    flat_windows = (
        len(windows)
        - positive_windows
        - negative_windows
    )

    if windows:

        average_window_return = (
            sum(
                window["return"]
                for window in windows
            )
            / len(windows)
        )

    else:

        average_window_return = 0.0

    return {
        "start_date":
            dates[0].strftime(
                "%Y-%m-%d"
            ),

        "end_date":
            dates[-1].strftime(
                "%Y-%m-%d"
            ),

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
            total_wins,

        "losses":
            total_losses,

        "win_rate":
            total_win_rate,

        "profit_factor":
            total_pf,

        "drawdown":
            total_dd,

        "drawdown_dollars":
            total_dd_dollars,

        "sharpe":
            total_sharpe,

        "losing_streak":
            total_losing_streak,

        "commissions":
            total_commissions,

        "windows":
            windows,

        "total_windows":
            len(windows),

        "positive_windows":
            positive_windows,

        "negative_windows":
            negative_windows,

        "flat_windows":
            flat_windows,

        "average_window_return":
            average_window_return
    }


# ============================================================
# EJECUCION
# ============================================================

print()
print("==============================================")
print("       AI TRADER — MULTI BACKTEST V6")
print("==============================================")
print()
print("WALK-FORWARD REAL / ROLLING OOS")
print(f"WARMUP: {WARMUP_DAYS} días")
print(
    f"VENTANA OOS: {TEST_WINDOW_DAYS} días"
)
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
                WARMUP_DAYS
                + TEST_WINDOW_DAYS
                + 20
            ):

                print(
                    f"  {period_name}: "
                    "DATOS INSUFICIENTES"
                )

                continue

            result = run_walk_forward(
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
                f"TOTAL "
                f"{result['return']:.2f}% | "
                f"B&H "
                f"{result['buy_hold']:.2f}% | "
                f"VENTANAS "
                f"{result['total_windows']} | "
                f"POSITIVAS "
                f"{result['positive_windows']} | "
                f"NEGATIVAS "
                f"{result['negative_windows']}"
            )

            print(
                f"      OOS acumulado: "
                f"{result['return']:.2f}% | "
                f"PF "
                f"{format_pf(result['profit_factor'])} | "
                f"DD "
                f"{result['drawdown']:.2f}% | "
                f"Sharpe "
                f"{result['sharpe']:.2f}"
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
# RESULTADOS GLOBALES
# ============================================================

print()
print("==============================================")
print("             RESULTADOS V6")
print("==============================================")
print()

print(
    "ACTIVO | PERIODO | TOTAL | B&H | "
    "VENTANAS | + | - | WIN% | PF | DD | SHARPE"
)

print("-" * 115)


for result in results:

    print(
        f"{result['symbol']:6} | "
        f"{result['period']:7} | "
        f"{result['return']:6.2f}% | "
        f"{result['buy_hold']:6.2f}% | "
        f"{result['total_windows']:8} | "
        f"{result['positive_windows']:1} | "
        f"{result['negative_windows']:1} | "
        f"{result['win_rate']:5.1f}% | "
        f"{format_pf(result['profit_factor']):>4} | "
        f"{result['drawdown']:5.2f}% | "
        f"{result['sharpe']:6.2f}"
    )


# ============================================================
# DETALLE DE CADA VENTANA
# ============================================================

print()
print("==============================================")
print("          VENTANAS WALK-FORWARD")
print("==============================================")
print()


for result in results:

    print(
        f"{result['symbol']} — "
        f"{result['period']}"
    )

    print()

    for window in result["windows"]:

        print(
            f"  W{window['number']:02d} | "
            f"{window['start']} -> "
            f"{window['end']} | "
            f"{window['return']:7.2f}% | "
            f"Trades "
            f"{window['trades']:3} | "
            f"Win "
            f"{window['win_rate']:5.1f}% | "
            f"PF "
            f"{format_pf(window['profit_factor']):>4} | "
            f"DD "
            f"{window['drawdown']:5.2f}% | "
            f"Sharpe "
            f"{window['sharpe']:5.2f}"
        )

    print()

    print(
        f"  Ventanas positivas: "
        f"{result['positive_windows']}"
    )

    print(
        f"  Ventanas negativas: "
        f"{result['negative_windows']}"
    )

    print(
        f"  Rendimiento promedio "
        f"por ventana: "
        f"{result['average_window_return']:.2f}%"
    )

    print()


# ============================================================
# EXPORTAR RESULTADOS
# ============================================================

output = []

output.append(
    "AI TRADER — MULTI BACKTEST V6"
)

output.append(
    "=============================================="
)

output.append(
    "WALK-FORWARD REAL / ROLLING OOS"
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
    "RESULTADOS V6"
)

output.append(
    "ACTIVO | PERIODO | TOTAL | B&H | "
    "VENTANAS | + | - | WIN% | PF | DD | SHARPE"
)

output.append(
    "-" * 115
)


for result in results:

    output.append(
        f"{result['symbol']:6} | "
        f"{result['period']:7} | "
        f"{result['return']:6.2f}% | "
        f"{result['buy_hold']:6.2f}% | "
        f"{result['total_windows']:8} | "
        f"{result['positive_windows']:1} | "
        f"{result['negative_windows']:1} | "
        f"{result['win_rate']:5.1f}% | "
        f"{format_pf(result['profit_factor']):>4} | "
        f"{result['drawdown']:5.2f}% | "
        f"{result['sharpe']:6.2f}"
    )


output.append("")
output.append(
    "VENTANAS WALK-FORWARD"
)
output.append(
    "=============================================="
)
output.append("")


for result in results:

    output.append(
        f"{result['symbol']} — "
        f"{result['period']}"
    )

    output.append("")

    for window in result["windows"]:

        output.append(
            f"W{window['number']:02d} | "
            f"{window['start']} -> "
            f"{window['end']} | "
            f"Return "
            f"{window['return']:.2f}% | "
            f"Trades "
            f"{window['trades']} | "
            f"Win "
            f"{window['win_rate']:.1f}% | "
            f"PF "
            f"{format_pf(window['profit_factor'])} | "
            f"DD "
            f"{window['drawdown']:.2f}% | "
            f"Sharpe "
            f"{window['sharpe']:.2f}"
        )

    output.append("")

    output.append(
        f"Ventanas positivas: "
        f"{result['positive_windows']}"
    )

    output.append(
        f"Ventanas negativas: "
        f"{result['negative_windows']}"
    )

    output.append(
        f"Rendimiento promedio "
        f"por ventana: "
        f"{result['average_window_return']:.2f}%"
    )

    output.append("")


try:

    with open(
        "backtest_results_v6.txt",
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
        "RESULTADOS V6 EXPORTADOS"
    )

    print(
        "Archivo: backtest_results_v6.txt"
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
print("       BACKTEST V6 FINALIZADO")
print("       NO SE ENVIARON ORDENES")
print("==============================================")
