"""Lightweight heartbeat persistence and queue orchestration structure."""
import ast
import sqlite3
import unittest
from pathlib import Path

import connector_health


ROOT=Path(__file__).resolve().parents[1]


class ConnectorHealthTests(unittest.TestCase):
    def test_remembers_last_success_when_new_probe_fails(self):
        conn=sqlite3.connect(":memory:")
        conn.row_factory=sqlite3.Row
        connector_health.ensure_schema(conn,"sqlite")
        connector_health.record(conn,"sqlite",3,"ga4","ok")
        good=connector_health.list_status(conn,3)[0]
        self.assertTrue(good["last_success_at"])
        connector_health.record(conn,"sqlite",3,"ga4","failed","HTTPError")
        conn.commit()
        bad=connector_health.list_status(conn,3)[0]
        self.assertEqual(bad["status"],"failed")
        self.assertEqual(bad["error_type"],"HTTPError")
        self.assertEqual(bad["last_success_at"],good["last_success_at"])
        conn.close()

    def test_queue_is_claimed_one_at_a_time_and_locked_from_cli(self):
        tree=ast.parse((ROOT/"manage.py").read_text("utf-8"))
        functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        run=ast.get_source_segment((ROOT/"manage.py").read_text("utf-8"), functions["process_seo_apply_jobs"])
        lock=ast.get_source_segment((ROOT/"manage.py").read_text("utf-8"), functions["locked_work_queue"])
        self.assertIn("_claim_jobs(1)",run)
        self.assertIn("JobHeartbeat",run)
        self.assertIn("exclusive_lock",lock)

    def test_data_sync_and_live_probes_are_independent(self):
        src=(ROOT/"manage.py").read_text("utf-8")
        tree=ast.parse(src)
        funcs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        probe=ast.get_source_segment(src,funcs["connector_heartbeat"])
        self.assertNotIn("sync_ga4",probe)
        self.assertNotIn("sync_search_console",probe)
        daily=ast.get_source_segment(src,funcs["run_daily_sync"])
        self.assertIn("prague_now",daily)
        self.assertIn("sync_schedule.record_state",daily)


if __name__=="__main__":
    unittest.main()
