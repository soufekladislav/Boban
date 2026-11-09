import sqlite3
import unittest
from datetime import datetime, timedelta
import advisor_intelligence as ai
from sync_reporting import status_label


class AdvisorIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        ai.ensure_schema(self.conn,'sqlite')
        self.conn.execute('CREATE TABLE projects (id INTEGER,business_goal TEXT,primary_conversion TEXT)')
        self.conn.execute('CREATE TABLE integrations (project_id INTEGER,provider TEXT,status TEXT,updated_at TEXT)')
        self.conn.execute('CREATE TABLE source_snapshots (id INTEGER PRIMARY KEY,project_id INTEGER,provider TEXT,payload TEXT,captured_at TEXT)')
        self.conn.execute('CREATE TABLE analytics_business_outcomes (project_id INTEGER,outcome_type TEXT,status TEXT,test_record INTEGER,amount REAL,currency TEXT,id INTEGER)')
        self.conn.execute('INSERT INTO projects VALUES (3,?,?)',('Získat prvních deset reálných objednávek bez placené reklamy','purchase'))
        self.conn.execute('INSERT INTO integrations VALUES (3,?,?,?)',('meta','connected',datetime.now().isoformat()))
        self.conn.commit()
    def tearDown(self):self.conn.close()
    def test_memory_is_idempotent_and_provenance_is_visible(self):
        self.assertEqual(ai.sync_project_facts(self.conn,'sqlite',3),2)
        ai.sync_project_facts(self.conn,'sqlite',3)
        notes=ai.recent_memory(self.conn,3)
        self.assertEqual(len(notes),2)
        self.assertEqual([x for x in notes if x['kind']=='goal'][0]['status'],'decision')
        self.assertIn('connected',[x for x in notes if x['kind']=='integration'][0]['statement'])
        self.assertIn('dostupnost dat se ověřuje',str(notes))
    def test_stale_note_has_expiry(self):
        ai.upsert_memory(self.conn,'sqlite',3,'x','observation','Old','audit',valid_until='2025-01-01T00:00:00')
        self.assertTrue(ai.recent_memory(self.conn,3)[0]['stale'])
    def test_missing_sales_are_not_zero(self):
        data=ai.analyze(self.conn,3,'Kolik máme objednávek?')
        self.assertIsNone(data['facts']['business_outcomes']['real_orders_in_loaded_sample'])
        self.assertIn('Chybí ověřený',data['limitations'][0])
    def test_analysis_trace(self):
        result=ai.analyze(self.conn,3,'Co zákazníci hledají?')
        ai.record_analysis(self.conn,3,'Co zákazníci hledají?',result)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM advisor_analysis_runs').fetchone()[0],1)
        self.assertEqual(result['tool'],'search_demand')
    def test_sync_skip_is_not_success_claim(self):
        self.assertIn('SKIPPED',status_label(True,True,'2026-11-08T20:00:00','completed',False))
        self.assertIn('ERROR',status_label(True,True,'2026-11-08T20:00:00','failed',False,'invalid_grant'))
        self.assertIn('NOT_CONNECTED',status_label(False,True))
    def test_no_inferred_merchant_sales(self):
        r=ai.analyze(self.conn,3,'Katalog Meta a výsledky')
        self.assertEqual(r['facts']['connections'][0]['status'],'connected')
        self.assertIn('neznamená měřitelný',r['limitations'][0])

if __name__=='__main__':unittest.main()
