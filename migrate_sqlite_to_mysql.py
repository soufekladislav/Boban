#!/usr/bin/env python3
"""One-time migration from the current Web Booster SQLite database to MariaDB/MySQL.

Usage (from the Web Booster virtualenv):
  DATABASE_URL='mysql://USER:PASSWORD@localhost/DBNAME' \
  python migrate_sqlite_to_mysql.py --sqlite /home/.../webbooster.db

The destination database must be empty or initialized by the current Web Booster.
The script preserves IDs, password hashes, encrypted connector secrets, projects,
messages, audits, issues, actions and analytics snapshots.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", required=True, help="Path to the source webbooster.db")
    p.add_argument("--allow-nonempty", action="store_true", help="Allow destination tables containing data (not recommended)")
    return p.parse_args()


def main():
    args = parse_args()
    source_path = Path(args.sqlite).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"SQLite file not found: {source_path}")
    if not (os.getenv("DATABASE_URL") or "").startswith(("mysql://", "mysql+pymysql://", "mariadb://")):
        raise SystemExit("Set DATABASE_URL to the empty MariaDB/MySQL database before running this script.")

    # Import after DATABASE_URL is already present. app.init_db() creates destination schema.
    import app as wb
    if wb.DB_BACKEND != "mysql":
        raise SystemExit("Web Booster did not select mysql backend. Check DATABASE_URL.")

    src = sqlite3.connect(str(source_path))
    src.row_factory = sqlite3.Row
    dst = wb.db()

    tables = [
        "users", "projects", "messages", "activities", "snapshots", "integrations",
        "audits", "issues", "actions", "action_revisions", "metric_points", "source_snapshots",
        "search_performance", "engine_runs", "jobs", "notifications",
    ]

    src_tables = {r["name"] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    # Do not accidentally duplicate data.
    if not args.allow_nonempty:
        nonempty = []
        for table in tables:
            try:
                c = dst.execute(f"SELECT COUNT(*) AS c FROM `{table}`").fetchone()["c"]
            except Exception:
                c = 0
            if c:
                nonempty.append((table, c))
        if nonempty:
            raise SystemExit("Destination is not empty: " + ", ".join(f"{t}={c}" for t, c in nonempty))

    imported = {}
    try:
        for table in tables:
            if table not in src_tables:
                imported[table] = 0
                continue
            src_cols = [r["name"] for r in src.execute(f'PRAGMA table_info("{table}")').fetchall()]
            dst_cols = wb._table_columns(dst, table)
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                imported[table] = 0
                continue
            rows = src.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()
            if not rows:
                imported[table] = 0
                continue
            marks = ",".join("?" for _ in cols)
            col_sql = ",".join(f"`{c}`" for c in cols)
            sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({marks})"
            count = 0
            for row in rows:
                dst.execute(sql, tuple(row[c] for c in cols))
                count += 1
            imported[table] = count
            # Keep next auto-increment above copied IDs.
            if "id" in cols and count:
                max_id = src.execute(f'SELECT MAX(id) AS m FROM "{table}"').fetchone()["m"] or 0
                if max_id:
                    dst.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT={int(max_id)+1}")
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()

    # Rebuild dedupe fingerprints/scores after data copy (safe for v0.3+ and useful for older snapshots).
    wb.migrate_issue_fingerprints()

    # Verification using a fresh destination connection.
    dst = wb.db()
    failed = False
    print("\nMigration summary")
    print("-----------------")
    for table, src_count in imported.items():
        try:
            dst_count = int(dst.execute(f"SELECT COUNT(*) AS c FROM `{table}`").fetchone()["c"])
        except Exception:
            dst_count = -1
        ok = dst_count == src_count
        print(f"{table:18} source={src_count:6} destination={dst_count:6} {'OK' if ok else 'MISMATCH'}")
        failed = failed or not ok
    dst.close()

    if failed:
        raise SystemExit("Migration finished with count mismatches. Keep the SQLite backup and do not switch production yet.")
    print("\nMigration verified. Keep the original SQLite file as a backup until production is checked.")


if __name__ == "__main__":
    main()
