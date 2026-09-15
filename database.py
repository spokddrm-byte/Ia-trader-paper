import os
import sqlite3
from datetime import datetime, timezone


# =========================
# CONFIGURACIÓN
# =========================

DB_PATH = os.getenv("DATABASE_PATH", "trade_history.db")


# =========================
# CONEXIÓN
# =========================

def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


# =========================
# CREAR / ACTUALIZAR BASE
# =========================

def initialize_database():
    connection = get_connection()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS trade_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_price REAL NOT NULL,
            position_size INTEGER NOT NULL,
            status TEXT NOT NULL,
            profit_loss REAL NOT NULL DEFAULT 0.0,
            order_id TEXT,
            client_order_id TEXT
        )
    """)

    # Compatibilidad con una base de datos creada
    # por una versión anterior del bot.
    columns = connection.execute(
        "PRAGMA table_info(trade_events)"
    ).fetchall()

    column_names = {column["name"] for column in columns}

    if "order_id" not in column_names:
        connection.execute("""
            ALTER TABLE trade_events
            ADD COLUMN order_id TEXT
        """)

    if "client_order_id" not in column_names:
        connection.execute("""
            ALTER TABLE trade_events
            ADD COLUMN client_order_id TEXT
        """)

    connection.commit()
    connection.close()


# =========================
# REGISTRAR EVENTO
# =========================

def log_event(
    symbol,
    signal,
    entry_price,
    stop_price,
    position_size,
    status,
    profit_loss=0.0,
    order_id=None,
    client_order_id=None
):
    connection = get_connection()

    event = (
        datetime.now(timezone.utc).isoformat(),
        symbol,
        signal,
        float(entry_price),
        float(stop_price),
        int(position_size),
        status,
        float(profit_loss),
        str(order_id) if order_id else None,
        str(client_order_id) if client_order_id else None
    )

    cursor = connection.execute("""
        INSERT INTO trade_events (
            timestamp,
            symbol,
            signal,
            entry_price,
            stop_price,
            position_size,
            status,
            profit_loss,
            order_id,
            client_order_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, event)

    connection.commit()

    event_id = cursor.lastrowid

    connection.close()

    return event_id


# =========================
# ACTUALIZAR EVENTO
# =========================

def update_event(
    event_id,
    status=None,
    profit_loss=None,
    order_id=None,
    client_order_id=None
):
    connection = get_connection()

    updates = []
    values = []

    if status is not None:
        updates.append("status = ?")
        values.append(status)

    if profit_loss is not None:
        updates.append("profit_loss = ?")
        values.append(float(profit_loss))

    if order_id is not None:
        updates.append("order_id = ?")
        values.append(str(order_id))

    if client_order_id is not None:
        updates.append("client_order_id = ?")
        values.append(str(client_order_id))

    if not updates:
        connection.close()
        return False

    values.append(int(event_id))

    connection.execute(
        f"""
        UPDATE trade_events
        SET {", ".join(updates)}
        WHERE id = ?
        """,
        values
    )

    connection.commit()
    connection.close()

    return True


# =========================
# BUSCAR EVENTO POR ORDEN
# =========================

def get_event_by_order_id(order_id):
    connection = get_connection()

    row = connection.execute("""
        SELECT *
        FROM trade_events
        WHERE order_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (str(order_id),)).fetchone()

    connection.close()

    return dict(row) if row else None


# =========================
# EVENTOS DE HOY
# =========================

def get_today_events():
    today = datetime.now(timezone.utc).date().isoformat()

    connection = get_connection()

    rows = connection.execute("""
        SELECT *
        FROM trade_events
        WHERE timestamp LIKE ?
        ORDER BY id DESC
    """, (f"{today}%",)).fetchall()

    connection.close()

    return [dict(row) for row in rows]


# =========================
# OPERACIONES EJECUTADAS
# =========================

def get_today_trade_count():
    events = get_today_events()

    return sum(
        1
        for event in events
        if event["status"] in [
            "FILLED",
            "CLOSED",
            "STOPPED"
        ]
    )


# =========================
# PÉRDIDA DEL DÍA
# =========================

def get_today_loss():
    events = get_today_events()

    total_loss = 0.0

    for event in events:
        profit_loss = float(event["profit_loss"])

        if profit_loss < 0:
            total_loss += abs(profit_loss)

    return total_loss


# =========================
# RESULTADO DEL DÍA
# =========================

def get_today_profit_loss():
    events = get_today_events()

    return sum(
        float(event["profit_loss"])
        for event in events
        if event["status"] in [
            "CLOSED",
            "STOPPED"
        ]
    )


# =========================
# PRUEBA
# =========================

if __name__ == "__main__":

    print("=== AI TRADER - DATABASE ===")

    initialize_database()

    event_id = log_event(
        symbol="AAPL",
        signal="COMPRAR",
        entry_price=333.00,
        stop_price=323.01,
        position_size=100,
        status="SIGNAL_ONLY",
        profit_loss=0.0,
        order_id=None,
        client_order_id=None
    )

    print(f"Evento registrado: #{event_id}")

    events = get_today_events()

    print(f"Eventos de hoy: {len(events)}")
    print(f"Operaciones ejecutadas: {get_today_trade_count()}")
    print(f"Pérdida del día: ${get_today_loss():.2f}")
    print(f"Resultado del día: ${get_today_profit_loss():.2f}")

    print()
    print("BASE DE DATOS FUNCIONANDO 👽")
