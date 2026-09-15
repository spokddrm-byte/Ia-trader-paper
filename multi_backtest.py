import os
import csv
import math
import statistics
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# AI TRADER — MULTI BACKTEST V7.2
# AUDITORÍA PROFUNDA DE OPERACIONES
# ============================================================

INITIAL_CAPITAL = 100_000.0

RISK_PER_TRADE = 0.01
STOP_DISTANCE = 0.03

SLIPPAGE_RATE = 0.0005
COMMISSION_PER_SHARE = 0.005

WARMUP_DAYS = 252
OOS_WINDOW = 63

SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
]

RESULTS_FILE = "backtest_results_v7_2.txt"
AUDIT_FILE = "trade_audit_v7_2.csv"


# ============================================================
# ALPACA
# ============================================================

API_KEY = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "FALTAN ALPACA_API_KEY O ALPACA_SECRET_KEY EN LAS VARIABLES DE RAILWAY"
    )

client = StockHistoricalDataClient(
    API_KEY,
    API_SECRET
)


# ============================================================
# INDICADORES
# ============================================================

def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


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

    rs = average_gain / average_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# DATOS
# ============================================================

def download_data(symbol):

    end = datetime.now(timezone.utc) - timedelta(days=1)

    start = end - timedelta(days=365 * 6)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment="all",
        feed=DataFeed.IEX,
    )

    bars = client.get_stock_bars(request)

    if symbol not in bars.data:
        raise RuntimeError(
            f"No se recibieron datos para {symbol}"
        )

    rows = []

    for bar in bars.data[symbol]:

        rows.append({
            "date": bar.timestamp.date().isoformat(),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        })

    return rows


# ============================================================
# SEÑAL
# ============================================================

def calculate_signal(closes):

    ema20 = ema(closes, 20)
    rsi14 = rsi(closes, 14)

    if ema20 is None or rsi14 is None:
        return "ESPERAR"

    current_price = closes[-1]

    if current_price > ema20 and rsi14 < 70:
        return "COMPRAR"

    if current_price < ema20 and rsi14 > 30:
        return "VENDER"

    return "ESPERAR"


# ============================================================
# UTILIDADES
# ============================================================

def apply_entry_slippage(price):
    return price * (1 + SLIPPAGE_RATE)


def apply_exit_slippage(price):
    return price * (1 - SLIPPAGE_RATE)


def calculate_position_size(
    equity,
    entry_price,
    stop_price
):

    risk_amount = equity * RISK_PER_TRADE

    risk_per_share = abs(
        entry_price - stop_price
    )

    if risk_per_share <= 0:
        return 0

    shares = int(
        risk_amount / risk_per_share
    )

    return max(shares, 0)


def calculate_max_risk(
    equity_before,
    entry_price,
    stop_price,
    shares
):

    if shares <= 0:
        return 0.0

    risk = (
        abs(entry_price - stop_price)
        * shares
    )

    return risk / equity_before


# ============================================================
# MÉTRICAS
# ============================================================

def calculate_profit_factor(trades):

    gross_profit = sum(
        t["net_pnl"]
        for t in trades
        if t["net_pnl"] > 0
    )

    gross_loss = sum(
        abs(t["net_pnl"])
        for t in trades
        if t["net_pnl"] < 0
    )

    if gross_loss == 0:
        return float("inf")

    return gross_profit / gross_loss


def calculate_win_rate(trades):

    if not trades:
        return 0.0

    wins = sum(
        1
        for t in trades
        if t["net_pnl"] > 0
    )

    return wins / len(trades)


def calculate_sharpe(equity_curve):

    if len(equity_curve) < 2:
        return 0.0

    returns = []

    for i in range(1, len(equity_curve)):

        previous = equity_curve[i - 1]

        current = equity_curve[i]

        if previous <= 0:
            continue

        returns.append(
            (current / previous) - 1
        )

    if len(returns) < 2:
        return 0.0

    mean_return = statistics.mean(returns)

    std_return = statistics.stdev(returns)

    if std_return == 0:
        return 0.0

    return (
        mean_return / std_return
    ) * math.sqrt(252)


def calculate_max_drawdown(equity_curve):

    if not equity_curve:
        return 0.0

    peak = equity_curve[0]

    max_drawdown = 0.0

    for equity in equity_curve:

        if equity > peak:
            peak = equity

        if peak > 0:

            drawdown = (
                peak - equity
            ) / peak

            max_drawdown = max(
                max_drawdown,
                drawdown
            )

    return max_drawdown


def calculate_streaks(trades):

    max_win_streak = 0
    max_loss_streak = 0

    current_win = 0
    current_loss = 0

    for trade in trades:

        pnl = trade["net_pnl"]

        if pnl > 0:

            current_win += 1
            current_loss = 0

        elif pnl < 0:

            current_loss += 1
            current_win = 0

        else:

            current_win = 0
            current_loss = 0

        max_win_streak = max(
            max_win_streak,
            current_win
        )

        max_loss_streak = max(
            max_loss_streak,
            current_loss
        )

    return max_win_streak, max_loss_streak


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(symbol, bars):

    if len(bars) <= WARMUP_DAYS + 2:
        raise RuntimeError(
            f"No hay suficientes datos para {symbol}"
        )

    cash = INITIAL_CAPITAL

    position = 0

    entry_price = 0.0
    entry_date = None
    stop_price = 0.0

    entry_commission = 0.0

    trades = []

    equity_curve = []

    max_risk_observed = 0.0

    highest_trade = None
    lowest_trade = None

    # --------------------------------------------------------
    # OOS WINDOWS
    # --------------------------------------------------------

    window_results = []

    test_start = WARMUP_DAYS

    while test_start < len(bars) - 1:

        window_end = min(
            test_start + OOS_WINDOW,
            len(bars) - 1
        )

        window_equity_start = cash

        window_equity_curve = []

        window_trade_start = len(trades)

        i = test_start

        while i < window_end:

            bar = bars[i]

            close_prices = [
                x["close"]
                for x in bars[:i + 1]
            ]

            signal = calculate_signal(
                close_prices
            )

            # ------------------------------------------------
            # POSICIÓN ABIERTA
            # ------------------------------------------------

            if position > 0:

                exit_price = None
                exit_reason = None

                # STOP NORMAL
                if bar["low"] <= stop_price:

                    if bar["open"] <= stop_price:

                        exit_price = (
                            bar["open"]
                        )

                        exit_reason = "STOP_GAP"

                    else:

                        exit_price = (
                            stop_price
                        )

                        exit_reason = "STOP"

                # SALIDA POR EMA / SEÑAL
                elif signal == "VENDER":

                    if i + 1 < len(bars):

                        next_open = (
                            bars[i + 1]["open"]
                        )

                        exit_price = (
                            next_open
                        )

                        exit_reason = "EMA_EXIT"

                # FIN DEL BACKTEST
                elif i == len(bars) - 2:

                    exit_price = (
                        bars[i + 1]["open"]
                    )

                    exit_reason = "END"

                if exit_price is not None:

                    adjusted_exit = (
                        apply_exit_slippage(
                            exit_price
                        )
                    )

                    exit_value = (
                        adjusted_exit
                        * position
                    )

                    exit_commission = (
                        position
                        * COMMISSION_PER_SHARE
                    )

                    gross_pnl = (
                        adjusted_exit
                        - entry_price
                    ) * position

                    total_commission = (
                        entry_commission
                        + exit_commission
                    )

                    net_pnl = (
                        gross_pnl
                        - total_commission
                    )

                    cash += (
                        exit_value
                        - exit_commission
                    )

                    equity_after = cash

                    planned_risk = (
                        abs(
                            entry_price
                            - stop_price
                        )
                        * position
                    )

                    risk_percent = 0.0

                    if (
                        equity_after
                        - net_pnl
                    ) > 0:

                        risk_percent = (
                            planned_risk
                            / (
                                equity_after
                                - net_pnl
                            )
                        )

                    holding_days = 0

                    if entry_date:

                        try:

                            entry_dt = (
                                datetime.fromisoformat(
                                    entry_date
                                )
                            )

                            exit_dt = (
                                datetime.fromisoformat(
                                    bar["date"]
                                )
                            )

                            holding_days = (
                                exit_dt
                                - entry_dt
                            ).days

                        except Exception:
                            holding_days = 0

                    trade = {
                        "symbol": symbol,
                        "signal_date": entry_date,
                        "entry_date": entry_date,
                        "exit_date": bar["date"],
                        "entry_price": entry_price,
                        "stop_price": stop_price,
                        "exit_price": adjusted_exit,
                        "shares": position,
                        "gross_pnl": gross_pnl,
                        "entry_commission": entry_commission,
                        "exit_commission": exit_commission,
                        "total_commission": total_commission,
                        "net_pnl": net_pnl,
                        "planned_risk": planned_risk,
                        "risk_percent": risk_percent,
                        "holding_days": holding_days,
                        "exit_reason": exit_reason,
                        "equity_before": (
                            equity_after
                            - net_pnl
                        ),
                        "equity_after": equity_after,
                    }

                    trades.append(trade)

                    if (
                        highest_trade is None
                        or net_pnl
                        > highest_trade["net_pnl"]
                    ):
                        highest_trade = trade

                    if (
                        lowest_trade is None
                        or net_pnl
                        < lowest_trade["net_pnl"]
                    ):
                        lowest_trade = trade

                    max_risk_observed = max(
                        max_risk_observed,
                        risk_percent
                    )

                    position = 0

                    entry_price = 0.0
                    entry_date = None
                    stop_price = 0.0
                    entry_commission = 0.0

            # ------------------------------------------------
            # ENTRADA
            # ------------------------------------------------

            if (
                position == 0
                and signal == "COMPRAR"
                and i + 1 < len(bars)
            ):

                next_bar = bars[i + 1]

                raw_entry = next_bar["open"]

                adjusted_entry = (
                    apply_entry_slippage(
                        raw_entry
                    )
                )

                planned_stop = (
                    adjusted_entry
                    * (1 - STOP_DISTANCE)
                )

                equity_now = cash

                shares = calculate_position_size(
                    equity_now,
                    adjusted_entry,
                    planned_stop
                )

                if shares > 0:

                    cost = (
                        adjusted_entry
                        * shares
                    )

                    commission = (
                        shares
                        * COMMISSION_PER_SHARE
                    )

                    total_cost = (
                        cost
                        + commission
                    )

                    # Nunca permitir cash negativo
                    if total_cost <= cash:

                        cash -= total_cost

                        position = shares

                        entry_price = (
                            adjusted_entry
                        )

                        stop_price = (
                            planned_stop
                        )

                        entry_date = (
                            next_bar["date"]
                        )

                        entry_commission = (
                            commission
                        )

                        risk_percent = (
                            calculate_max_risk(
                                equity_now,
                                entry_price,
                                stop_price,
                                shares
                            )
                        )

                        max_risk_observed = max(
                            max_risk_observed,
                            risk_percent
                        )

            # ------------------------------------------------
            # EQUITY DIARIA
            # ------------------------------------------------

            if position > 0:

                equity = (
                    cash
                    + (
                        position
                        * bar["close"]
                    )
                )

            else:

                equity = cash

            equity_curve.append(equity)

            window_equity_curve.append(
                equity
            )

            i += 1

        # ----------------------------------------------------
        # WINDOW SUMMARY
        # ----------------------------------------------------

        window_trades = trades[
            window_trade_start:
        ]

        window_end_equity = (
            window_equity_curve[-1]
            if window_equity_curve
            else window_equity_start
        )

        window_return = 0.0

        if window_equity_start > 0:

            window_return = (
                window_end_equity
                / window_equity_start
            ) - 1

        window_results.append({
            "start": bars[test_start]["date"],
            "end": bars[window_end - 1]["date"],
            "start_equity": window_equity_start,
            "end_equity": window_end_equity,
            "return": window_return,
            "trades": len(window_trades),
        })

        test_start = window_end

    # ========================================================
    # SI QUEDA POSICIÓN ABIERTA, CERRAR AL ÚLTIMO CLOSE
    # ========================================================

    if position > 0:

        final_bar = bars[-1]

        adjusted_exit = apply_exit_slippage(
            final_bar["close"]
        )

        exit_value = (
            adjusted_exit
            * position
        )

        exit_commission = (
            position
            * COMMISSION_PER_SHARE
        )

        gross_pnl = (
            adjusted_exit
            - entry_price
        ) * position

        total_commission = (
            entry_commission
            + exit_commission
        )

        net_pnl = (
            gross_pnl
            - total_commission
        )

        cash += (
            exit_value
            - exit_commission
        )

        equity_after = cash

        planned_risk = (
            abs(
                entry_price
                - stop_price
            )
            * position
        )

        risk_percent = 0.0

        if (
            equity_after
            - net_pnl
        ) > 0:

            risk_percent = (
                planned_risk
                / (
                    equity_after
                    - net_pnl
                )
            )

        holding_days = 0

        if entry_date:

            try:

                entry_dt = (
                    datetime.fromisoformat(
                        entry_date
                    )
                )

                exit_dt = (
                    datetime.fromisoformat(
                        final_bar["date"]
                    )
                )

                holding_days = (
                    exit_dt
                    - entry_dt
                ).days

            except Exception:
                holding_days = 0

        trade = {
            "symbol": symbol,
            "signal_date": entry_date,
            "entry_date": entry_date,
            "exit_date": final_bar["date"],
            "entry_price": entry_price,
            "stop_price": stop_price,
            "exit_price": adjusted_exit,
            "shares": position,
            "gross_pnl": gross_pnl,
            "entry_commission": entry_commission,
            "exit_commission": exit_commission,
            "total_commission": total_commission,
            "net_pnl": net_pnl,
            "planned_risk": planned_risk,
            "risk_percent": risk_percent,
            "holding_days": holding_days,
            "exit_reason": "END",
            "equity_before": (
                equity_after
                - net_pnl
            ),
            "equity_after": equity_after,
        }

        trades.append(trade)

        if (
            highest_trade is None
            or net_pnl
            > highest_trade["net_pnl"]
        ):
            highest_trade = trade

        if (
            lowest_trade is None
            or net_pnl
            < lowest_trade["net_pnl"]
        ):
            lowest_trade = trade

        max_risk_observed = max(
            max_risk_observed,
            risk_percent
        )

        position = 0

    # ========================================================
    # RESULTADOS
    # ========================================================

    final_equity = cash

    total_return = (
        final_equity
        / INITIAL_CAPITAL
    ) - 1

    test_bars = bars[WARMUP_DAYS:]

    if len(test_bars) >= 2:

        buy_hold_return = (
            test_bars[-1]["close"]
            / test_bars[0]["close"]
        ) - 1

    else:

        buy_hold_return = 0.0

    max_dd = calculate_max_drawdown(
        equity_curve
    )

    sharpe = calculate_sharpe(
        equity_curve
    )

    win_rate = calculate_win_rate(
        trades
    )

    profit_factor = calculate_profit_factor(
        trades
    )

    wins = [
        t["net_pnl"]
        for t in trades
        if t["net_pnl"] > 0
    ]

    losses = [
        t["net_pnl"]
        for t in trades
        if t["net_pnl"] < 0
    ]

    avg_win = (
        statistics.mean(wins)
        if wins else 0.0
    )

    avg_loss = (
        statistics.mean(losses)
        if losses else 0.0
    )

    median_win = (
        statistics.median(wins)
        if wins else 0.0
    )

    median_loss = (
        statistics.median(losses)
        if losses else 0.0
    )

    payoff_ratio = 0.0

    if avg_loss != 0:

        payoff_ratio = (
            avg_win
            / abs(avg_loss)
        )

    max_win_streak, max_loss_streak = (
        calculate_streaks(trades)
    )

    stop_count = sum(
        1
        for t in trades
        if t["exit_reason"] == "STOP"
    )

    gap_stop_count = sum(
        1
        for t in trades
        if t["exit_reason"] == "STOP_GAP"
    )

    ema_exit_count = sum(
        1
        for t in trades
        if t["exit_reason"] == "EMA_EXIT"
    )

    end_exit_count = sum(
        1
        for t in trades
        if t["exit_reason"] == "END"
    )

    average_holding = (
        statistics.mean(
            [t["holding_days"] for t in trades]
        )
        if trades
        else 0.0
    )

    median_holding = (
        statistics.median(
            [t["holding_days"] for t in trades]
        )
        if trades
        else 0.0
    )

    gross_profit = sum(wins)

    gross_loss = abs(
        sum(losses)
    )

    # ========================================================
    # CONCENTRACIÓN DE GANANCIAS
    # ========================================================

    sorted_positive = sorted(
        wins,
        reverse=True
    )

    top_5_profit = sum(
        sorted_positive[:5]
    )

    total_net_profit = sum(
        t["net_pnl"]
        for t in trades
    )

    top_5_contribution = 0.0

    if total_net_profit > 0:

        top_5_contribution = (
            top_5_profit
            / total_net_profit
        )

    # ========================================================
    # AUDITORÍA
    # ========================================================

    audit_ok = True

    for trade in trades:

        if trade["risk_percent"] > (
            RISK_PER_TRADE + 0.000001
        ):

            audit_ok = False

        if trade["equity_before"] < 0:
            audit_ok = False

        if trade["equity_after"] < 0:
            audit_ok = False

        if trade["shares"] < 0:
            audit_ok = False

    return {
        "symbol": symbol,
        "final_equity": final_equity,
        "total_return": total_return,
        "buy_hold_return": buy_hold_return,
        "trades": trades,
        "trade_count": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "median_win": median_win,
        "median_loss": median_loss,
        "payoff_ratio": payoff_ratio,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "stop_count": stop_count,
        "gap_stop_count": gap_stop_count,
        "ema_exit_count": ema_exit_count,
        "end_exit_count": end_exit_count,
        "average_holding": average_holding,
        "median_holding": median_holding,
        "top_5_profit": top_5_profit,
        "top_5_contribution": top_5_contribution,
        "max_risk": max_risk_observed,
        "audit_ok": audit_ok,
        "windows": window_results,
        "best_trade": highest_trade,
        "worst_trade": lowest_trade,
    }


# ============================================================
# CSV
# ============================================================

def save_trade_csv(all_results):

    fields = [
        "symbol",
        "signal_date",
        "entry_date",
        "exit_date",
        "entry_price",
        "stop_price",
        "exit_price",
        "shares",
        "gross_pnl",
        "entry_commission",
        "exit_commission",
        "total_commission",
        "net_pnl",
        "planned_risk",
        "risk_percent",
        "holding_days",
        "exit_reason",
        "equity_before",
        "equity_after",
    ]

    with open(
        AUDIT_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()

        for result in all_results:

            for trade in result["trades"]:

                writer.writerow(trade)


# ============================================================
# REPORTE
# ============================================================

def create_report(all_results):

    lines = []

    lines.append("=" * 70)
    lines.append(
        "       AI TRADER — MULTI BACKTEST V7.2"
    )
    lines.append("=" * 70)
    lines.append(
        "AUDITORÍA PROFUNDA DE OPERACIONES"
    )
    lines.append(
        "FUENTE DE DATOS: IEX"
    )
    lines.append(
        f"WARMUP: {WARMUP_DAYS} días"
    )
    lines.append(
        f"VENTANA OOS: {OOS_WINDOW} días"
    )
    lines.append(
        "DATOS AJUSTADOS: SPLITS + DIVIDENDOS"
    )
    lines.append(
        "ENTRADA: OPEN DEL DÍA SIGUIENTE"
    )
    lines.append(
        "STOP: LOW REAL + PROTECCIÓN GAP"
    )
    lines.append(
        "SLIPPAGE + COMISIONES ACTIVOS"
    )
    lines.append(
        "SOLO BACKTEST"
    )
    lines.append(
        "NO SE ENVÍAN ÓRDENES"
    )
    lines.append("")

    for result in all_results:

        symbol = result["symbol"]

        lines.append("-" * 70)
        lines.append(
            f"{symbol} — RESUMEN"
        )
        lines.append("-" * 70)

        lines.append(
            f"TOTAL: {result['total_return'] * 100:.2f}%"
        )

        lines.append(
            f"B&H: {result['buy_hold_return'] * 100:.2f}%"
        )

        lines.append(
            f"TRADES: {result['trade_count']}"
        )

        lines.append(
            f"WIN RATE: {result['win_rate'] * 100:.1f}%"
        )

        lines.append(
            f"PROFIT FACTOR: {result['profit_factor']:.2f}"
        )

        lines.append(
            f"DRAWDOWN: {result['max_drawdown'] * 100:.2f}%"
        )

        lines.append(
            f"SHARPE: {result['sharpe']:.2f}"
        )

        lines.append("")

        lines.append(
            "AUDITORÍA DE RIESGO"
        )

        lines.append(
            f"RIESGO MÁXIMO: "
            f"{result['max_risk'] * 100:.4f}%"
        )

        lines.append(
            "AUDITORÍA: "
            + (
                "OK"
                if result["audit_ok"]
                else "FALLO"
            )
        )

        lines.append("")

        lines.append(
            "ESTADÍSTICAS DE OPERACIONES"
        )

        lines.append(
            f"GANANCIA PROMEDIO: "
            f"${result['avg_win']:.2f}"
        )

        lines.append(
            f"PÉRDIDA PROMEDIO: "
            f"${result['avg_loss']:.2f}"
        )

        lines.append(
            f"GANANCIA MEDIANA: "
            f"${result['median_win']:.2f}"
        )

        lines.append(
            f"PÉRDIDA MEDIANA: "
            f"${result['median_loss']:.2f}"
        )

        lines.append(
            f"PAYOFF RATIO: "
            f"{result['payoff_ratio']:.2f}"
        )

        lines.append("")

        lines.append(
            "SALIDAS"
        )

        lines.append(
            f"STOP: {result['stop_count']}"
        )

        lines.append(
            f"STOP GAP: {result['gap_stop_count']}"
        )

        lines.append(
            f"EMA EXIT: {result['ema_exit_count']}"
        )

        lines.append(
            f"END: {result['end_exit_count']}"
        )

        lines.append("")

        lines.append(
            "RACHAS"
        )

        lines.append(
            f"MÁXIMA GANADORA: "
            f"{result['max_win_streak']}"
        )

        lines.append(
            f"MÁXIMA PERDEDORA: "
            f"{result['max_loss_streak']}"
        )

        lines.append("")

        lines.append(
            "DURACIÓN"
        )

        lines.append(
            f"PROMEDIO: "
            f"{result['average_holding']:.1f} días"
        )

        lines.append(
            f"MEDIANA: "
            f"{result['median_holding']:.1f} días"
        )

        lines.append("")

        lines.append(
            "CONCENTRACIÓN DE RESULTADOS"
        )

        lines.append(
            f"TOP 5 GANANCIAS: "
            f"${result['top_5_profit']:.2f}"
        )

        lines.append(
            f"CONTRIBUCIÓN TOP 5: "
            f"{result['top_5_contribution'] * 100:.1f}%"
        )

        lines.append("")

        best = result["best_trade"]
        worst = result["worst_trade"]

        if best:

            lines.append(
                "MEJOR OPERACIÓN"
            )

            lines.append(
                f"{best['entry_date']} → "
                f"{best['exit_date']} | "
                f"P&L ${best['net_pnl']:.2f} | "
                f"Salida {best['exit_reason']}"
            )

        if worst:

            lines.append(
                "PEOR OPERACIÓN"
            )

            lines.append(
                f"{worst['entry_date']} → "
                f"{worst['exit_date']} | "
                f"P&L ${worst['net_pnl']:.2f} | "
                f"Salida {worst['exit_reason']}"
            )

        lines.append("")

        # ----------------------------------------------------
        # VENTANAS
        # ----------------------------------------------------

        lines.append(
            "VENTANAS OOS DE 63 DÍAS"
        )

        positive_windows = 0
        negative_windows = 0

        for window in result["windows"]:

            if window["return"] >= 0:
                positive_windows += 1
            else:
                negative_windows += 1

            lines.append(
                f"{window['start']} → "
                f"{window['end']} | "
                f"{window['return'] * 100:+.2f}% | "
                f"TRADES {window['trades']} | "
                f"EQUITY "
                f"${window['start_equity']:.2f} → "
                f"${window['end_equity']:.2f}"
            )

        lines.append(
            f"VENTANAS POSITIVAS: "
            f"{positive_windows}"
        )

        lines.append(
            f"VENTANAS NEGATIVAS: "
            f"{negative_windows}"
        )

        lines.append("")

    lines.append("=" * 70)
    lines.append(
        "FIN DEL REPORTE V7.2"
    )
    lines.append("=" * 70)

    report = "\n".join(lines)

    with open(
        RESULTS_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(report)

    return report


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "       AI TRADER — MULTI BACKTEST V7.2"
    )
    print("=" * 70)
    print(
        "AUDITORÍA PROFUNDA DE OPERACIONES"
    )
    print(
        "FUENTE DE DATOS: IEX"
    )
    print(
        f"WARMUP: {WARMUP_DAYS} días"
    )
    print(
        f"VENTANA OOS: {OOS_WINDOW} días"
    )
    print(
        "DATOS AJUSTADOS: SPLITS + DIVIDENDOS"
    )
    print(
        "ENTRADA: OPEN DEL DÍA SIGUIENTE"
    )
    print(
        "STOP: LOW REAL + PROTECCIÓN GAP"
    )
    print(
        "SLIPPAGE + COMISIONES ACTIVOS"
    )
    print(
        "IMPORTANTE: SOLO BACKTEST"
    )
    print(
        "NO SE ENVIAN ORDENES"
    )
    print()

    all_results = []

    for symbol in SYMBOLS:

        print(
            f"Descargando datos: {symbol}..."
        )

        try:

            bars = download_data(symbol)

            print(
                f"{symbol}: "
                f"{len(bars)} velas"
            )

            print()

            result = run_backtest(
                symbol,
                bars
            )

            all_results.append(result)

            print(
                f"{symbol} TOTAL "
                f"{result['total_return'] * 100:.2f}% "
                f"| B&H "
                f"{result['buy_hold_return'] * 100:.2f}% "
                f"| TRADES "
                f"{result['trade_count']} "
                f"| WIN "
                f"{result['win_rate'] * 100:.1f}% "
                f"| PF "
                f"{result['profit_factor']:.2f} "
                f"| DD "
                f"{result['max_drawdown'] * 100:.2f}% "
                f"| SHARPE "
                f"{result['sharpe']:.2f}"
            )

            print(
                "AUDITORÍA "
                + (
                    "OK"
                    if result["audit_ok"]
                    else "FALLO"
                )
            )

            print(
                f"RIESGO MÁXIMO "
                f"{result['max_risk'] * 100:.4f}%"
            )

            print()

            # ------------------------------------------------
            # AUDITORÍA PROFUNDA EN LOGS
            # ------------------------------------------------

            print(
                f"===== AUDITORÍA DETALLADA {symbol} ====="
            )

            print(
                f"GANANCIA PROMEDIO: "
                f"${result['avg_win']:.2f}"
            )

            print(
                f"PÉRDIDA PROMEDIO: "
                f"${result['avg_loss']:.2f}"
            )

            print(
                f"PAYOFF RATIO: "
                f"{result['payoff_ratio']:.2f}"
            )

            print(
                f"STOP: "
                f"{result['stop_count']}"
            )

            print(
                f"STOP GAP: "
                f"{result['gap_stop_count']}"
            )

            print(
                f"EMA EXIT: "
                f"{result['ema_exit_count']}"
            )

            print(
                f"END: "
                f"{result['end_exit_count']}"
            )

            print(
                f"RACHA GANADORA MÁXIMA: "
                f"{result['max_win_streak']}"
            )

            print(
                f"RACHA PERDEDORA MÁXIMA: "
                f"{result['max_loss_streak']}"
            )

            print(
                f"DURACIÓN PROMEDIO: "
                f"{result['average_holding']:.1f} días"
            )

            print(
                f"TOP 5 GANANCIAS REPRESENTAN: "
                f"{result['top_5_contribution'] * 100:.1f}% "
                f"DEL P&L NETO"
            )

            if result["best_trade"]:

                best = result["best_trade"]

                print(
                    f"MEJOR TRADE: "
                    f"{best['entry_date']} → "
                    f"{best['exit_date']} | "
                    f"${best['net_pnl']:.2f} | "
                    f"{best['exit_reason']}"
                )

            if result["worst_trade"]:

                worst = result["worst_trade"]

                print(
                    f"PEOR TRADE: "
                    f"{worst['entry_date']} → "
                    f"{worst['exit_date']} | "
                    f"${worst['net_pnl']:.2f} | "
                    f"{worst['exit_reason']}"
                )

            positive_windows = sum(
                1
                for w in result["windows"]
                if w["return"] >= 0
            )

            negative_windows = sum(
                1
                for w in result["windows"]
                if w["return"] < 0
            )

            print(
                f"VENTANAS POSITIVAS: "
                f"{positive_windows}"
            )

            print(
                f"VENTANAS NEGATIVAS: "
                f"{negative_windows}"
            )

            print(
                "======================================"
            )

            print()

        except Exception as error:

            print(
                f"ERROR EN {symbol}: {error}"
            )

            print()

    if not all_results:

        raise RuntimeError(
            "NO SE GENERARON RESULTADOS"
        )

    save_trade_csv(
        all_results
    )

    report = create_report(
        all_results
    )

    print(report)

    print()
    print("=" * 70)
    print(
        f"REPORTE GUARDADO: "
        f"{RESULTS_FILE}"
    )
    print(
        f"TRADES GUARDADOS: "
        f"{AUDIT_FILE}"
    )
    print("=" * 70)
    print(
        "V7.2 TERMINADO"
    )


if __name__ == "__main__":
    main()
