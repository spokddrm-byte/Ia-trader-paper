"""
============================================================
AI TRADER — DATABASE ENGINE
============================================================

Version: 5.0 OMNIPRESENT

Purpose:
    Persistent memory, trade lifecycle, position state,
    reconciliation, auditing, performance foundation and
    system telemetry.

IMPORTANT:
    - Never deletes existing trade history.
    - Alpaca remains the source of truth for real positions.
    - SQLite stores persistent bot state and historical evidence.
    - Designed to remain compatible with previous V3/V4 code.

Architecture:

    ALPACA
       │
       ▼
    EXECUTION
       │
       ├──────────────► trade_events
       │
       ├──────────────► position_state
       │
       ├──────────────► order_state
       │
       └──────────────► audit_log

    SYSTEM
       │
       ├──────────────► system_events
       ├──────────────► portfolio_snapshots
       └──────────────► reconciliation_log

============================================================
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List


# ============================================================
# CONFIGURATION
# ============================================================

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "trade_history.db"
)

DB_TIMEOUT = 30

SCHEMA_VERSION = 5

BOT_VERSION = os.getenv(
    "BOT_VERSION",
    "V5 OMNIPRESENT"
)


# ============================================================
# TIME
# ============================================================

def now_iso() -> str:
    """UTC timestamp with second precision."""

    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def today_prefix() -> str:
    """UTC date prefix."""

    return datetime.now(
        timezone.utc
    ).date().isoformat()


# ============================================================
# CONNECTION
# ============================================================

def get_connection():
    """
    Open a robust SQLite connection.

    WAL allows safer concurrent reads/writes.
    """

    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=DB_TIMEOUT
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn


# ============================================================
# JSON HELPERS
# ============================================================

def json_dumps(data: Any) -> Optional[str]:
    """Safely serialize metadata."""

    if data is None:
        return None

    try:
        return json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str
        )
    except Exception:
        return json.dumps(
            {"serialization_error": str(data)}
        )


def json_loads(data: Optional[str]) -> Any:
    """Safely deserialize metadata."""

    if not data:
        return None

    try:
        return json.loads(data)
    except Exception:
        return data


# ============================================================
# SCHEMA HELPERS
# ============================================================

def table_exists(
    conn,
    table_name: str
) -> bool:

    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name=?
        """,
        (table_name,)
    ).fetchone()

    return row is not None


def get_columns(
    conn,
    table_name: str
) -> set:

    if not table_exists(conn, table_name):
        return set()

    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {
        row["name"]
        for row in rows
    }


def add_column_if_missing(
    conn,
    table_name: str,
    column_name: str,
    column_type: str
):

    columns = get_columns(
        conn,
        table_name
    )

    if column_name not in columns:

        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {column_type}
            """
        )


# ============================================================
# INITIALIZATION / MIGRATION
# ============================================================

def initialize_database():
    """
    Create and migrate the database.

    Migration is additive:
    existing information is preserved.
    """

    conn = get_connection()

    try:

        cursor = conn.cursor()

        # ----------------------------------------------------
        # Schema metadata
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # Original trade_events table
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_events (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,

                symbol TEXT NOT NULL,

                signal TEXT,

                entry_price REAL,

                stop_price REAL,

                position_size REAL,

                status TEXT,

                profit_loss REAL,

                order_id TEXT,

                client_order_id TEXT
            )
            """
        )

        # ----------------------------------------------------
        # Upgrade legacy trade_events
        # ----------------------------------------------------

        legacy_columns = {

            "strategy_version": "TEXT",
            "reason": "TEXT",

            "event_type": "TEXT",
            "event_key": "TEXT",

            "entry_timestamp": "TEXT",
            "exit_timestamp": "TEXT",

            "exit_price": "REAL",

            "quantity": "REAL",

            "realized_pl": "REAL",
            "realized_pl_pct": "REAL",

            "unrealized_pl": "REAL",
            "unrealized_pl_pct": "REAL",

            "peak_price": "REAL",

            "original_stop": "REAL",
            "current_stop": "REAL",

            "state": "TEXT",

            "managed_by": "TEXT",

            "alpaca_order_id": "TEXT",
            "alpaca_client_order_id": "TEXT",

            "metadata": "TEXT",

            "last_update": "TEXT"
        }

        for column, column_type in legacy_columns.items():

            add_column_if_missing(
                conn,
                "trade_events",
                column,
                column_type
            )

        # ----------------------------------------------------
        # Position state
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS position_state (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                symbol TEXT NOT NULL UNIQUE,

                quantity REAL DEFAULT 0,

                entry_price REAL,

                current_price REAL,

                market_value REAL,

                original_stop REAL,

                current_stop REAL,

                peak_price REAL,

                unrealized_pl REAL,

                unrealized_pl_pct REAL,

                realized_pl REAL DEFAULT 0,

                realized_pl_pct REAL,

                state TEXT DEFAULT 'OPEN',

                entry_order_id TEXT,

                protective_order_id TEXT,

                strategy_version TEXT,

                managed_by TEXT,

                entry_timestamp TEXT,

                last_seen_alpaca TEXT,

                last_update TEXT,

                metadata TEXT,

                created_at TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # Order state
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS order_state (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                order_id TEXT NOT NULL UNIQUE,

                client_order_id TEXT,

                symbol TEXT NOT NULL,

                side TEXT,

                order_type TEXT,

                order_class TEXT,

                time_in_force TEXT,

                quantity REAL,

                filled_quantity REAL DEFAULT 0,

                limit_price REAL,

                stop_price REAL,

                status TEXT,

                submitted_at TEXT,

                filled_at TEXT,

                canceled_at TEXT,

                replaced_by_order_id TEXT,

                strategy_version TEXT,

                last_update TEXT,

                metadata TEXT,

                created_at TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # System events
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_events (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,

                event_type TEXT NOT NULL,

                severity TEXT DEFAULT 'INFO',

                symbol TEXT,

                message TEXT,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # Audit log
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,

                entity_type TEXT NOT NULL,

                entity_id TEXT,

                action TEXT NOT NULL,

                old_state TEXT,

                new_state TEXT,

                reason TEXT,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # Portfolio snapshots
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,

                equity REAL,

                cash REAL,

                buying_power REAL,

                market_value REAL,

                total_exposure REAL,

                portfolio_risk REAL,

                daily_pl REAL,

                open_positions INTEGER,

                open_orders INTEGER,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # Reconciliation
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_log (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,

                symbol TEXT,

                entity_type TEXT NOT NULL,

                local_state TEXT,

                alpaca_state TEXT,

                status TEXT NOT NULL,

                discrepancy TEXT,

                resolution TEXT,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # Indexes
        # ----------------------------------------------------

        indexes = [

            """
            CREATE INDEX IF NOT EXISTS
            idx_trade_symbol
            ON trade_events(symbol)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_trade_status
            ON trade_events(status)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_trade_state
            ON trade_events(state)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_trade_timestamp
            ON trade_events(timestamp)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_trade_order
            ON trade_events(order_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_trade_event_key
            ON trade_events(event_key)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_orders_symbol
            ON order_state(symbol)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_orders_status
            ON order_state(status)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_system_timestamp
            ON system_events(timestamp)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_audit_timestamp
            ON audit_log(timestamp)
            """,

            """
            CREATE INDEX IF NOT EXISTS
            idx_reconciliation_timestamp
            ON reconciliation_log(timestamp)
            """
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)

        # ----------------------------------------------------
        # Schema metadata
        # ----------------------------------------------------

        cursor.execute(
            """
            INSERT INTO schema_meta (
                key,
                value,
                updated_at
            )

            VALUES (
                'schema_version',
                ?,
                ?
            )

            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (
                str(SCHEMA_VERSION),
                now_iso()
            )
        )

        cursor.execute(
            """
            INSERT INTO schema_meta (
                key,
                value,
                updated_at
            )

            VALUES (
                'bot_version',
                ?,
                ?
            )

            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (
                BOT_VERSION,
                now_iso()
            )
        )

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# ============================================================
# EVENT KEY
# ============================================================

def make_event_key(
    event_type: str,
    symbol: Optional[str] = None,
    order_id: Optional[str] = None,
    extra: Optional[str] = None
) -> str:
    """
    Create deterministic event identifier.

    Prevents accidental duplicate records.
    """

    raw = "|".join(
        str(x or "")
        for x in [
            event_type,
            symbol,
            order_id,
            extra
        ]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# TRADE EVENT
# ============================================================

def log_event(
    symbol: str,
    signal: Optional[str] = None,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    position_size: Optional[float] = None,
    status: Optional[str] = None,
    profit_loss: Optional[float] = None,
    order_id: Optional[str] = None,
    client_order_id: Optional[str] = None,

    strategy_version: Optional[str] = None,
    reason: Optional[str] = None,

    entry_timestamp: Optional[str] = None,
    exit_timestamp: Optional[str] = None,

    exit_price: Optional[float] = None,
    quantity: Optional[float] = None,

    realized_pl: Optional[float] = None,
    realized_pl_pct: Optional[float] = None,

    peak_price: Optional[float] = None,

    current_stop: Optional[float] = None,
    original_stop: Optional[float] = None,

    state: Optional[str] = None,

    managed_by: Optional[str] = None,

    alpaca_order_id: Optional[str] = None,
    alpaca_client_order_id: Optional[str] = None,

    event_type: Optional[str] = None,

    metadata: Optional[Dict[str, Any]] = None,

    event_key: Optional[str] = None
) -> int:
    """
    Insert a trade event.

    Compatible with previous versions.

    Returns:
        Existing or newly created event ID.
    """

    timestamp = now_iso()

    if entry_timestamp is None and entry_price is not None:
        entry_timestamp = timestamp

    if quantity is None:
        quantity = position_size

    if realized_pl is None:
        realized_pl = profit_loss

    if state is None:
        state = status

    if event_type is None:
        event_type = status or signal or "EVENT"

    actual_order_id = (
        alpaca_order_id
        or order_id
    )

    actual_client_order_id = (
        alpaca_client_order_id
        or client_order_id
    )

    if event_key is None:

        event_key = make_event_key(
            event_type,
            symbol,
            actual_order_id,
            client_order_id
        )

    conn = get_connection()

    try:

        # ----------------------------------------------------
        # Idempotency check
        # ----------------------------------------------------

        existing = conn.execute(
            """
            SELECT id
            FROM trade_events
            WHERE event_key = ?
            LIMIT 1
            """,
            (event_key,)
        ).fetchone()

        if existing:

            return int(existing["id"])

        cursor = conn.cursor()

        cursor.execute(
            """
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
                client_order_id,

                strategy_version,
                reason,

                event_type,
                event_key,

                entry_timestamp,
                exit_timestamp,

                exit_price,
                quantity,

                realized_pl,
                realized_pl_pct,

                unrealized_pl,
                unrealized_pl_pct,

                peak_price,

                original_stop,
                current_stop,

                state,

                managed_by,

                alpaca_order_id,
                alpaca_client_order_id,

                metadata,

                last_update
            )

            VALUES (
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?,
                ?,
                ?,
                ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                timestamp,
                symbol,
                signal,

                entry_price,
                stop_price,
                position_size,

                status,
                profit_loss,

                order_id,
                client_order_id,

                strategy_version,
                reason,

                event_type,
                event_key,

                entry_timestamp,
                exit_timestamp,

                exit_price,
                quantity,

                realized_pl,
                realized_pl_pct,

                None,
                None,

                peak_price,

                original_stop,
                current_stop,

                state,

                managed_by,

                actual_order_id,
                actual_client_order_id,

                json_dumps(metadata),

                timestamp
            )
        )

        conn.commit()

        return int(cursor.lastrowid)

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# ============================================================
# UPDATE EVENT
# ============================================================

def update_event(
    event_id: int,
    **fields
) -> bool:
    """
    Update an existing event.

    Unknown fields are ignored.
    """

    allowed = {

        "symbol",
        "signal",

        "entry_price",
        "stop_price",
        "position_size",

        "status",
        "profit_loss",

        "order_id",
        "client_order_id",

        "strategy_version",
        "reason",

        "event_type",
        "event_key",

        "entry_timestamp",
        "exit_timestamp",

        "exit_price",
        "quantity",

        "realized_pl",
        "realized_pl_pct",

        "unrealized_pl",
        "unrealized_pl_pct",

        "peak_price",

        "original_stop",
        "current_stop",

        "state",

        "managed_by",

        "alpaca_order_id",
        "alpaca_client_order_id",

        "metadata"
    }

    updates = {}

    for key, value in fields.items():

        if key not in allowed:
            continue

        if key == "metadata":
            value = json_dumps(value)

        updates[key] = value

    if not updates:
        return False

    updates["last_update"] = now_iso()

    set_clause = ", ".join(
        f"{key} = ?"
        for key in updates
    )

    values = list(
        updates.values()
    )

    values.append(event_id)

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            f"""
            UPDATE trade_events
            SET {set_clause}
            WHERE id = ?
            """,
            values
        )

        conn.commit()

        return cursor.rowcount > 0

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# ============================================================
# ORDER STATE
# ============================================================

def upsert_order(
    order_id: str,
    symbol: str,
    client_order_id: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[str] = None,
    order_class: Optional[str] = None,
    time_in_force: Optional[str] = None,
    quantity: Optional[float] = None,
    filled_quantity: Optional[float] = None,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    status: Optional[str] = None,
    submitted_at: Optional[str] = None,
    filled_at: Optional[str] = None,
    canceled_at: Optional[str] = None,
    replaced_by_order_id: Optional[str] = None,
    strategy_version: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Insert or update an Alpaca order.
    """

    if not order_id:
        return False

    timestamp = now_iso()

    conn = get_connection()

    try:

        conn.execute(
            """
            INSERT INTO order_state (

                order_id,
                client_order_id,

                symbol,
                side,

                order_type,
                order_class,
                time_in_force,

                quantity,
                filled_quantity,

                limit_price,
                stop_price,

                status,

                submitted_at,
                filled_at,
                canceled_at,

                replaced_by_order_id,

                strategy_version,

                last_update,

                metadata,

                created_at
            )

            VALUES (
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?, ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )

            ON CONFLICT(order_id)
            DO UPDATE SET

                client_order_id =
                    COALESCE(
                        excluded.client_order_id,
                        order_state.client_order_id
                    ),

                symbol =
                    excluded.symbol,

                side =
                    COALESCE(
                        excluded.side,
                        order_state.side
                    ),

                order_type =
                    COALESCE(
                        excluded.order_type,
                        order_state.order_type
                    ),

                order_class =
                    COALESCE(
                        excluded.order_class,
                        order_state.order_class
                    ),

                time_in_force =
                    COALESCE(
                        excluded.time_in_force,
                        order_state.time_in_force
                    ),

                quantity =
                    COALESCE(
                        excluded.quantity,
                        order_state.quantity
                    ),

                filled_quantity =
                    COALESCE(
                        excluded.filled_quantity,
                        order_state.filled_quantity
                    ),

                limit_price =
                    COALESCE(
                        excluded.limit_price,
                        order_state.limit_price
                    ),

                stop_price =
                    COALESCE(
                        excluded.stop_price,
                        order_state.stop_price
                    ),

                status =
                    COALESCE(
                        excluded.status,
                        order_state.status
                    ),

                submitted_at =
                    COALESCE(
                        excluded.submitted_at,
                        order_state.submitted_at
                    ),

                filled_at =
                    COALESCE(
                        excluded.filled_at,
                        order_state.filled_at
                    ),

                canceled_at =
                    COALESCE(
                        excluded.canceled_at,
                        order_state.canceled_at
                    ),

                replaced_by_order_id =
                    COALESCE(
                        excluded.replaced_by_order_id,
                        order_state.replaced_by_order_id
                    ),

                strategy_version =
                    COALESCE(
                        excluded.strategy_version,
                        order_state.strategy_version
                    ),

                last_update =
                    excluded.last_update,

                metadata =
                    COALESCE(
                        excluded.metadata,
                        order_state.metadata
                    )
            """,
            (
                order_id,
                client_order_id,

                symbol,
                side,

                order_type,
                order_class,
                time_in_force,

                quantity,
                filled_quantity or 0,

                limit_price,
                stop_price,

                status,

                submitted_at,
                filled_at,
                canceled_at,

                replaced_by_order_id,

                strategy_version,

                timestamp,

                json_dumps(metadata),

                timestamp
            )
        )

        conn.commit()

        return True

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


def get_order(
    order_id: str
) -> Optional[Dict[str, Any]]:

    if not order_id:
        return None

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT *
            FROM order_state
            WHERE order_id = ?
            LIMIT 1
            """,
            (order_id,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)

        result["metadata"] = json_loads(
            result.get("metadata")
        )

        return result

    finally:

        conn.close()


# ============================================================
# POSITION STATE
# ============================================================

def upsert_position_state(
    symbol: str,

    quantity: Optional[float] = None,

    entry_price: Optional[float] = None,

    current_price: Optional[float] = None,

    market_value: Optional[float] = None,

    original_stop: Optional[float] = None,

    current_stop: Optional[float] = None,

    peak_price: Optional[float] = None,

    unrealized_pl: Optional[float] = None,

    unrealized_pl_pct: Optional[float] = None,

    realized_pl: Optional[float] = None,

    realized_pl_pct: Optional[float] = None,

    state: str = "OPEN",

    entry_order_id: Optional[str] = None,

    protective_order_id: Optional[str] = None,

    strategy_version: Optional[str] = None,

    managed_by: Optional[str] = None,

    entry_timestamp: Optional[str] = None,

    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Persistent state of an open position.
    """

    timestamp = now_iso()

    conn = get_connection()

    try:

        conn.execute(
            """
            INSERT INTO position_state (

                symbol,

                quantity,

                entry_price,
                current_price,
                market_value,

                original_stop,
                current_stop,

                peak_price,

                unrealized_pl,
                unrealized_pl_pct,

                realized_pl,
                realized_pl_pct,

                state,

                entry_order_id,
                protective_order_id,

                strategy_version,
                managed_by,

                entry_timestamp,

                last_seen_alpaca,
                last_update,

                metadata,

                created_at
            )

            VALUES (
                ?,
                ?,
                ?, ?, ?,
                ?, ?,
                ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?,
                ?, ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )

            ON CONFLICT(symbol)
            DO UPDATE SET

                quantity =
                    COALESCE(
                        excluded.quantity,
                        position_state.quantity
                    ),

                entry_price =
                    COALESCE(
                        excluded.entry_price,
                        position_state.entry_price
                    ),

                current_price =
                    COALESCE(
                        excluded.current_price,
                        position_state.current_price
                    ),

                market_value =
                    COALESCE(
                        excluded.market_value,
                        position_state.market_value
                    ),

                original_stop =
                    COALESCE(
                        excluded.original_stop,
                        position_state.original_stop
                    ),

                current_stop =
                    COALESCE(
                        excluded.current_stop,
                        position_state.current_stop
                    ),

                peak_price =
                    CASE

                        WHEN excluded.peak_price IS NULL
                            THEN position_state.peak_price

                        WHEN position_state.peak_price IS NULL
                            THEN excluded.peak_price

                        WHEN excluded.peak_price >
                             position_state.peak_price
                            THEN excluded.peak_price

                        ELSE position_state.peak_price

                    END,

                unrealized_pl =
                    COALESCE(
                        excluded.unrealized_pl,
                        position_state.unrealized_pl
                    ),

                unrealized_pl_pct =
                    COALESCE(
                        excluded.unrealized_pl_pct,
                        position_state.unrealized_pl_pct
                    ),

                realized_pl =
                    COALESCE(
                        excluded.realized_pl,
                        position_state.realized_pl
                    ),

                realized_pl_pct =
                    COALESCE(
                        excluded.realized_pl_pct,
                        position_state.realized_pl_pct
                    ),

                state =
                    COALESCE(
                        excluded.state,
                        position_state.state
                    ),

                entry_order_id =
                    COALESCE(
                        excluded.entry_order_id,
                        position_state.entry_order_id
                    ),

                protective_order_id =
                    COALESCE(
                        excluded.protective_order_id,
                        position_state.protective_order_id
                    ),

                strategy_version =
                    COALESCE(
                        excluded.strategy_version,
                        position_state.strategy_version
                    ),

                managed_by =
                    COALESCE(
                        excluded.managed_by,
                        position_state.managed_by
                    ),

                entry_timestamp =
                    COALESCE(
                        excluded.entry_timestamp,
                        position_state.entry_timestamp
                    ),

                last_seen_alpaca =
                    excluded.last_seen_alpaca,

                last_update =
                    excluded.last_update,

                metadata =
                    COALESCE(
                        excluded.metadata,
                        position_state.metadata
                    )
            """,
            (
                symbol,

                quantity,

                entry_price,
                current_price,
                market_value,

                original_stop,
                current_stop,

                peak_price,

                unrealized_pl,
                unrealized_pl_pct,

                realized_pl,
                realized_pl_pct,

                state,

                entry_order_id,
                protective_order_id,

                strategy_version,
                managed_by,

                entry_timestamp,

                timestamp,
                timestamp,

                json_dumps(metadata),

                timestamp
            )
        )

        conn.commit()

        return True

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


def get_position_state(
    symbol: str
) -> Optional[Dict[str, Any]]:

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT *
            FROM position_state
            WHERE symbol = ?
            LIMIT 1
            """,
            (symbol,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)

        result["metadata"] = json_loads(
            result.get("metadata")
        )

        return result

    finally:

        conn.close()


def get_all_open_position_states()
-> List[Dict[str, Any]]:

    conn = get_connection()

    try:

        rows = conn.execute(
            """
            SELECT *
            FROM position_state
            WHERE state = 'OPEN'
            ORDER BY symbol
            """
        ).fetchall()

        results = []

        for row in rows:

            result = dict(row)

            result["metadata"] = json_loads(
                result.get("metadata")
            )

            results.append(result)

        return results

    finally:

        conn.close()


def close_position_state(
    symbol: str,
    exit_price: Optional[float] = None,
    realized_pl: Optional[float] = None,
    realized_pl_pct: Optional[float] = None,
    state: str = "CLOSED"
) -> bool:

    timestamp = now_iso()

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE position_state

            SET

                current_price =
                    COALESCE(
                        ?,
                        current_price
                    ),

                unrealized_pl = NULL,

                unrealized_pl_pct = NULL,

                realized_pl =
                    COALESCE(
                        ?,
                        realized_pl
                    ),

                realized_pl_pct =
                    COALESCE(
                        ?,
                        realized_pl_pct
                    ),

                state = ?,

                last_update = ?

            WHERE symbol = ?
            """,
            (
                exit_price,
                realized_pl,
                realized_pl_pct,
                state,
                timestamp,
                symbol
            )
        )

        conn.commit()

        return cursor.rowcount > 0

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# ============================================================
# TRADE LOOKUPS
# ============================================================

def get_event_by_order_id(
    order_id: str
) -> Optional[Dict[str, Any]]:

    if not order_id:
        return None

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT *
            FROM trade_events

            WHERE order_id = ?
               OR alpaca_order_id = ?

            ORDER BY id DESC

            LIMIT 1
            """,
            (
                order_id,
                order_id
            )
        ).fetchone()

        return dict(row) if row else None

    finally:

        conn.close()


def get_open_position_event(
    symbol: str
) -> Optional[Dict[str, Any]]:

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT *
            FROM trade_events

            WHERE symbol = ?

              AND (

                    state IN (
                        'OPEN',
                        'POSITION_OPEN',
                        'FILLED'
                    )

                    OR

                    status IN (
                        'OPEN',
                        'POSITION_OPEN',
                        'FILLED'
                    )

                  )

            ORDER BY id DESC

            LIMIT 1
            """,
            (symbol,)
        ).fetchone()

        return dict(row) if row else None

    finally:

        conn.close()


# ============================================================
# CLOSE TRADE
# ============================================================

def close_position_event(
    symbol: str,
    exit_price: Optional[float] = None,
    profit_loss: Optional[float] = None,
    status: str = "CLOSED",
    reason: Optional[str] = None,
    realized_pl_pct: Optional[float] = None
) -> bool:

    event = get_open_position_event(
        symbol
    )

    if not event:
        return False

    event_id = event["id"]

    updated = update_event(
        event_id,

        status=status,
        state=status,

        exit_price=exit_price,
        exit_timestamp=now_iso(),

        profit_loss=profit_loss,
        realized_pl=profit_loss,

        realized_pl_pct=realized_pl_pct,

        reason=reason,

        event_type="EXIT"
    )

    if updated:

        close_position_state(
            symbol=symbol,

            exit_price=exit_price,

            realized_pl=profit_loss,

            realized_pl_pct=realized_pl_pct,

            state=status
        )

    return updated


# ============================================================
# HISTORY
# ============================================================

def get_today_events()
-> List[Dict[str, Any]]:

    prefix = today_prefix()

    conn = get_connection()

    try:

        rows = conn.execute(
            """
            SELECT *
            FROM trade_events

            WHERE timestamp LIKE ?

            ORDER BY id ASC
            """,
            (
                prefix + "%",
            )
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


def get_trade_history(
    symbol: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    conn = get_connection()

    try:

        if symbol:

            rows = conn.execute(
                """
                SELECT *
                FROM trade_events

                WHERE symbol = ?

                ORDER BY id DESC

                LIMIT ?
                """,
                (
                    symbol,
                    limit
                )
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT *
                FROM trade_events

                ORDER BY id DESC

                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


# ============================================================
# REALIZED P/L
# ============================================================

def get_today_profit_loss() -> float:
    """
    Realized P/L only.

    Management events are excluded.
    """

    prefix = today_prefix()

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT
                COALESCE(
                    SUM(
                        COALESCE(
                            realized_pl,
                            profit_loss,
                            0
                        )
                    ),
                    0
                )

            FROM trade_events

            WHERE timestamp LIKE ?

              AND (

                    state IN (
                        'CLOSED',
                        'STOPPED',
                        'EXIT_FILLED'
                    )

                    OR

                    status IN (
                        'CLOSED',
                        'STOPPED',
                        'EXIT_FILLED'
                    )

                  )
            """,
            (
                prefix + "%",
            )
        ).fetchone()

        return float(
            row[0] or 0.0
        )

    finally:

        conn.close()


def get_today_loss() -> float:

    pnl = get_today_profit_loss()

    return abs(pnl) if pnl < 0 else 0.0


def get_today_profit() -> float:

    pnl = get_today_profit_loss()

    return pnl if pnl > 0 else 0.0


# ============================================================
# TRADE COUNT
# ============================================================

def get_today_trade_count() -> int:

    prefix = today_prefix()

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT COUNT(*)

            FROM trade_events

            WHERE timestamp LIKE ?

              AND (

                    event_type IN (
                        'ENTRY_FILLED',
                        'ENTRY'
                    )

                    OR

                    status IN (
                        'FILLED',
                        'POSITION_OPEN'
                    )

                  )
            """,
            (
                prefix + "%",
            )
        ).fetchone()

        return int(
            row[0] or 0
        )

    finally:

        conn.close()


# ============================================================
# SYSTEM EVENTS
# ============================================================

def log_system_event(
    event_type: str,
    severity: str = "INFO",
    symbol: Optional[str] = None,
    message: Optional[str] = None,
    data: Optional[Any] = None
) -> int:

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO system_events (

                timestamp,
                event_type,
                severity,
                symbol,
                message,
                metadata

            )

            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                event_type,
                severity,
                symbol,
                message,
                json_dumps(data)
            )
        )

        conn.commit()

        return int(
            cursor.lastrowid
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


def get_recent_system_events(
    limit: int = 100
) -> List[Dict[str, Any]]:

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    conn = get_connection()

    try:

        rows = conn.execute(
            """
            SELECT *
            FROM system_events

            ORDER BY id DESC

            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        results = []

        for row in rows:

            result = dict(row)

            result["metadata"] = json_loads(
                result.get("metadata")
            )

            results.append(result)

        return results

    finally:

        conn.close()


# ============================================================
# AUDIT LOG
# ============================================================

def log_audit(
    entity_type: str,
    action: str,
    entity_id: Optional[str] = None,
    old_state: Optional[Any] = None,
    new_state: Optional[Any] = None,
    reason: Optional[str] = None,
    metadata: Optional[Any] = None
) -> int:

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO audit_log (

                timestamp,

                entity_type,
                entity_id,

                action,

                old_state,
                new_state,

                reason,

                metadata
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),

                entity_type,
                entity_id,

                action,

                json_dumps(old_state),
                json_dumps(new_state),

                reason,

                json_dumps(metadata)
            )
        )

        conn.commit()

        return int(
            cursor.lastrowid
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# ============================================================
# PORTFOLIO SNAPSHOT
# ============================================================

def save_portfolio_snapshot(
    equity: Optional[float] = None,
    cash: Optional[float] = None,
    buying_power: Optional[float] = None,
    market_value: Optional[float] = None,
    total_exposure: Optional[float] = None,
    portfolio_risk: Optional[float] = None,
    daily_pl: Optional[float] = None,
    open_positions: Optional[int] = None,
    open_orders: Optional[int] = None,
    metadata: Optional[Any] = None
) -> int:

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO portfolio_snapshots (

                timestamp,

                equity,
                cash,
                buying_power,

                market_value,

                total_exposure,
                portfolio_risk,

                daily_pl,

                open_positions,
                open_orders,

                metadata
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),

                equity,
                cash,
                buying_power,

                market_value,

                total_exposure,
                portfolio_risk,

                daily_pl,

                open_positions,
                open_orders,

                json_dumps(metadata)
            )
        )

        conn.commit()

        return int(
            cursor.lastrowid
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


def get_recent_portfolio_snapshots(
    limit: int = 100
) -> List[Dict[str, Any]]:

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    conn = get_connection()

    try:

        rows = conn.execute(
            """
            SELECT *
            FROM portfolio_snapshots

            ORDER BY id DESC

            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        results = []

        for row in rows:

            result = dict(row)

            result["metadata"] = json_loads(
                result.get("metadata")
            )

            results.append(result)

        return results

    finally:

        conn.close()


# ============================================================
# RECONCILIATION
# ============================================================

def log_reconciliation(
    entity_type: str,
    status: str,
    symbol: Optional[str] = None,
    local_state: Optional[Any] = None,
    alpaca_state: Optional[Any] = None,
    discrepancy: Optional[str] = None,
    resolution: Optional[str] = None,
    metadata: Optional[Any] = None
) -> int:

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO reconciliation_log (

                timestamp,

                symbol,

                entity_type,

                local_state,

                alpaca_state,

                status,

                discrepancy,

                resolution,

                metadata
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),

                symbol,

                entity_type,

                json_dumps(local_state),
                json_dumps(alpaca_state),

                status,

                discrepancy,

                resolution,

                json_dumps(metadata)
            )
        )

        conn.commit()

        return int(
            cursor.lastrowid
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# ============================================================
# ORPHAN DETECTION
# ============================================================

def get_database_open_symbols() -> List[str]:
    """
    Symbols locally marked OPEN.
    """

    conn = get_connection()

    try:

        rows = conn.execute(
            """
            SELECT symbol
            FROM position_state
            WHERE state = 'OPEN'
            ORDER BY symbol
            """
        ).fetchall()

        return [
            row["symbol"]
            for row in rows
        ]

    finally:

        conn.close()


def find_orphaned_database_positions(
    alpaca_symbols: List[str]
) -> List[str]:
    """
    Find positions stored as OPEN locally but absent from Alpaca.

    Does not modify anything.
    """

    alpaca_set = {
        str(symbol).upper()
        for symbol in alpaca_symbols
    }

    local_symbols = set(
        get_database_open_symbols()
    )

    return sorted(
        local_symbols - alpaca_set
    )


def find_unknown_alpaca_positions(
    alpaca_symbols: List[str]
) -> List[str]:
    """
    Find Alpaca positions not known as OPEN in SQLite.

    Does not close anything automatically.
    """

    alpaca_set = {
        str(symbol).upper()
        for symbol in alpaca_symbols
    }

    local_symbols = set(
        get_database_open_symbols()
    )

    return sorted(
        alpaca_set - local_symbols
    )


# ============================================================
# DATABASE HEALTH
# ============================================================

def database_health_check()
-> Dict[str, Any]:

    result = {

        "database": DATABASE_PATH,

        "connected": False,

        "integrity": False,

        "schema_version": None,

        "trade_events": 0,

        "open_positions": 0,

        "orders": 0,

        "system_events": 0,

        "audit_events": 0,

        "snapshots": 0,

        "reconciliation_events": 0,

        "error": None
    }

    conn = None

    try:

        conn = get_connection()

        result["connected"] = True

        integrity = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if integrity:

            result["integrity"] = (
                integrity[0] == "ok"
            )

        schema = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key='schema_version'
            LIMIT 1
            """
        ).fetchone()

        if schema:
            result["schema_version"] = (
                schema["value"]
            )

        result["trade_events"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM trade_events"
            ).fetchone()[0]
            or 0
        )

        result["open_positions"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM position_state
                WHERE state='OPEN'
                """
            ).fetchone()[0]
            or 0
        )

        result["orders"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM order_state"
            ).fetchone()[0]
            or 0
        )

        result["system_events"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM system_events"
            ).fetchone()[0]
            or 0
        )

        result["audit_events"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_log"
            ).fetchone()[0]
            or 0
        )

        result["snapshots"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM portfolio_snapshots
                """
            ).fetchone()[0]
            or 0
        )

        result["reconciliation_events"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM reconciliation_log
                """
            ).fetchone()[0]
            or 0
        )

    except Exception as exc:

        result["error"] = str(exc)

    finally:

        if conn:
            conn.close()

    return result


# ============================================================
# DATABASE BACKUP
# ============================================================

def backup_database(
    backup_path: Optional[str] = None
) -> str:
    """
    Create a SQLite backup using the native backup API.

    Returns:
        Backup path.
    """

    if backup_path is None:

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d_%H%M%S"
        )

        backup_path = (
            f"{DATABASE_PATH}.{timestamp}.bak"
        )

    source = get_connection()

    destination = sqlite3.connect(
        backup_path
    )

    try:

        source.backup(
            destination
        )

    finally:

        destination.close()
        source.close()

    return backup_path


# ============================================================
# STARTUP
# ============================================================

initialize_database()


if __name__ == "__main__":

    print()
    print("=" * 72)
    print("          AI TRADER — DATABASE V5 OMNIPRESENT")
    print("=" * 72)

    health = database_health_check()

    print(
        f"Database:              {health['database']}"
    )

    print(
        f"Connected:             {health['connected']}"
    )

    print(
        f"Integrity:             {health['integrity']}"
    )

    print(
        f"Schema:                {health['schema_version']}"
    )

    print(
        f"Trade events:          {health['trade_events']}"
    )

    print(
        f"Open positions:        {health['open_positions']}"
    )

    print(
        f"Orders tracked:        {health['orders']}"
    )

    print(
        f"System events:         {health['system_events']}"
    )

    print(
        f"Audit events:          {health['audit_events']}"
    )

    print(
        f"Portfolio snapshots:   {health['snapshots']}"
    )

    print(
        f"Reconciliation logs:   {health['reconciliation_events']}"
    )

    if health["error"]:

        print(
            f"ERROR:                 {health['error']}"
        )

    print("=" * 72)
    print()
