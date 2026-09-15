import os

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus


def main():
    api_key = os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not api_secret:
        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY"
        )

    print("==============================================")
    print("       AI TRADER — PAPER ORDERS CHECK")
    print("==============================================")
    print("Conectando con Alpaca Paper...")

    client = TradingClient(
        api_key,
        api_secret,
        paper=True
    )

    print("Conexión: OK")
    print()
    print("Consultando últimas órdenes...")
    print("----------------------------------------------")

    request = GetOrdersRequest(
        status=QueryOrderStatus.ALL,
        limit=10,
        nested=True
    )

    orders = client.get_orders(filter=request)

    if not orders:
        print("No hay órdenes registradas.")
    else:
        print(f"Órdenes encontradas: {len(orders)}")
        print()

        for order in orders:
            print("==============================================")
            print(f"ID: {order.id}")
            print(f"Símbolo: {order.symbol}")
            print(f"Lado: {order.side}")
            print(f"Cantidad solicitada: {order.qty}")
            print(f"Cantidad ejecutada: {order.filled_qty}")
            print(f"Estado: {order.status}")
            print(f"Tipo: {order.type}")
            print(f"Time in force: {order.time_in_force}")
            print(f"Enviada: {order.submitted_at}")
            print(f"Ejecutada: {order.filled_at}")
            print(f"Cancelada: {order.canceled_at}")
            print(f"Precio promedio ejecutado: {order.filled_avg_price}")

    print()
    print("==============================================")
    print("CONSULTA COMPLETADA")
    print("NO SE ENVIARON ÓRDENES")
    print("NO SE CANCELARON ÓRDENES")
    print("==============================================")


if __name__ == "__main__":
    main()
