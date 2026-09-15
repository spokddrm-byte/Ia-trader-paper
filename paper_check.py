import os

from alpaca.trading.client import TradingClient


def main():
    api_key = os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not api_secret:
        raise RuntimeError(
            "FALTAN APCA_API_KEY_ID O APCA_API_SECRET_KEY"
        )

    client = TradingClient(
        api_key,
        api_secret,
        paper=True
    )

    print("==============================================")
    print("       AI TRADER — PAPER ACCOUNT CHECK")
    print("==============================================")

    account = client.get_account()

    print(f"Capital: ${float(account.equity):,.2f}")
    print(f"Efectivo: ${float(account.cash):,.2f}")
    print(f"Buying Power: ${float(account.buying_power):,.2f}")

    positions = client.get_all_positions()

    print()
    print(f"POSICIONES ABIERTAS: {len(positions)}")
    print("----------------------------------------------")

    if not positions:
        print("No hay posiciones abiertas.")
    else:
        for position in positions:
            print(f"Símbolo: {position.symbol}")
            print(f"Cantidad: {position.qty}")
            print(f"Precio promedio: ${float(position.avg_entry_price):,.2f}")
            print(f"Precio actual: ${float(position.current_price):,.2f}")
            print(f"Valor de mercado: ${float(position.market_value):,.2f}")
            print(f"P/L: ${float(position.unrealized_pl):,.2f}")
            print(f"P/L %: {float(position.unrealized_plpc) * 100:.2f}%")
            print("----------------------------------------------")

    print("==============================================")
    print("LECTURA DE CUENTA: COMPLETADA")
    print("NO SE ENVIARON ÓRDENES")
    print("==============================================")


if __name__ == "__main__":
    main()
