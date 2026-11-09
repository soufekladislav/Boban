import ast
import pathlib
import unittest
import merchant_connector as m

ROOT=pathlib.Path(__file__).resolve().parents[1]

class FirstFetchTests(unittest.TestCase):
    def test_fetch_endpoint_and_account_binding(self):
        calls=[]
        def api(method,url,payload=None):
            calls.append((method,url,payload));return {}
        m.fetch_source(api,'accounts/5073368700/dataSources/10791492491','accounts/5073368700')
        self.assertEqual(calls[0],('POST','https://merchantapi.googleapis.com/datasources/v1/accounts/5073368700/dataSources/10791492491:fetch',{}))
        with self.assertRaises(ValueError):
            m.fetch_source(api,'accounts/2/dataSources/3','accounts/1')
    def test_app_routes_and_handling(self):
        code=(ROOT/'app.py').read_text()
        ast.parse(code)
        self.assertIn("def merchant_fetch_now(project_id):",code)
        self.assertIn('merchant_check_csrf()',code)
        self.assertIn('merchant_feed_address(project_id)',code)
        self.assertIn("'File upload not found' in message",code)
        self.assertIn("cfg['fetch_requested_at']=now()",code)
        self.assertIn('20*3600',code)
        self.assertIn('merchant_published_feed_fingerprint(project_id)',code)
        self.assertIn("cfg['fetch_feed_sha256']=digest",code)
        self.assertIn('Načíst aktuální XML Googlem',(ROOT/'templates/ecommerce.html').read_text())

if __name__=='__main__': unittest.main()
