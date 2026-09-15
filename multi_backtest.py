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
            (average_loss * (
