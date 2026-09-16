# ============================================================
# AI TRADER — RISK MANAGER V3
# ============================================================
#
# OBJETIVO:
#   Controlar el riesgo antes de que cualquier orden llegue
#   a Alpaca.
#
# PRINCIPIOS:
#   - Riesgo máximo por operación
#   - Riesgo máximo de cartera
#   - Pérdida máxima diaria
#   - Límite de operaciones
#   - Límite de posiciones
#   - Límite de capital por posición
#   - Límite de exposición total
#   - Límite de concentración por símbolo
#   - Comprobación de buying power
#   - Validación del stop loss
#   - Cálculo detallado de riesgo
#
# ============================================================


# ============================================================
# CONFIGURACIÓN CENTRAL
# ============================================================

# ------------------------------------------------------------
# RIESGO POR OPERACIÓN
# ------------------------------------------------------------

MAX_RISK_PER_TRADE = 0.01
# 1% máximo de riesgo teórico por operación.


# ------------------------------------------------------------
# RIESGO TOTAL DE CARTERA
# ------------------------------------------------------------

MAX_PORTFOLIO_RISK = 0.03
# Máximo 3% de riesgo teórico acumulado.


# ------------------------------------------------------------
# PÉRDIDA DIARIA
# ------------------------------------------------------------

MAX_DAILY_LOSS = 0.03
# El bot deja de abrir operaciones al alcanzar 3% de pérdida
# diaria.


# ------------------------------------------------------------
# OPERACIONES
# ------------------------------------------------------------

MAX_TRADES_PER_DAY = 5


# ------------------------------------------------------------
# POSICIONES
# ------------------------------------------------------------

MAX_OPEN_POSITIONS = 5


# ------------------------------------------------------------
# CAPITAL POR POSICIÓN
# ------------------------------------------------------------

MAX_POSITION_VALUE = 0.20
# Una posición individual no puede representar más del 20%
# del equity.


# ------------------------------------------------------------
# EXPOSICIÓN TOTAL
# ------------------------------------------------------------

MAX_TOTAL_EXPOSURE = 0.70
# Como máximo 70% del equity puede estar comprometido
# en posiciones LONG.


# ------------------------------------------------------------
# CONCENTRACIÓN POR SÍMBOLO
# ------------------------------------------------------------

MAX_SYMBOL_EXPOSURE = 0.20


# ------------------------------------------------------------
# STOP LOSS
# ------------------------------------------------------------

MIN_STOP_DISTANCE = 0.005
# 0.5% mínimo de distancia.

MAX_STOP_DISTANCE = 0.10
# 10% máximo de distancia.


# ------------------------------------------------------------
# CAPITAL MÍNIMO PARA OPERAR
# ------------------------------------------------------------

MIN_ACCOUNT_VALUE = 100.0


# ============================================================
# UTILIDADES
# ============================================================

def _safe_float(value, default=0.0):
    """
    Convierte un valor a float de forma segura.
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    """
    Convierte un valor a int de forma segura.
    """

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ============================================================
# VALIDAR PRECIOS
# ============================================================

def validate_prices(entry_price, stop_price):
    """
    Valida entrada y stop.

    Devuelve:

        True, mensaje

    o:

        False, motivo
    """

    entry_price = _safe_float(entry_price)
    stop_price = _safe_float(stop_price)

    if entry_price <= 0:
        return False, "PRECIO DE ENTRADA INVÁLIDO"

    if stop_price <= 0:
        return False, "STOP LOSS INVÁLIDO"

    if entry_price == stop_price:
        return False, "ENTRADA Y STOP SON IGUALES"

    # Este bot actualmente trabaja LONG.
    if stop_price >= entry_price:
        return (
            False,
            "STOP LONG DEBE ESTAR DEBAJO DE LA ENTRADA"
        )

    stop_distance = (
        entry_price - stop_price
    ) / entry_price

    if stop_distance < MIN_STOP_DISTANCE:
        return (
            False,
            "STOP DEMASIADO CERCANO"
        )

    if stop_distance > MAX_STOP_DISTANCE:
        return (
            False,
            "STOP DEMASIADO ALEJADO"
        )

    return True, "PRECIOS VÁLIDOS"


# ============================================================
# RIESGO MONETARIO DISPONIBLE
# ============================================================

def get_risk_budget(account_value):
    """
    Dinero máximo que puede arriesgarse en una operación.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    return (
        account_value
        * MAX_RISK_PER_TRADE
    )


# ============================================================
# RIESGO DIARIO MÁXIMO
# ============================================================

def get_daily_loss_limit(account_value):
    """
    Límite monetario de pérdida diaria.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    return (
        account_value
        * MAX_DAILY_LOSS
    )


# ============================================================
# RIESGO MÁXIMO DE CARTERA
# ============================================================

def get_portfolio_risk_limit(account_value):
    """
    Riesgo monetario máximo permitido para toda la cartera.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    return (
        account_value
        * MAX_PORTFOLIO_RISK
    )


# ============================================================
# CAPITAL MÁXIMO POR POSICIÓN
# ============================================================

def get_max_position_value(account_value):
    """
    Valor máximo permitido para una posición individual.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    return (
        account_value
        * MAX_POSITION_VALUE
    )


# ============================================================
# EXPOSICIÓN MÁXIMA TOTAL
# ============================================================

def get_max_total_exposure(account_value):
    """
    Valor máximo permitido de posiciones abiertas.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    return (
        account_value
        * MAX_TOTAL_EXPOSURE
    )


# ============================================================
# RIESGO DE UNA POSICIÓN
# ============================================================

def calculate_trade_risk(
    position_size,
    entry_price,
    stop_price
):
    """
    Riesgo monetario aproximado si el precio llega al stop.
    """

    position_size = _safe_int(position_size)
    entry_price = _safe_float(entry_price)
    stop_price = _safe_float(stop_price)

    if position_size <= 0:
        return 0.0

    if entry_price <= 0:
        return 0.0

    if stop_price <= 0:
        return 0.0

    risk_per_share = (
        entry_price - stop_price
    )

    if risk_per_share <= 0:
        return 0.0

    return (
        position_size
        * risk_per_share
    )


# ============================================================
# RIESGO PORCENTUAL
# ============================================================

def calculate_trade_risk_percent(
    account_value,
    position_size,
    entry_price,
    stop_price
):
    """
    Riesgo de una operación como porcentaje del equity.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    trade_risk = calculate_trade_risk(
        position_size,
        entry_price,
        stop_price
    )

    return (
        trade_risk
        / account_value
    )


# ============================================================
# VALOR DE POSICIÓN
# ============================================================

def calculate_position_value(
    position_size,
    entry_price
):
    """
    Valor monetario de una posición.
    """

    position_size = _safe_int(position_size)
    entry_price = _safe_float(entry_price)

    if position_size <= 0 or entry_price <= 0:
        return 0.0

    return (
        position_size
        * entry_price
    )


# ============================================================
# EXPOSICIÓN PORCENTUAL
# ============================================================

def calculate_exposure_percent(
    account_value,
    position_size,
    entry_price
):
    """
    Exposición de una posición respecto al equity.
    """

    account_value = _safe_float(account_value)

    if account_value <= 0:
        return 0.0

    position_value = calculate_position_value(
        position_size,
        entry_price
    )

    return (
        position_value
        / account_value
    )


# ============================================================
# TAMAÑO DE POSICIÓN
# ============================================================

def calculate_position_size(
    account_value,
    entry_price,
    stop_price,
    risk_percent=MAX_RISK_PER_TRADE,
    max_position_percent=MAX_POSITION_VALUE,
    buying_power=None
):
    """
    Calcula el tamaño máximo de una posición.

    El resultado queda limitado por:

        1. Riesgo monetario
        2. Exposición máxima individual
        3. Buying power, si se proporciona
    """

    account_value = _safe_float(account_value)
    entry_price = _safe_float(entry_price)
    stop_price = _safe_float(stop_price)

    if account_value < MIN_ACCOUNT_VALUE:
        return 0

    if entry_price <= 0:
        return 0

    if stop_price <= 0:
        return 0

    if risk_percent <= 0:
        return 0

    if max_position_percent <= 0:
        return 0

    valid, _ = validate_prices(
        entry_price,
        stop_price
    )

    if not valid:
        return 0

    # --------------------------------------------------------
    # LÍMITE POR RIESGO
    # --------------------------------------------------------

    risk_amount = (
        account_value
        * risk_percent
    )

    risk_per_share = (
        entry_price
        - stop_price
    )

    if risk_per_share <= 0:
        return 0

    shares_by_risk = (
        risk_amount
        / risk_per_share
    )

    # --------------------------------------------------------
    # LÍMITE POR CAPITAL
    # --------------------------------------------------------

    max_position_value = (
        account_value
        * max_position_percent
    )

    shares_by_position_value = (
        max_position_value
        / entry_price
    )

    # --------------------------------------------------------
    # LÍMITE POR BUYING POWER
    # --------------------------------------------------------

    limits = [
        shares_by_risk,
        shares_by_position_value
    ]

    if buying_power is not None:

        buying_power = _safe_float(
            buying_power
        )

        if buying_power <= 0:
            return 0

        shares_by_buying_power = (
            buying_power
            / entry_price
        )

        limits.append(
            shares_by_buying_power
        )

    shares = min(limits)

    return max(
        0,
        int(shares)
    )


# ============================================================
# RIESGO DE CARTERA
# ============================================================

def calculate_portfolio_risk(
    account_value,
    positions
):
    """
    Calcula el riesgo total de las posiciones.

    Cada posición puede contener:

        symbol
        position_size
        entry_price
        stop_price

    También acepta aliases comunes:

        qty
        avg_entry_price
    """

    account_value = _safe_float(
        account_value
    )

    if account_value <= 0:
        return 0.0

    total_risk = 0.0

    for position in positions:

        position_size = position.get(
            "position_size",
            position.get("qty", 0)
        )

        entry_price = position.get(
            "entry_price",
            position.get("avg_entry_price", 0)
        )

        stop_price = position.get(
            "stop_price",
            0
        )

        total_risk += calculate_trade_risk(
            position_size,
            entry_price,
            stop_price
        )

    return (
        total_risk
        / account_value
    )


# ============================================================
# EXPOSICIÓN TOTAL
# ============================================================

def calculate_total_exposure(
    account_value,
    positions
):
    """
    Calcula la exposición total de la cartera.
    """

    account_value = _safe_float(
        account_value
    )

    if account_value <= 0:
        return 0.0

    total_value = 0.0

    for position in positions:

        position_size = position.get(
            "position_size",
            position.get("qty", 0)
        )

        entry_price = position.get(
            "entry_price",
            position.get("avg_entry_price", 0)
        )

        total_value += calculate_position_value(
            position_size,
            entry_price
        )

    return (
        total_value
        / account_value
    )


# ============================================================
# EXPOSICIÓN DE UN SÍMBOLO
# ============================================================

def symbol_exposure_check(
    account_value,
    symbol,
    position_size,
    entry_price,
    existing_symbol_value=0.0
):
    """
    Comprueba que un símbolo no concentre demasiado capital.
    """

    account_value = _safe_float(
        account_value
    )

    existing_symbol_value = _safe_float(
        existing_symbol_value
    )

    new_value = calculate_position_value(
        position_size,
        entry_price
    )

    projected_value = (
        existing_symbol_value
        + new_value
    )

    if account_value <= 0:
        return False, "CUENTA INVÁLIDA"

    projected_exposure = (
        projected_value
        / account_value
    )

    if projected_exposure > MAX_SYMBOL_EXPOSURE:

        return (
            False,
            (
                f"EXPOSICIÓN DE {symbol} "
                f"SUPERA EL LÍMITE"
            )
        )

    return (
        True,
        (
            f"EXPOSICIÓN {symbol}: "
            f"{projected_exposure * 100:.2f}%"
        )
    )


# ============================================================
# CHECK DE CARTERA
# ============================================================

def portfolio_risk_check(
    account_value,
    current_portfolio_risk,
    new_trade_risk,
    current_exposure=0.0,
    new_position_value=0.0,
    open_positions=0
):
    """
    Comprueba si una nueva posición puede entrar
    en la cartera.
    """

    account_value = _safe_float(
        account_value
    )

    current_portfolio_risk = _safe_float(
        current_portfolio_risk
    )

    new_trade_risk = _safe_float(
        new_trade_risk
    )

    current_exposure = _safe_float(
        current_exposure
    )

    new_position_value = _safe_float(
        new_position_value
    )

    open_positions = _safe_int(
        open_positions
    )

    if account_value <= 0:
        return False, "CUENTA INVÁLIDA"

    # --------------------------------------------------------
    # POSICIONES
    # --------------------------------------------------------

    if open_positions >= MAX_OPEN_POSITIONS:

        return (
            False,
            "MÁXIMO DE POSICIONES ALCANZADO"
        )

    # --------------------------------------------------------
    # RIESGO
    # --------------------------------------------------------

    projected_risk = (
        current_portfolio_risk
        + new_trade_risk
    )

    if projected_risk > MAX_PORTFOLIO_RISK:

        return (
            False,
            (
                "RIESGO MÁXIMO DE CARTERA "
                "ALCANZADO"
            )
        )

    # --------------------------------------------------------
    # EXPOSICIÓN
    # --------------------------------------------------------

    projected_exposure = (
        current_exposure
        + (
            new_position_value
            / account_value
        )
    )

    if projected_exposure > MAX_TOTAL_EXPOSURE:

        return (
            False,
            (
                "EXPOSICIÓN TOTAL "
                "DE CARTERA ALCANZADA"
            )
        )

    return (
        True,
        (
            "CARTERA APROBADA | "
            f"Riesgo proyectado: "
            f"{projected_risk * 100:.2f}% | "
            f"Exposición proyectada: "
            f"{projected_exposure * 100:.2f}%"
        )
    )


# ============================================================
# RISK CHECK PRINCIPAL
# ============================================================

def risk_check(
    signal,
    account_value,
    entry_price,
    stop_price,
    daily_loss,
    trades_today,
    current_portfolio_risk=0.0,
    open_positions=0,
    current_exposure=0.0,
    buying_power=None,
    existing_symbol_value=0.0
):
    """
    AUTORIZACIÓN FINAL.

    Esta función NO manda órdenes.

    Solamente responde:

        ¿Está permitido intentar esta operación?

    """

    # ========================================================
    # SEÑAL
    # ========================================================

    if signal not in [
        "COMPRAR",
        "VENDER",
        "ESPERAR"
    ]:

        return (
            False,
            "SEÑAL NO VÁLIDA"
        )

    if signal == "ESPERAR":

        return (
            False,
            "SIN OPERACIÓN"
        )

    # ========================================================
    # CUENTA
    # ========================================================

    account_value = _safe_float(
        account_value
    )

    if account_value < MIN_ACCOUNT_VALUE:

        return (
            False,
            "CAPITAL INSUFICIENTE"
        )

    # ========================================================
    # PRECIOS
    # ========================================================

    valid, message = validate_prices(
        entry_price,
        stop_price
    )

    if not valid:
        return False, message

    # ========================================================
    # PÉRDIDA DIARIA
    # ========================================================

    daily_loss = _safe_float(
        daily_loss
    )

    daily_limit = get_daily_loss_limit(
        account_value
    )

    if daily_loss >= daily_limit:

        return (
            False,
            (
                "LÍMITE DE PÉRDIDA DIARIA "
                "ALCANZADO"
            )
        )

    # ========================================================
    # OPERACIONES
    # ========================================================

    trades_today = _safe_int(
        trades_today
    )

    if trades_today >= MAX_TRADES_PER_DAY:

        return (
            False,
            "LÍMITE DE OPERACIONES DIARIAS ALCANZADO"
        )

    # ========================================================
    # POSICIONES
    # ========================================================

    open_positions = _safe_int(
        open_positions
    )

    if open_positions >= MAX_OPEN_POSITIONS:

        return (
            False,
            "MÁXIMO DE POSICIONES ABIERTAS ALCANZADO"
        )

    # ========================================================
    # TAMAÑO
    # ========================================================

    position_size = calculate_position_size(
        account_value=account_value,
        entry_price=entry_price,
        stop_price=stop_price,
        buying_power=buying_power
    )

    if position_size <= 0:

        return (
            False,
            "TAMAÑO DE POSICIÓN INVÁLIDO"
        )

    # ========================================================
    # VALOR DE POSICIÓN
    # ========================================================

    new_position_value = calculate_position_value(
        position_size,
        entry_price
    )

    # ========================================================
    # BUYING POWER
    # ========================================================

    if buying_power is not None:

        buying_power = _safe_float(
            buying_power
        )

        if new_position_value > buying_power:

            return (
                False,
                "BUYING POWER INSUFICIENTE"
            )

    # ========================================================
    # RIESGO DE OPERACIÓN
    # ========================================================

    new_trade_risk = (
        calculate_trade_risk_percent(
            account_value=account_value,
            position_size=position_size,
            entry_price=entry_price,
            stop_price=stop_price
        )
    )

    if new_trade_risk > MAX_RISK_PER_TRADE:

        return (
            False,
            "RIESGO POR OPERACIÓN DEMASIADO ALTO"
        )

    # ========================================================
    # RIESGO DE CARTERA
    # ========================================================

    approved, message = portfolio_risk_check(
        account_value=account_value,
        current_portfolio_risk=current_portfolio_risk,
        new_trade_risk=new_trade_risk,
        current_exposure=current_exposure,
        new_position_value=new_position_value,
        open_positions=open_positions
    )

    if not approved:

        return False, message

    # ========================================================
    # CONCENTRACIÓN DEL SÍMBOLO
    # ========================================================

    symbol_ok, symbol_message = (
        symbol_exposure_check(
            account_value=account_value,
            symbol="ACTIVO",
            position_size=position_size,
            entry_price=entry_price,
            existing_symbol_value=existing_symbol_value
        )
    )

    if not symbol_ok:

        return False, symbol_message

    # ========================================================
    # AUTORIZADO
    # ========================================================

    risk_amount = calculate_trade_risk(
        position_size,
        entry_price,
        stop_price
    )

    projected_risk = (
        current_portfolio_risk
        + new_trade_risk
    )

    projected_exposure = (
        current_exposure
        + (
            new_position_value
            / account_value
        )
    )

    return (
        True,
        (
            "RIESGO APROBADO | "
            f"Acciones: {position_size} | "
            f"Capital posición: "
            f"${new_position_value:,.2f} | "
            f"Riesgo: ${risk_amount:,.2f} "
            f"({new_trade_risk * 100:.2f}%) | "
            f"Riesgo cartera: "
            f"{projected_risk * 100:.2f}% | "
            f"Exposición: "
            f"{projected_exposure * 100:.2f}%"
        )
    )


# ============================================================
# DIAGNÓSTICO COMPLETO
# ============================================================

def get_risk_limits(account_value):
    """
    Devuelve todos los límites monetarios importantes
    para que main.py pueda mostrarlos.
    """

    account_value = _safe_float(
        account_value
    )

    return {
        "account_value": account_value,

        "risk_per_trade": (
            account_value
            * MAX_RISK_PER_TRADE
        ),

        "portfolio_risk": (
            account_value
            * MAX_PORTFOLIO_RISK
        ),

        "daily_loss_limit": (
            account_value
            * MAX_DAILY_LOSS
        ),

        "max_position_value": (
            account_value
            * MAX_POSITION_VALUE
        ),

        "max_total_exposure": (
            account_value
            * MAX_TOTAL_EXPOSURE
        ),

        "max_open_positions": (
            MAX_OPEN_POSITIONS
        ),

        "max_trades_per_day": (
            MAX_TRADES_PER_DAY
        )
    }


# ============================================================
# PRUEBA DEL MÓDULO
# ============================================================

if __name__ == "__main__":

    print()
    print("================================================")
    print("       AI TRADER — RISK MANAGER V3")
    print("================================================")
    print()

    account_value = 100000.00
    entry_price = 333.00
    stop_price = 323.00
    buying_power = 360000.00

    # --------------------------------------------------------
    # LÍMITES
    # --------------------------------------------------------

    limits = get_risk_limits(
        account_value
    )

    print("=== LÍMITES ===")
    print(
        f"Capital: "
        f"${limits['account_value']:,.2f}"
    )

    print(
        f"Riesgo por operación: "
        f"${limits['risk_per_trade']:,.2f}"
    )

    print(
        f"Riesgo máximo cartera: "
        f"${limits['portfolio_risk']:,.2f}"
    )

    print(
        f"Pérdida diaria máxima: "
        f"${limits['daily_loss_limit']:,.2f}"
    )

    print(
        f"Máximo por posición: "
        f"${limits['max_position_value']:,.2f}"
    )

    print(
        f"Exposición máxima: "
        f"${limits['max_total_exposure']:,.2f}"
    )

    print(
        f"Máximo posiciones: "
        f"{limits['max_open_positions']}"
    )

    print(
        f"Máximo operaciones/día: "
        f"{limits['max_trades_per_day']}"
    )

    print()

    # --------------------------------------------------------
    # TAMAÑO
    # --------------------------------------------------------

    position_size = calculate_position_size(
        account_value=account_value,
        entry_price=entry_price,
        stop_price=stop_price,
        buying_power=buying_power
    )

    position_value = calculate_position_value(
        position_size,
        entry_price
    )

    trade_risk = calculate_trade_risk(
        position_size,
        entry_price,
        stop_price
    )

    trade_risk_percent = (
        calculate_trade_risk_percent(
            account_value,
            position_size,
            entry_price,
            stop_price
        )
    )

    print("=== POSICIÓN CALCULADA ===")

    print(
        f"Acciones: "
        f"{position_size}"
    )

    print(
        f"Valor: "
        f"${position_value:,.2f}"
    )

    print(
        f"Riesgo al stop: "
        f"${trade_risk:,.2f}"
    )

    print(
        f"Riesgo porcentual: "
        f"{trade_risk_percent * 100:.2f}%"
    )

    print()

    # --------------------------------------------------------
    # AUTORIZACIÓN
    # --------------------------------------------------------

    approved, message = risk_check(
        signal="COMPRAR",
        account_value=account_value,
        entry_price=entry_price,
        stop_price=stop_price,
        daily_loss=0.0,
        trades_today=0,
        current_portfolio_risk=0.0,
        open_positions=0,
        current_exposure=0.0,
        buying_power=buying_power,
        existing_symbol_value=0.0
    )

    print("=== AUTORIZACIÓN ===")
    print(
        f"Autorización: "
        f"{approved}"
    )

    print(message)

    print()
    print("================================================")
    print("       RISK MANAGER V3 OPERATIVO")
    print("================================================")
