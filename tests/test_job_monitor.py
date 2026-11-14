import json
import sqlite3
import unittest

import job_monitor


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(":memory:")
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT);
            CREATE TABLE actions(id INTEGER PRIMARY KEY,project_id INTEGER,issue_id INTEGER,
             action_type TEXT,reason TEXT,target_url TEXT,proposed_json TEXT);
            CREATE TABLE issues(id INTEGER PRIMARY KEY,project_id INTEGER,title TEXT);
            CREATE TABLE jobs(id INTEGER PRIMARY KEY,project_id INTEGER,action_id INTEGER,
             job_type TEXT,status TEXT,attempts INTEGER,max_attempts INTEGER,
             created_at TEXT,started_at TEXT,updated_at TEXT,finished_at TEXT,
             run_after TEXT,locked_at TEXT,payload_json TEXT);
        """)
        self.conn.execute("INSERT INTO projects VALUES(3,'Fresh Crackers')")
        self.conn.execute("INSERT INTO projects VALUES(4,'Adrenaline Race')")
        self.conn.execute("INSERT INTO issues VALUES(8,3,'Chybějící title na hlavní stránce')")
        self.conn.execute("INSERT INTO actions VALUES(19,3,8,'update_seo_metadata','Zlepšit CTR','https://example.org/','{}')")
        self.conn.execute("""INSERT INTO jobs VALUES
            (21,3,19,'seo_apply_action','running',1,3,
             '2026-11-14T14:00:00','2026-11-14T14:10:00','2026-11-14T14:11:00',NULL,NULL,NULL,'{}')""")
        self.conn.execute("""INSERT INTO jobs VALUES
            (22,4,NULL,'seo_ai_prepare','queued',0,3,
             '2026-11-14T14:20:00',NULL,NULL,NULL,NULL,NULL,'{}')""")
        self.conn.execute("""INSERT INTO jobs VALUES
            (23,3,NULL,'seo_ai_prepare','queued',0,3,
             '2026-11-14T14:23:00',NULL,NULL,NULL,NULL,NULL,?)""",
            (json.dumps({'issue_ids':[8]}),))
        self.conn.execute("""INSERT INTO jobs VALUES
            (24,3,NULL,'seo_verify_action','completed',1,3,
             '2026-11-14T13:00:00','2026-11-14T13:02:00',
             '2026-11-14T13:07:00','2026-11-14T13:07:00',NULL,NULL,'{}')""")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_real_issue_title_and_actual_timestamps(self):
        rows=job_monitor.load_jobs(self.conn,project_id=3)
        item=next(x for x in rows if x['id']==21)
        self.assertEqual(item['title'],'Chybějící title na hlavní stránce')
        self.assertEqual(item['started_at'],'2026-11-14T14:10:00')
        self.assertIsNone(item['finished_at'])
        self.assertEqual(item['stage'],'Právě probíhá')
        self.assertIn('/projects/3/actions?',item['action_url'])

    def test_ai_batch_resolves_issue_title_from_payload_without_exposing_payload(self):
        item=next(x for x in job_monitor.load_jobs(self.conn,project_id=3) if x['id']==23)
        self.assertIn('Chybějící title',item['title'])
        self.assertNotIn('payload_json',item)

    def test_isolation_by_project_and_status(self):
        project=job_monitor.load_jobs(self.conn,project_id=4)
        self.assertEqual([r['id'] for r in project],[22])
        errors=job_monitor.load_jobs(self.conn,project_id=3,status='failed')
        self.assertEqual(errors,[])
        other=job_monitor.load_jobs(self.conn,project_id=3,status='nonsense')
        self.assertEqual(len(other),3)

    def test_summary_distinguishes_finished_from_heartbeat(self):
        stats=job_monitor.stats(self.conn,project_id=3)
        self.assertEqual(stats['active'],2)
        self.assertEqual(stats['last_completed'],'2026-11-14T13:07:00')
        bad=job_monitor.movement_state(stats,{'last_seen':'2026-11-14T14:00:00','age_seconds':999})
        self.assertEqual(bad['status'],'unconfirmed')
        good=job_monitor.movement_state(stats,{'last_seen':'2026-11-14T14:00:00','age_seconds':15})
        self.assertTrue(good['cron_confirmed'])
        self.assertEqual(good['status'],'running')

    def test_title_fallback_does_not_invent_issue(self):
        title=job_monitor.title_for({'job_type':'seo_ai_prepare','project_id':3,
                                      'payload_json':json.dumps({'issue_ids':[999]})})
        self.assertEqual(title,'Příprava SEO návrhů')


if __name__=='__main__':
    unittest.main()
