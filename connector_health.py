"""Durable, independent connector connectivity probes (not analytics downloads)."""
from datetime import datetime, timezone


def ensure_schema(conn, backend):
    if backend == "mysql":
        conn.execute("""CREATE TABLE IF NOT EXISTS connector_health (
            project_id BIGINT UNSIGNED NOT NULL,
            provider VARCHAR(48) NOT NULL,
            status VARCHAR(16) NOT NULL,
            checked_at VARCHAR(40) NOT NULL,
            last_success_at VARCHAR(40) NULL,
            error_type VARCHAR(100) NULL,
            PRIMARY KEY(project_id,provider)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS connector_health (
            project_id INTEGER NOT NULL,provider TEXT NOT NULL,status TEXT NOT NULL,
            checked_at TEXT NOT NULL,last_success_at TEXT,error_type TEXT,
            PRIMARY KEY(project_id,provider))""")


def record(conn, backend, project_id, provider, status, error_type=None):
    """Keep last known good proof when a later probe fails."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = conn.execute("SELECT last_success_at FROM connector_health WHERE project_id=? AND provider=?",
                            (project_id,provider)).fetchone()
    success = now if status == "ok" else (existing["last_success_at"] if existing else None)
    data = (project_id,provider,status,now,success,str(error_type or "")[:100] or None)
    if backend == "mysql":
        conn.execute("""INSERT INTO connector_health(project_id,provider,status,checked_at,last_success_at,error_type)
            VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE status=VALUES(status),
            checked_at=VALUES(checked_at),last_success_at=VALUES(last_success_at),error_type=VALUES(error_type)""",data)
    else:
        conn.execute("""INSERT INTO connector_health(project_id,provider,status,checked_at,last_success_at,error_type)
            VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,provider) DO UPDATE SET
            status=excluded.status,checked_at=excluded.checked_at,
            last_success_at=excluded.last_success_at,error_type=excluded.error_type""",data)


def list_status(conn, project_id):
    return [dict(row) for row in conn.execute(
        "SELECT provider,status,checked_at,last_success_at,error_type "
        "FROM connector_health WHERE project_id=? ORDER BY provider",(project_id,)).fetchall()]
