import os
import uuid
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopLossRequest
)
from alpaca.trading.enums import (
    OrderSide,
    OrderClass,
    QueryOrderStatus,
    TimeInForce
)

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from indicators import sma, ema, rsi, volatility
from risk_manager import risk_check, calculate_position_size

from database import (
    initialize_database,
    log_event,
    update_event,
    get_event_by_order_id,
    get_open_position_event,
    get_today_trade_count,
    get_today_loss,
    get_today_profit_loss
)


# ============================================================
# AI TRADER V2
# UNIVERSO INICIAL: 25 ACTIVOS
# ============================================================

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


# ============================================================
# CONFIGURACIÓN
# ============================================================

MIN_BARS = 20
LOOKBACK_DAYS = 180

# Máximo de candidatos que pueden intentar entrar
MAX_NEW_POSITIONS_PER_CYCLE = 2


# ============================================================
# FUNCIÓN: ANALIZAR ACTIVO
# ============================================================

def analyze_symbol(data_client, symbol):

    try:

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=LOOKBACK_DAYS)

        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=DataFeed.IEX
        )

        bars = data_client.get_stock_bars(request)

        if symbol not in bars:
            print(f"{symbol}: SIN DATOS")
            return None

        symbol_bars = bars[symbol]

        closes = [
            float(bar.close)
            for bar in symbol_bars
        ]

        if len(closes) < MIN_BARS:
            print(
                f"{symbol}: DATOS INSUFICIENTES "
                f"({len(closes)} velas)"
            )
            return None

        current_price = closes[-1]

        sma20 = sma(closes, 20)
        ema20 = ema(closes, 20)
        rsi14 = rsi(closes, 14)
        vol20 = volatility(closes, 20)

        if (
            sma20 is None
            or ema20 is None
            or rsi14 is None
            or vol20 is None
        ):
            print(f"{symbol}: INDICADORES INCOMPLETOS")
            return None

        # ====================================================
        # ESTRATEGIA V2
        # ====================================================

        if current_price > ema20 and rsi14 < 70:
            signal = "COMPRAR"

        elif current_price < ema20 and rsi14 > 30:
            signal = "VENDER"

        else:
            signal = "ESPERAR"

        # ====================================================
        # SCORE
        # ====================================================

        score = 0

        if current_price > ema20:
            score += 1

        if current_price > sma20:
            score += 1

        if ema20 > sma20:
            score += 1

        if 40 <= rsi14 < 65:
            score += 1

        if signal == "COMPRAR":
            score += 1

        return {
            "symbol": symbol,
            "price": current_price,
            "sma20": sma20,
            "ema20": ema20,
            "rsi14": rsi14,
            "vol20": vol20,
            "signal": signal,
            "score": score
        }

    except Exception as error:

        print(
            f"{symbol}: ERROR DURANTE ANALISIS"
        )
        print(str(error))

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # BASE DE DATOS
    # ========================================================

    initialize_database()

    # ========================================================
    # CREDENCIALES
    # ========================================================

    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not secret_key:

        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY "
            "EN RAILWAY"
        )

    # ========================================================
    # CONEXIÓN ALPACA
    # ========================================================

    trading_client = TradingClient(
        api_key,
        secret_key,
        paper=True
    )

    data_client = StockHistoricalDataClient(
        api_key,
        secret_key
    )

    account = trading_client.get_account()

    account_value = float(account.equity)

    print()
    print("================================================")
    print("          AI TRADER V2 — PAPER")
    print("================================================")
    print()
    print("CONEXION CON ALPACA: OK")
    print(f"Cuenta: {account.status}")
    print(f"Capital: ${account_value:,.2f}")
    print("MODO: PAPER")
    print()
    print(f"Activos monitoreados: {len(SYMBOLS)}")
    print()

    # ========================================================
    # ESTADO DEL BOT
    # ========================================================

    trades_today = get_today_trade_count()
    daily_loss = get_today_loss()
    today_profit_loss = get_today_profit_loss()

    print("=== ESTADO DEL BOT ===")
    print(
        f"Fecha UTC: "
        f"{datetime.now(timezone.utc).date()}"
    )
    print(
        f"Operaciones ejecutadas hoy: "
        f"{trades_today}"
    )
    print(
        f"Perdida diaria: "
        f"${daily_loss:.2f}"
    )
    print(
        f"Resultado del dia: "
        f"${today_profit_loss:.2f}"
    )
    print()

    # ========================================================
    # ESTADO DEL MERCADO
    # ========================================================

    clock = trading_client.get_clock()

    print("=== ESTADO DEL MERCADO ===")
    print(f"Mercado abierto: {clock.is_open}")

    if not clock.is_open:

        print(f"Proxima apertura: {clock.next_open}")
        print(f"Proximo cierre: {clock.next_close}")
        print()
        print("MERCADO CERRADO")
        print("NO SE ENVIARA NINGUNA ORDEN")
        print("================================================")

        return

    print()

    # ========================================================
    # POSICIONES EXISTENTES
    # ========================================================

    print("================================================")
    print("        SINCRONIZACION DE POSICIONES")
    print("================================================")

    positions = trading_client.get_all_positions()

    open_symbols = set()

    for position in positions:

        symbol = position.symbol

        open_symbols.add(symbol)

        qty = int(float(position.qty))
        avg_entry = float(position.avg_entry_price)
        current_price = float(position.current_price)
        unrealized_pl = float(position.unrealized_pl)

        print()
        print(f"POSICION: {symbol}")
        print(f"Cantidad: {qty}")
        print(f"Precio promedio: ${avg_entry:.2f}")
        print(f"Precio actual: ${current_price:.2f}")
        print(f"P/L no realizado: ${unrealized_pl:.2f}")

        # ====================================================
        # SINCRONIZAR DB
        # ====================================================

        db_position = get_open_position_event(symbol)

        if db_position is None:

            print(
                "Posicion no encontrada en DB."
            )
            print("SINCRONIZANDO...")

            synced_event_id = log_event(
                symbol=symbol,
                signal="COMPRAR",
                entry_price=avg_entry,
                stop_price=0.0,
                position_size=qty,
                status="POSITION_OPEN",
                profit_loss=0.0,
                order_id=None,
                client_order_id=None
            )

            print(
                f"Posicion sincronizada "
                f"Evento DB: #{synced_event_id}"
            )

        else:

            print(
                f"DB: posicion registrada "
                f"#{db_position['id']}"
            )

    if not open_symbols:

        print("No existen posiciones abiertas.")

    print()

    # ========================================================
    # ORDENES PENDIENTES
    # ========================================================

    print("================================================")
    print("          ORDENES PENDIENTES")
    print("================================================")

    open_orders_request = GetOrdersRequest(
        status=QueryOrderStatus.OPEN,
        limit=50,
        nested=True
    )

    open_orders = trading_client.get_orders(
        filter=open_orders_request
    )

    pending_symbols = set()

    for order in open_orders:

        pending_symbols.add(order.symbol)

        print(
            f"{order.symbol} | "
            f"ID: {order.id} | "
            f"Estado: {order.status}"
        )

    if not pending_symbols:

        print("No existen ordenes pendientes.")

    print()

    # ========================================================
    # CAPACIDAD DE NUEVAS POSICIONES
    # ========================================================

    available_slots = (
        MAX_NEW_POSITIONS_PER_CYCLE
        - len(open_symbols)
    )

    if available_slots <= 0:

        print("================================================")
        print("LIMITE DE POSICIONES ALCANZADO")
        print("NO SE BUSCARAN NUEVAS ENTRADAS")
        print("================================================")

        return

    # ========================================================
    # ESCANEO DE LOS 25 ACTIVOS
    # ========================================================

    print("================================================")
    print("             ESCANEO MULTI-ACTIVO")
    print("================================================")
    print()

    candidates = []

    for symbol in SYMBOLS:

        print(f"Analizando {symbol}...")

        # ----------------------------------------------------
        # Si ya tiene posición
        # ----------------------------------------------------

        if symbol in open_symbols:

            print(
                f"{symbol}: POSICION ABIERTA "
                f"-> NO SE COMPRA"
            )
            print()
            continue

        # ----------------------------------------------------
        # Si tiene orden pendiente
        # ----------------------------------------------------

        if symbol in pending_symbols:

            print(
                f"{symbol}: ORDEN PENDIENTE "
                f"-> NO SE ENVIA OTRA"
            )
            print()
            continue

        # ----------------------------------------------------
        # Analizar
        # ----------------------------------------------------

        result = analyze_symbol(
            data_client,
            symbol
        )

        if result is None:

            print()
            continue

        print(
            f"Precio: ${result['price']:.2f}"
        )

        print(
            f"EMA20: ${result['ema20']:.2f}"
        )

        print(
            f"SMA20: ${result['sma20']:.2f}"
        )

        print(
            f"RSI14: {result['rsi14']:.2f}"
        )

        print(
            f"Score: {result['score']}/5"
        )

        print(
            f"Señal: {result['signal']}"
        )

        # ----------------------------------------------------
        # Solo candidatos LONG
        # ----------------------------------------------------

        if result["signal"] == "COMPRAR":

            candidates.append(result)

            print(
                ">>> CANDIDATO DE COMPRA"
            )

        else:

            print(
                "No hay entrada."
            )

        print()

    # ========================================================
    # RESULTADO DEL ESCANEO
    # ========================================================

    print("================================================")
    print("          RESULTADO DEL ESCANEO")
    print("================================================")

    if not candidates:

        print(
            "No se encontraron oportunidades "
            "de compra."
        )
        print()
        print(
            "El bot NO enviara ninguna orden."
        )
        print("================================================")

        return

    # ========================================================
    # ORDENAR CANDIDATOS
    # ========================================================

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    print()
    print(
        f"Oportunidades encontradas: "
        f"{len(candidates)}"
    )
    print()

    for candidate in candidates:

        print(
            f"{candidate['symbol']} | "
            f"Score {candidate['score']}/5 | "
            f"RSI {candidate['rsi14']:.2f}"
        )

    print()

    # ========================================================
    # LIMITAR ENTRADAS
    # ========================================================

    selected_candidates = candidates[
        :available_slots
    ]

    print(
        f"Candidatos seleccionados: "
        f"{len(selected_candidates)}"
    )

    print()

    # ========================================================
    # EJECUTAR CANDIDATOS
    # ========================================================

    executed_count = 0

    for candidate in selected_candidates:

        symbol = candidate["symbol"]
        current_price = candidate["price"]

        print()
        print("================================================")
        print(
            f"          PROCESANDO {symbol}"
        )
        print("================================================")

        # ====================================================
        # STOP LOSS
        # ====================================================

        stop_price = round(
            current_price * 0.97,
            2
        )

        print(
            f"Entrada referencia: "
            f"${current_price:.2f}"
        )

        print(
            f"Stop loss: "
            f"${stop_price:.2f}"
        )

        # ====================================================
        # RISK MANAGER
        # ====================================================

        approved, message = risk_check(
            signal="COMPRAR",
            account_value=account_value,
            entry_price=current_price,
            stop_price=stop_price,
            daily_loss=daily_loss,
            trades_today=trades_today
        )

        print(
            f"Autorizacion: {approved}"
        )

        print(message)

        if not approved:

            print(
                f"{symbol}: RISK MANAGER "
                f"RECHAZO LA OPERACION"
            )

            continue

        # ====================================================
        # POSITION SIZE
        # ====================================================

        position_size = calculate_position_size(
            account_value=account_value,
            entry_price=current_price,
            stop_price=stop_price
        )

        if position_size <= 0:

            print(
                f"{symbol}: TAMAÑO DE POSICION INVALIDO"
            )

            continue

        print()
        print("=== POSICION ===")
        print(
            f"Acciones: {position_size}"
        )
        print(
            f"Riesgo por accion: "
            f"${abs(current_price - stop_price):.2f}"
        )

        # ====================================================
        # CLIENT ORDER ID
        # ====================================================

        client_order_id = (
            f"ai-trader-{symbol.lower()}-"
            f"{uuid.uuid4().hex[:12]}"
        )

        # ====================================================
        # ORDEN PAPER
        # ====================================================

        print()
        print("=== EJECUCION PAPER ===")
        print(
            f"COMPRA {position_size} {symbol}"
        )
        print(
            f"Stop loss: ${stop_price:.2f}"
        )
        print(
            "Enviando orden a Alpaca Paper..."
        )

        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=position_size,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.OTO,
            stop_loss=StopLossRequest(
                stop_price=stop_price
            ),
            client_order_id=client_order_id
        )

        # ====================================================
        # ENVIAR ORDEN
        # ====================================================

        try:

            order = trading_client.submit_order(
                order_data=order_request
            )

        except Exception as error:

            print()
            print("ERROR AL ENVIAR ORDEN")
            print(str(error))
            print(
                f"{symbol}: NO SE REGISTRA "
                "COMO EJECUTADA"
            )

            continue

        # ====================================================
        # REGISTRAR EN DATABASE
        # ====================================================

        order_id = str(order.id)

        event_id = log_event(
            symbol=symbol,
            signal="COMPRAR",
            entry_price=current_price,
            stop_price=stop_price,
            position_size=position_size,
            status="ORDER_SUBMITTED",
            profit_loss=0.0,
            order_id=order_id,
            client_order_id=client_order_id
        )

        print()
        print("================================================")
        print("             ORDEN PAPER ENVIADA")
        print("================================================")

        print(
            f"Evento DB: #{event_id}"
        )

        print(
            f"Order ID: {order.id}"
        )

        print(
            f"Estado: {order.status}"
        )

        print(
            f"Simbolo: {order.symbol}"
        )

        print(
            f"Cantidad: {order.qty}"
        )

        print(
            f"Lado: {order.side}"
        )

        print(
            f"Stop loss: ${stop_price:.2f}"
        )

        print(
            f"Client Order ID: "
            f"{client_order_id}"
        )

        # ====================================================
        # VERIFICAR ORDEN
        # ====================================================

        try:

            updated_order = (
                trading_client.get_order_by_id(
                    order.id
                )
            )

            order_status = (
                str(updated_order.status)
                .upper()
            )

            print()
            print("=== VERIFICACION DE ORDEN ===")
            print(
                f"Estado actual: "
                f"{order_status}"
            )

            if order_status == "FILLED":

                filled_price = (
                    float(
                        updated_order.filled_avg_price
                    )
                    if updated_order.filled_avg_price
                    else current_price
                )

                filled_qty = (
                    int(
                        float(
                            updated_order.filled_qty
                        )
                    )
                    if updated_order.filled_qty
                    else position_size
                )

                update_event(
                    event_id=event_id,
                    status="FILLED",
                    order_id=order_id,
                    client_order_id=client_order_id
                )

                print(
                    f"Precio ejecutado: "
                    f"${filled_price:.2f}"
                )

                print(
                    f"Cantidad ejecutada: "
                    f"{filled_qty}"
                )

                print(
                    "DATABASE: FILLED"
                )

            elif order_status in [
                "CANCELED",
                "EXPIRED",
                "REJECTED"
            ]:

                update_event(
                    event_id=event_id,
                    status=order_status,
                    order_id=order_id,
                    client_order_id=client_order_id
                )

                print(
                    f"DATABASE: "
                    f"{order_status}"
                )

            else:

                print(
                    "La orden aun no tiene "
                    "estado final."
                )

                print(
                    "DATABASE: ORDER_SUBMITTED"
                )

        except Exception as error:

            print()
            print(
                "NO SE PUDO VERIFICAR "
                "EL ESTADO DE LA ORDEN"
            )

            print(str(error))

        executed_count += 1

        # ====================================================
        # ACTUALIZAR CONTADORES LOCALES
        # ====================================================

        trades_today += 1

        # ----------------------------------------------------
        # Seguridad adicional:
        # no mandar más operaciones de las permitidas
        # ----------------------------------------------------

        if trades_today >= 5:

            print()
            print(
                "LIMITE DIARIO DE OPERACIONES "
                "ALCANZADO"
            )

            break

    # ========================================================
    # RESULTADO FINAL
    # ========================================================

    print()
    print("================================================")
    print("              CICLO COMPLETADO")
    print("================================================")

    print(
        f"Activos escaneados: "
        f"{len(SYMBOLS)}"
    )

    print(
        f"Oportunidades encontradas: "
        f"{len(candidates)}"
    )

    print(
        f"Ordenes procesadas: "
        f"{executed_count}"
    )

    print(
        f"Operaciones del dia: "
        f"{trades_today}"
    )

    print()
    print(
        "MODO PAPER — NO ES DINERO REAL"
    )

    print("================================================")


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()
