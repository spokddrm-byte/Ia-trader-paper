# ============================================================
# AI TRADER — TRADE MANAGER V1
# ============================================================
#
# OBJETIVO:
#   Administrar posiciones YA ABIERTAS.
#
# ESTE MÓDULO NO ABRE COMPRAS.
#
# FUNCIONES:
#   - Sincronización Alpaca ↔ SQLite
#   - Detección de posiciones desconocidas
#   - Protección de posiciones
#   - Stop original de la estrategia
#   - Trailing dinámico basado en ATR
#   - Protección de ganancias
#   - Salida por deterioro de tendencia
#   - Salida por tiempo
#   - Detección de órdenes protectoras
#   - Cancelación segura antes de salida manual
#   - Salida de emergencia
#   - Paper Trading
#
# ============================================================


import os
import time
import traceback
from datetime import datetime, timezone, timedelta


from alpaca.trading.client import TradingClient

from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopOrderRequest
)

from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    QueryOrderStatus
)

from alpaca.data.historical import (
    StockHistoricalDataClient
)

from alpaca.data.requests import (
    StockBarsRequest
)

from alpaca.data.timeframe import (
    TimeFrame
)

from alpaca.data.enums import (
    DataFeed
)


from indicators import (
    sma,
    ema,
    rsi
)

from database import (
    initialize_database,
    get_open_position_event,
    log_event,
    close_position_event
)


# ============================================================
# CONFIGURACIÓN
# ============================================================


API_KEY = os.getenv(
    "APCA_API_KEY_ID"
)

API_SECRET = os.getenv(
    "APCA_API_SECRET_KEY"
)

PAPER_TRADING = True


# ============================================================
# DATOS
# ============================================================


DATA_FEED = DataFeed.IEX

LOOKBACK_DAYS = 120

MIN_BARS = 40


# ============================================================
# ATR
# ============================================================


ATR_PERIOD = 14

ATR_TRAILING_MULTIPLIER = 2.2


# ============================================================
# TRAILING STOP
# ============================================================


# El trailing no se activa inmediatamente.
#
# Primero queremos que la operación tenga algo de aire.


TRAILING_ACTIVATION_PERCENT = 0.015
# +1.5%


TRAILING_MIN_PROFIT_PERCENT = 0.003
# Una vez activado intentamos conservar
# al menos +0.3% sobre la entrada.


TRAILING_MAX_DISTANCE_PERCENT = 0.08
# Nunca permitimos un trailing absurdo >8%.


# ============================================================
# PROTECCIÓN DE GANANCIAS
# ============================================================


PROFIT_PROTECTION_TRIGGER = 0.025
# +2.5%


PROFIT_PROTECTION_PERCENT = 0.008
# Protege aproximadamente +0.8%.


# ============================================================
# SALIDA POR DETERIORO
# ============================================================


EXIT_RSI_LEVEL = 42

EXIT_BELOW_EMA = True

EXIT_BELOW_SMA = False


# ============================================================
# SALIDA POR TIEMPO
# ============================================================


MAX_HOLDING_DAYS = 15


# ============================================================
# PÉRDIDA DE EMERGENCIA
# ============================================================


EMERGENCY_LOSS_PERCENT = 0.10


# ============================================================
# SPREAD DE SEGURIDAD
# ============================================================


MIN_EXIT_DISTANCE_PERCENT = 0.002
# 0.2%


# ============================================================
# FUNCIONES BÁSICAS
# ============================================================


def safe_float(
    value,
    default=0.0
):

    try:

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


def safe_int(
    value,
    default=0
):

    try:

        return int(
            float(value)
        )

    except (
        TypeError,
        ValueError
    ):

        return default


def utc_now():

    return datetime.now(
        timezone.utc
    )


# ============================================================
# CLIENTES
# ============================================================


def create_clients():

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID "
            "O APCA_API_SECRET_KEY"
        )

    trading_client = TradingClient(
        API_KEY,
        API_SECRET,
        paper=PAPER_TRADING
    )

    data_client = StockHistoricalDataClient(
        API_KEY,
        API_SECRET
    )

    return (
        trading_client,
        data_client
    )


# ============================================================
# POSICIONES
# ============================================================


def get_positions(
    trading_client
):

    positions = (
        trading_client
        .get_all_positions()
    )

    result = {}

    for position in positions:

        symbol = str(
            position.symbol
        ).upper()

        result[symbol] = {
            "symbol": symbol,

            "qty": safe_float(
                position.qty
            ),

            "avg_entry_price": safe_float(
                position.avg_entry_price
            ),

            "current_price": safe_float(
                position.current_price
            ),

            "market_value": safe_float(
                position.market_value
            ),

            "unrealized_pl": safe_float(
                position.unrealized_pl
            ),

            "unrealized_plpc": safe_float(
                position.unrealized_plpc
            )
        }

    return result


# ============================================================
# ÓRDENES ABIERTAS
# ============================================================


def get_open_orders(
    trading_client
):

    request = GetOrdersRequest(
        status=QueryOrderStatus.OPEN,
        limit=500,
        nested=True
    )

    orders = trading_client.get_orders(
        filter=request
    )

    result = {}

    for order in orders:

        symbol = str(
            order.symbol
        ).upper()

        result.setdefault(
            symbol,
            []
        )

        result[symbol].append(
            order
        )

    return result


# ============================================================
# DATOS DEL ACTIVO
# ============================================================


def get_daily_bars(
    data_client,
    symbol
):

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        limit=LOOKBACK_DAYS,
        feed=DATA_FEED
    )

    response = (
        data_client
        .get_stock_bars(request)
    )

    try:

        return list(
            response[symbol]
        )

    except Exception:

        return []


# ============================================================
# ATR
# ============================================================


def calculate_atr(
    bars,
    period=ATR_PERIOD
):

    if len(bars) < period + 1:

        return None

    true_ranges = []

    for index in range(
        1,
        len(bars)
    ):

        current = bars[index]

        previous = bars[
            index - 1
        ]

        high = safe_float(
            current.high
        )

        low = safe_float(
            current.low
        )

        previous_close = safe_float(
            previous.close
        )

        if (
            high <= 0
            or low <= 0
            or previous_close <= 0
        ):

            continue

        true_range = max(
            high - low,

            abs(
                high
                - previous_close
            ),

            abs(
                low
                - previous_close
            )
        )

        true_ranges.append(
            true_range
        )

    if len(true_ranges) < period:

        return None

    return (
        sum(
            true_ranges[-period:]
        )
        / period
    )


# ============================================================
# INDICADORES
# ============================================================


def calculate_indicators(
    bars
):

    if len(bars) < MIN_BARS:

        return None

    closes = [
        safe_float(
            bar.close
        )
        for bar in bars
    ]

    if len(closes) < MIN_BARS:

        return None

    current_price = closes[-1]

    sma20 = sma(
        closes,
        20
    )

    ema20 = ema(
        closes,
        20
    )

    rsi14 = rsi(
        closes,
        14
    )

    atr14 = calculate_atr(
        bars,
        ATR_PERIOD
    )

    if (
        sma20 is None
        or ema20 is None
        or rsi14 is None
        or atr14 is None
    ):

        return None

    return {
        "price": current_price,
        "sma20": sma20,
        "ema20": ema20,
        "rsi14": rsi14,
        "atr": atr14
    }


# ============================================================
# PROFIT %
# ============================================================


def calculate_profit_percent(
    entry_price,
    current_price
):

    if entry_price <= 0:

        return 0.0

    return (
        current_price
        / entry_price
        - 1
    )


# ============================================================
# TRAILING STOP
# ============================================================


def calculate_trailing_stop(
    entry_price,
    current_price,
    atr
):

    if (
        entry_price <= 0
        or current_price <= 0
        or atr is None
        or atr <= 0
    ):

        return None

    profit_percent = (
        calculate_profit_percent(
            entry_price,
            current_price
        )
    )

    # --------------------------------------------------------
    # Todavía no ganó suficiente.
    # --------------------------------------------------------

    if (
        profit_percent
        < TRAILING_ACTIVATION_PERCENT
    ):

        return None

    # --------------------------------------------------------
    # ATR trailing.
    # --------------------------------------------------------

    atr_stop = (
        current_price
        - (
            atr
            * ATR_TRAILING_MULTIPLIER
        )
    )

    # --------------------------------------------------------
    # Protección mínima de ganancias.
    # --------------------------------------------------------

    profit_floor = (
        entry_price
        * (
            1
            + TRAILING_MIN_PROFIT_PERCENT
        )
    )

    trailing_stop = max(
        atr_stop,
        profit_floor
    )

    # --------------------------------------------------------
    # Nunca dejamos que la distancia sea absurda.
    # --------------------------------------------------------

    minimum_allowed = (
        current_price
        * (
            1
            - TRAILING_MAX_DISTANCE_PERCENT
        )
    )

    trailing_stop = max(
        trailing_stop,
        minimum_allowed
    )

    return trailing_stop


# ============================================================
# PROTECCIÓN DE GANANCIA
# ============================================================


def calculate_profit_protection(
    entry_price,
    current_price
):

    if (
        entry_price <= 0
        or current_price <= 0
    ):

        return None

    profit_percent = (
        calculate_profit_percent(
            entry_price,
            current_price
        )
    )

    if (
        profit_percent
        < PROFIT_PROTECTION_TRIGGER
    ):

        return None

    protected_price = (
        entry_price
        * (
            1
            + PROFIT_PROTECTION_PERCENT
        )
    )

    return protected_price


# ============================================================
# OBTENER STOP ORIGINAL
# ============================================================


def get_original_stop(
    symbol,
    db_event
):

    if not db_event:

        return None

    stop = safe_float(
        db_event.get(
            "stop_price",
            0
        )
    )

    if stop <= 0:

        return None

    return stop


# ============================================================
# FECHA DEL EVENTO
# ============================================================


def parse_event_timestamp(
    db_event
):

    if not db_event:

        return None

    timestamp = db_event.get(
        "timestamp"
    )

    if not timestamp:

        return None

    try:

        parsed = datetime.fromisoformat(
            timestamp
        )

        if parsed.tzinfo is None:

            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    except Exception:

        return None


# ============================================================
# DÍAS EN POSICIÓN
# ============================================================


def calculate_holding_days(
    db_event
):

    timestamp = (
        parse_event_timestamp(
            db_event
        )
    )

    if timestamp is None:

        return None

    difference = (
        utc_now()
        - timestamp
    )

    return (
        difference.total_seconds()
        / 86400.0
    )


# ============================================================
# DETECTAR STOP EXISTENTE
# ============================================================


def find_protective_orders(
    symbol,
    orders
):

    protective = []

    for order in orders:

        order_symbol = str(
            getattr(
                order,
                "symbol",
                ""
            )
        ).upper()

        if order_symbol != symbol:

            continue

        side = str(
            getattr(
                order,
                "side",
                ""
            )
        ).lower()

        order_type = str(
            getattr(
                order,
                "type",
                ""
            )
        ).lower()

        if (
            side == "sell"
            and (
                "stop" in order_type
                or "trailing" in order_type
            )
        ):

            protective.append(
                order
            )

    return protective


# ============================================================
# CANCELAR ÓRDENES DE UN SÍMBOLO
# ============================================================


def cancel_symbol_orders(
    trading_client,
    symbol,
    orders
):

    cancelled = 0

    for order in orders:

        order_symbol = str(
            getattr(
                order,
                "symbol",
                ""
            )
        ).upper()

        if order_symbol != symbol:

            continue

        order_id = getattr(
            order,
            "id",
            None
        )

        if not order_id:

            continue

        try:

            trading_client.cancel_order_by_id(
                order_id
            )

            cancelled += 1

            print(
                f"[{symbol}] "
                f"Orden cancelada: "
                f"{order_id}"
            )

        except Exception as error:

            print(
                f"[{symbol}] "
                f"No se pudo cancelar "
                f"{order_id}: {error}"
            )

    return cancelled
