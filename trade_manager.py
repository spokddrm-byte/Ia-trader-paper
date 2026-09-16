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


# ============================================================
# SALIDA DE MERCADO
# ============================================================


def submit_exit_order(
    trading_client,
    symbol,
    quantity,
    reason
):

    quantity = safe_int(
        quantity
    )

    if quantity <= 0:

        return None

    print()
    print(
        "================================================"
    )

    print(
        f"[{symbol}] SALIDA AUTORIZADA"
    )

    print(
        f"Razón: {reason}"
    )

    print(
        f"Cantidad: {quantity}"
    )

    print(
        "================================================"
    )

    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY
    )

    order = (
        trading_client
        .submit_order(
            order_data=order_request
        )
    )

    return order


# ============================================================
# EVALUAR POSICIÓN
# ============================================================


def evaluate_position(
    symbol,
    position,
    db_event,
    indicators,
    protective_orders
):

    current_price = safe_float(
        position["current_price"]
    )

    entry_price = safe_float(
        position["avg_entry_price"]
    )

    quantity = safe_float(
        position["qty"]
    )

    if (
        current_price <= 0
        or entry_price <= 0
        or quantity <= 0
    ):

        return {
            "action": "HOLD",
            "reason": "DATOS DE POSICIÓN INVÁLIDOS"
        }

    profit_percent = (
        calculate_profit_percent(
            entry_price,
            current_price
        )
    )

    original_stop = get_original_stop(
        symbol,
        db_event
    )

    atr = indicators["atr"]

    trailing_stop = (
        calculate_trailing_stop(
            entry_price,
            current_price,
            atr
        )
    )

    profit_protection = (
        calculate_profit_protection(
            entry_price,
            current_price
        )
    )

    # ========================================================
    # 1. STOP ORIGINAL
    # ========================================================

    if (
        original_stop is not None
        and current_price <= original_stop
    ):

        return {
            "action": "EXIT",
            "reason": (
                "PRECIO POR DEBAJO "
                "DEL STOP ORIGINAL"
            ),
            "priority": 100
        }

    # ========================================================
    # 2. PÉRDIDA EXTREMA
    # ========================================================

    if (
        profit_percent
        <= -EMERGENCY_LOSS_PERCENT
    ):

        return {
            "action": "EXIT",
            "reason": (
                "PÉRDIDA DE EMERGENCIA "
                f"{profit_percent * 100:.2f}%"
            ),
            "priority": 99
        }

    # ========================================================
    # 3. TRAILING STOP
    # ========================================================

    if (
        trailing_stop is not None
        and current_price <= trailing_stop
    ):

        return {
            "action": "EXIT",
            "reason": (
                "TRAILING STOP ACTIVADO | "
                f"Stop ${trailing_stop:.2f}"
            ),
            "priority": 90
        }

    # ========================================================
    # 4. PROTECCIÓN DE GANANCIA
    # ========================================================

    if (
        profit_protection is not None
        and current_price
        <= profit_protection
    ):

        return {
            "action": "EXIT",
            "reason": (
                "PROTECCIÓN DE GANANCIA | "
                f"Precio protegido "
                f"${profit_protection:.2f}"
            ),
            "priority": 85
        }

    # ========================================================
    # 5. DETERIORO DE TENDENCIA
    # ========================================================

    price = indicators["price"]
    ema20 = indicators["ema20"]
    sma20 = indicators["sma20"]
    rsi14 = indicators["rsi14"]

    if (
        EXIT_BELOW_EMA
        and price < ema20
        and rsi14 < EXIT_RSI_LEVEL
    ):

        return {
            "action": "EXIT",
            "reason": (
                "DETERIORO DE TENDENCIA | "
                f"Precio < EMA20 | "
                f"RSI {rsi14:.1f}"
            ),
            "priority": 70
        }

    if (
        EXIT_BELOW_SMA
        and price < sma20
        and rsi14 < EXIT_RSI_LEVEL
    ):

        return {
            "action": "EXIT",
            "reason": (
                "PÉRDIDA DE SMA20 + "
                "MOMENTUM DÉBIL"
            ),
            "priority": 65
        }

    # ========================================================
    # 6. TIEMPO
    # ========================================================

    holding_days = (
        calculate_holding_days(
            db_event
        )
    )

    if (
        holding_days is not None
        and holding_days >= MAX_HOLDING_DAYS
        and profit_percent < 0.01
    ):

        return {
            "action": "EXIT",
            "reason": (
                "SALIDA POR TIEMPO | "
                f"{holding_days:.1f} días "
                "sin suficiente progreso"
            ),
            "priority": 50
        }

    # ========================================================
    # HOLD
    # ========================================================

    return {
        "action": "HOLD",
        "reason": (
            "POSICIÓN SANA | "
            f"P/L {profit_percent * 100:.2f}%"
        ),
        "priority": 0,

        "profit_percent": profit_percent,

        "original_stop": original_stop,

        "trailing_stop": trailing_stop,

        "profit_protection": (
            profit_protection
        ),

        "protective_orders": len(
            protective_orders
        )
    }


# ============================================================
# PROTEGER POSICIÓN
# ============================================================


def ensure_protection(
    trading_client,
    symbol,
    position,
    db_event,
    protective_orders
):

    if protective_orders:

        return True

    original_stop = get_original_stop(
        symbol,
        db_event
    )

    if original_stop is None:

        print(
            f"[{symbol}] "
            "⚠️ POSICIÓN SIN STOP CONOCIDO"
        )

        return False

    current_price = safe_float(
        position["current_price"]
    )

    if (
        current_price <= 0
        or original_stop >= current_price
    ):

        print(
            f"[{symbol}] "
            "⚠️ STOP INVALIDADO"
        )

        return False

    quantity = safe_int(
        position["qty"]
    )

    if quantity <= 0:

        return False

    try:

        request = StopOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=round(
                original_stop,
                2
            )
        )

        order = (
            trading_client
            .submit_order(
                order_data=request
            )
        )

        print(
            f"[{symbol}] "
            f"🛡️ STOP RESTAURADO "
            f"${original_stop:.2f}"
        )

        return True

    except Exception as error:

        print(
            f"[{symbol}] "
            f"❌ ERROR RESTAURANDO STOP: "
            f"{error}"
        )

        return False


# ============================================================
# REGISTRAR SALIDA
# ============================================================


def register_exit(
    symbol,
    position,
    reason,
    order
):

    try:

        order_id = getattr(
            order,
            "id",
            None
        )

        log_event(
            symbol=symbol,
            signal="VENDER",
            entry_price=position[
                "avg_entry_price"
            ],
            stop_price=0.0,
            position_size=safe_int(
                position["qty"]
            ),
            status="EXIT_SUBMITTED",
            profit_loss=position[
                "unrealized_pl"
            ],
            order_id=order_id
        )

    except Exception as error:

        print(
            f"[{symbol}] "
            f"Error registrando salida: "
            f"{error}"
        )


# ============================================================
# POSICIÓN HUÉRFANA
# ============================================================


def handle_unknown_position(
    symbol,
    position
):

    print()
    print(
        "⚠️ ================================================"
    )

    print(
        f"POSICIÓN NO RECONOCIDA: {symbol}"
    )

    print(
        f"Cantidad: {position['qty']}"
    )

    print(
        f"Entrada: "
        f"${position['avg_entry_price']:.2f}"
    )

    print(
        "El bot NO la cerrará automáticamente."
    )

    print(
        "Se requiere reconciliación."
    )

    print(
        "⚠️ ================================================"
    )

    try:

        log_event(
            symbol=symbol,
            signal="DESCONOCIDO",
            entry_price=position[
                "avg_entry_price"
            ],
            stop_price=0.0,
            position_size=safe_int(
                position["qty"]
            ),
            status="UNKNOWN_POSITION",
            profit_loss=position[
                "unrealized_pl"
            ]
        )

    except Exception:

        pass


# ============================================================
# PROCESAR POSICIÓN
# ============================================================


def process_position(
    trading_client,
    data_client,
    symbol,
    position,
    open_orders
):

    print()
    print(
        "------------------------------------------------"
    )

    print(
        f"🔎 ADMINISTRANDO {symbol}"
    )

    print(
        f"Cantidad: "
        f"{position['qty']}"
    )

    print(
        f"Entrada: "
        f"${position['avg_entry_price']:.2f}"
    )

    print(
        f"Actual: "
        f"${position['current_price']:.2f}"
    )

    print(
        f"P/L: "
        f"${position['unrealized_pl']:.2f}"
    )

    print(
        "------------------------------------------------"
    )

    # --------------------------------------------------------
    # DB
    # --------------------------------------------------------

    db_event = None

    try:

        db_event = (
            get_open_position_event(
                symbol
            )
        )

    except Exception as error:

        print(
            f"[{symbol}] "
            f"Error leyendo DB: {error}"
        )

    if db_event is None:

        handle_unknown_position(
            symbol,
            position
        )

        return "UNKNOWN"

    # --------------------------------------------------------
    # DATOS
    # --------------------------------------------------------

    try:

        bars = get_daily_bars(
            data_client,
            symbol
        )

    except Exception as error:

        print(
            f"[{symbol}] "
            f"Error descargando datos: "
            f"{error}"
        )

        return "DATA_ERROR"

    if len(bars) < MIN_BARS:

        print(
            f"[{symbol}] "
            "Datos insuficientes. "
            "NO SE TOCA LA POSICIÓN."
        )

        return "DATA_ERROR"

    indicators = (
        calculate_indicators(
            bars
        )
    )

    if indicators is None:

        print(
            f"[{symbol}] "
            "Indicadores inválidos."
        )

        return "DATA_ERROR"

    print(
        f"EMA20: "
        f"${indicators['ema20']:.2f}"
    )

    print(
        f"SMA20: "
        f"${indicators['sma20']:.2f}"
    )

    print(
        f"RSI: "
        f"{indicators['rsi14']:.2f}"
    )

    print(
        f"ATR: "
        f"${indicators['atr']:.2f}"
    )

    # --------------------------------------------------------
    # ÓRDENES PROTECTORAS
    # --------------------------------------------------------

    symbol_orders = open_orders.get(
        symbol,
        []
    )

    protective_orders = (
        find_protective_orders(
            symbol,
            symbol_orders
        )
    )

    print(
        f"Órdenes protectoras: "
        f"{len(protective_orders)}"
    )

    # --------------------------------------------------------
    # EVALUACIÓN
    # --------------------------------------------------------

    decision = evaluate_position(
        symbol=symbol,
        position=position,
        db_event=db_event,
        indicators=indicators,
        protective_orders=protective_orders
    )

    action = decision["action"]

    print(
        f"DECISIÓN: {action}"
    )

    print(
        f"MOTIVO: "
        f"{decision['reason']}"
    )

    # --------------------------------------------------------
    # SALIDA
    # --------------------------------------------------------

    if action == "EXIT":

        print()
        print(
            f"🚨 {symbol}: "
            f"SE REQUIERE SALIDA"
        )

        # ----------------------------------------------
        # CANCELAR PROTECCIONES
        # ----------------------------------------------

        if symbol_orders:

            cancel_symbol_orders(
                trading_client,
                symbol,
                symbol_orders
            )

            # Pequeña pausa para permitir
            # que Alpaca procese cancelaciones.

            time.sleep(
                0.50
            )

        # ----------------------------------------------
        # REVALIDAR POSICIÓN
        # ----------------------------------------------

        try:

            fresh_positions = get_positions(
                trading_client
            )

        except Exception as error:

            print(
                f"[{symbol}] "
                f"No se pudo revalidar posición: "
                f"{error}"
            )

            return "EXIT_ABORTED"

        if symbol not in fresh_positions:

            print(
                f"[{symbol}] "
                "La posición ya no existe."
            )

            return "ALREADY_CLOSED"

        fresh_position = (
            fresh_positions[symbol]
        )

        quantity = safe_int(
            fresh_position["qty"]
        )

        if quantity <= 0:

            return "ALREADY_CLOSED"

        # ----------------------------------------------
        # SALIDA
        # ----------------------------------------------

        try:

            order = submit_exit_order(
                trading_client,
                symbol,
                quantity,
                decision["reason"]
            )

        except Exception as error:

            print(
                f"[{symbol}] "
                f"❌ ERROR EN SALIDA: "
                f"{error}"
            )

            return "EXIT_ERROR"

        register_exit(
            symbol,
            fresh_position,
            decision["reason"],
            order
        )

        print(
            f"[{symbol}] "
            "✅ ORDEN DE SALIDA ENVIADA"
        )

        return "EXIT_SUBMITTED"

    # --------------------------------------------------------
    # POSICIÓN NORMAL
    # --------------------------------------------------------

    if not protective_orders:

        print(
            f"[{symbol}] "
            "🛡️ No hay stop visible. "
            "Intentando restaurarlo..."
        )

        ensure_protection(
            trading_client,
            symbol,
            position,
            db_event,
            protective_orders
        )

    else:

        print(
            f"[{symbol}] "
            "🛡️ Protección presente."
        )

    # --------------------------------------------------------
    # INFORMACIÓN DEL TRAILING
    # --------------------------------------------------------

    trailing_stop = decision.get(
        "trailing_stop"
    )

    if trailing_stop is not None:

        print(
            f"[{symbol}] "
            f"Trailing dinámico calculado: "
            f"${trailing_stop:.2f}"
        )

    profit_protection = (
        decision.get(
            "profit_protection"
        )
    )

    if profit_protection is not None:

        print(
            f"[{symbol}] "
            f"Protección de ganancia: "
            f"${profit_protection:.2f}"
        )

    print(
        f"[{symbol}] "
        "🟢 POSICIÓN MANTENIDA"
    )

    return "HOLD"


# ============================================================
# SINCRONIZACIÓN GLOBAL
# ============================================================


def synchronize(
    trading_client
):

    positions = get_positions(
        trading_client
    )

    orders = get_open_orders(
        trading_client
    )

    return (
        positions,
        orders
    )


# ============================================================
# MAIN
# ============================================================


def main():

    print()
    print("=" * 72)
    print(
        "          AI TRADER — TRADE MANAGER V1"
    )
    print("=" * 72)
    print()

    initialize_database()

    # --------------------------------------------------------
    # CLIENTES
    # --------------------------------------------------------

    try:

        trading_client, data_client = (
            create_clients()
        )

    except Exception as error:

        print(
            f"❌ ERROR CREANDO CLIENTES: "
            f"{error}"
        )

        return

    # --------------------------------------------------------
    # RELOJ
    # --------------------------------------------------------

    try:

        clock = (
            trading_client
            .get_clock()
        )

    except Exception as error:

        print(
            f"❌ ERROR OBTENIENDO RELOJ: "
            f"{error}"
        )

        return

    if not clock.is_open:

        print(
            "⏸️ MERCADO CERRADO."
        )

        print(
            "Trade Manager no ejecutará salidas "
            "normales fuera del horario."
        )

        return

    print(
        "🟢 MERCADO ABIERTO"
    )

    print()

    # --------------------------------------------------------
    # SINCRONIZACIÓN
    # --------------------------------------------------------

    try:

        positions, open_orders = (
            synchronize(
                trading_client
            )
        )

    except Exception as error:

        print(
            f"❌ ERROR DE SINCRONIZACIÓN: "
            f"{error}"
        )

        return

    print(
        f"Posiciones encontradas: "
        f"{len(positions)}"
    )

    print(
        f"Símbolos con órdenes: "
        f"{len(open_orders)}"
    )

    print()

    if not positions:

        print(
            "No hay posiciones que administrar."
        )

        return

    # --------------------------------------------------------
    # PROCESAR
    # --------------------------------------------------------

    results = {}

    for symbol, position in positions.items():

        try:

            result = process_position(
                trading_client=trading_client,
                data_client=data_client,
                symbol=symbol,
                position=position,
                open_orders=open_orders
            )

            results[symbol] = result

        except Exception as error:

            results[symbol] = (
                "ERROR"
            )

            print()
            print(
                f"❌ ERROR PROCESANDO {symbol}: "
                f"{error}"
            )

            traceback.print_exc()

        print()

    # --------------------------------------------------------
    # RESUMEN
    # --------------------------------------------------------

    print()
    print("=" * 72)
    print(
        "              RESUMEN TRADE MANAGER"
    )
    print("=" * 72)

    for symbol, result in results.items():

        print(
            f"{symbol:<8} -> {result}"
        )

    print()
    print("=" * 72)
    print(
        "        TRADE MANAGER V1 — CICLO TERMINADO"
    )
    print("=" * 72)
    print()


# ============================================================
# EJECUCIÓN
# ============================================================


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "Ejecución detenida manualmente."
        )

    except Exception as error:

        print()
        print(
            "🚨 KILL SWITCH — ERROR NO CONTROLADO"
        )

        print(
            str(error)
        )

        traceback.print_exc()

        print()
        print(
            "NO SE INTENTARÁN MÁS OPERACIONES."
        )
