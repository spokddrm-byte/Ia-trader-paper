import os
import math
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# AI TRADER — MULTI BACKTEST V5
# ============================================================
#
# SOLO BACKTEST
# NO ENVÍA ÓRDENES
#
# V5 — ROLLING OUT-OF-SAMPLE
#
# - Datos OHLC
# - Ajuste por splits/dividendos
# - Señal al cierre
# - Entrada al OPEN del día siguiente
# - Stop usando LOW real
# - Protección contra GAP
# - Slippage
# - Comisiones
# - Position sizing por riesgo
# - Equity curve
# - Drawdown
# - Profit Factor
# - Win Rate
# - CAGR
# - Sharpe
# - Buy & Hold
# - Rolling Out-of-Sample
# - Resultados OOS separados
# - Exportación de resultados
#
# IMPORTANTE:
#
# Esta V5 NO modifica los parámetros de la estrategia
# durante el período de prueba.
#
# Los primeros días sirven como WARMUP.
#
# Después, el rendimiento se mide únicamente sobre
# datos posteriores, siguiendo el tiempo cronológicamente.
#
# NO PAPER ORDERS
# NO LIVE ORDERS
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

RISK_PER_TRADE = 0.01

STOP_PERCENT = 0.03

SLIPPAGE_PERCENT = 0.0005

COMMISSION_PER_SHARE = 0.01


# ============================================================
# WALK-FORWARD
# ============================================================

# Aproximadamente 1 año de calentamiento.
WARMUP_DAYS = 252

# Aproximadamente 3 meses por bloque OOS.
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
# EMA
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


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []

    losses = []

    for i in range(1, len(values)):

        change = (
            values[i] -
            values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    average_gain = (
        sum(gains[:period]) /
        period
    )

    average_loss = (
        sum(losses[:period]) /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        average_gain = (
            (
                average_gain *
                (period - 1)
            )
            + gains[i]
        ) / period

        average_loss = (
            (
                average_loss *
                (period - 1)
            )
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    relative_strength = (
        average_gain /
        average_loss
    )

    return 100 - (
        100 /
        (1 + relative_strength)
    )


# ============================================================
# LIMPIAR DATOS
# ============================================================

def clean_bars(symbol_bars):

    data = []

    for bar in symbol_bars:

        timestamp = bar.timestamp

        open_price = float(
            bar.open
        )

        high = float(
            bar.high
        )

        low = float(
            bar.low
        )

        close = float(
            bar.close
        )

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
# MAX DRAWDOWN
# ============================================================

def calculate_max_drawdown(
    equity_curve
):

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

        drawdown = (
            peak -
            equity
        )

        drawdown_percent = (
            drawdown /
            peak
        ) * 100

        if drawdown > max_drawdown:
            max_drawdown = drawdown

        if (
            drawdown_percent >
            max_drawdown_percent
        ):
            max_drawdown_percent = (
                drawdown_percent
            )

    return (
        max_drawdown,
        max_drawdown_percent
    )


# ============================================================
# SHARPE
# ============================================================

def calculate_sharpe(
    equity_curve
):

    if len(equity_curve) < 2:
        return 0.0

    returns = []

    for i in range(
        1,
        len(equity_curve)
    ):

        previous = (
            equity_curve[i - 1]
        )

        current = (
            equity_curve[i]
        )

        if previous <= 0:
            continue

        daily_return = (
            current -
            previous
        ) / previous

        returns.append(
            daily_return
        )

    if len(returns) < 2:
        return 0.0

    average = (
        sum(returns) /
        len(returns)
    )

    variance = sum(
        (
            value -
            average
        ) ** 2
        for value in returns
    ) / (
        len(returns) - 1
    )

    standard_deviation = math.sqrt(
        variance
    )

    if standard_deviation == 0:
        return 0.0

    return (
        average /
        standard_deviation
    ) * math.sqrt(252)


# ============================================================
# RACHA MÁXIMA DE PÉRDIDAS
# ============================================================

def calculate_max_losing_streak(
    trades
):

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
# BACKTEST V5
# ============================================================

def run_backtest(data):

    if len(data) < 50:
        return None

    dates = [
        item[0]
        for item in data
    ]

    opens = [
        item[1]
        for item in data
    ]

    highs = [
        item[2]
        for item in data
    ]

    lows = [
        item[3]
        for item in data
    ]

    closes = [
        item[4]
