import os

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest


def main():
    api_key = os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not api_secret:
        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY"
        )

    print("==============================================")
    print("     AI TRADER — PAPER ORDER TEST")
    print("==============================================")

    client = TradingClient(
        api_key,
        api_secret,
        paper=True
    )

    print("Conexión con Alpaca Paper: OK")

    order_request = MarketOrderRequest(
        symbol="AAPL",
        qty=1,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY
    )

    print("Enviando orden Paper...")
    print("Símbolo: AAPL")
    print("Cantidad: 1")
    print("Lado: COMPRA")

    order = client.submit_order(order_data=order_request)

    print()
    print("==============================================")
    print("ORDEN ENVIADA CORRECTAMENTE")
    print("==============================================")
    print(f"ID: {order.id}")
    print(f"Estado: {order.status}")
    print(f"Símbolo: {order.symbol}")
    print(f"Cantidad: {order.qty}")
    print("==============================================")


if __name__ == "__main__":
    main()
