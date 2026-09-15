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


SYMBOL = "AAPL"


def main():

    # =========================
    # BASE DE DATOS
    # =========================

    initialize_database()

    # =========================
    # CREDENCIALES
    # =========================

    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not secret_key:
        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY EN RAILWAY"
        )

    # =========================
    # CONEXIÓN CON ALPACA
    # =========================

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

    print("==============================================")
    print("       AI TRADER — PAPER TRADING")
    print("==============================================")
    print()
    print("CONEXION CON ALPACA: OK")
    print(f"Cuenta: {account.status}")
    print(f"Capital: ${account_value:,.2f}")
    print("MODO: PAPER")
    print()

    # =========================
    # ESTADO DEL BOT
    # =========================

    trades_today = get_today_trade_count()
    daily_loss = get_today_loss()
    today_profit_loss = get_today_profit_loss()

    print("=== ESTADO DEL BOT ===")
    print(f"Fecha UTC: {datetime.now(timezone.utc).date()}")
    print(f"Operaciones ejecutadas hoy: {trades_today}")
    print(f"Perdida diaria: ${daily_loss:.2f}")
    print(f"Resultado del dia: ${today_profit_loss:.2f}")
    print()

    # =========================
    # ESTADO DEL MERCADO
    # =========================

    clock = trading_client.get_clock()

    print("=== ESTADO DEL MERCADO ===")
    print(f"Mercado abierto: {clock.is_open}")

    if not clock.is_open:
        print(f"Proxima apertura: {clock.next_open}")
        print(f"Proximo cierre: {clock.next_close}")
        print()
        print("MERCADO CERRADO")
        print("NO SE ENVIARA NINGUNA ORDEN")
        print("==============================================")
        return

    print()

    # ==================================================
    # SINCRONIZACIÓN DE POSICIONES
    # ==================================================

    print("=== SINCRONIZACION DE POSICIONES ===")

    positions = trading_client.get_all_positions()

    existing_position = None

    for position in positions:
        if position.symbol == SYMBOL:
            existing_position = position
            break

    if existing_position is not None:

        qty = int(float(existing_position.qty))
        avg_entry = float(existing_position.avg_entry_price)
        current_price = float(existing_position.current_price)
        unrealized_pl = float(existing_position.unrealized_pl)

        print(f"Posicion encontrada: {SYMBOL}")
        print(f"Cantidad: {qty}")
        print(f"Precio promedio: ${avg_entry:.2f}")
        print(f"Precio actual: ${current_price:.2f}")
        print(f"P/L no realizado: ${unrealized_pl:.2f}")

        # =========================
        # BUSCAR EN DATABASE
        # =========================

        db_position = get_open_position_event(SYMBOL)

        if db_position is None:

            print()
            print("La posicion existe en Alpaca")
            print("pero no estaba registrada en nuestra DB.")
            print("SINCRONIZANDO...")

            synced_event_id = log_event(
                symbol=SYMBOL,
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
                f"Posicion sincronizada. "
                f"Evento DB: #{synced_event_id}"
            )

        else:

            print()
            print(
                f"Posicion ya registrada en DB. "
                f"Evento #{db_position['id']}"
            )

        print()
        print("==============================================")
        print("PROTECCION DE POSICION")
        print("==============================================")
        print(f"Ya existe una posicion en {SYMBOL}")
        print(f"Cantidad: {qty}")
        print(f"Precio promedio: ${avg_entry:.2f}")
        print(f"Ganancia/perdida: ${unrealized_pl:.2f}")
        print("NO SE ENVIARA OTRA COMPRA")
        print("==============================================")

        return

    # ==================================================
    # NO EXISTE POSICIÓN
    # ==================================================

    print("No existe una posicion abierta en", SYMBOL)
    print()

    # =========================
    # PROTECCIÓN:
    # ORDEN PENDIENTE
    # =========================

    open_orders_request = GetOrdersRequest(
        status=QueryOrderStatus.OPEN,
        limit=50,
        nested=True
    )

    open_orders = trading_client.get_orders(
        filter=open_orders_request
    )

    for order in open_orders:

        if order.symbol == SYMBOL:

            print("=== PROTECCION DE ORDEN ===")
            print(f"Ya existe una orden pendiente para {SYMBOL}")
            print(f"ID: {order.id}")
            print(f"Estado: {order.status}")
            print("NO SE ENVIARA OTRA ORDEN")
            print("==============================================")

            return

    # =========================
    # DATOS DEL MERCADO
    # =========================

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)

    request = StockBarsRequest(
        symbol_or_symbols=[SYMBOL],
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=DataFeed.IEX
    )

    bars = data_client.get_stock_bars(request)
    symbol_bars = bars[SYMBOL]

    closes = [
        float(bar.close)
        for bar in symbol_bars
    ]

    print("=== DATOS DEL MERCADO ===")
    print(f"Simbolo: {SYMBOL}")
    print("Feed: IEX")
    print(f"Velas recibidas: {len(closes)}")
    print()

    if len(closes) < 20:

        print("DATOS INSUFICIENTES")
        print("NO SE GENERA SEÑAL")

        return

    # =========================
    # INDICADORES
    # =========================

    current_price = closes[-1]

    sma20 = sma(closes, 20)
    ema20 = ema(closes, 20)
    rsi14 = rsi(closes, 14)
    vol20 = volatility(closes, 20)

    print("=== AAPL — ANALISIS ===")
    print(f"Precio: ${current_price:.2f}")
    print(f"SMA 20: ${sma20:.2f}")
    print(f"EMA 20: ${ema20:.2f}")
    print(f"RSI 14: {rsi14:.2f}")
    print(f"Volatilidad 20: {vol20:.4f}")
    print()

    # =========================
    # ESTRATEGIA
    # =========================

    print("=== ESTRATEGIA ===")

    if current_price > ema20 and rsi14 < 70:
        signal = "COMPRAR"

    elif current_price < ema20 and rsi14 > 30:
        signal = "VENDER"

    else:
        signal = "ESPERAR"

    print(f"Señal generada: {signal}")
    print()

    # =========================
    # SOLO LONG
    # =========================

    if signal != "COMPRAR":

        print("=== EJECUCION ===")
        print(f"Señal: {signal}")
        print("Esta version solo abre posiciones LONG.")
        print("NO SE ENVIA NINGUNA ORDEN")
        print("==============================================")

        return

    # =========================
    # STOP LOSS
    # =========================

    stop_price = round(current_price * 0.97, 2)

    print("=== GESTION DE RIESGO ===")
    print(f"Entrada de referencia: ${current_price:.2f}")
    print(f"Stop loss: ${stop_price:.2f}")

    # =========================
    # RISK MANAGER
    # =========================

    approved, message = risk_check(
        signal=signal,
        account_value=account_value,
        entry_price=current_price,
        stop_price=stop_price,
        daily_loss=daily_loss,
        trades_today=trades_today
    )

    print(f"Autorizacion: {approved}")
    print(message)
    print()

    if not approved:

        print("RISK MANAGER RECHAZO LA OPERACION")
        print("NO SE ENVIA NINGUNA ORDEN")
        print("==============================================")

        return

    # =========================
    # TAMAÑO DE POSICIÓN
    # =========================

    position_size = calculate_position_size(
        account_value=account_value,
        entry_price=current_price,
        stop_price=stop_price
    )

    if position_size <= 0:

        print("TAMAÑO DE POSICION INVALIDO")
        print("NO SE ENVIA NINGUNA ORDEN")

        return

    print("=== POSICION ===")
    print(f"Acciones: {position_size}")
    print(
        f"Riesgo por accion: "
        f"${abs(current_price - stop_price):.2f}"
    )
    print()

    # =========================
    # ID DE ORDEN
    # =========================

    client_order_id = (
        f"ai-trader-{SYMBOL.lower()}-"
        f"{uuid.uuid4().hex[:12]}"
    )

    # =========================
    # ORDEN PAPER
    # =========================

    print("=== EJECUCION PAPER ===")
    print("Riesgo aprobado")
    print("Sin posicion existente")
    print("Sin orden pendiente")
    print(f"Orden: COMPRA {position_size} {SYMBOL}")
    print(f"Stop loss: ${stop_price:.2f}")
    print("Enviando orden a Alpaca Paper...")

    order_request = MarketOrderRequest(
        symbol=SYMBOL,
        qty=position_size,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.OTO,
        stop_loss=StopLossRequest(
            stop_price=stop_price
        ),
        client_order_id=client_order_id
    )

    try:

        order = trading_client.submit_order(
            order_data=order_request
        )

    except Exception as error:

        print()
        print("==============================================")
        print("ERROR AL ENVIAR LA ORDEN")
        print("==============================================")
        print(str(error))
        print("NO SE REGISTRA COMO EJECUTADA")

        return

    # =========================
    # REGISTRAR ORDEN ENVIADA
    # =========================

    order_id = str(order.id)

    event_id = log_event(
        symbol=SYMBOL,
        signal=signal,
        entry_price=current_price,
        stop_price=stop_price,
        position_size=position_size,
        status="ORDER_SUBMITTED",
        profit_loss=0.0,
        order_id=order_id,
        client_order_id=client_order_id
    )

    print()
    print("==============================================")
    print("ORDEN PAPER ENVIADA")
    print("==============================================")
    print(f"Evento DB: #{event_id}")
    print(f"Order ID: {order.id}")
    print(f"Estado: {order.status}")
    print(f"Simbolo: {order.symbol}")
    print(f"Cantidad: {order.qty}")
    print(f"Lado: {order.side}")
    print(f"Stop loss: ${stop_price:.2f}")
    print(f"Client Order ID: {client_order_id}")
    print("==============================================")

    # =========================
    # COMPROBAR ESTADO ACTUAL
    # =========================

    try:

        updated_order = trading_client.get_order_by_id(
            order.id
        )

        order_status = str(updated_order.status).upper()

        print()
        print("=== VERIFICACION DE ORDEN ===")
        print(f"Estado actual: {order_status}")

        if order_status == "FILLED":

            filled_price = (
                float(updated_order.filled_avg_price)
                if updated_order.filled_avg_price
                else current_price
            )

            filled_qty = (
                int(float(updated_order.filled_qty))
                if updated_order.filled_qty
                else position_size
            )

            update_event(
                event_id=event_id,
                status="FILLED",
                order_id=order_id,
                client_order_id=client_order_id
            )

            print(f"Precio ejecutado: ${filled_price:.2f}")
            print(f"Cantidad ejecutada: {filled_qty}")
            print("DATABASE: FILLED")

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

            print(f"DATABASE: {order_status}")
            print("La orden NO quedo abierta.")

        else:

            print("La orden aun no tiene estado final.")
            print("DATABASE: ORDER_SUBMITTED")

    except Exception as error:

        print()
        print("NO SE PUDO VERIFICAR EL ESTADO DE LA ORDEN")
        print(str(error))
        print("La orden original permanece registrada.")

    # =========================
    # RESULTADO FINAL
    # =========================

    print()
    print("=== DATABASE ===")

    saved_event = get_event_by_order_id(order_id)

    if saved_event:

        print(f"Evento encontrado: #{saved_event['id']}")
        print(f"Estado: {saved_event['status']}")
        print(f"Order ID: {saved_event['order_id']}")

    else:

        print("No se encontro el evento en la base de datos.")

    print()
    print("=== SEGURIDAD ===")
    print("ORDEN ENVIADA SOLAMENTE A ALPACA PAPER")
    print("NO ES DINERO REAL")
    print("STOP LOSS ASOCIADO A LA ORDEN")
    print()

    print("==============================================")
    print("          CICLO COMPLETADO")
    print("==============================================")


if __name__ == "__main__":
    main()
