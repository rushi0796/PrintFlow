import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    for env_file in [Path(__file__).resolve().parent / ".env.local", Path(__file__).resolve().parent / ".env"]:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == "DATABASE_URL":
                        DATABASE_URL = v.strip().strip('"').strip("'")
                        os.environ["DATABASE_URL"] = DATABASE_URL
                        break
        if DATABASE_URL:
            break

from contextlib import contextmanager

LOCAL_DB = Path(__file__).resolve().parent / "orders" / "printflow.sqlite3"
_STORAGE_INITIALIZED = False
_PG_POOL = None


def _get_pg_pool():
    global _PG_POOL
    if _PG_POOL is None and DATABASE_URL:
        try:
            import psycopg2.pool
            _PG_POOL = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL, connect_timeout=5)
        except Exception as exc:
            print(f"[STORAGE POOL WARNING]: {exc}")
            _PG_POOL = None
    return _PG_POOL


def _postgres():
    if not DATABASE_URL:
        return None
    try:
        import psycopg2
        return psycopg2.connect(DATABASE_URL, connect_timeout=5)
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL is configured but psycopg2-binary is not installed") from exc


def _sqlite():
    LOCAL_DB.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(str(LOCAL_DB), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def get_connection():
    pool = _get_pg_pool()
    conn = None
    is_pooled = False
    if pool:
        try:
            conn = pool.getconn()
            is_pooled = True
            if conn.closed:
                pool.putconn(conn, close=True)
                conn = pool.getconn()
        except Exception:
            is_pooled = False
            conn = _postgres()
    else:
        conn = _postgres() or _sqlite()

    try:
        yield conn
    finally:
        if is_pooled and pool and conn:
            try:
                if not conn.closed:
                    conn.rollback()
            except Exception:
                pass
            try:
                pool.putconn(conn)
            except Exception:
                pass
        elif conn and not is_pooled:
            try:
                conn.close()
            except Exception:
                pass


def _connection():
    return _postgres() or _sqlite()


def init_storage():
    global _STORAGE_INITIALIZED
    if _STORAGE_INITIALIZED:
        return
    with get_connection() as connection:
        if DATABASE_URL:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS printflow_orders (
                        order_id TEXT PRIMARY KEY,
                        razorpay_order_id TEXT,
                        razorpay_payment_id TEXT,
                        file_name TEXT NOT NULL,
                        file_path TEXT,
                        file_size BIGINT DEFAULT 0,
                        pages INTEGER NOT NULL,
                        copies INTEGER NOT NULL,
                        paper_size TEXT DEFAULT 'A4',
                        page_range TEXT DEFAULT 'all',
                        color_mode TEXT NOT NULL,
                        duplex TEXT NOT NULL,
                        orientation TEXT NOT NULL,
                        print_quality TEXT DEFAULT 'normal',
                        dpi INTEGER DEFAULT 300,
                        scaling TEXT DEFAULT 'actual_size',
                        custom_scale DOUBLE PRECISION DEFAULT 100,
                        margins TEXT DEFAULT 'default',
                        amount DOUBLE PRECISION NOT NULL,
                        paid BOOLEAN NOT NULL DEFAULT FALSE,
                        status TEXT NOT NULL,
                        document_status TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        created_at TEXT,
                        completed_at TEXT,
                        print_error TEXT,
                        claimed_at DOUBLE PRECISION,
                        printed_by_printer TEXT,
                        backup_printer TEXT DEFAULT '',
                        retry_count INTEGER DEFAULT 0
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS printflow_documents (
                        document_id TEXT PRIMARY KEY,
                        file_name TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        content BYTEA NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                migration_cols = {
                    "file_size": "BIGINT DEFAULT 0",
                    "paper_size": "TEXT DEFAULT 'A4'",
                    "page_range": "TEXT DEFAULT 'all'",
                    "print_quality": "TEXT DEFAULT 'normal'",
                    "dpi": "INTEGER DEFAULT 300",
                    "scaling": "TEXT DEFAULT 'actual_size'",
                    "custom_scale": "DOUBLE PRECISION DEFAULT 100",
                    "margins": "TEXT DEFAULT 'default'",
                    "created_at": "TEXT",
                    "completed_at": "TEXT",
                    "backup_printer": "TEXT DEFAULT ''",
                    "retry_count": "INTEGER DEFAULT 0",
                    "scale_mode": "TEXT DEFAULT 'fit'",
                    "print_mode": "TEXT DEFAULT 'standard'",
                    "pages_per_sheet": "INTEGER DEFAULT 1",
                    "page_order": "TEXT DEFAULT 'horizontal'",
                    "customer_mobile": "TEXT DEFAULT 'Guest'",
                    "binding": "TEXT DEFAULT ''"
                }
                batch_alter = ", ".join(f"ADD COLUMN IF NOT EXISTS {col} {definition}" for col, definition in migration_cols.items())
                cursor.execute(f"ALTER TABLE printflow_orders {batch_alter}")
            connection.commit()
        else:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS printflow_orders (
                    order_id TEXT PRIMARY KEY, razorpay_order_id TEXT,
                    razorpay_payment_id TEXT, file_name TEXT NOT NULL,
                    file_path TEXT, pages INTEGER NOT NULL, copies INTEGER NOT NULL,
                    color_mode TEXT NOT NULL, duplex TEXT NOT NULL,
                    orientation TEXT NOT NULL, amount REAL NOT NULL,
                    paid INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
                    document_status TEXT NOT NULL, timestamp TEXT NOT NULL,
                    print_error TEXT, claimed_at REAL, printed_by_printer TEXT
                );
                CREATE TABLE IF NOT EXISTS printflow_documents (
                    document_id TEXT PRIMARY KEY, file_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL, content BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            existing_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(printflow_orders)").fetchall()
            }
            migration_columns = {
                "file_size": "INTEGER DEFAULT 0",
                "paper_size": "TEXT DEFAULT 'A4'",
                "page_range": "TEXT DEFAULT 'all'",
                "print_quality": "TEXT DEFAULT 'normal'",
                "dpi": "INTEGER DEFAULT 300",
                "scaling": "TEXT DEFAULT 'actual_size'",
                "custom_scale": "REAL DEFAULT 100",
                "margins": "TEXT DEFAULT 'default'",
                "created_at": "TEXT",
                "completed_at": "TEXT",
                "backup_printer": "TEXT DEFAULT ''",
                "retry_count": "INTEGER DEFAULT 0",
                "scale_mode": "TEXT DEFAULT 'fit'",
                "print_mode": "TEXT DEFAULT 'standard'",
                "pages_per_sheet": "INTEGER DEFAULT 1",
                "page_order": "TEXT DEFAULT 'horizontal'",
                "customer_mobile": "TEXT DEFAULT 'Guest'",
                "binding": "TEXT DEFAULT ''"
            }
            for column, definition in migration_columns.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE printflow_orders ADD COLUMN {column} {definition}")
            connection.commit()
        _STORAGE_INITIALIZED = True


def _row_to_dict(row: Any) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        item = dict(row)
    else:
        item = dict(row)
    if "paid" in item:
        item["paid"] = bool(item["paid"])
    return item


def _execute(sql: str, params=(), fetch: str = "none"):
    with get_connection() as connection:
        if DATABASE_URL:
            from psycopg2.extras import RealDictCursor
            cursor = connection.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            result = None
            if fetch == "one":
                result = _row_to_dict(cursor.fetchone())
            elif fetch == "all":
                result = [_row_to_dict(row) for row in cursor.fetchall()]
            connection.commit()
            return result
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            cursor.close()


def save_order(order: dict) -> dict:
    init_storage()
    order.setdefault("razorpay_order_id", None)
    order.setdefault("razorpay_payment_id", None)
    order.setdefault("file_path", "")
    order.setdefault("pages", 1)
    order.setdefault("copies", 1)
    order.setdefault("color_mode", "black_white")
    order.setdefault("duplex", "double")
    order.setdefault("orientation", "portrait")
    order.setdefault("amount", 0.0)
    order.setdefault("paid", False)
    order.setdefault("status", "Pending")
    order.setdefault("document_status", "UPLOADED")
    order.setdefault("timestamp", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    order.setdefault("print_error", None)
    order.setdefault("claimed_at", None)
    order.setdefault("printed_by_printer", None)
    order.setdefault("file_size", 0)
    order.setdefault("paper_size", "A4")
    order.setdefault("page_range", "all")
    order.setdefault("print_quality", "normal")
    order.setdefault("dpi", 300)
    order.setdefault("scaling", "actual_size")
    order.setdefault("custom_scale", 100)
    order.setdefault("margins", "default")
    order.setdefault("created_at", order.get("timestamp"))
    order.setdefault("completed_at", None)
    order.setdefault("backup_printer", "")
    order.setdefault("retry_count", 0)
    order.setdefault("scale_mode", "fit")
    order.setdefault("print_mode", "standard")
    order.setdefault("pages_per_sheet", 1)
    order.setdefault("page_order", "horizontal")
    order.setdefault("customer_mobile", "Guest")
    order.setdefault("binding", "")
    # Clean claimed_at to ensure it matches DOUBLE PRECISION schema
    raw_claimed = order.get("claimed_at")
    if raw_claimed is not None and not isinstance(raw_claimed, (int, float)):
        try:
            order["claimed_at"] = float(raw_claimed)
        except (ValueError, TypeError):
            try:
                order["claimed_at"] = datetime.strptime(str(raw_claimed), "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                order["claimed_at"] = None
    columns = ["order_id", "razorpay_order_id", "razorpay_payment_id", "file_name", "file_path", "file_size", "pages", "copies", "paper_size", "page_range", "color_mode", "duplex", "binding", "orientation", "print_quality", "dpi", "scaling", "custom_scale", "margins", "amount", "paid", "status", "document_status", "timestamp", "created_at", "completed_at", "print_error", "claimed_at", "printed_by_printer", "backup_printer", "retry_count", "scale_mode", "print_mode", "pages_per_sheet", "page_order", "customer_mobile"]
    values = [order.get(column) for column in columns]
    placeholders = ", ".join(["%s"] * len(columns)) if DATABASE_URL else ", ".join(["?"] * len(columns))
    updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "order_id")
    if DATABASE_URL:
        sql = f"INSERT INTO printflow_orders ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT (order_id) DO UPDATE SET {updates} RETURNING *"
    else:
        sql = f"INSERT INTO printflow_orders ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT(order_id) DO UPDATE SET {updates}"
    result = _execute(sql, values, "one" if DATABASE_URL else "none")
    return result or get_order(order["order_id"])


def get_order(order_id: str) -> Optional[dict]:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    return _execute(f"SELECT * FROM printflow_orders WHERE order_id={placeholder} OR razorpay_order_id={placeholder} LIMIT 1", (order_id, order_id), "one")


def list_orders() -> list[dict]:
    init_storage()
    return _execute("SELECT * FROM printflow_orders ORDER BY created_at DESC", fetch="all") or []


def get_queued_orders() -> list[dict]:
    init_storage()
    return _execute("SELECT * FROM printflow_orders WHERE status='PRINT_QUEUED' ORDER BY created_at ASC", fetch="all") or []


def get_active_queue_orders() -> list[dict]:
    init_storage()
    return _execute("SELECT * FROM printflow_orders WHERE status IN ('PRINTING', 'PRINT_QUEUED') ORDER BY CASE WHEN status='PRINTING' THEN 0 ELSE 1 END, created_at ASC", fetch="all") or []


def queue_paid_order(order_id: str, razorpay_order_id: str, payment_id: str) -> Optional[dict]:
    init_storage()
    if DATABASE_URL:
        with get_connection() as connection:
            from psycopg2.extras import RealDictCursor
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM printflow_orders WHERE order_id=%s FOR UPDATE", (order_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                if row["paid"] and row["razorpay_payment_id"] != payment_id:
                    raise ValueError("Order is already paid")
                cursor.execute("UPDATE printflow_orders SET paid=TRUE, razorpay_order_id=%s, razorpay_payment_id=%s, status='PRINT_QUEUED', document_status='UPLOADED' WHERE order_id=%s RETURNING *", (razorpay_order_id, payment_id, order_id))
                result = dict(cursor.fetchone())
            connection.commit()
            return result
    order = get_order(order_id)
    if not order:
        return None
    if order["paid"] and order.get("razorpay_payment_id") != payment_id:
        raise ValueError("Order is already paid")
    order.update({"paid": True, "razorpay_order_id": razorpay_order_id, "razorpay_payment_id": payment_id, "status": "PRINT_QUEUED", "document_status": "UPLOADED"})
    return save_order(order)


def claim_order(order_id: str) -> Optional[dict]:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    if DATABASE_URL:
        return _execute(
            f"UPDATE printflow_orders SET status='PRINTING', document_status='PRINTING', claimed_at=EXTRACT(EPOCH FROM NOW()) WHERE (order_id={placeholder} OR razorpay_order_id={placeholder}) AND status='PRINT_QUEUED' RETURNING *",
            (order_id, order_id),
            "one"
        )
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE printflow_orders SET status='PRINTING', document_status='PRINTING', claimed_at=strftime('%s', 'now') WHERE (order_id=? OR razorpay_order_id=?) AND status='PRINT_QUEUED'",
            (order_id, order_id)
        )
        connection.commit()
        return get_order(order_id) if cursor.rowcount == 1 else None


def complete_order(order_id: str, status: str, error: str = "", printer: str = "") -> Optional[dict]:
    order = get_order(order_id)
    if not order:
        return None
    order["status"] = status
    order["document_status"] = "PRINTED" if status == "COMPLETED" else "UPLOADED"
    order["print_error"] = error or None
    order["printed_by_printer"] = printer or order.get("printed_by_printer")
    if status == "COMPLETED":
        order["completed_at"] = datetime.utcnow().isoformat()
    return save_order(order)


def save_document(file_name: str, mime_type: str, content: bytes) -> str:
    init_storage()
    document_id = uuid4().hex
    columns = "document_id, file_name, mime_type, content, created_at"
    placeholders = "%s, %s, %s, %s, %s" if DATABASE_URL else "?, ?, ?, ?, ?"
    _execute(f"INSERT INTO printflow_documents ({columns}) VALUES ({placeholders})", (document_id, file_name, mime_type or "application/octet-stream", content, datetime.utcnow().isoformat()))
    return document_id


def get_document(document_id: str) -> Optional[dict]:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    return _execute(f"SELECT document_id, file_name, mime_type, content FROM printflow_documents WHERE document_id={placeholder}", (document_id,), "one")


def delete_document(document_id: str):
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    _execute(f"DELETE FROM printflow_documents WHERE document_id={placeholder}", (document_id,))


def delete_order(order_id: str):
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    _execute(f"DELETE FROM printflow_orders WHERE order_id={placeholder} OR razorpay_order_id={placeholder}", (order_id, order_id))

