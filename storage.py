import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

DATABASE_URL = os.environ.get("DATABASE_URL_UNPOOLED", "").strip() or os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    for env_file in [Path(__file__).resolve().parent / ".env.local", Path(__file__).resolve().parent / ".env"]:
        if env_file.exists():
            env_dict = {}
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_dict[k.strip()] = v.strip().strip('"').strip("'")
            if env_dict.get("DATABASE_URL_UNPOOLED"):
                DATABASE_URL = env_dict["DATABASE_URL_UNPOOLED"]
                break
            elif env_dict.get("DATABASE_URL"):
                DATABASE_URL = env_dict["DATABASE_URL"]
                break

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL

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
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL is configured but psycopg2-binary is not installed") from exc

    for attempt in range(3):
        try:
            return psycopg2.connect(DATABASE_URL, connect_timeout=5)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.5)


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
    is_broken = False
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
    except Exception:
        is_broken = True
        raise
    finally:
        if is_pooled and pool and conn:
            if is_broken or conn.closed:
                try:
                    pool.putconn(conn, close=True)
                except Exception:
                    pass
            else:
                try:
                    conn.rollback()
                    pool.putconn(conn)
                except Exception:
                    try:
                        pool.putconn(conn, close=True)
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
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS printflow_agent_state (
                        id TEXT PRIMARY KEY,
                        printers TEXT DEFAULT '[]',
                        status TEXT DEFAULT 'OFFLINE',
                        last_seen DOUBLE PRECISION DEFAULT 0.0
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS printflow_upload_chunks (
                        upload_id TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        total_chunks INTEGER NOT NULL,
                        chunk_data BYTEA NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (upload_id, chunk_index)
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
                    "binding": "TEXT DEFAULT ''",
                    "files": "TEXT DEFAULT '[]'",
                    "spooler_job_id": "INTEGER DEFAULT 0"
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
                CREATE TABLE IF NOT EXISTS printflow_agent_state (
                    id TEXT PRIMARY KEY,
                    printers TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'OFFLINE',
                    last_seen REAL DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS printflow_upload_chunks (
                    upload_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    chunk_data BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (upload_id, chunk_index)
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
                "binding": "TEXT DEFAULT ''",
                "files": "TEXT DEFAULT '[]'",
                "spooler_job_id": "INTEGER DEFAULT 0"
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
    if "files" in item and item["files"]:
        try:
            if isinstance(item["files"], str):
                item["files"] = json.loads(item["files"])
        except Exception:
            pass
    elif "files" not in item:
        item["files"] = []
    if "print_error" in item and "error" not in item:
        item["error"] = item["print_error"]
    elif "error" in item and "print_error" not in item:
        item["print_error"] = item["error"]
    return item


def _execute(sql: str, params=(), fetch: str = "none", _retries: int = 1):
    try:
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
    except Exception as e:
        if DATABASE_URL and _retries > 0:
            import psycopg2
            if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
                return _execute(sql, params, fetch=fetch, _retries=_retries - 1)
        raise


def save_order(order: dict) -> dict:
    init_storage()
    order.setdefault("razorpay_order_id", None)
    order.setdefault("razorpay_payment_id", None)
    order.setdefault("file_name", "document.pdf")
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
    order.setdefault("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
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
    order.setdefault("spooler_job_id", 0)

    # Serialize files manifest if given as list/dict
    raw_files = order.get("files")
    if isinstance(raw_files, (list, dict)):
        order["files"] = json.dumps(raw_files)
    elif not raw_files:
        order["files"] = "[]"

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

    columns = [
        "order_id", "razorpay_order_id", "razorpay_payment_id", "file_name", "file_path",
        "file_size", "pages", "copies", "paper_size", "page_range", "color_mode", "duplex",
        "binding", "orientation", "print_quality", "dpi", "scaling", "custom_scale", "margins",
        "amount", "paid", "status", "document_status", "timestamp", "created_at", "completed_at",
        "print_error", "claimed_at", "printed_by_printer", "backup_printer", "retry_count",
        "scale_mode", "print_mode", "pages_per_sheet", "page_order", "customer_mobile",
        "files", "spooler_job_id"
    ]
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


def complete_order(order_id: str, status: str, error: str = "", printer: str = "", spooler_job_id: int = 0, **kwargs) -> Optional[dict]:
    order = get_order(order_id)
    if not order:
        return None
    order["status"] = status
    order["document_status"] = "PRINTED" if status == "COMPLETED" else "UPLOADED"
    order["print_error"] = error or None
    effective_printer = printer or kwargs.get("printer_name") or order.get("printed_by_printer")
    order["printed_by_printer"] = effective_printer
    if spooler_job_id:
        order["spooler_job_id"] = spooler_job_id
    if status == "COMPLETED":
        order["completed_at"] = datetime.now(timezone.utc).isoformat()
    return save_order(order)


def save_document(file_name: str, mime_type: str, content: bytes) -> str:
    init_storage()
    document_id = uuid4().hex
    safe_mime = mime_type if isinstance(mime_type, str) and mime_type.strip() else "application/octet-stream"
    columns = "document_id, file_name, mime_type, content, created_at"
    if DATABASE_URL:
        import psycopg2
        _execute(
            f"INSERT INTO printflow_documents ({columns}) VALUES (%s, %s, %s, %s, %s)",
            (document_id, str(file_name), safe_mime, psycopg2.Binary(content), datetime.now(timezone.utc).isoformat())
        )
    else:
        _execute(
            f"INSERT INTO printflow_documents ({columns}) VALUES (?, ?, ?, ?, ?)",
            (document_id, str(file_name), safe_mime, bytes(content), datetime.now(timezone.utc).isoformat())
        )
    return document_id


def get_document(document_id: str) -> Optional[dict]:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    row = _execute(f"SELECT document_id, file_name, mime_type, content FROM printflow_documents WHERE document_id={placeholder}", (document_id,), "one")
    if row and "content" in row and row["content"] is not None:
        row["content"] = bytes(row["content"])
    return row


def get_document_meta(document_id: str) -> Optional[dict]:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    if DATABASE_URL:
        sql = f"SELECT document_id, file_name, mime_type, OCTET_LENGTH(content) AS file_size, created_at FROM printflow_documents WHERE document_id={placeholder}"
    else:
        sql = f"SELECT document_id, file_name, mime_type, length(content) AS file_size, created_at FROM printflow_documents WHERE document_id={placeholder}"
    return _execute(sql, (document_id,), "one")


def delete_document(document_id: str):
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    _execute(f"DELETE FROM printflow_documents WHERE document_id={placeholder}", (document_id,))


def save_upload_chunk(upload_id: str, chunk_index: int, total_chunks: int, chunk_data: bytes) -> None:
    init_storage()
    now_iso = datetime.now(timezone.utc).isoformat()
    if DATABASE_URL:
        import psycopg2
        sql = """
            INSERT INTO printflow_upload_chunks (upload_id, chunk_index, total_chunks, chunk_data, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (upload_id, chunk_index) DO UPDATE SET chunk_data = EXCLUDED.chunk_data, created_at = EXCLUDED.created_at
        """
        _execute(sql, (upload_id, chunk_index, total_chunks, psycopg2.Binary(chunk_data), now_iso), fetch="none")
    else:
        sql = """
            INSERT INTO printflow_upload_chunks (upload_id, chunk_index, total_chunks, chunk_data, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(upload_id, chunk_index) DO UPDATE SET chunk_data = excluded.chunk_data, created_at = excluded.created_at
        """
        _execute(sql, (upload_id, chunk_index, total_chunks, bytes(chunk_data), now_iso), fetch="none")


def assemble_upload_chunks(upload_id: str, total_chunks: int) -> bytes:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    rows = _execute(
        f"SELECT chunk_index, chunk_data FROM printflow_upload_chunks WHERE upload_id={placeholder} ORDER BY chunk_index ASC",
        (upload_id,),
        fetch="all"
    )
    if not rows or len(rows) < total_chunks:
        count = len(rows) if rows else 0
        raise ValueError(f"Incomplete upload for {upload_id}: expected {total_chunks} chunks, found {count}")

    assembled = bytearray()
    for row in rows:
        data = row["chunk_data"] if isinstance(row, dict) else row[1]
        assembled.extend(bytes(data))

    # Clean up upload chunks after successful assembly
    _execute(f"DELETE FROM printflow_upload_chunks WHERE upload_id={placeholder}", (upload_id,), fetch="none")
    return bytes(assembled)


def cleanup_expired_upload_chunks(max_age_hours: int = 2) -> int:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    return _execute(f"DELETE FROM printflow_upload_chunks WHERE created_at < {placeholder}", (cutoff_iso,), fetch="none") or 0


def delete_order(order_id: str):
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    _execute(f"DELETE FROM printflow_orders WHERE order_id={placeholder} OR razorpay_order_id={placeholder}", (order_id, order_id))


def save_agent_state(printers: list, status: str = "ONLINE", last_seen: float = 0.0):
    init_storage()
    if not last_seen:
        last_seen = time.time()
    printers_json = json.dumps(printers)
    if DATABASE_URL:
        sql = """
            INSERT INTO printflow_agent_state (id, printers, status, last_seen)
            VALUES ('default', %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                printers = EXCLUDED.printers,
                status = EXCLUDED.status,
                last_seen = EXCLUDED.last_seen
        """
        _execute(sql, (printers_json, status, last_seen), fetch="none")
    else:
        sql = """
            INSERT INTO printflow_agent_state (id, printers, status, last_seen)
            VALUES ('default', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                printers = excluded.printers,
                status = excluded.status,
                last_seen = excluded.last_seen
        """
        _execute(sql, (printers_json, status, last_seen), fetch="none")


def get_agent_state() -> dict:
    init_storage()
    placeholder = "%s" if DATABASE_URL else "?"
    row = _execute(f"SELECT printers, status, last_seen FROM printflow_agent_state WHERE id={placeholder} LIMIT 1", ('default',), fetch="one")
    if not row:
        return {"printers": [], "status": "OFFLINE", "last_seen": 0.0}
    printers = []
    if row.get("printers"):
        try:
            printers = json.loads(row["printers"]) if isinstance(row["printers"], str) else row["printers"]
        except Exception:
            pass
    return {
        "printers": printers,
        "status": row.get("status", "OFFLINE"),
        "last_seen": float(row.get("last_seen", 0.0) or 0.0)
    }


