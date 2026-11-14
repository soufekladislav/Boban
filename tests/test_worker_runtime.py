"""Queue runtime and Prague daily sync regression tests (no network / app import)."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import worker_runtime
import sync_schedule


class WorkerRuntimeTests(unittest.TestCase):
    def test_exclusive_lock_rejects_concurrent_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.lock"
            with worker_runtime.exclusive_lock(path) as first:
                self.assertTrue(first)
                with worker_runtime.exclusive_lock(path) as second:
                    self.assertFalse(second)
            with worker_runtime.exclusive_lock(path) as third:
                self.assertTrue(third)

    def test_prague_05_gate(self):
        before = datetime(2026, 11, 14, 4, 55, tzinfo=worker_runtime.PRAGUE)
        after = datetime(2026, 11, 14, 5, 1, tzinfo=worker_runtime.PRAGUE)
        self.assertFalse(worker_runtime.daily_due(None, before))
        self.assertTrue(worker_runtime.daily_due(None, after))
        self.assertTrue(worker_runtime.daily_due(None, before, force=True))

    def test_completed_source_not_refetched_and_force_can_repeat(self):
        now = worker_runtime.prague_now()
        state = {"status": "completed", "started_at": datetime.now(timezone.utc).isoformat()}
        self.assertFalse(worker_runtime.daily_due(state, now))
        self.assertTrue(worker_runtime.daily_due(state, now, force=True))

    def test_running_source_remains_locked_even_if_manual(self):
        state = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
        self.assertFalse(worker_runtime.daily_due(state, worker_runtime.prague_now(), force=True))

    def test_failure_backoff(self):
        at = worker_runtime.prague_now()
        state = {"status": "failed", "started_at": datetime.now(timezone.utc).isoformat()}
        self.assertFalse(worker_runtime.daily_due(state, at))
        state["started_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertTrue(worker_runtime.daily_due(state, at))

    def test_public_status_does_not_fake_running(self):
        w = {"status": "idle", "healthy": False}
        q = {"total": 4, "queued": 4}
        self.assertIn("čekají", worker_runtime.public_worker_summary(w, q))
        q = {"total": 1, "running": 1}
        self.assertIn("neposílá", worker_runtime.public_worker_summary(w, q))
        w["healthy"] = True; w["status"] = "running"
        self.assertIn("Pracuji", worker_runtime.public_worker_summary(w, q))


class DailyStateTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        sync_schedule.ensure_schema(self.conn, "sqlite")

    def tearDown(self):
        self.conn.close()

    def test_independent_sources_and_days(self):
        today = "2026-11-14"
        sync_schedule.record_state(self.conn, "sqlite", 3, "ga4", today, "running")
        sync_schedule.record_state(self.conn, "sqlite", 3, "ga4", today, "failed", "upstream timeout")
        sync_schedule.record_state(self.conn, "sqlite", 3, "search_console", today, "completed")
        self.conn.commit()
        state = sync_schedule.get_state(self.conn, 3, "ga4", today)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(len(sync_schedule.latest_status(self.conn, 3, today)), 2)
        self.assertIsNone(sync_schedule.get_state(self.conn, 3, "ga4", "2026-11-15"))

    def test_restart_from_failure(self):
        today = "2026-11-14"
        for status in ("running", "failed", "running", "completed"):
            sync_schedule.record_state(self.conn, "sqlite", 3, "ga4", today, status)
        self.conn.commit()
        self.assertEqual(sync_schedule.get_state(self.conn, 3, "ga4", today)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
