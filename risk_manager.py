MAX_RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.03
MAX_TRADES_PER_DAY = 5


def calculate_position_size(account_value, entry_price, stop_price):
    risk_amount = account_value * MAX_RISK_PER_TRADE

    risk_per_share = abs(entry_price - stop_price)

    if risk_per_share <= 0:
        return 0

    shares = risk_amount / risk_per_share

    return int(shares)


def risk_check(
    signal,
    account_value,
    entry_price,
    stop_price,
    daily_loss,
    trades_today
):
    if signal not in ["COMPRAR", "VENDER", "ESPERAR"]:
        return False, "SEÑAL NO VÁLIDA"

    if signal == "ESPERAR":
        return False, "SIN OPERACIÓN"

    if account_value <= 0:
        return False, "CUENTA INVÁLIDA"

    if daily_loss >= account_value * MAX_DAILY_LOSS:
        return False, "LÍMITE DE PÉRDIDA DIARIA ALCANZADO"

    if trades_today >= MAX_TRADES_PER_DAY:
        return False, "LÍMITE DE OPERACIONES ALCANZADO"

    if stop_price <= 0 or entry_price <= 0:
        return False, "PRECIO INVÁLIDO"

    position_size = calculate_position_size(
        account_value,
        entry_price,
        stop_price
    )

    if position_size <= 0:
        return False, "TAMAÑO DE POSICIÓN INVÁLIDO"

    return True, f"RIESGO APROBADO — {position_size} ACCIONES"


if __name__ == "__main__":
    print("=== AI TRADER — RISK MANAGER ===")

    account_value = 100000
    entry_price = 333.00
    stop_price = 323.00

    approved, message = risk_check(
        signal="COMPRAR",
        account_value=account_value,
        entry_price=entry_price,
        stop_price=stop_price,
        daily_loss=0,
        trades_today=0
    )

    print(f"Autorización: {approved}")
    print(message)
