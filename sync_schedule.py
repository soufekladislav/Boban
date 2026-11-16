"""Durable, per-project daily analytics schedule; additive MariaDB/SQLite schema."""
from datetime import datetime, timezone
import worker_runtime


def ensure_schema(conn, backend):
    if backend == "mysql":
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_sync_state (
            project_id BIGINT UNSIGNED NOT NULL,
            provider VARCHAR(48) NOT NULL,
            sync_date VARCHAR(10) NOT NULL,
            status VARCHAR(16) NOT NULL,
            started_at VARCHAR(40) NOT NULL,
            finished_at VARCHAR(40) NULL,
            last_error TEXT NULL,
            PRIMARY KEY(project_id,provider,sync_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_sync_state (
            project_id INTEGER NOT NULL,provider TEXT NOT NULL,sync_date TEXT NOT NULL,
            status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,last_error TEXT,
            PRIMARY KEY(project_id,provider,sync_date))""")


def get_state(conn, project_id, provider, sync_date):
    row = conn.execute(
        "SELECT status,started_at,finished_at,last_error FROM daily_sync_state "
        "WHERE project_id=? AND provider=? AND sync_date=?",
        (project_id, provider, sync_date),
    ).fetchone()
    return dict(row) if row else None


def record_state(conn, backend, project_id, provider, sync_date, status, error=None):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = get_state(conn, project_id, provider, sync_date)
    started_at = now if status == "running" else ((existing or {}).get("started_at") or now)
    finished_at = None if status == "running" else now
    data = (project_id, provider, sync_date, status, started_at, finished_at, (str(error)[:500] if error else None))
    if backend == "mysql":
        conn.execute("""INSERT INTO daily_sync_state
        (project_id,provider,sync_date,status,started_at,finished_at,last_error)
        VALUES(?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE
        status=VALUES(status),started_at=VALUES(started_at),
        finished_at=VALUES(finished_at),last_error=VALUES(last_error)""", data)
    else:
        conn.execute("""INSERT INTO daily_sync_state
        (project_id,provider,sync_date,status,started_at,finished_at,last_error)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id,provider,sync_date)
        DO UPDATE SET status=excluded.status,started_at=excluded.started_at,
        finished_at=excluded.finished_at,last_error=excluded.last_error""", data)


def carry_pending_request(conn, backend, project_id, provider, today):
    """Carry a late-night manual request into the current Prague day.

    This prevents a request at 23:59 disappearing when the five-minute cron
    first wakes up after midnight.
    """
    row = conn.execute(
        "SELECT sync_date FROM daily_sync_state "
        "WHERE project_id=? AND provider=? AND status='requested' AND sync_date<? "
        "ORDER BY sync_date LIMIT 1",
        (project_id, provider, today)
    ).fetchone()
    if not row:
        return False
    previous = row["sync_date"]
    conn.execute(
        "UPDATE daily_sync_state SET status='superseded' WHERE project_id=? AND provider=? AND sync_date=? AND status='requested'",
        (project_id, provider, previous)
    )
    record_state(conn, backend, project_id, provider, today, "requested")
    return True


def latest_status(conn, project_id, sync_date):
    rows = conn.execute(
        "SELECT provider,status,started_at,finished_at,last_error FROM daily_sync_state "
        "WHERE project_id=? AND sync_date=? ORDER BY provider",
        (project_id, sync_date)
    ).fetchall()
    return [dict(r) for r in rows]
