import sqlite3
import unittest
import commerce_analytics as a


class AnalyticsFoundationTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.conn.row_factory=sqlite3.Row
        a.ensure_schema(self.conn,'sqlite')

    def tearDown(self):self.conn.close()

    def test_schemas_exist(self):
        existing={r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'analytics_sync_runs','analytics_observations','analytics_entity_links','analytics_business_outcomes'} <= existing)

    def test_ga4_snapshot_idempotent(self):
        payload={'period':{'start':'2026-10-11','end':'2026-11-07'},'current_total':{'sessions':25},'extended_reports':{'channels':[{'sessionDefaultChannelGroup':'Organic Search','sessions':13,'activeUsers':10}], 'daily_channels':[{'date':'20261106','sessionDefaultChannelGroup':'Organic Search','sessions':3}]}}
        a.record_snapshot(self.conn,2,'ga4',payload,'sqlite')
        a.record_snapshot(self.conn,2,'ga4',payload,'sqlite')
        rows=self.conn.execute('SELECT report_type,period_start,period_end,metrics_json FROM analytics_observations WHERE project_id=2').fetchall()
        self.assertEqual(len(rows),3)
        self.assertTrue(any(r['report_type']=='daily_channels' and r['period_start']=='2026-11-06' for r in rows))

    def test_gsc_query_period_not_assumed_daily(self):
        p={'period':{'start':'2026-10-11','end':'2026-11-07'},'top_queries':[{'keys':['fitness guma'],'clicks':12,'impressions':120,'ctr':.1,'position':5}]}
        a.record_snapshot(self.conn,1,'search_console',p,'sqlite')
        r=self.conn.execute("SELECT period_start,period_end FROM analytics_observations WHERE report_type='queries'").fetchone()
        self.assertEqual((r['period_start'],r['period_end']),('2026-10-11','2026-11-07'))

    def test_no_outcomes_is_unknown_not_zero(self):
        self.assertEqual(a.outcomes_summary(self.conn,1)['orders'],None)
        self.assertFalse(a.outcomes_summary(self.conn,1)['available'])

    def test_test_orders_excluded(self):
        for external_id,test_record in [('test1',1),('real1',0),('unknown1',None)]:
            self.conn.execute('''INSERT INTO analytics_business_outcomes(project_id,source,external_id,outcome_type,occurred_at,status,test_record,amount,currency,observed_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?)''',(1,'woo',external_id,'order','2026-11-08','completed',test_record,100,'CZK','2026-11-08'))
        d=a.outcomes_summary(self.conn,1)
        self.assertEqual(d['orders'],1)
        self.assertEqual(d['revenue'],100)
        self.assertEqual(d['unclassified_test_rows'],1)


if __name__=='__main__': unittest.main()
