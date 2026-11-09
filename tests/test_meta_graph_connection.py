import unittest
from unittest.mock import patch
import meta_graph

class GraphMetaTests(unittest.TestCase):
    def test_existing_feed_matched_by_url(self):
        feeds=[{'id':'1','schedule':{'url':'https://site.example/catalog/meta/other.xml'}},
               {'id':'2','schedule':{'url':'https://site.example/catalog/meta/token.xml'}}]
        self.assertEqual(meta_graph.match_feed(feeds,'/catalog/meta/token.xml')['id'],'2')
    def test_no_guessing_existing_feed(self):
        self.assertIsNone(meta_graph.match_feed([{'id':'1','name':'Boban'}],'/catalog/meta/t.xml'))
    def test_upload_requires_https(self):
        with self.assertRaises(meta_graph.MetaAPIError):
            meta_graph.trigger_upload('secret','123','http://unsafe.test/feed.xml')
    def test_error_message_does_not_reveal_token(self):
        class Response:
            status_code=403
            def json(self):return {'error':{'code':190,'message':'secret token text'}}
        with patch('requests.request',return_value=Response()):
            with self.assertRaises(meta_graph.MetaAPIError) as e:
                meta_graph.call('GET','123',token='test-secret')
        self.assertNotIn('secret',str(e.exception))
    def test_uploads_returns_processing_counters(self):
        with patch.object(meta_graph,'call',return_value={'data':[{'id':'77','num_detected_items':5604,'num_persisted_items':5500}]}) as f:
            items=meta_graph.uploads('token','123')
            self.assertEqual(items[0]['num_detected_items'],5604)
            self.assertIn('num_persisted_items', f.call_args.kwargs['params']['fields'])

    def test_errors_only_return_safe_descriptions(self):
        with patch.object(meta_graph,'call',return_value={'data':[{'summary':'Missing image','severity':'fatal','total_count':4,'token':'secret'}]}):
            rows=meta_graph.upload_errors('token','555')
            self.assertEqual(rows[0]['total_count'],4)
            self.assertNotIn('token',rows[0])

    def test_catalog_id_must_be_numeric(self):
        with self.assertRaises(meta_graph.MetaAPIError):meta_graph.catalog('valid','not-numeric')

if __name__=='__main__': unittest.main()
