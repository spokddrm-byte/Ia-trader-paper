import os

from alpaca.trading.client import TradingClient


def main():
    api_key = os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not api_secret:
        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID o APCA_API_SECRET_KEY EN RAILWAY"
        )

    print("==============================================")
    print("       AI TRADER — ALPACA PAPER TEST")
    print("==============================================")
    print("Conectando con Alpaca Paper...")

    client = TradingClient(
        api_key,
        api_secret,
        paper=True
    )

    account = client.get_account()

    print()
    print("CONEXIÓN EXITOSA")
    print("----------------------------------------------")
    print(f"Cuenta: {account.id}")
    print(f"Estado: {account.status}")
    print(f"Capital: ${float(account.equity):,.2f}")
    print(f"Buying Power: ${float(account.buying_power):,.2f}")
    print(f"Efectivo: ${float(account.cash):,.2f}")
    print("----------------------------------------------")
    print("ÓRDENES: DESACTIVADAS")
    print("NO SE HA ENVIADO NINGUNA ORDEN")
    print("==============================================")


if __name__ == "__main__":
    main()
