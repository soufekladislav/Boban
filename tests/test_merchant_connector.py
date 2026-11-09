import unittest
import merchant_connector as m

class MerchantTests(unittest.TestCase):
    def test_account_validation(self):
        self.assertEqual(m.account_name('123'),'accounts/123')
        with self.assertRaises(ValueError):m.account_name('accounts/123/../../other')
    def test_source_account_binding(self):
        self.assertEqual(m.source_name('accounts/1/dataSources/4','accounts/1'),'accounts/1/dataSources/4')
        with self.assertRaises(ValueError):m.source_name('accounts/2/dataSources/4','accounts/1')
    def test_existing_source_reused(self):
        sources=[{'name':'accounts/1/dataSources/2','primaryProductDataSource':{},'fileInput':{'fetchSettings':{'fetchUri':'https://demo.test/feed.xml'}}}]
        # The type dictionary can be empty yet present: valid primary source.
        self.assertEqual(m.find_existing_source(sources,'https://demo.test/feed.xml')['name'],'accounts/1/dataSources/2')
    def test_creation_is_authorized_one_source(self):
        calls=[]
        def fake(method,url,payload=None):calls.append((method,url,payload));return {'name':'accounts/1/dataSources/10'}
        self.assertEqual(m.create_source(fake,'accounts/1','https://demo.test/feed.xml','A')['name'],'accounts/1/dataSources/10')
        self.assertEqual(calls[0][0],'POST')
        self.assertEqual(calls[0][2]['fileInput']['fetchSettings']['frequency'],'FREQUENCY_DAILY')
        with self.assertRaises(ValueError):m.create_source(fake,'accounts/1','http://demo.test/feed.xml','A')
    def test_organic_report_calculations(self):
        calls=[]
        def fake(method,url,payload=None):
            calls.append(payload)
            return {'results':[{'productPerformanceView':{'clicks':'10','impressions':'200'}}]}
        r=m.performance(fake,'accounts/1')
        self.assertEqual((r['clicks'],r['impressions'],r['ctr_percent']),(10,200,5.0))
        self.assertIn('ORGANIC',calls[0]['query'])
if __name__=='__main__':unittest.main()
