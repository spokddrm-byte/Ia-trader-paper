# ============================================================
# AI TRADER — MAIN V4 PANTERA + AI ENGINE V1
# ============================================================
#
# FLUJO:
#
#   ALPACA
#      ↓
#   MARKET DATA
#      ↓
#   SCANNER 25
#      ↓
#   SIGNAL / SCORE
#      ↓
#   AI ENGINE — MEMORIA
#      ↓
#   PORTFOLIO ANALYZER
#      ↓
#   RISK MANAGER V3
#      ↓
#   ÚLTIMA SINCRONIZACIÓN
#      ↓
#   EXECUTOR
#      ↓
#   DATABASE
#
# IMPORTANTE:
# AI ENGINE V1 NO AUTORIZA NI RECHAZA OPERACIONES.
# SOLAMENTE REGISTRA LA EXPERIENCIA DE LAS SEÑALES.
#
# ============================================================

import os
import math
import time
import traceback
import inspect
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
    QueryOrderStatus
)

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from indicators import sma, ema, rsi

from risk_manager import (
    risk_check,
    calculate_position_size,
    calculate_position_value,
    calculate_trade_risk,
    calculate_trade_risk_percent,
    calculate_portfolio_risk,
    calculate_total_exposure,
    symbol_exposure_check,
    MAX_OPEN_POSITIONS,
    MAX_TOTAL_EXPOSURE,
    MAX_PORTFOLIO_RISK,
    MAX_RISK_PER_TRADE,
    MAX_DAILY_LOSS
)

from portfolio_analyzer import (
    PortfolioAnalyzer,
    PositionSnapshot
)

from database import (
    initialize_database,
    log_event,
    get_today_trade_count,
    get_today_loss,
    get_today_profit_loss,
    get_open_position_event
)

# ============================================================
# AI ENGINE
# ============================================================

from ai_engine import (
    initialize_ai_engine,
    record_ai_signal
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")

PAPER_TRADING = True

SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "NFLX",
    "JPM",
    "V",
    "MA",
    "COST",
    "WMT",
    "HD",
    "ORCL",
    "CRM",
    "ADBE",
    "INTC",
    "QCOM",
    "MU",
    "AMAT",
    "SPY",
    "QQQ"
]

BENCHMARK = "SPY"

LOOKBACK_DAYS = 180
MIN_BARS = 60

DATA_FEED = DataFeed.IEX

MAX_NEW_POSITIONS_PER_CYCLE = 2
MIN_SCORE_TO_TRADE = 70

MIN_PRICE = 5.0
MIN_AVG_VOLUME = 500_000

SMA_FAST = 20
EMA_FAST = 20
RSI_PERIOD = 14
ATR_PERIOD = 14

RELATIVE_STRENGTH_PERIOD = 20
VOLUME_PERIOD = 20

ATR_STOP_MULTIPLIER = 2.0

MIN_STOP_PERCENT = 0.005
MAX_STOP_PERCENT = 0.10

MIN_RSI = 45
MAX_RSI = 68

REQUEST_DELAY = 0.15


# ============================================================
# OUTPUT
# ============================================================

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"


# ============================================================
# UTILIDADES
# ============================================================

def safe_float(value, default=0.0):

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clamp(value, minimum, maximum):

    return max(
        minimum,
        min(maximum, value)
    )


def now_utc():

    return datetime.now(timezone.utc)


def print_header():

    print()
    print("=" * 72)
    print("        AI TRADER — V4 PANTERA + AI ENGINE V1")
    print("=" * 72)
    print()


# ============================================================
# CLIENTES
# ============================================================

def create_clients():

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY"
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

    return trading_client, data_client


# ============================================================
# CUENTA
# ============================================================

def get_account_snapshot(trading_client):

    account = trading_client.get_account()

    return {
        "equity": safe_float(account.equity),
        "buying_power": safe_float(account.buying_power),
        "cash": safe_float(account.cash),
        "status": str(account.status)
    }


# ============================================================
# MERCADO
# ============================================================

def check_market(trading_client):

    clock = trading_client.get_clock()

    return bool(clock.is_open), clock


# ============================================================
# POSICIONES
# ============================================================

def get_positions(trading_client):

    positions = trading_client.get_all_positions()

    result = {}

    for position in positions:

        symbol = str(
            position.symbol
        ).upper()

        result[symbol] = {
            "symbol": symbol,
            "qty": safe_float(position.qty),
            "market_value": safe_float(
                position.market_value
            ),
            "avg_entry_price": safe_float(
                position.avg_entry_price
            ),
            "current_price": safe_float(
                position.current_price
            ),
            "unrealized_pl": safe_float(
                position.unrealized_pl
            )
        }

    return result


# ============================================================
# ÓRDENES
# ============================================================

def get_open_orders(trading_client):

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

        result[symbol].append(order)

    return result


# ============================================================
# BLOQUEO DE SÍMBOLO
# ============================================================

def symbol_is_locked(
    symbol,
    positions,
    open_orders
):

    return (
        symbol in positions
        or symbol in open_orders
    )


# ============================================================
# BARRAS
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

    response = data_client.get_stock_bars(
        request
    )

    try:
        bars = response[symbol]
    except Exception:
        return []

    return list(bars)


# ============================================================
# RETORNOS DIARIOS
# ============================================================

def calculate_returns(bars):

    if len(bars) < 2:
        return []

    returns = []

    for index in range(1, len(bars)):

        previous = safe_float(
            bars[index - 1].close
        )

        current = safe_float(
            bars[index].close
        )

        if previous <= 0 or current <= 0:
            continue

        returns.append(
            (current / previous) - 1.0
        )

    return returns


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    bars,
    period=14
):

    if len(bars) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(bars)):

        current = bars[i]
        previous = bars[i - 1]

        high = safe_float(current.high)
        low = safe_float(current.low)
        previous_close = safe_float(
            previous.close
        )

        if high <= 0 or low <= 0:
            continue

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        true_ranges.append(
            true_range
        )

    if len(true_ranges) < period:
        return None

    return (
        sum(true_ranges[-period:])
        / period
    )


# ============================================================
# ATR %
# ============================================================

def calculate_atr_percent(
    price,
    atr_value
):

    if price <= 0 or atr_value is None:
        return 0.0

    return atr_value / price


# ============================================================
# VOLUMEN
# ============================================================

def calculate_average_volume(
    bars,
    period=20
):

    if len(bars) < period:
        return None

    volumes = [
        safe_float(bar.volume)
        for bar in bars[-period:]
    ]

    if not volumes:
        return None

    return sum(volumes) / len(volumes)


# ============================================================
# FUERZA RELATIVA
# ============================================================

def calculate_relative_strength(
    symbol_bars,
    benchmark_bars,
    period=20
):

    if (
        len(symbol_bars) < period + 1
        or len(benchmark_bars) < period + 1
    ):
        return None

    symbol_start = safe_float(
        symbol_bars[-period - 1].close
    )

    symbol_end = safe_float(
        symbol_bars[-1].close
    )

    benchmark_start = safe_float(
        benchmark_bars[-period - 1].close
    )

    benchmark_end = safe_float(
        benchmark_bars[-1].close
    )

    if (
        symbol_start <= 0
        or benchmark_start <= 0
    ):
        return None

    symbol_return = (
        symbol_end / symbol_start
        - 1
    )

    benchmark_return = (
        benchmark_end / benchmark_start
        - 1
    )

    return (
        symbol_return
        - benchmark_return
    )


# ============================================================
# SCORE TENDENCIA
# ============================================================

def score_trend(
    price,
    sma_value,
    ema_value
):

    score = 0

    if sma_value is not None:
        if price > sma_value:
            score += 10

    if ema_value is not None:
        if price > ema_value:
            score += 10

    if (
        ema_value is not None
        and sma_value is not None
        and ema_value > sma_value
    ):
        score += 10

    return score


# ============================================================
# SCORE RSI
# ============================================================

def score_rsi(rsi_value):

    if rsi_value is None:
        return 0

    if 50 <= rsi_value <= 62:
        return 15

    if 45 <= rsi_value < 50:
        return 10

    if 62 < rsi_value <= 68:
        return 8

    if 40 <= rsi_value < 45:
        return 4

    return 0


# ============================================================
# SCORE MOMENTUM
# ============================================================

def score_momentum(bars):

    if len(bars) < 21:
        return 0

    current = safe_float(
        bars[-1].close
    )

    previous = safe_float(
        bars[-21].close
    )

    if previous <= 0:
        return 0

    return_pct = (
        current / previous
        - 1
    )

    if return_pct >= 0.10:
        return 15

    if return_pct >= 0.05:
        return 12

    if return_pct >= 0.02:
        return 8

    if return_pct > 0:
        return 4

    return 0


# ============================================================
# SCORE VOLUMEN
# ============================================================

def score_volume(bars):

    if len(bars) < VOLUME_PERIOD + 1:
        return 0

    average_volume = calculate_average_volume(
        bars,
        VOLUME_PERIOD
    )

    current_volume = safe_float(
        bars[-1].volume
    )

    if (
        average_volume is None
        or average_volume <= 0
    ):
        return 0

    ratio = (
        current_volume
        / average_volume
    )

    if ratio >= 1.50:
        return 10

    if ratio >= 1.20:
        return 7

    if ratio >= 1.00:
        return 4

    return 0


# ============================================================
# SCORE FUERZA RELATIVA
# ============================================================

def score_relative_strength(
    relative_strength
):

    if relative_strength is None:
        return 0

    if relative_strength >= 0.08:
        return 10

    if relative_strength >= 0.04:
        return 8

    if relative_strength >= 0.01:
        return 5

    if relative_strength > 0:
        return 2

    return 0


# ============================================================
# SCORE VOLATILIDAD
# ============================================================

def score_volatility(
    atr_percent
):

    if atr_percent <= 0:
        return 0

    if 0.015 <= atr_percent <= 0.045:
        return 10

    if 0.01 <= atr_percent < 0.015:
        return 6

    if 0.045 < atr_percent <= 0.07:
        return 5

    return 0


# ============================================================
# ANALIZAR ACTIVO
# ============================================================

def analyze_symbol(
    symbol,
    bars,
    benchmark_bars
):

    if len(bars) < MIN_BARS:
        return None

    closes = [
        safe_float(bar.close)
        for bar in bars
    ]

    if not closes:
        return None

    price = closes[-1]

    if price < MIN_PRICE:
        return None

    sma_value = sma(
        closes,
        SMA_FAST
    )

    ema_value = ema(
        closes,
        EMA_FAST
    )

    rsi_value = rsi(
        closes,
        RSI_PERIOD
    )

    atr_value = calculate_atr(
        bars,
        ATR_PERIOD
    )

    average_volume = calculate_average_volume(
        bars,
        VOLUME_PERIOD
    )

    current_volume = safe_float(
        bars[-1].volume
    )

    relative_strength = calculate_relative_strength(
        bars,
        benchmark_bars,
        RELATIVE_STRENGTH_PERIOD
    )

    atr_percent = calculate_atr_percent(
        price,
        atr_value
    )

    if (
        sma_value is None
        or ema_value is None
        or rsi_value is None
        or atr_value is None
    ):
        return None

    trend_score = score_trend(
        price,
        sma_value,
        ema_value
    )

    rsi_score = score_rsi(
        rsi_value
    )

    momentum_score = score_momentum(
        bars
    )

    volume_score = score_volume(
        bars
    )

    relative_score = score_relative_strength(
        relative_strength
    )

    volatility_score = score_volatility(
        atr_percent
    )

    total_score = (
        trend_score
        + rsi_score
        + momentum_score
        + volume_score
        + relative_score
        + volatility_score
    )

    bullish_trend = (
        price > ema_value
        and ema_value > sma_value
    )

    valid_rsi = (
        MIN_RSI
        <= rsi_value
        <= MAX_RSI
    )

    positive_relative_strength = (
        relative_strength is not None
        and relative_strength > 0
    )

    enough_volume = (
        average_volume is not None
        and average_volume >= MIN_AVG_VOLUME
    )

    buy_signal = (
        bullish_trend
        and valid_rsi
        and positive_relative_strength
        and enough_volume
        and total_score >= MIN_SCORE_TO_TRADE
    )

    raw_stop = (
        price
        - (
            atr_value
            * ATR_STOP_MULTIPLIER
        )
    )

    stop_distance = (
        price - raw_stop
    ) / price

    stop_distance = clamp(
        stop_distance,
        MIN_STOP_PERCENT,
        MAX_STOP_PERCENT
    )

    stop_price = (
        price
        * (
            1 - stop_distance
        )
    )

    # --------------------------------------------------------
    # DATOS EXTRA PARA AI ENGINE
    # --------------------------------------------------------

    volume_ratio = 0.0

    if (
        average_volume is not None
        and average_volume > 0
    ):

        volume_ratio = (
            current_volume
            / average_volume
        )

    price_vs_ema_pct = 0.0

    if ema_value > 0:

        price_vs_ema_pct = (
            price / ema_value
            - 1.0
        )

    price_vs_sma_pct = 0.0

    if sma_value > 0:

        price_vs_sma_pct = (
            price / sma_value
            - 1.0
        )

    trend_strength = 0.0

    if sma_value > 0:

        trend_strength = (
            ema_value / sma_value
            - 1.0
        )

    return {
        "symbol": symbol,
        "price": price,
        "sma": sma_value,
        "ema": ema_value,
        "rsi": rsi_value,
        "atr": atr_value,
        "atr_percent": atr_percent,
        "average_volume": average_volume,
        "current_volume": current_volume,
        "volume_ratio": volume_ratio,
        "relative_strength": (
            relative_strength
            if relative_strength is not None
            else 0.0
        ),
        "price_vs_ema_pct": price_vs_ema_pct,
        "price_vs_sma_pct": price_vs_sma_pct,
        "trend_strength": trend_strength,
        "trend_score": trend_score,
        "rsi_score": rsi_score,
        "momentum_score": momentum_score,
        "volume_score": volume_score,
        "relative_score": relative_score,
        "volatility_score": volatility_score,
        "score": total_score,
        "bullish_trend": bullish_trend,
        "valid_rsi": valid_rsi,
        "positive_relative_strength": (
            positive_relative_strength
        ),
        "enough_volume": enough_volume,
        "buy_signal": buy_signal,
        "stop_price": stop_price,
        "stop_distance": stop_distance
    }


# ============================================================
# AI ENGINE — REGISTRAR SEÑAL
# ============================================================

def record_signal_for_ai(analysis):

    """
    Guarda la señal en AI Engine.

    IMPORTANTE:
    Esta función NO modifica buy_signal.
    Tampoco aprueba/rechaza operaciones.

    Solamente construye memoria histórica.
    """

    try:

        experience_id = record_ai_signal(
            symbol=analysis["symbol"],
            score=analysis["score"],
            rsi=analysis["rsi"],
            atr_pct=analysis["atr_percent"],
            volume_ratio=analysis["volume_ratio"],
            relative_strength=analysis["relative_strength"],
            price_vs_ema_pct=analysis["price_vs_ema_pct"],
            price_vs_sma_pct=analysis["price_vs_sma_pct"],
            trend_strength=analysis["trend_strength"],
            metadata={
                "buy_signal": analysis["buy_signal"],
                "trend_score": analysis["trend_score"],
                "rsi_score": analysis["rsi_score"],
                "momentum_score": analysis["momentum_score"],
                "volume_score": analysis["volume_score"],
                "relative_score": analysis["relative_score"],
                "volatility_score": analysis["volatility_score"],
                "stop_distance": analysis["stop_distance"],
                "engine": "V4_PANTERA"
            }
        )

        if experience_id is not None:

            print(
                GREEN
                + f"[AI MEMORY] {analysis['symbol']} "
                  f"registrado — ID {experience_id}"
                + RESET
            )

        else:

            print(
                YELLOW
                + f"[AI MEMORY] {analysis['symbol']} "
                  "no pudo registrarse"
                + RESET
            )

        return experience_id

    except Exception as error:

        print(
            YELLOW
            + f"[AI MEMORY] Error registrando "
              f"{analysis['symbol']}: {error}"
            + RESET
        )

        return None


# ============================================================
# OUTPUT DEL ANALYZER
# ============================================================

def print_analysis(analysis):

    symbol = analysis["symbol"]
    score = analysis["score"]
    price = analysis["price"]
    rsi_value = analysis["rsi"]

    relative = (
        analysis["relative_strength"]
        * 100
    )

    stop_distance = (
        analysis["stop_distance"]
        * 100
    )

    if analysis["buy_signal"]:

        status = (
            GREEN
            + "COMPRABLE"
            + RESET
        )

    else:

        status = (
            YELLOW
            + "ESPERAR"
            + RESET
        )

    print(
        f"{symbol:<6} "
        f"Score {score:>3}/100 | "
        f"${price:>9.2f} | "
        f"RSI {rsi_value:>5.1f} | "
        f"RS {relative:>6.2f}% | "
        f"Stop {stop_distance:>5.2f}% | "
        f"{status}"
    )


# ============================================================
# DB
# ============================================================

def load_db_position_events(positions):

    result = {}

    for symbol in positions:

        try:

            event = get_open_position_event(
                symbol
            )

            if event:
                result[symbol] = event

        except Exception:

            pass

    return result


# ============================================================
# RIESGO ACTUAL
# ============================================================

def calculate_current_portfolio_risk_safe(
    account_value,
    positions,
    db_events
):

    if not positions:
        return 0.0, False

    risk_positions = []
    unknown_stop = False

    for symbol, position in positions.items():

        event = db_events.get(symbol)

        if event is None:

            unknown_stop = True
            continue

        stop_price = safe_float(
            event.get(
                "stop_price",
                0
            )
        )

        if stop_price <= 0:

            unknown_stop = True
            continue

        risk_positions.append({
            "position_size": position["qty"],
            "entry_price": position[
                "avg_entry_price"
            ],
            "stop_price": stop_price
        })

    if unknown_stop:

        return MAX_PORTFOLIO_RISK, True

    risk = calculate_portfolio_risk(
        account_value,
        risk_positions
    )

    return risk, False


# ============================================================
# EXPOSICIÓN ACTUAL
# ============================================================

def calculate_current_exposure(
    account_value,
    positions
):

    if account_value <= 0:
        return 1.0

    total_market_value = 0.0

    for position in positions.values():

        total_market_value += abs(
            safe_float(
                position["market_value"]
            )
        )

    return (
        total_market_value
        / account_value
    )


# ============================================================
# RECHAZO
# ============================================================

def log_rejection(
    symbol,
    analysis,
    reason
):

    try:

        log_event(
            symbol=symbol,
            signal="COMPRAR",
            entry_price=analysis.get(
                "price",
                0
            ),
            stop_price=analysis.get(
                "stop_price",
                0
            ),
            position_size=0,
            status="REJECTED",
            profit_loss=0.0
        )

    except Exception as error:

        print(
            RED
            + f"[DB] Error registrando rechazo: {error}"
            + RESET
        )

    print(
        RED
        + f"[RECHAZADO] {symbol} -> {reason}"
        + RESET
    )


# ============================================================
# CONSTRUIR SNAPSHOT DEL ANALYZER
# ============================================================

def build_analyzer_position(
    symbol,
    position,
    event,
    returns
):

    signature = inspect.signature(
        PositionSnapshot
    )

    fields = signature.parameters

    market_value = abs(
        safe_float(
            position.get(
                "market_value",
                0
            )
        )
    )

    qty = safe_float(
        position.get(
            "qty",
            0
        )
    )

    entry_price = safe_float(
        position.get(
            "avg_entry_price",
            0
        )
    )

    current_price = safe_float(
        position.get(
            "current_price",
            0
        )
    )

    original_stop = 0.0

    if event:

        original_stop = safe_float(
            event.get(
                "stop_price",
                event.get(
                    "original_stop",
                    0
                )
            )
        )

    possible_values = {
        "symbol": symbol,
        "ticker": symbol,
        "position_symbol": symbol,

        "quantity": qty,
        "qty": qty,
        "position_size": qty,

        "entry_price": entry_price,
        "avg_entry_price": entry_price,

        "current_price": current_price,
        "price": current_price,

        "market_value": market_value,
        "position_value": market_value,

        "original_stop": original_stop,
        "stop_price": original_stop,
        "current_stop": original_stop,

        "returns": returns,
        "return_series": returns,
        "daily_returns": returns
    }

    kwargs = {}

    for name in fields:

        parameter = fields[name]

        if name == "self":
            continue

        if name in possible_values:
            kwargs[name] = possible_values[name]

        elif (
            parameter.default
            is not inspect.Parameter.empty
        ):
            continue

    try:

        return PositionSnapshot(
            **kwargs
        )

    except TypeError as error:

        raise RuntimeError(
            "No se pudo construir PositionSnapshot "
            f"para {symbol}: {error}"
        )


# ============================================================
# PORTFOLIO ANALYZER
# ============================================================

def run_portfolio_analyzer(
    analyzer,
    equity,
    current_portfolio_risk,
    positions,
    db_events,
    returns_cache,
    candidate_symbol,
    candidate_value,
    candidate_price,
    candidate_stop,
    candidate_qty
):

    snapshots = []

    for symbol, position in positions.items():

        event = db_events.get(symbol)

        returns = returns_cache.get(
            symbol,
            []
        )

        snapshot = build_analyzer_position(
            symbol=symbol,
            position=position,
            event=event,
            returns=returns
        )

        snapshots.append(
            snapshot
        )

    candidate_returns = returns_cache.get(
        candidate_symbol,
        []
    )

    method = analyzer.analyze_candidate

    signature = inspect.signature(method)

    available = {
        "symbol": candidate_symbol,
        "candidate_symbol": candidate_symbol,
        "ticker": candidate_symbol,

        "candidate_value": candidate_value,
        "proposed_value": candidate_value,
        "position_value": candidate_value,
        "trade_value": candidate_value,

        "candidate_price": candidate_price,
        "entry_price": candidate_price,
        "price": candidate_price,

        "candidate_stop": candidate_stop,
        "stop_price": candidate_stop,

        "candidate_quantity": candidate_qty,
        "quantity": candidate_qty,
        "qty": candidate_qty,
        "position_size": candidate_qty,

        "account_value": equity,
        "equity": equity,

        "positions": snapshots,
        "portfolio_positions": snapshots,
        "existing_positions": snapshots,

        "returns": candidate_returns,
        "candidate_returns": candidate_returns,
        "return_series": candidate_returns,
        "daily_returns": candidate_returns,

        "current_portfolio_risk": current_portfolio_risk,
        "portfolio_risk": current_portfolio_risk
    }

    kwargs = {}

    for name, parameter in signature.parameters.items():

        if name == "self":
            continue

        if name in available:

            kwargs[name] = available[name]

        elif (
            parameter.default
            is not inspect.Parameter.empty
        ):

            continue

        else:

            raise RuntimeError(
                "PortfolioAnalyzer.analyze_candidate "
                f"requiere el argumento '{name}' "
                "que MAIN V4 no pudo proporcionar."
            )

    result = method(
        **kwargs
    )

    return result


# ============================================================
# EXTRAER RESULTADO DEL ANALYZER
# ============================================================

def analyzer_result_data(result):

    if result is None:

        return {
            "approved": False,
            "score": 0,
            "reasons": [
                "ANALYZER NO DEVOLVIÓ RESULTADO"
            ]
        }

    if isinstance(result, dict):

        data = result

    elif hasattr(result, "__dict__"):

        data = vars(result)

    else:

        data = {}

        for name in (
            "approved",
            "score",
            "reasons",
            "approval_reasons",
            "block_reasons",
            "risk_violation",
            "correlation_block",
            "concentration_block",
            "projected_total_exposure",
            "projected_symbol_exposure",
            "risk_increment",
            "remaining_risk_after"
        ):

            if hasattr(result, name):

                data[name] = getattr(
                    result,
                    name
                )

    approved = bool(
        data.get(
            "approved",
            False
        )
    )

    score = safe_float(
        data.get(
            "score",
            0
        )
    )

    reasons = data.get(
        "reasons",
        data.get(
            "approval_reasons",
            []
        )
    )

    if reasons is None:
        reasons = []

    if isinstance(reasons, str):
        reasons = [reasons]

    reasons = list(reasons)

    return {
        "approved": approved,
        "score": score,
        "reasons": reasons,
        "projected_total_exposure": safe_float(
            data.get(
                "projected_total_exposure",
                0
            )
        ),
        "projected_symbol_exposure": safe_float(
            data.get(
                "projected_symbol_exposure",
                0
            )
        ),
        "risk_increment": safe_float(
            data.get(
                "risk_increment",
                0
            )
        ),
        "remaining_risk_after": safe_float(
            data.get(
                "remaining_risk_after",
                0
            )
        ),
        "raw": data
    }


# ============================================================
# CLIENT ORDER ID
# ============================================================

def create_client_order_id(symbol):

    timestamp = int(
        time.time() * 1000
    )

    return (
        f"AI_V4_{symbol}_{timestamp}"
    )[:128]


# ============================================================
# EJECUTOR
# ============================================================

def submit_trade(
    trading_client,
    symbol,
    quantity,
    stop_price
):

    client_order_id = create_client_order_id(
        symbol
    )

    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.OTO,
        stop_loss=StopLossRequest(
            stop_price=round(
                stop_price,
                2
            )
        ),
        client_order_id=client_order_id
    )

    order = trading_client.submit_order(
        order_data=order_request
    )

    return order, client_order_id


# ============================================================
# MAIN
# ============================================================

def main():

    print_header()

    initialize_database()

    # --------------------------------------------------------
    # AI ENGINE
    # --------------------------------------------------------

    try:

        ai_ready = initialize_ai_engine()

        if ai_ready:

            print(
                GREEN
                + "AI Engine V1: ONLINE — MEMORIA ACTIVA"
                + RESET
            )

        else:

            print(
                YELLOW
                + "AI Engine V1: NO DISPONIBLE"
                + RESET
            )

            print(
                YELLOW
                + "El bot continuará sin memoria de IA."
                + RESET
            )

    except Exception as error:

        print(
            YELLOW
            + f"AI Engine: ERROR DE INICIALIZACIÓN: {error}"
            + RESET
        )

    print()

    # --------------------------------------------------------
    # CLIENTES
    # --------------------------------------------------------

    try:

        trading_client, data_client = (
            create_clients()
        )

    except Exception as error:

        print(
            RED
            + f"ERROR DE CONEXIÓN: {error}"
            + RESET
        )

        return

    # --------------------------------------------------------
    # PORTFOLIO ANALYZER
    # --------------------------------------------------------

    try:

        portfolio_analyzer = PortfolioAnalyzer()

        print(
            GREEN
            + "Portfolio Analyzer: ONLINE"
            + RESET
        )

    except Exception as error:

        print(
            RED
            + "ERROR INICIALIZANDO PORTFOLIO ANALYZER: "
            + str(error)
            + RESET
        )

        return

    # --------------------------------------------------------
    # CUENTA
    # --------------------------------------------------------

    try:

        account = get_account_snapshot(
            trading_client
        )

    except Exception as error:

        print(
            RED
            + f"ERROR OBTENIENDO CUENTA: {error}"
            + RESET
        )

        return

    equity = account["equity"]
    buying_power = account["buying_power"]

    print(
        CYAN
        + "=== CUENTA ==="
        + RESET
    )

    print(
        f"Equity:       ${equity:,.2f}"
    )

    print(
        f"Buying Power: ${buying_power:,.2f}"
    )

    print(
        f"Cash:         ${account['cash']:,.2f}"
    )

    print(
        f"Estado:       {account['status']}"
    )

    print()

    if equity <= 0:

        print(
            RED
            + "CUENTA INVÁLIDA"
            + RESET
        )

        return

    # --------------------------------------------------------
    # MERCADO
    # --------------------------------------------------------

    try:

        market_open, clock = check_market(
            trading_client
        )

    except Exception as error:

        print(
            RED
            + f"ERROR REVISANDO MERCADO: {error}"
            + RESET
        )

        return

    if not market_open:

        print(
            YELLOW
            + "MERCADO CERRADO — NO SE OPERARÁ"
            + RESET
        )

        return

    print(
        GREEN
        + "MERCADO ABIERTO"
        + RESET
    )

    print()

    # --------------------------------------------------------
    # MÉTRICAS DEL DÍA
    # --------------------------------------------------------

    trades_today = get_today_trade_count()
    daily_loss = get_today_loss()
    daily_profit_loss = get_today_profit_loss()

    print(
        CYAN
        + "=== ESTADO DEL DÍA ==="
        + RESET
    )

    print(
        f"Operaciones: {trades_today}"
    )

    print(
        f"Pérdida acumulada: ${daily_loss:,.2f}"
    )

    print(
        f"P/L cerrado: ${daily_profit_loss:,.2f}"
    )

    print()

    daily_limit = equity * MAX_DAILY_LOSS

    if daily_loss >= daily_limit:

        print(
            RED
            + "KILL SWITCH: LÍMITE DE PÉRDIDA DIARIA"
            + RESET
        )

        return

    # --------------------------------------------------------
    # POSICIONES
    # --------------------------------------------------------

    try:

        positions = get_positions(
            trading_client
        )

    except Exception as error:

        print(
            RED
            + f"ERROR OBTENIENDO POSICIONES: {error}"
            + RESET
        )

        return

    # --------------------------------------------------------
    # ÓRDENES
    # --------------------------------------------------------

    try:

        open_orders = get_open_orders(
            trading_client
        )

    except Exception as error:

        print(
            RED
            + f"ERROR OBTENIENDO ÓRDENES: {error}"
            + RESET
        )

        return

    print(
        CYAN
        + "=== CARTERA ==="
        + RESET
    )

    print(
        f"Posiciones abiertas: {len(positions)}"
    )

    print(
        f"Símbolos con órdenes: {len(open_orders)}"
    )

    print()

    available_slots = (
        MAX_OPEN_POSITIONS
        - len(positions)
    )

    if available_slots <= 0:

        print(
            YELLOW
            + "No hay espacio para nuevas posiciones."
            + RESET
        )

        return

    max_entries = min(
        available_slots,
        MAX_NEW_POSITIONS_PER_CYCLE
    )

    # --------------------------------------------------------
    # DB
    # --------------------------------------------------------

    db_events = load_db_position_events(
        positions
    )

    # --------------------------------------------------------
    # RIESGO
    # --------------------------------------------------------

    current_portfolio_risk, unknown_stop = (
        calculate_current_portfolio_risk_safe(
            equity,
            positions,
            db_events
        )
    )

    current_exposure = (
        calculate_current_exposure(
            equity,
            positions
        )
    )

    print(
        CYAN
        + "=== RIESGO ACTUAL ==="
        + RESET
    )

    print(
        f"Riesgo cartera: "
        f"{current_portfolio_risk * 100:.2f}%"
    )

    print(
        f"Exposición: "
        f"{current_exposure * 100:.2f}%"
    )

    if unknown_stop:

        print(
            YELLOW
            + "ADVERTENCIA: existen posiciones "
              "con stop desconocido."
            + RESET
        )

        print(
            YELLOW
            + "Riesgo tratado conservadoramente."
            + RESET
        )

    print()

    if current_exposure >= MAX_TOTAL_EXPOSURE:

        print(
            RED
            + "EXPOSICIÓN MÁXIMA ALCANZADA."
            + RESET
        )

        return

    # --------------------------------------------------------
    # CACHE DE DATOS
    # --------------------------------------------------------

    bars_cache = {
        BENCHMARK: None
    }

    returns_cache = {}

    # --------------------------------------------------------
    # SPY
    # --------------------------------------------------------

    print(
        CYAN
        + "=== PREPARANDO BENCHMARK ==="
        + RESET
    )

    try:

        benchmark_bars = get_daily_bars(
            data_client,
            BENCHMARK
        )

    except Exception as error:

        print(
            RED
            + f"ERROR DESCARGANDO SPY: {error}"
            + RESET
        )

        return

    if len(benchmark_bars) < MIN_BARS:

        print(
            RED
            + "No hay suficientes datos de SPY."
            + RESET
        )

        return

    bars_cache[BENCHMARK] = benchmark_bars

    returns_cache[BENCHMARK] = (
        calculate_returns(
            benchmark_bars
        )
    )

    print(
        GREEN
        + f"SPY listo: {len(benchmark_bars)} barras"
        + RESET
    )

    print()

    # --------------------------------------------------------
    # DATOS DE POSICIONES EXISTENTES
    # --------------------------------------------------------

    if positions:

        print(
            CYAN
            + "=== DATOS DE CARTERA PARA CORRELACIÓN ==="
            + RESET
        )

    for symbol in positions:

        try:

            bars = get_daily_bars(
                data_client,
                symbol
            )

            bars_cache[symbol] = bars

            returns_cache[symbol] = (
                calculate_returns(bars)
            )

            time.sleep(
                REQUEST_DELAY
            )

        except Exception as error:

            print(
                YELLOW
                + f"{symbol}: "
                  f"no se pudieron cargar retornos "
                  f"({error})"
                + RESET
            )

            returns_cache[symbol] = []

    if positions:
        print()

    # --------------------------------------------------------
    # ESCÁNER
    # --------------------------------------------------------

    print(
        CYAN
        + "=== ESCÁNER MULTI-ACTIVO ==="
        + RESET
    )

    analyses = []

    for symbol in SYMBOLS:

        if symbol == BENCHMARK:
            continue

        if symbol_is_locked(
            symbol,
            positions,
            open_orders
        ):

            print(
                YELLOW
                + f"{symbol:<6} BLOQUEADO "
                  "(posición/orden existente)"
                + RESET
            )

            continue

        try:

            bars = get_daily_bars(
                data_client,
                symbol
            )

            time.sleep(
                REQUEST_DELAY
            )

            bars_cache[symbol] = bars

            returns_cache[symbol] = (
                calculate_returns(bars)
            )

            analysis = analyze_symbol(
                symbol,
                bars,
                benchmark_bars
            )

            if analysis is None:

                print(
                    YELLOW
                    + f"{symbol:<6} "
                      "datos insuficientes/filtro"
                    + RESET
                )

                continue

            # ------------------------------------------------
            # AI ENGINE — MEMORIA
            # ------------------------------------------------

            record_signal_for_ai(
                analysis
            )

            analyses.append(
                analysis
            )

            print_analysis(
                analysis
            )

        except Exception as error:

            print(
                RED
                + f"{symbol:<6} ERROR: {error}"
                + RESET
            )

    print()

    # --------------------------------------------------------
    # RANKING
    # --------------------------------------------------------

    analyses.sort(
        key=lambda item: (
            item["score"],
            item["relative_strength"],
            item["momentum_score"]
        ),
        reverse=True
    )

    print(
        MAGENTA
        + "=== RANKING DE OPORTUNIDADES ==="
        + RESET
    )

    if not analyses:

        print(
            YELLOW
            + "No se encontraron oportunidades."
            + RESET
        )

        return

    for index, analysis in enumerate(
        analyses[:10],
        start=1
    ):

        print(
            f"{index:>2}. "
            f"{analysis['symbol']:<6} "
            f"Score {analysis['score']:>3}/100 | "
            f"RSI {analysis['rsi']:>5.1f} | "
            f"RS "
            f"{analysis['relative_strength'] * 100:>6.2f}%"
        )

    print()

    # --------------------------------------------------------
    # CANDIDATOS
    # --------------------------------------------------------

    candidates = [
        item
        for item in analyses
        if item["buy_signal"]
    ]

    if not candidates:

        print(
            YELLOW
            + "Ningún activo pasó todos los filtros."
            + RESET
        )

        return

    print(
        GREEN
        + f"Candidatos válidos: {len(candidates)}"
        + RESET
    )

    print()

    # ========================================================
    # EJECUCIÓN
    # ========================================================

    executed = 0

    for analysis in candidates:

        if executed >= max_entries:
            break

        symbol = analysis["symbol"]

        print()
        print("=" * 72)

        print(
            MAGENTA
            + f"ANALIZANDO ENTRADA: {symbol}"
            + RESET
        )

        print(
            f"Score:          {analysis['score']}/100"
        )

        print(
            f"Precio:         ${analysis['price']:.2f}"
        )

        print(
            f"RSI:            {analysis['rsi']:.2f}"
        )

        print(
            f"ATR:            ${analysis['atr']:.2f}"
        )

        print(
            f"Stop:           ${analysis['stop_price']:.2f}"
        )

        print(
            f"Distancia stop: "
            f"{analysis['stop_distance'] * 100:.2f}%"
        )

        # ----------------------------------------------------
        # POSITION SIZE
        # ----------------------------------------------------

        position_size = calculate_position_size(
            account_value=equity,
            entry_price=analysis["price"],
            stop_price=analysis["stop_price"],
            risk_percent=MAX_RISK_PER_TRADE,
            buying_power=buying_power
        )

        if position_size <= 0:

            log_rejection(
                symbol,
                analysis,
                "TAMAÑO DE POSICIÓN INVÁLIDO"
            )

            continue

        position_value = calculate_position_value(
            position_size,
            analysis["price"]
        )

        trade_risk = calculate_trade_risk(
            position_size,
            analysis["price"],
            analysis["stop_price"]
        )

        trade_risk_percent = (
            calculate_trade_risk_percent(
                equity,
                position_size,
                analysis["price"],
                analysis["stop_price"]
            )
        )

        print(
            f"Acciones:       {position_size}"
        )

        print(
            f"Capital:        ${position_value:,.2f}"
        )

        print(
            f"Riesgo:         ${trade_risk:,.2f}"
        )

        print(
            f"Riesgo %:       "
            f"{trade_risk_percent * 100:.2f}%"
        )

        # ----------------------------------------------------
        # BUYING POWER
        # ----------------------------------------------------

        if position_value > buying_power:

            log_rejection(
                symbol,
                analysis,
                "BUYING POWER INSUFICIENTE"
            )

            continue

        # ----------------------------------------------------
        # SYMBOL EXPOSURE
        # ----------------------------------------------------

        symbol_ok, symbol_message = (
            symbol_exposure_check(
                account_value=equity,
                symbol=symbol,
                position_size=position_size,
                entry_price=analysis["price"],
                existing_symbol_value=0.0
            )
        )

        if not symbol_ok:

            log_rejection(
                symbol,
                analysis,
                symbol_message
            )

            continue

        # ====================================================
        # PORTFOLIO ANALYZER
        # ====================================================

        print()
        print(
            CYAN
            + "=== PORTFOLIO ANALYZER ==="
            + RESET
        )

        try:

            analyzer_result = run_portfolio_analyzer(
                analyzer=portfolio_analyzer,
                equity=equity,
                current_portfolio_risk=(
                    current_portfolio_risk
                ),
                positions=positions,
                db_events=db_events,
                returns_cache=returns_cache,
                candidate_symbol=symbol,
                candidate_value=position_value,
                candidate_price=analysis["price"],
                candidate_stop=analysis["stop_price"],
                candidate_qty=position_size
            )

            analyzer_data = (
                analyzer_result_data(
                    analyzer_result
                )
            )

        except Exception as error:

            print(
                RED
                + "ERROR DEL PORTFOLIO ANALYZER: "
                + str(error)
                + RESET
            )

            log_rejection(
                symbol,
                analysis,
                "PORTFOLIO ANALYZER ERROR"
            )

            continue

        print(
            f"Analyzer aprobado: "
            f"{analyzer_data['approved']}"
        )

        print(
            f"Analyzer score: "
            f"{analyzer_data['score']:.1f}"
        )

        if analyzer_data[
            "projected_total_exposure"
        ] > 0:

            print(
                f"Exposición proyectada: "
                f"{analyzer_data['projected_total_exposure'] * 100:.2f}%"
            )

        if analyzer_data[
            "projected_symbol_exposure"
        ] > 0:

            print(
                f"Exposición símbolo: "
                f"{analyzer_data['projected_symbol_exposure'] * 100:.2f}%"
            )

        if analyzer_data["risk_increment"] > 0:

            print(
                f"Riesgo incremental: "
                f"{analyzer_data['risk_increment'] * 100:.2f}%"
            )

        if analyzer_data["reasons"]:

            for reason in analyzer_data["reasons"]:

                print(
                    "  • "
                    + str(reason)
                )

        if not analyzer_data["approved"]:

            log_rejection(
                symbol,
                analysis,
                "PORTFOLIO ANALYZER RECHAZÓ LA ENTRADA"
            )

            continue

        print(
            GREEN
            + "Portfolio Analyzer: AUTORIZADO"
            + RESET
        )

        # ====================================================
        # PORTFOLIO RISK CHECK
        # ====================================================

        portfolio_risk_check_ok = (
            current_portfolio_risk
            + trade_risk_percent
            <= MAX_PORTFOLIO_RISK
        )

        projected_exposure = (
            current_exposure
            + (
                position_value
                / equity
            )
        )

        if not portfolio_risk_check_ok:

            log_rejection(
                symbol,
                analysis,
                "RIESGO TOTAL DE CARTERA EXCEDIDO"
            )

            continue

        if projected_exposure > MAX_TOTAL_EXPOSURE:

            log_rejection(
                symbol,
                analysis,
                "EXPOSICIÓN TOTAL EXCEDIDA"
            )

            continue

        # ====================================================
        # RISK MANAGER V3
        # ====================================================

        approved, risk_message = risk_check(
            signal="COMPRAR",
            account_value=equity,
            entry_price=analysis["price"],
            stop_price=analysis["stop_price"],
            daily_loss=daily_loss,
            trades_today=trades_today,
            current_portfolio_risk=(
                current_portfolio_risk
            ),
            open_positions=len(
                positions
            ),
            current_exposure=current_exposure,
            buying_power=buying_power,
            existing_symbol_value=0.0
        )

        print(
            f"Risk Manager: {risk_message}"
        )

        if not approved:

            log_rejection(
                symbol,
                analysis,
                risk_message
            )

            continue

        print(
            GREEN
            + "Risk Manager: AUTORIZADO"
            + RESET
        )

        # ====================================================
        # ÚLTIMA SINCRONIZACIÓN
        # ====================================================

        try:

            fresh_account = (
                get_account_snapshot(
                    trading_client
                )
            )

            fresh_positions = get_positions(
                trading_client
            )

            fresh_orders = get_open_orders(
                trading_client
            )

        except Exception as error:

            log_rejection(
                symbol,
                analysis,
                f"ERROR DE SINCRONIZACIÓN: {error}"
            )

            continue

        fresh_equity = safe_float(
            fresh_account["equity"]
        )

        fresh_buying_power = safe_float(
            fresh_account["buying_power"]
        )

        if fresh_equity <= 0:

            log_rejection(
                symbol,
                analysis,
                "EQUITY INVÁLIDO EN ÚLTIMA COMPROBACIÓN"
            )

            continue

        if position_value > fresh_buying_power:

            log_rejection(
                symbol,
                analysis,
                "BUYING POWER CAMBIÓ ANTES DE EJECUTAR"
            )

            continue

        if symbol_is_locked(
            symbol,
            fresh_positions,
            fresh_orders
        ):

            log_rejection(
                symbol,
                analysis,
                "EL ACTIVO SE BLOQUEÓ DURANTE EL CICLO"
            )

            continue

        if len(fresh_positions) >= MAX_OPEN_POSITIONS:

            log_rejection(
                symbol,
                analysis,
                "SE ALCANZÓ EL MÁXIMO DE POSICIONES"
            )

            continue

        # ====================================================
        # EJECUTAR
        # ====================================================

        print()

        print(
            GREEN
            + f"🔥 AUTORIZADO FINAL: COMPRAR {symbol}"
            + RESET
        )

        try:

            order, client_order_id = submit_trade(
                trading_client=trading_client,
                symbol=symbol,
                quantity=position_size,
                stop_price=analysis["stop_price"]
            )

        except Exception as error:

            print(
                RED
                + f"ERROR ENVIANDO ORDEN {symbol}: {error}"
                + RESET
            )

            try:

                log_event(
                    symbol=symbol,
                    signal="COMPRAR",
                    entry_price=analysis["price"],
                    stop_price=analysis["stop_price"],
                    position_size=position_size,
                    status="ORDER_ERROR",
                    profit_loss=0.0,
                    client_order_id=None
                )

            except Exception:

                pass

            continue

        # ====================================================
        # REGISTRO
        # ====================================================

        order_id = getattr(
            order,
            "id",
            None
        )

        order_status = str(
            getattr(
                order,
                "status",
                "SUBMITTED"
            )
        )

        try:

            event_id = log_event(
                symbol=symbol,
                signal="COMPRAR",
                entry_price=analysis["price"],
                stop_price=analysis["stop_price"],
                position_size=position_size,
                status=order_status,
                profit_loss=0.0,
                order_id=order_id,
                client_order_id=client_order_id
            )

        except Exception as error:

            event_id = None

            print(
                RED
                + f"ERROR GUARDANDO EVENTO DB: {error}"
                + RESET
            )

        print()
        print(
            GREEN
            + "================================================"
            + RESET
        )

        print(
            GREEN
            + f"ORDEN ENVIADA: {symbol}"
            + RESET
        )

        print(
            f"Cantidad:       {position_size}"
        )

        print(
            f"Precio aprox.:  ${analysis['price']:.2f}"
        )

        print(
            f"Stop:           ${analysis['stop_price']:.2f}"
        )

        print(
            f"Score:          {analysis['score']}/100"
        )

        print(
            f"Order ID:       {order_id}"
        )

        print(
            f"Client ID:      {client_order_id}"
        )

        print(
            f"DB Event:       {event_id}"
        )

        print(
            f"Estado:         {order_status}"
        )

        print(
            GREEN
            + "================================================"
            + RESET
        )

        executed += 1

        # ----------------------------------------------------
        # ACTUALIZAR ESTADO LOCAL
        # ----------------------------------------------------

        trades_today += 1

        current_portfolio_risk += (
            trade_risk_percent
        )

        current_exposure = projected_exposure

        buying_power = (
            fresh_buying_power
            - position_value
        )

        positions[symbol] = {
            "symbol": symbol,
            "qty": position_size,
            "market_value": position_value,
            "avg_entry_price": analysis["price"],
            "current_price": analysis["price"],
            "unrealized_pl": 0.0
        }

        if executed >= max_entries:

            break

    # ========================================================
    # RESUMEN
    # ========================================================

    print()
    print("=" * 72)

    print(
        CYAN
        + "              RESUMEN DEL CICLO"
        + RESET
    )

    print("=" * 72)

    print(
        f"Activos escaneados:     {len(SYMBOLS) - 1}"
    )

    print(
        f"Activos analizados:     {len(analyses)}"
    )

    print(
        f"Candidatos:             {len(candidates)}"
    )

    print(
        f"Nuevas entradas:        {executed}"
    )

    print(
        f"Posiciones actuales:    {len(positions)}"
    )

    print(
        f"Riesgo cartera aprox.:  "
        f"{current_portfolio_risk * 100:.2f}%"
    )

    print(
        f"Exposición aprox.:      "
        f"{current_exposure * 100:.2f}%"
    )

    print(
        f"Buying Power restante:  "
        f"${buying_power:,.2f}"
    )

    print()

    if executed == 0:

        print(
            YELLOW
            + "El bot no abrió operaciones en este ciclo."
            + RESET
        )

    else:

        print(
            GREEN
            + f"El bot ejecutó {executed} nueva(s) entrada(s)."
            + RESET
        )

    print()
    print("=" * 72)
    print("       AI TRADER V4 — CICLO TERMINADO")
    print("=" * 72)
    print()


# ============================================================
# EJECUCIÓN SEGURA
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            YELLOW
            + "Ejecución detenida manualmente."
            + RESET
        )

    except Exception as error:

        print()
        print(
            RED
            + "================================================"
            + RESET
        )

        print(
            RED
            + "KILL SWITCH — ERROR NO CONTROLADO"
            + RESET
        )

        print(
            RED
            + str(error)
            + RESET
        )

        print()

        traceback.print_exc()

        print(
            RED
            + "NO SE INTENTARÁN MÁS ÓRDENES."
            + RESET
        )
