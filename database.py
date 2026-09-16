"""
AI TRADER — DATABASE V5.1 OMNIPRESENTE
=======================================

Base de datos central del bot.

Objetivos:
- Historial de operaciones
- Estado actual de posiciones
- Estado de órdenes Alpaca
- Idempotencia
- Reconciliación Alpaca <-> SQLite
- Auditoría
- Eventos del sistema
- Snapshots de portafolio
- Métricas básicas
- Migraciones aditivas
- Backups
- Compatibilidad con versiones anteriores

IMPORTANTE:
- SQLite es persistencia/local state.
- Alpaca sigue siendo la fuente de verdad para posiciones y órdenes reales.
- Nunca se eliminan datos durante una migración.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ============================================================
# CONFIGURACIÓN
# ============================================================

DATABASE_PATH = os.getenv("DATABASE_PATH", "trade_history.db")

DB_TIMEOUT = 30
DB_BUSY_TIMEOUT_MS = 30000

SCHEMA_VERSION = 5
BOT_VERSION = os.getenv("BOT_VERSION", "V5.1 OMNIPRESENTE")


# ============================================================
# TIEMPO
# ============================================================

def now_iso() -> str:
    """UTC actual en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def today_prefix() -> str:
    """Fecha UTC actual YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ============================================================
# CONEXIÓN
# ============================================================

def get_connection() -> sqlite3.Connection:
    """
    Abre conexión SQLite configurada para operación estable.
    """
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=DB_TIMEOUT,
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn


def _connect() -> sqlite3.Connection:
    """Alias interno."""
    return get_connection()


# ============================================================
# HELPERS
# ============================================================

def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(value)
    except Exception:
        return value


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None

    return dict(row)


def _rows_to_dicts(rows: Sequence[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def _event_key(
    symbol: str,
    event_type: str,
    order_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    extra: Optional[Any] = None,
) -> str:
    """
    Genera una clave determinista para evitar eventos duplicados.
    """
    raw = "|".join(
        [
            _normalize_symbol(symbol),
            str(event_type or "").strip().upper(),
            str(order_id or ""),
            str(timestamp or ""),
            _json_dumps(extra) or "",
        ]
    )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# SCHEMA HELPERS
# ============================================================

def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name=?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def get_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> List[str]:
    if not table_exists(conn, table_name):
        return []

    rows = conn.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    return [row["name"] for row in rows]


def add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = get_columns(conn, table_name)

    if column_name not in columns:
        conn.execute(
            f'ALTER TABLE "{table_name}" '
            f'ADD COLUMN "{column_name}" {column_definition}'
        )


# ============================================================
# INICIALIZACIÓN / MIGRACIÓN
# ============================================================

def initialize_database() -> None:
    """
    Crea la base de datos y aplica migraciones aditivas.

    Nunca elimina columnas ni tablas existentes.
    """
    Path(DATABASE_PATH).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = get_connection()

    try:
        # ----------------------------------------------------
        # META
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # TRADE EVENTS
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT,
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

        # V5 columns
        trade_columns = [
            ("strategy_version", "TEXT"),
            ("reason", "TEXT"),
            ("event_type", "TEXT"),
            ("event_key", "TEXT"),
            ("entry_timestamp", "TEXT"),
            ("exit_timestamp", "TEXT"),
            ("exit_price", "REAL"),
            ("quantity", "REAL"),
            ("realized_pl", "REAL"),
            ("realized_pl_pct", "REAL"),
            ("unrealized_pl", "REAL"),
            ("unrealized_pl_pct", "REAL"),
            ("peak_price", "REAL"),
            ("original_stop", "REAL"),
            ("current_stop", "REAL"),
            ("state", "TEXT"),
            ("managed_by", "TEXT"),
            ("alpaca_order_id", "TEXT"),
            ("alpaca_client_order_id", "TEXT"),
            ("metadata", "TEXT"),
            ("last_update", "TEXT"),
        ]

        for column, definition in trade_columns:
            add_column_if_missing(
                conn,
                "trade_events",
                column,
                definition,
            )

        # ----------------------------------------------------
        # POSITION STATE
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS position_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                quantity REAL NOT NULL DEFAULT 0,

                entry_price REAL,
                current_price REAL,
                market_value REAL,

                original_stop REAL,
                current_stop REAL,
                peak_price REAL,

                unrealized_pl REAL,
                unrealized_pl_pct REAL,
                realized_pl REAL,
                realized_pl_pct REAL,

                state TEXT NOT NULL DEFAULT 'OPEN',
                entry_timestamp TEXT,
                last_update TEXT,

                alpaca_order_id TEXT,
                alpaca_client_order_id TEXT,

                strategy_version TEXT,
                managed_by TEXT,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # ORDER STATE
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS order_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                order_id TEXT NOT NULL UNIQUE,
                client_order_id TEXT,

                symbol TEXT,
                side TEXT,
                order_type TEXT,
                order_class TEXT,
                time_in_force TEXT,

                quantity REAL,
                filled_quantity REAL,
                filled_avg_price REAL,

                status TEXT,
                submitted_at TEXT,
                filled_at TEXT,
                canceled_at TEXT,

                stop_price REAL,
                limit_price REAL,

                strategy_version TEXT,
                purpose TEXT,

                metadata TEXT,
                last_update TEXT
            )
            """
        )

        # ----------------------------------------------------
        # SYSTEM EVENTS
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT,

                component TEXT,
                event_key TEXT,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # AUDIT LOG
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                component TEXT,

                symbol TEXT,
                order_id TEXT,

                old_state TEXT,
                new_state TEXT,

                reason TEXT,
                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # PORTFOLIO SNAPSHOTS
        # ----------------------------------------------------

        conn.execute(
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
                daily_profit_loss REAL,

                open_positions INTEGER,

                metadata TEXT
            )
            """
        )

        # ----------------------------------------------------
        # RECONCILIATION
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT NOT NULL,

                symbol TEXT,
                source TEXT,

                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,

                database_quantity REAL,
                alpaca_quantity REAL,

                database_state TEXT,
                alpaca_state TEXT,

                resolved INTEGER NOT NULL DEFAULT 0,

                details TEXT
            )
            """
        )

        # ----------------------------------------------------
        # INDEXES
        # ----------------------------------------------------

        indexes = [
            """
            CREATE INDEX IF NOT EXISTS idx_trade_events_timestamp
            ON trade_events(timestamp)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trade_events_symbol
            ON trade_events(symbol)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trade_events_event_type
            ON trade_events(event_type)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trade_events_event_key
            ON trade_events(event_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trade_events_order_id
            ON trade_events(order_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_position_state_state
            ON position_state(state)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_order_state_symbol
            ON order_state(symbol)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_order_state_status
            ON order_state(status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_system_events_timestamp
            ON system_events(timestamp)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_system_events_level
            ON system_events(level)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
            ON audit_log(timestamp)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_reconciliation_symbol
            ON reconciliation_log(symbol)
            """,
        ]

        for sql in indexes:
            conn.execute(sql)

        # ----------------------------------------------------
        # META
        # ----------------------------------------------------

        conn.execute(
            """
            INSERT INTO schema_meta(key, value, updated_at)
            VALUES ('schema_version', ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (str(SCHEMA_VERSION), now_iso()),
        )

        conn.execute(
            """
            INSERT INTO schema_meta(key, value, updated_at)
            VALUES ('bot_version', ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (BOT_VERSION, now_iso()),
        )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# TRADE EVENTS
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
    event_type: Optional[str] = None,
    event_key: Optional[str] = None,
    entry_timestamp: Optional[str] = None,
    exit_timestamp: Optional[str] = None,
    exit_price: Optional[float] = None,
    quantity: Optional[float] = None,
    realized_pl: Optional[float] = None,
    realized_pl_pct: Optional[float] = None,
    unrealized_pl: Optional[float] = None,
    unrealized_pl_pct: Optional[float] = None,
    peak_price: Optional[float] = None,
    original_stop: Optional[float] = None,
    current_stop: Optional[float] = None,
    state: Optional[str] = None,
    managed_by: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> int:
    """
    Registra evento de trading.

    Devuelve ID del evento.
    Si event_key ya existe, devuelve el evento existente.
    """

    symbol = _normalize_symbol(symbol)
    timestamp = timestamp or now_iso()

    event_type = (
        str(event_type).strip().upper()
        if event_type
        else None
    )

    if event_key is None:
        event_key = _event_key(
            symbol=symbol,
            event_type=event_type or signal or "EVENT",
            order_id=order_id,
            timestamp=timestamp,
            extra={
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity or position_size,
                "status": status,
            },
        )

    conn = get_connection()

    try:
        existing = conn.execute(
            """
            SELECT id
            FROM trade_events
            WHERE event_key=?
            LIMIT 1
            """,
            (event_key,),
        ).fetchone()

        if existing:
            return int(existing["id"])

        cursor = conn.execute(
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
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                timestamp,
                symbol,
                signal,
                _safe_float(entry_price),
                _safe_float(stop_price),
                _safe_float(position_size),
                status,
                _safe_float(profit_loss),
                order_id,
                client_order_id,

                strategy_version,
                reason,
                event_type,
                event_key,

                entry_timestamp,
                exit_timestamp,
                _safe_float(exit_price),
                _safe_float(quantity or position_size),

                _safe_float(realized_pl),
                _safe_float(realized_pl_pct),
                _safe_float(unrealized_pl),
                _safe_float(unrealized_pl_pct),

                _safe_float(peak_price),
                _safe_float(original_stop),
                _safe_float(current_stop),

                state,
                managed_by,

                order_id,
                client_order_id,

                _json_dumps(metadata),
                now_iso(),
            ),
        )

        conn.commit()

        return int(cursor.lastrowid)

    finally:
        conn.close()


def update_event(
    event_id: int,
    **fields: Any,
) -> bool:
    """
    Actualiza únicamente columnas permitidas.
    """

    allowed = {
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
        "metadata",
    }

    updates = []

    values: List[Any] = []

    for key, value in fields.items():
        if key not in allowed:
            continue

        updates.append(f'"{key}"=?')

        if key == "metadata":
            value = _json_dumps(value)

        values.append(value)

    if not updates:
        return False

    updates.append('"last_update"=?')
    values.append(now_iso())
    values.append(event_id)

    conn = get_connection()

    try:
        cursor = conn.execute(
            f"""
            UPDATE trade_events
            SET {", ".join(updates)}
            WHERE id=?
            """,
            values,
        )

        conn.commit()

        return cursor.rowcount > 0

    finally:
        conn.close()


# ============================================================
# ORDER STATE
# ============================================================

def upsert_order(
    order_id: str,
    client_order_id: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[str] = None,
    order_class: Optional[str] = None,
    time_in_force: Optional[str] = None,
    quantity: Optional[float] = None,
    filled_quantity: Optional[float] = None,
    filled_avg_price: Optional[float] = None,
    status: Optional[str] = None,
    submitted_at: Optional[str] = None,
    filled_at: Optional[str] = None,
    canceled_at: Optional[str] = None,
    stop_price: Optional[float] = None,
    limit_price: Optional[float] = None,
    strategy_version: Optional[str] = None,
    purpose: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Inserta o actualiza estado de una orden Alpaca.
    """

    if not order_id:
        return

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
                filled_avg_price,

                status,
                submitted_at,
                filled_at,
                canceled_at,

                stop_price,
                limit_price,

                strategy_version,
                purpose,

                metadata,
                last_update
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            ON CONFLICT(order_id)
            DO UPDATE SET
                client_order_id=COALESCE(
                    excluded.client_order_id,
                    order_state.client_order_id
                ),
                symbol=COALESCE(
                    excluded.symbol,
                    order_state.symbol
                ),
                side=COALESCE(
                    excluded.side,
                    order_state.side
                ),
                order_type=COALESCE(
                    excluded.order_type,
                    order_state.order_type
                ),
                order_class=COALESCE(
                    excluded.order_class,
                    order_state.order_class
                ),
                time_in_force=COALESCE(
                    excluded.time_in_force,
                    order_state.time_in_force
                ),

                quantity=COALESCE(
                    excluded.quantity,
                    order_state.quantity
                ),
                filled_quantity=COALESCE(
                    excluded.filled_quantity,
                    order_state.filled_quantity
                ),
                filled_avg_price=COALESCE(
                    excluded.filled_avg_price,
                    order_state.filled_avg_price
                ),

                status=COALESCE(
                    excluded.status,
                    order_state.status
                ),
                submitted_at=COALESCE(
                    excluded.submitted_at,
                    order_state.submitted_at
                ),
                filled_at=COALESCE(
                    excluded.filled_at,
                    order_state.filled_at
                ),
                canceled_at=COALESCE(
                    excluded.canceled_at,
                    order_state.canceled_at
                ),

                stop_price=COALESCE(
                    excluded.stop_price,
                    order_state.stop_price
                ),
                limit_price=COALESCE(
                    excluded.limit_price,
                    order_state.limit_price
                ),

                strategy_version=COALESCE(
                    excluded.strategy_version,
                    order_state.strategy_version
                ),
                purpose=COALESCE(
                    excluded.purpose,
                    order_state.purpose
                ),

                metadata=COALESCE(
                    excluded.metadata,
                    order_state.metadata
                ),

                last_update=excluded.last_update
            """,
            (
                str(order_id),
                client_order_id,
                _normalize_symbol(symbol),
                side,
                order_type,
                order_class,
                time_in_force,

                _safe_float(quantity),
                _safe_float(filled_quantity),
                _safe_float(filled_avg_price),

                status,
                submitted_at,
                filled_at,
                canceled_at,

                _safe_float(stop_price),
                _safe_float(limit_price),

                strategy_version,
                purpose,

                _json_dumps(metadata),
                now_iso(),
            ),
        )

        conn.commit()

    finally:
        conn.close()


def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM order_state
            WHERE order_id=?
            LIMIT 1
            """,
            (str(order_id),),
        ).fetchone()

        result = _row_to_dict(row)

        if result and result.get("metadata"):
            result["metadata"] = _json_loads(result["metadata"])

        return result

    finally:
        conn.close()


# ============================================================
# POSITION STATE
# ============================================================

def upsert_position_state(
    symbol: str,
    quantity: float,
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
    entry_timestamp: Optional[str] = None,
    alpaca_order_id: Optional[str] = None,
    alpaca_client_order_id: Optional[str] = None,
    strategy_version: Optional[str] = None,
    managed_by: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Inserta o actualiza el estado persistente de una posición.

    peak_price nunca retrocede.
    """

    symbol = _normalize_symbol(symbol)

    if not symbol:
        return

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
                entry_timestamp,
                last_update,

                alpaca_order_id,
                alpaca_client_order_id,

                strategy_version,
                managed_by,

                metadata
            )
            VALUES (
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            ON CONFLICT(symbol)
            DO UPDATE SET

                quantity=excluded.quantity,

                entry_price=COALESCE(
                    excluded.entry_price,
                    position_state.entry_price
                ),

                current_price=COALESCE(
                    excluded.current_price,
                    position_state.current_price
                ),

                market_value=COALESCE(
                    excluded.market_value,
                    position_state.market_value
                ),

                original_stop=COALESCE(
                    excluded.original_stop,
                    position_state.original_stop
                ),

                current_stop=COALESCE(
                    excluded.current_stop,
                    position_state.current_stop
                ),

                peak_price=CASE
                    WHEN excluded.peak_price IS NULL
                        THEN position_state.peak_price
                    WHEN position_state.peak_price IS NULL
                        THEN excluded.peak_price
                    WHEN excluded.peak_price >
                         position_state.peak_price
                        THEN excluded.peak_price
                    ELSE position_state.peak_price
                END,

                unrealized_pl=COALESCE(
                    excluded.unrealized_pl,
                    position_state.unrealized_pl
                ),

                unrealized_pl_pct=COALESCE(
                    excluded.unrealized_pl_pct,
                    position_state.unrealized_pl_pct
                ),

                realized_pl=COALESCE(
                    excluded.realized_pl,
                    position_state.realized_pl
                ),

                realized_pl_pct=COALESCE(
                    excluded.realized_pl_pct,
                    position_state.realized_pl_pct
                ),

                state=COALESCE(
                    excluded.state,
                    position_state.state
                ),

                entry_timestamp=COALESCE(
                    excluded.entry_timestamp,
                    position_state.entry_timestamp
                ),

                alpaca_order_id=COALESCE(
                    excluded.alpaca_order_id,
                    position_state.alpaca_order_id
                ),

                alpaca_client_order_id=COALESCE(
                    excluded.alpaca_client_order_id,
                    position_state.alpaca_client_order_id
                ),

                strategy_version=COALESCE(
                    excluded.strategy_version,
                    position_state.strategy_version
                ),

                managed_by=COALESCE(
                    excluded.managed_by,
                    position_state.managed_by
                ),

                metadata=COALESCE(
                    excluded.metadata,
                    position_state.metadata
                ),

                last_update=excluded.last_update
            """,
            (
                symbol,
                _safe_float(quantity, 0.0),

                _safe_float(entry_price),
                _safe_float(current_price),
                _safe_float(market_value),

                _safe_float(original_stop),
                _safe_float(current_stop),
                _safe_float(peak_price),

                _safe_float(unrealized_pl),
                _safe_float(unrealized_pl_pct),
                _safe_float(realized_pl),
                _safe_float(realized_pl_pct),

                state,
                entry_timestamp,
                now_iso(),

                alpaca_order_id,
                alpaca_client_order_id,

                strategy_version,
                managed_by,

                _json_dumps(metadata),
            ),
        )

        conn.commit()

    finally:
        conn.close()


def get_position_state(
    symbol: str,
) -> Optional[Dict[str, Any]]:
    symbol = _normalize_symbol(symbol)

    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM position_state
            WHERE symbol=?
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

        result = _row_to_dict(row)

        if result and result.get("metadata"):
            result["metadata"] = _json_loads(result["metadata"])

        return result

    finally:
        conn.close()


def get_all_open_position_states() -> List[Dict[str, Any]]:
    """
    Devuelve posiciones que la DB considera abiertas.
    """

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM position_state
            WHERE quantity > 0
              AND UPPER(state) NOT IN (
                  'CLOSED',
                  'STOPPED',
                  'EXIT_FILLED'
              )
            ORDER BY symbol
            """
        ).fetchall()

        result = _rows_to_dicts(rows)

        for item in result:
            if item.get("metadata"):
                item["metadata"] = _json_loads(item["metadata"])

        return result

    finally:
        conn.close()


def close_position_state(
    symbol: str,
    realized_pl: Optional[float] = None,
    realized_pl_pct: Optional[float] = None,
    exit_price: Optional[float] = None,
    state: str = "CLOSED",
) -> bool:
    symbol = _normalize_symbol(symbol)

    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            UPDATE position_state
            SET
                quantity=0,
                current_price=COALESCE(?, current_price),
                realized_pl=COALESCE(?, realized_pl),
                realized_pl_pct=COALESCE(
                    ?,
                    realized_pl_pct
                ),
                state=?,
                last_update=?
            WHERE symbol=?
            """,
            (
                _safe_float(exit_price),
                _safe_float(realized_pl),
                _safe_float(realized_pl_pct),
                state,
                now_iso(),
                symbol,
            ),
        )

        conn.commit()

        return cursor.rowcount > 0

    finally:
        conn.close()


# ============================================================
# EVENT QUERIES
# ============================================================

def get_event_by_order_id(
    order_id: str,
) -> Optional[Dict[str, Any]]:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM trade_events
            WHERE order_id=?
               OR alpaca_order_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(order_id), str(order_id)),
        ).fetchone()

        result = _row_to_dict(row)

        if result and result.get("metadata"):
            result["metadata"] = _json_loads(result["metadata"])

        return result

    finally:
        conn.close()


def get_open_position_event(
    symbol: str,
) -> Optional[Dict[str, Any]]:
    """
    Busca primero el estado persistente de posición.

    Si no existe, hace fallback al historial de eventos.
    """

    symbol = _normalize_symbol(symbol)

    state = get_position_state(symbol)

    if state:
        quantity = _safe_float(state.get("quantity"), 0.0)

        if quantity and quantity > 0:
            return state

    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM trade_events
            WHERE symbol=?
              AND (
                  UPPER(COALESCE(state, '')) NOT IN (
                      'CLOSED',
                      'STOPPED',
                      'EXIT_FILLED'
                  )
              )
              AND (
                  UPPER(COALESCE(status, '')) IN (
                      'FILLED',
                      'POSITION_OPEN',
                      'OPEN'
                  )
                  OR UPPER(COALESCE(event_type, '')) IN (
                      'ENTRY',
                      'ENTRY_SUBMITTED',
                      'ENTRY_FILLED'
                  )
              )
            ORDER BY id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

        result = _row_to_dict(row)

        if result and result.get("metadata"):
            result["metadata"] = _json_loads(result["metadata"])

        return result

    finally:
        conn.close()


def close_position_event(
    symbol: str,
    exit_price: Optional[float] = None,
    profit_loss: Optional[float] = None,
    reason: Optional[str] = None,
    event_type: str = "EXIT_FILLED",
) -> Optional[int]:
    """
    Cierra una posición registrada y crea evento de salida.
    """

    symbol = _normalize_symbol(symbol)
    timestamp = now_iso()

    event_id = log_event(
        symbol=symbol,
        signal="EXIT",
        status="CLOSED",
        profit_loss=profit_loss,
        event_type=event_type,
        reason=reason,
        exit_timestamp=timestamp,
        exit_price=exit_price,
        realized_pl=profit_loss,
        state="CLOSED",
        managed_by="trade_manager",
        timestamp=timestamp,
    )

    close_position_state(
        symbol=symbol,
        realized_pl=profit_loss,
        exit_price=exit_price,
        state="CLOSED",
    )

    return event_id


# ============================================================
# HISTORIAL
# ============================================================

def get_today_events() -> List[Dict[str, Any]]:
    prefix = today_prefix()

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM trade_events
            WHERE timestamp LIKE ?
            ORDER BY id DESC
            """,
            (f"{prefix}%",),
        ).fetchall()

        result = _rows_to_dicts(rows)

        for item in result:
            if item.get("metadata"):
                item["metadata"] = _json_loads(item["metadata"])

        return result

    finally:
        conn.close()


def get_trade_history(
    limit: int = 500,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 10000))

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM trade_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        result = _rows_to_dicts(rows)

        for item in result:
            if item.get("metadata"):
                item["metadata"] = _json_loads(item["metadata"])

        return result

    finally:
        conn.close()


# ============================================================
# P/L
# ============================================================

def get_today_profit_loss() -> float:
    """
    P/L realizado de posiciones cerradas hoy.

    Se toma de position_state para evitar sumar arbitrariamente
    eventos repetidos.
    """

    prefix = today_prefix()

    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(realized_pl), 0)
            FROM position_state
            WHERE last_update LIKE ?
              AND UPPER(state) IN (
                  'CLOSED',
                  'STOPPED',
                  'EXIT_FILLED'
              )
            """,
            (f"{prefix}%",),
        ).fetchone()

        return float(row[0] or 0.0)

    finally:
        conn.close()


def get_today_loss() -> float:
    pnl = get_today_profit_loss()

    return abs(pnl) if pnl < 0 else 0.0


def get_today_profit() -> float:
    pnl = get_today_profit_loss()

    return pnl if pnl > 0 else 0.0


def get_today_trade_count() -> int:
    """
    Cuenta entradas únicas del día.

    Prioridad:
    1. event_key
    2. order_id
    3. id como fallback
    """

    prefix = today_prefix()

    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    COALESCE(
                        NULLIF(event_key, ''),
                        NULLIF(order_id, ''),
                        CAST(id AS TEXT)
                    ) AS unique_trade
                FROM trade_events
                WHERE timestamp LIKE ?
                  AND UPPER(
                      COALESCE(event_type, '')
                  ) IN (
                      'ENTRY',
                      'ENTRY_SUBMITTED',
                      'ENTRY_FILLED'
                  )
                GROUP BY unique_trade
            )
            """,
            (f"{prefix}%",),
        ).fetchone()

        return int(row[0] or 0)

    finally:
        conn.close()


# ============================================================
# SYSTEM EVENTS
# ============================================================

def log_system_event(
    level: str,
    event_type: str,
    message: Optional[str] = None,
    component: Optional[str] = None,
    event_key: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Registra eventos del sistema.

    Si se proporciona event_key, evita duplicados.
    """

    level = str(level or "INFO").upper()
    event_type = str(event_type or "SYSTEM").upper()

    conn = get_connection()

    try:
        if event_key:
            existing = conn.execute(
                """
                SELECT id
                FROM system_events
                WHERE event_key=?
                LIMIT 1
                """,
                (event_key,),
            ).fetchone()

            if existing:
                return int(existing["id"])

        cursor = conn.execute(
            """
            INSERT INTO system_events (
                timestamp,
                level,
                event_type,
                message,
                component,
                event_key,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                level,
                event_type,
                message,
                component,
                event_key,
                _json_dumps(metadata),
            ),
        )

        conn.commit()

        return int(cursor.lastrowid)

    finally:
        conn.close()


def get_recent_system_events(
    limit: int = 100,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 5000))

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM system_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        result = _rows_to_dicts(rows)

        for item in result:
            if item.get("metadata"):
                item["metadata"] = _json_loads(item["metadata"])

        return result

    finally:
        conn.close()


# ============================================================
# AUDITORÍA
# ============================================================

def log_audit(
    action: str,
    component: Optional[str] = None,
    symbol: Optional[str] = None,
    order_id: Optional[str] = None,
    old_state: Optional[str] = None,
    new_state: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO audit_log (
                timestamp,
                action,
                component,
                symbol,
                order_id,
                old_state,
                new_state,
                reason,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                action,
                component,
                _normalize_symbol(symbol),
                order_id,
                old_state,
                new_state,
                reason,
                _json_dumps(metadata),
            ),
        )

        conn.commit()

        return int(cursor.lastrowid)

    finally:
        conn.close()


# ============================================================
# PORTFOLIO SNAPSHOTS
# ============================================================

def save_portfolio_snapshot(
    equity: Optional[float] = None,
    cash: Optional[float] = None,
    buying_power: Optional[float] = None,
    market_value: Optional[float] = None,
    total_exposure: Optional[float] = None,
    portfolio_risk: Optional[float] = None,
    daily_profit_loss: Optional[float] = None,
    open_positions: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                timestamp,
                equity,
                cash,
                buying_power,
                market_value,
                total_exposure,
                portfolio_risk,
                daily_profit_loss,
                open_positions,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                _safe_float(equity),
                _safe_float(cash),
                _safe_float(buying_power),
                _safe_float(market_value),
                _safe_float(total_exposure),
                _safe_float(portfolio_risk),
                _safe_float(daily_profit_loss),
                _safe_int(open_positions),
                _json_dumps(metadata),
            ),
        )

        conn.commit()

        return int(cursor.lastrowid)

    finally:
        conn.close()


def get_recent_portfolio_snapshots(
    limit: int = 100,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 5000))

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM portfolio_snapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        result = _rows_to_dicts(rows)

        for item in result:
            if item.get("metadata"):
                item["metadata"] = _json_loads(item["metadata"])

        return result

    finally:
        conn.close()


# ============================================================
# RECONCILIACIÓN
# ============================================================

def log_reconciliation(
    symbol: Optional[str],
    source: str,
    issue_type: str,
    severity: str,
    database_quantity: Optional[float] = None,
    alpaca_quantity: Optional[float] = None,
    database_state: Optional[str] = None,
    alpaca_state: Optional[str] = None,
    resolved: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> int:
    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO reconciliation_log (
                timestamp,
                symbol,
                source,
                issue_type,
                severity,
                database_quantity,
                alpaca_quantity,
                database_state,
                alpaca_state,
                resolved,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                _normalize_symbol(symbol),
                source,
                issue_type,
                severity,
                _safe_float(database_quantity),
                _safe_float(alpaca_quantity),
                database_state,
                alpaca_state,
                1 if resolved else 0,
                _json_dumps(details),
            ),
        )

        conn.commit()

        return int(cursor.lastrowid)

    finally:
        conn.close()


def get_database_open_symbols() -> List[str]:
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT symbol
            FROM position_state
            WHERE quantity > 0
              AND UPPER(state) NOT IN (
                  'CLOSED',
                  'STOPPED',
                  'EXIT_FILLED'
              )
            ORDER BY symbol
            """
        ).fetchall()

        return [
            _normalize_symbol(row["symbol"])
            for row in rows
        ]

    finally:
        conn.close()


def find_orphaned_database_positions(
    alpaca_symbols: Sequence[str],
) -> List[str]:
    """
    DB dice que existen, Alpaca dice que no.
    """

    alpaca_set = {
        _normalize_symbol(symbol)
        for symbol in alpaca_symbols
    }

    db_symbols = set(get_database_open_symbols())

    return sorted(db_symbols - alpaca_set)


def find_unknown_alpaca_positions(
    alpaca_symbols: Sequence[str],
) -> List[str]:
    """
    Alpaca tiene posiciones que DB no conoce.
    """

    alpaca_set = {
        _normalize_symbol(symbol)
        for symbol in alpaca_symbols
    }

    db_symbols = set(get_database_open_symbols())

    return sorted(alpaca_set - db_symbols)


def reconcile_positions(
    alpaca_positions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compara posiciones conocidas por DB contra posiciones de Alpaca.

    NO modifica automáticamente posiciones de Alpaca.
    """

    alpaca_symbols = [
        _normalize_symbol(
            item.get("symbol")
        )
        for item in alpaca_positions
        if item.get("symbol")
    ]

    orphaned_db = find_orphaned_database_positions(
        alpaca_symbols
    )

    unknown_alpaca = find_unknown_alpaca_positions(
        alpaca_symbols
    )

    for symbol in orphaned_db:
        log_reconciliation(
            symbol=symbol,
            source="reconcile_positions",
            issue_type="ORPHANED_DATABASE_POSITION",
            severity="WARNING",
            database_quantity=(
                get_position_state(symbol) or {}
            ).get("quantity"),
            alpaca_quantity=0,
            database_state="OPEN",
            alpaca_state="ABSENT",
            details={
                "message": (
                    "DB tiene posición que no aparece "
                    "en Alpaca."
                )
            },
        )

    for symbol in unknown_alpaca:
        alpaca_item = next(
            (
                item
                for item in alpaca_positions
                if _normalize_symbol(
                    item.get("symbol")
                ) == symbol
            ),
            {},
        )

        log_reconciliation(
            symbol=symbol,
            source="reconcile_positions",
            issue_type="UNKNOWN_ALPACA_POSITION",
            severity="CRITICAL",
            database_quantity=0,
            alpaca_quantity=_safe_float(
                alpaca_item.get("quantity")
            ),
            database_state="ABSENT",
            alpaca_state="OPEN",
            details={
                "message": (
                    "Alpaca tiene posición que DB "
                    "no conoce."
                )
            },
        )

    return {
        "alpaca_symbols": sorted(set(alpaca_symbols)),
        "orphaned_database_positions": orphaned_db,
        "unknown_alpaca_positions": unknown_alpaca,
        "clean": not orphaned_db and not unknown_alpaca,
    }


# ============================================================
# SALUD DE BASE DE DATOS
# ============================================================

def database_health_check() -> Dict[str, Any]:
    """
    Diagnóstico completo de SQLite.
    """

    result: Dict[str, Any] = {
        "database_path": DATABASE_PATH,
        "connected": False,
        "integrity": False,
        "schema_version": None,
        "bot_version": BOT_VERSION,
        "trade_events": 0,
        "open_positions": 0,
        "orders": 0,
        "system_events": 0,
        "audit_events": 0,
        "portfolio_snapshots": 0,
        "reconciliation_events": 0,
        "error": None,
    }

    try:
        conn = get_connection()

        result["connected"] = True

        integrity = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        result["integrity"] = (
            integrity is not None
            and str(integrity[0]).lower() == "ok"
        )

        meta = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key='schema_version'
            """
        ).fetchone()

        if meta:
            result["schema_version"] = _safe_int(
                meta["value"]
            )

        tables = {
            "trade_events": """
                SELECT COUNT(*) FROM trade_events
            """,
            "open_positions": """
                SELECT COUNT(*)
                FROM position_state
                WHERE quantity > 0
                  AND UPPER(state) NOT IN (
                      'CLOSED',
                      'STOPPED',
                      'EXIT_FILLED'
                  )
            """,
            "orders": """
                SELECT COUNT(*) FROM order_state
            """,
            "system_events": """
                SELECT COUNT(*) FROM system_events
            """,
            "audit_events": """
                SELECT COUNT(*) FROM audit_log
            """,
            "portfolio_snapshots": """
                SELECT COUNT(*)
                FROM portfolio_snapshots
            """,
            "reconciliation_events": """
                SELECT COUNT(*)
                FROM reconciliation_log
            """,
        }

        for key, sql in tables.items():
            row = conn.execute(sql).fetchone()
            result[key] = int(row[0] or 0)

        conn.close()

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ============================================================
# BACKUP
# ============================================================

def backup_database(
    destination: Optional[str] = None,
) -> Optional[str]:
    """
    Crea backup consistente mediante SQLite backup API.

    Si destination no existe, crea:
        trade_history_backup_TIMESTAMP.db
    """

    if not os.path.exists(DATABASE_PATH):
        return None

    if destination is None:
        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%d_%H%M%S")

        destination = (
            f"trade_history_backup_{timestamp}.db"
        )

    destination = str(destination)

    destination_dir = os.path.dirname(
        os.path.abspath(destination)
    )

    os.makedirs(
        destination_dir,
        exist_ok=True,
    )

    source = get_connection()

    try:
        target = sqlite3.connect(
            destination,
            timeout=DB_TIMEOUT,
        )

        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()

    finally:
        source.close()

    return destination


# ============================================================
# LIMPIEZA SEGURA DE WAL
# ============================================================

def checkpoint_database() -> bool:
    """
    Fuerza checkpoint del WAL.

    No elimina historial.
    """

    conn = get_connection()

    try:
        conn.execute(
            "PRAGMA wal_checkpoint(PASSIVE)"
        )

        return True

    except Exception:
        return False

    finally:
        conn.close()


# ============================================================
# ESTADÍSTICAS
# ============================================================

def get_database_stats() -> Dict[str, Any]:
    """
    Estadísticas generales de persistencia.
    """

    health = database_health_check()

    return {
        "database_path": DATABASE_PATH,
        "schema_version": health.get("schema_version"),
        "bot_version": health.get("bot_version"),
        "trade_events": health.get("trade_events"),
        "open_positions": health.get("open_positions"),
        "orders": health.get("orders"),
        "system_events": health.get("system_events"),
        "audit_events": health.get("audit_events"),
        "portfolio_snapshots": health.get(
            "portfolio_snapshots"
        ),
        "reconciliation_events": health.get(
            "reconciliation_events"
        ),
        "integrity": health.get("integrity"),
    }


# ============================================================
# ARRANQUE
# ============================================================

initialize_database()


# ============================================================
# SELF TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 72)
    print("AI TRADER — DATABASE V5.1 OMNIPRESENTE")
    print("=" * 72)

    health = database_health_check()

    print(
        f"Database:       {health.get('database_path')}"
    )
    print(
        f"Connected:      {health.get('connected')}"
    )
    print(
        f"Integrity:      {health.get('integrity')}"
    )
    print(
        f"Schema:         {health.get('schema_version')}"
    )
    print(
        f"Bot version:    {health.get('bot_version')}"
    )
    print(
        f"Trade events:   {health.get('trade_events')}"
    )
    print(
        f"Open positions: {health.get('open_positions')}"
    )
    print(
        f"Orders:         {health.get('orders')}"
    )
    print(
        f"System events:  {health.get('system_events')}"
    )
    print(
        f"Audit events:   {health.get('audit_events')}"
    )
    print(
        f"Snapshots:      {health.get('portfolio_snapshots')}"
    )
    print(
        f"Reconciliation:{health.get('reconciliation_events')}"
    )

    if health.get("error"):
        print(
            f"ERROR:          {health.get('error')}"
        )

    print("=" * 72)
