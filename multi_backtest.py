import csv
import math
import os
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


# ============================================================
# AI TRADER — MULTI BACKTEST V7
# AUDITORÍA DE CONTABILIDAD Y RIESGO
# ============================================================

SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]

START_CAPITAL = 100000.0

RISK_PER_TRADE = 0.01
STOP_PERCENT = 0.03

MAX_TRADES_PER_DAY = 5

SLIPPAGE_RATE = 0.0005
COMMISSION_PER_SHARE = 0.01

WARMUP_DAYS = 252
TEST_WINDOW_DAYS = 63

OUTPUT_FILE = "backtest_results_v7.txt"
TRADE_FILE = "trade_audit_v7.csv"


# ============================================================
# ALPACA
# ============================================================

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise RuntimeError(
        "FALTAN ALPACA_API_KEY O ALPACA_SECRET_KEY EN VARIABLES DE RAILWAY"
    )

client = StockHistoricalDataClient(
    API_KEY,
    SECRET_KEY
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

    relative_strength = average_gain / average_loss

    return 100 - (
        100 / (1 + relative_strength)
    )


def volatility(values, period=20):
    if len(values) < period:
        return None

    recent = values[-period:]

    average = sum(recent) / period

    variance = sum(
        (price - average) ** 2
        for price in recent
    ) / period

    return math.sqrt(variance)


# ============================================================
# MÉTRICAS
# ============================================================

def calculate_profit_factor(trades):
    gross_profit = 0.0
    gross_loss = 0.0

    for trade in trades:
        pnl = trade["net_pnl"]

        if pnl > 0:
            gross_profit += pnl

        elif pnl < 0:
            gross_loss += abs(pnl)

    if gross_loss == 0:
        if gross_profit > 0:
            return float("inf")
        return 0.0

    return gross_profit / gross_loss


def calculate_win_rate(trades):
    if not trades:
        return 0.0

    wins = sum(
        1
        for trade in trades
        if trade["net_pnl"] > 0
    )

    return wins / len(trades)


def calculate_max_drawdown(equity_curve):
    if not equity_curve:
        return 0.0, 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0

    for equity in equity_curve:
        if equity > peak:
            peak = equity

        if peak > 0:
            drawdown = (
                (peak - equity) / peak
            )

            if drawdown > max_drawdown:
                max_drawdown = drawdown

    return max_drawdown, max_drawdown * (
        equity_curve[0]
    )


def calculate_sharpe(equity_curve):
    if len(equity_curve) < 3:
        return 0.0

    returns = []

    for i in range(1, len(equity_curve)):
        previous = equity_curve[i - 1]

        if previous <= 0:
            continue

        daily_return = (
            equity_curve[i] / previous
        ) - 1

        returns.append(daily_return)

    if len(returns) < 2:
        return 0.0

    average = sum(returns) / len(returns)

    variance = sum(
        (r - average) ** 2
        for r in returns
    ) / (len(returns) - 1)

    standard_deviation = math.sqrt(variance)

    if standard_deviation == 0:
        return 0.0

    return (
        average / standard_deviation
    ) * math.sqrt(252)


def calculate_buy_hold(bars):
    if len(bars) < 2:
        return 0.0

    first_price = bars[0]["close"]
    last_price = bars[-1]["close"]

    if first_price <= 0:
        return 0.0

    return (
        (last_price / first_price) - 1
    )


# ============================================================
# DATOS
# ============================================================

def get_data(symbol, years):
    end_date = datetime.now(timezone.utc).date()

    start_date = (
        end_date
        - timedelta(days=int(years * 365.25))
    )

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=datetime.combine(
            start_date,
            datetime.min.time(),
            tzinfo=timezone.utc
        ),
        end=datetime.combine(
            end_date + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc
        ),
        adjustment="all"
    )

    response = client.get_stock_bars(request)

    bars = response[symbol]

    cleaned = []

    for bar in bars:
        cleaned.append(
            {
                "date": bar.timestamp.date(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            }
        )

    cleaned.sort(
        key=lambda x: x["date"]
    )

    return cleaned


# ============================================================
# POSICIÓN
# ============================================================

def calculate_position_size(
    equity,
    entry_price,
    stop_price
):
    if equity <= 0:
        return 0

    risk_amount = (
        equity * RISK_PER_TRADE
    )

    risk_per_share = abs(
        entry_price - stop_price
    )

    if risk_per_share <= 0:
        return 0

    shares = int(
        risk_amount / risk_per_share
    )

    return max(shares, 0)


# ============================================================
# BACKTEST CONTINUO
# ============================================================

def run_backtest(symbol, bars):
    if len(bars) <= WARMUP_DAYS + 20:
        return None

    warmup = bars[
        :WARMUP_DAYS
    ]

    test_bars = bars[
        WARMUP_DAYS:
    ]

    cash = START_CAPITAL

    shares = 0

    entry_price = None
    entry_date = None
    signal_date = None
    stop_price = None

    position_equity_at_entry = None

    pending_entry = False
    pending_signal_date = None

    trades = []

    equity_curve = []
    equity_dates = []

    audit_errors = []

    daily_trade_count = 0
    current_date = None

    closes = [
        item["close"]
        for item in warmup
    ]

    all_bars = []

    all_bars.extend(warmup)
    all_bars.extend(test_bars)

    for index in range(
        WARMUP_DAYS,
        len(all_bars)
    ):
        bar = all_bars[index]

        date = bar["date"]

        open_price = bar["open"]
        high_price = bar["high"]
        low_price = bar["low"]
        close_price = bar["close"]

        if current_date != date:
            current_date = date
            daily_trade_count = 0

        # ----------------------------------------------------
        # EJECUTAR ENTRADA PENDIENTE
        # ----------------------------------------------------

        if pending_entry and shares == 0:

            if daily_trade_count >= MAX_TRADES_PER_DAY:
                pending_entry = False

            else:
                actual_entry = (
                    open_price
                    * (1 + SLIPPAGE_RATE)
                )

                actual_stop = (
                    actual_entry
                    * (1 - STOP_PERCENT)
                )

                equity_before = (
                    cash
                )

                position_size = calculate_position_size(
                    equity_before,
                    actual_entry,
                    actual_stop
                )

                if position_size > 0:

                    total_cost = (
                        actual_entry
                        * position_size
                    )

                    commission = (
                        position_size
                        * COMMISSION_PER_SHARE
                    )

                    if (
                        total_cost
                        + commission
                        <= cash
                    ):

                        cash -= (
                            total_cost
                            + commission
                        )

                        shares = position_size

                        entry_price = actual_entry
                        entry_date = date
                        signal_date = pending_signal_date
                        stop_price = actual_stop

                        position_equity_at_entry = (
                            equity_before
                        )

                        daily_trade_count += 1

                        pending_entry = False

                    else:
                        pending_entry = False

                else:
                    pending_entry = False

        # ----------------------------------------------------
        # GESTIONAR POSICIÓN
        # ----------------------------------------------------

        if shares > 0:

            exit_price = None
            exit_reason = None

            # GAP
            if open_price <= stop_price:

                exit_price = (
                    open_price
                    * (1 - SLIPPAGE_RATE)
                )

                exit_reason = "STOP_GAP"

            # STOP INTRADÍA
            elif low_price <= stop_price:

                exit_price = (
                    stop_price
                    * (1 - SLIPPAGE_RATE)
                )

                exit_reason = "STOP"

            else:

                historical_closes = (
                    closes
                    + [
                        close_price
                    ]
                )

                ema20 = ema(
                    historical_closes,
                    20
                )

                if (
                    ema20 is not None
                    and close_price < ema20
                ):

                    exit_price = (
                        close_price
                        * (1 - SLIPPAGE_RATE)
                    )

                    exit_reason = "EMA"

            # ------------------------------------------------
            # CERRAR
            # ------------------------------------------------

            if exit_price is not None:

                gross_pnl = (
                    exit_price
                    - entry_price
                ) * shares

                exit_commission = (
                    shares
                    * COMMISSION_PER_SHARE
                )

                net_pnl = (
                    gross_pnl
                    - exit_commission
                )

                cash += (
                    exit_price
                    * shares
                )

                cash -= exit_commission

                equity_after = cash

                planned_risk = (
                    abs(
                        entry_price
                        - stop_price
                    )
                    * shares
                )

                actual_risk_pct = 0.0

                if (
                    position_equity_at_entry
                    > 0
                ):
                    actual_risk_pct = (
                        planned_risk
                        / position_equity_at_entry
                    )

                trade = {
                    "symbol": symbol,
                    "signal_date": signal_date,
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "exit_date": date,
                    "exit_price": exit_price,
                    "shares": shares,
                    "exit_reason": exit_reason,
                    "gross_pnl": gross_pnl,
                    "entry_commission": (
                        shares
                        * COMMISSION_PER_SHARE
                    ),
                    "exit_commission": exit_commission,
                    "total_commission": (
                        shares
                        * COMMISSION_PER_SHARE
                        * 2
                    ),
                    "net_pnl": net_pnl,
                    "planned_risk": planned_risk,
                    "planned_risk_pct": actual_risk_pct,
                    "equity_before": (
                        position_equity_at_entry
                    ),
                    "equity_after": equity_after,
                }

                trades.append(trade)

                shares = 0

                entry_price = None
                entry_date = None
                signal_date = None
                stop_price = None
                position_equity_at_entry = None

        # ----------------------------------------------------
        # SEÑAL PARA MAÑANA
        # ----------------------------------------------------

        if shares == 0 and not pending_entry:

            historical_closes = (
                closes
                + [
                    close_price
                ]
            )

            ema20 = ema(
                historical_closes,
                20
            )

            rsi14 = rsi(
                historical_closes,
                14
            )

            if (
                ema20 is not None
                and rsi14 is not None
            ):

                if (
                    close_price > ema20
                    and rsi14 < 70
                ):

                    pending_entry = True
                    pending_signal_date = date

        # ----------------------------------------------------
        # EQUITY REAL
        # ----------------------------------------------------

        market_value = (
            shares
            * close_price
        )

        total_equity = (
            cash
            + market_value
        )

        if total_equity < 0:
            audit_errors.append(
                f"{date}: EQUITY NEGATIVA"
            )

        equity_curve.append(
            total_equity
        )

        equity_dates.append(
            date
        )

        closes.append(
            close_price
        )

    # ========================================================
    # CERRAR POSICIÓN FINAL
    # ========================================================

    if shares > 0:

        final_bar = all_bars[-1]

        final_price = (
            final_bar["close"]
            * (1 - SLIPPAGE_RATE)
        )

        gross_pnl = (
            final_price
            - entry_price
        ) * shares

        exit_commission = (
            shares
            * COMMISSION_PER_SHARE
        )

        net_pnl = (
            gross_pnl
            - exit_commission
        )

        cash += (
            final_price
            * shares
        )

        cash -= exit_commission

        planned_risk = (
            abs(
                entry_price
                - stop_price
            )
            * shares
        )

        risk_pct = 0.0

        if position_equity_at_entry > 0:
            risk_pct = (
                planned_risk
                / position_equity_at_entry
            )

        trades.append(
            {
                "symbol": symbol,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "exit_date": final_bar["date"],
                "exit_price": final_price,
                "shares": shares,
                "exit_reason": "END",
                "gross_pnl": gross_pnl,
                "entry_commission": (
                    shares
                    * COMMISSION_PER_SHARE
                ),
                "exit_commission": exit_commission,
                "total_commission": (
                    shares
                    * COMMISSION_PER_SHARE
                    * 2
                ),
                "net_pnl": net_pnl,
                "planned_risk": planned_risk,
                "planned_risk_pct": risk_pct,
                "equity_before": (
                    position_equity_at_entry
                ),
                "equity_after": cash,
            }
        )

        shares = 0

    # ========================================================
    # AUDITORÍA DE RIESGO
    # ========================================================

    max_risk_pct = 0.0

    for trade in trades:

        risk_pct = trade[
            "planned_risk_pct"
        ]

        if risk_pct > max_risk_pct:
            max_risk_pct = risk_pct

        if risk_pct > (
            RISK_PER_TRADE + 0.001
        ):
            audit_errors.append(
                (
                    f"{trade['entry_date']}: "
                    f"RIESGO EXCESIVO "
                    f"{risk_pct * 100:.2f}%"
                )
            )

    # ========================================================
    # AUDITORÍA DE CASH
    # ========================================================

    if cash < -0.01:
        audit_errors.append(
            "CASH FINAL NEGATIVO"
        )

    # ========================================================
    # VENTANAS 63 DÍAS
    # ========================================================

    windows = []

    total_points = len(
        equity_curve
    )

    window_start = 0

    while window_start < total_points:

        window_end = min(
            window_start
            + TEST_WINDOW_DAYS,
            total_points
        )

        window_equity = equity_curve[
            window_start:window_end
        ]

        window_dates = equity_dates[
            window_start:window_end
        ]

        if len(window_equity) < 2:
            break

        starting_equity = (
            window_equity[0]
        )

        ending_equity = (
            window_equity[-1]
        )

        if starting_equity <= 0:
            window_return = 0.0
        else:
            window_return = (
                ending_equity
                / starting_equity
            ) - 1

        window_trades = []

        start_date = window_dates[0]
        end_date = window_dates[-1]

        for trade in trades:

            exit_date = trade[
                "exit_date"
            ]

            if (
                start_date
                <= exit_date
                <= end_date
            ):
                window_trades.append(
                    trade
                )

        window_dd, _ = (
            calculate_max_drawdown(
                window_equity
            )
        )

        windows.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "starting_equity": starting_equity,
                "ending_equity": ending_equity,
                "return": window_return,
                "trades": window_trades,
                "drawdown": window_dd,
                "sharpe": calculate_sharpe(
                    window_equity
                ),
            }
        )

        window_start = window_end

    # ========================================================
    # MÉTRICAS FINALES
    # ========================================================

    initial_equity = (
        equity_curve[0]
        if equity_curve
        else START_CAPITAL
    )

    final_equity = (
        equity_curve[-1]
        if equity_curve
        else START_CAPITAL
    )

    total_return = (
        final_equity
        / initial_equity
    ) - 1

    buy_hold = calculate_buy_hold(
        test_bars
    )

    max_drawdown, _ = (
        calculate_max_drawdown(
            equity_curve
        )
    )

    sharpe = calculate_sharpe(
        equity_curve
    )

    profit_factor = (
        calculate_profit_factor(
            trades
        )
    )

    win_rate = (
        calculate_win_rate(
            trades
        )
    )

    total_commissions = sum(
        trade["total_commission"]
        for trade in trades
    )

    # ========================================================
    # AUDITORÍA DE VENTANAS
    # ========================================================

    suspicious_windows = []

    for number, window in enumerate(
        windows,
        start=1
    ):

        window_return = (
            window["return"]
        )

        # No es un error automático.
        # Solamente marca ventanas
        # extraordinarias para revisión.

        if abs(window_return) > 0.10:
            suspicious_windows.append(
                {
                    "number": number,
                    "return": window_return,
                    "start": window[
                        "start_date"
                    ],
                    "end": window[
                        "end_date"
                    ],
                }
            )

    return {
        "symbol": symbol,
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "total_return": total_return,
        "buy_hold": buy_hold,
        "trades": trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "total_commissions": total_commissions,
        "windows": windows,
        "audit_errors": audit_errors,
        "suspicious_windows": suspicious_windows,
        "max_risk_pct": max_risk_pct,
        "equity_curve": equity_curve,
        "equity_dates": equity_dates,
    }


# ============================================================
# CSV
# ============================================================

def save_trades(all_results):

    with open(
        TRADE_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow(
            [
                "symbol",
                "signal_date",
                "entry_date",
                "entry_price",
                "stop_price",
                "exit_date",
                "exit_price",
                "shares",
                "exit_reason",
                "gross_pnl",
                "entry_commission",
                "exit_commission",
                "total_commission",
                "net_pnl",
                "planned_risk",
                "planned_risk_pct",
                "equity_before",
                "equity_after",
            ]
        )

        for result in all_results:

            for trade in result["trades"]:

                writer.writerow(
                    [
                        trade["symbol"],
                        trade["signal_date"],
                        trade["entry_date"],
                        f"{trade['entry_price']:.4f}",
                        f"{trade['stop_price']:.4f}",
                        trade["exit_date"],
                        f"{trade['exit_price']:.4f}",
                        trade["shares"],
                        trade["exit_reason"],
                        f"{trade['gross_pnl']:.2f}",
                        f"{trade['entry_commission']:.2f}",
                        f"{trade['exit_commission']:.2f}",
                        f"{trade['total_commission']:.2f}",
                        f"{trade['net_pnl']:.2f}",
                        f"{trade['planned_risk']:.2f}",
                        f"{trade['planned_risk_pct'] * 100:.4f}",
                        f"{trade['equity_before']:.2f}",
                        f"{trade['equity_after']:.2f}",
                    ]
                )


# ============================================================
# REPORTE
# ============================================================

def generate_report(results):

    lines = []

    lines.append(
        "=============================================="
    )

    lines.append(
        "       AI TRADER — MULTI BACKTEST V7"
    )

    lines.append(
        "=============================================="
    )

    lines.append(
        "AUDITORÍA DE CONTABILIDAD Y RIESGO"
    )

    lines.append(
        "WARMUP: 252 días"
    )

    lines.append(
        "VENTANA: 63 días"
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
        "DATOS AJUSTADOS: SPLITS + DIVIDENDOS"
    )

    lines.append(
        "IMPORTANTE: SOLO BACKTEST"
    )

    lines.append(
        "NO SE ENVIAN ORDENES"
    )

    lines.append("")

    for result in results:

        symbol = result["symbol"]

        lines.append(
            "=============================================="
        )

        lines.append(
            f"{symbol}"
        )

        lines.append(
            "=============================================="
        )

        lines.append(
            f"Capital inicial: "
            f"${result['initial_equity']:,.2f}"
        )

        lines.append(
            f"Capital final: "
            f"${result['final_equity']:,.2f}"
        )

        lines.append(
            f"Retorno total: "
            f"{result['total_return'] * 100:.2f}%"
        )

        lines.append(
            f"Buy & Hold: "
            f"{result['buy_hold'] * 100:.2f}%"
        )

        lines.append(
            f"Operaciones: "
            f"{len(result['trades'])}"
        )

        lines.append(
            f"Win rate: "
            f"{result['win_rate'] * 100:.2f}%"
        )

        pf = result["profit_factor"]

        if math.isinf(pf):
            pf_text = "INF"
        else:
            pf_text = f"{pf:.2f}"

        lines.append(
            f"Profit Factor: {pf_text}"
        )

        lines.append(
            f"Max Drawdown: "
            f"{result['max_drawdown'] * 100:.2f}%"
        )

        lines.append(
            f"Sharpe: "
            f"{result['sharpe']:.2f}"
        )

        lines.append(
            f"Comisiones: "
            f"${result['total_commissions']:,.2f}"
        )

        lines.append(
            f"Máximo riesgo planeado: "
            f"{result['max_risk_pct'] * 100:.4f}%"
        )

        lines.append("")

        lines.append(
            "----- VENTANAS OOS -----"
        )

        for number, window in enumerate(
            result["windows"],
            start=1
        ):

            window_trades = (
                window["trades"]
            )

            window_pf = (
                calculate_profit_factor(
                    window_trades
                )
            )

            if math.isinf(window_pf):
                window_pf_text = "INF"
            else:
                window_pf_text = (
                    f"{window_pf:.2f}"
                )

            lines.append(
                (
                    f"W{number:02d} "
                    f"{window['start_date']} -> "
                    f"{window['end_date']} | "
                    f"${window['starting_equity']:,.2f} -> "
                    f"${window['ending_equity']:,.2f} | "
                    f"RET "
                    f"{window['return'] * 100:.2f}% | "
                    f"DD "
                    f"{window['drawdown'] * 100:.2f}% | "
                    f"TRADES "
                    f"{len(window_trades)} | "
                    f"PF "
                    f"{window_pf_text}"
                )
            )

        lines.append("")

        lines.append(
            "----- AUDITORÍA -----"
        )

        if not result["audit_errors"]:

            lines.append(
                "AUDITORÍA: OK"
            )

        else:

            lines.append(
                "AUDITORÍA: ERROR"
            )

            for error in result[
                "audit_errors"
            ]:

                lines.append(
                    f"  - {error}"
                )

        lines.append("")

        if result[
            "suspicious_windows"
        ]:

            lines.append(
                "VENTANAS EXTRAORDINARIAS:"
            )

            for item in result[
                "suspicious_windows"
            ]:

                lines.append(
                    (
                        f"  W{item['number']:02d} "
                        f"{item['start']} -> "
                        f"{item['end']} | "
                        f"{item['return'] * 100:.2f}%"
                    )
                )

        else:

            lines.append(
                "VENTANAS EXTRAORDINARIAS: NINGUNA"
            )

        lines.append("")

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=============================================="
    )

    print(
        "       AI TRADER — MULTI BACKTEST V7"
    )

    print(
        "=============================================="
    )

    print(
        "AUDITORÍA DE CONTABILIDAD Y RIESGO"
    )

    print(
        "WARMUP: 252 días"
    )

    print(
        "VENTANA OOS: 63 días"
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

    print("")

    all_results = []

    for symbol in SYMBOLS:

        print(
            f"Descargando datos: {symbol}..."
        )

        try:

            bars = get_data(
                symbol,
                5
            )

        except Exception as error:

            print(
                f"{symbol}: ERROR DATOS — {error}"
            )

            continue

        if len(bars) <= (
            WARMUP_DAYS + 20
        ):

            print(
                f"{symbol}: DATOS INSUFICIENTES"
            )

            continue

        print(
            f"{symbol}: "
            f"{len(bars)} velas"
        )

        result = run_backtest(
            symbol,
            bars
        )

        if result is None:

            print(
                f"{symbol}: BACKTEST NO DISPONIBLE"
            )

            continue

        all_results.append(
            result
        )

        print("")

        print(
            f"{symbol} TOTAL "
            f"{result['total_return'] * 100:.2f}% "
            f"| B&H "
            f"{result['buy_hold'] * 100:.2f}% "
            f"| TRADES "
            f"{len(result['trades'])} "
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
            f"AUDITORÍA "
            f"{'OK' if not result['audit_errors'] else 'ERROR'}"
        )

        print(
            f"RIESGO MÁXIMO "
            f"{result['max_risk_pct'] * 100:.4f}%"
        )

        print("")

    # ========================================================
    # GUARDAR
    # ========================================================

    report = generate_report(
        all_results
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(report)

    save_trades(
        all_results
    )

    print(report)

    print(
        "=============================================="
    )

    print(
        f"REPORTE GUARDADO: {OUTPUT_FILE}"
    )

    print(
        f"TRADES GUARDADOS: {TRADE_FILE}"
    )

    print(
        "=============================================="
    )

    print(
        "V7 TERMINADO"
    )


if __name__ == "__main__":
    main()
