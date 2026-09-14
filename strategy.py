def calculate_signal(price, moving_average):
    if price > moving_average:
        return "COMPRAR"

    if price < moving_average:
        return "VENDER"

    return "ESPERAR"


def risk_check(signal):
    allowed_signals = ["COMPRAR", "VENDER", "ESPERAR"]

    if signal not in allowed_signals:
        return "RECHAZAR"

    # Por ahora ninguna señal puede ejecutar órdenes.
    return "ANALISIS"


if __name__ == "__main__":
    print("=== AI TRADER — STRATEGY ENGINE ===")

    price = 318.25
    moving_average = 315.00

    signal = calculate_signal(price, moving_average)
    result = risk_check(signal)

    print(f"Precio: ${price}")
    print(f"Media móvil: ${moving_average}")
    print(f"Señal: {signal}")
    print(f"Resultado: {result}")
    print("ÓRDENES: DESACTIVADAS")
