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
