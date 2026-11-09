import unittest
from datetime import date
from business_dashboard import freshness, page_summary, query_page_samples, funnel_steps, business_mode, analytics_quality, normalize_path

class Dashboard19Tests(unittest.TestCase):
    def test_stale_observed_period(self):
        row={'period_end':'2026-10-08','captured_at':'2026-10-09T07:00:00'}
        self.assertEqual(freshness(row,date(2026,11,8))['state'],'stale')
        self.assertEqual(freshness({'period_end':'2026-11-07','captured_at':'2026-11-08'},date(2026,11,8))['state'],'fresh')
        self.assertEqual(freshness({},date(2026,11,8))['state'],'missing')
    def test_business_type(self):
        self.assertEqual(business_mode({'primary_conversion':'generate_lead'}),'lead')
        self.assertEqual(business_mode({'primary_conversion':'purchase'}),'shop')
    def test_page_join_not_query_attribution(self):
        ga={'extended_reports':{'landing_pages_all':[{'landingPagePlusQueryString':'/produkt/test/?utm_x=1','sessions':10,'engagedSessions':4}]}}
        gsc={'top_pages':[{'keys':['https://example.cz/produkt/test/'],'clicks':3,'impressions':80}],
             'query_pages':[{'keys':['test product','https://example.cz/produkt/test/'],'clicks':2,'impressions':25}]}
        x=page_summary(ga,gsc)
        self.assertEqual(len(x),1)
        self.assertEqual((x[0]['sessions'],x[0]['clicks'],x[0]['type']),(10,3,'product'))
        self.assertNotIn('query',x[0])
        self.assertEqual(query_page_samples(gsc)[0]['query'],'test product')
    def test_unmeasured_vs_zero(self):
        f=funnel_steps('shop',{'current_total':{'sessions':200},'extended_reports':{}},{'available':False})
        self.assertEqual(f[0]['value'],200)
        self.assertIsNone(f[2]['value'])
        f=funnel_steps('shop',{'current_total':{'sessions':200},'extended_reports':{'commerce_events':[]}}, {'available':False})
        self.assertIsNone(f[2]['value']) # no event row is not evidence of zero measured events
        self.assertFalse(f[4]['measured'])
    def test_url_normalization(self):
        self.assertEqual(normalize_path('https://a.cz/PRODUKT/Test/?q=3'),'/produkt/test')
if __name__=='__main__':unittest.main()
