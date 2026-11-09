import pathlib
import unittest
from merchant_connector import performance

ROOT = pathlib.Path(__file__).resolve().parents[1]

class BusinessDashboardFixTests(unittest.TestCase):
    def test_no_duplicate_desktop_statistics(self):
        txt = (ROOT / 'templates/base.html').read_text()
        self.assertEqual(txt.count("class=\"{{ 'active' if request.endpoint=='project_statistics' else '' }}\""), 1)

    def test_merchant_sql_uses_snake_case(self):
        called=[]
        def fake(method,url,payload=None):
            called.append(payload['query'])
            return {'results':[]}
        performance(fake,'accounts/123')
        self.assertIn('FROM product_performance_view', called[0])
        self.assertNotIn('ProductPerformanceView',called[0])

    def test_chart_markup_present(self):
        txt=(ROOT / 'templates/statistics.html').read_text()
        self.assertIn('stat-trend',txt)
        self.assertIn('stat-bar-chart',txt)

if __name__=='__main__':unittest.main()
