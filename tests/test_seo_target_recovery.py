"""Permanent 404s must not loop; Boban sends the exact WP permalink for recovery."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def isolated_app():
    tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name in ('apply_seo_action', 'FreshCorePermanentError')]
    assert len(nodes) == 2
    env = {
        'json': json,
        'decrypt_secret': lambda x: 'test-secret',
        'safe_http_url': lambda x: x,
        'normalize_host': lambda url: url.split('/')[2].removeprefix('www.'),
        'USER_AGENT': 'test',
        'CORE_WRITE_TIMEOUT': 10,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<isolated app>', 'exec'), env)
    return env


class Response:
    def __init__(self, code, data):
        self.status_code = code
        self._data = data
        self.headers = {'content-type':'application/json'}
    def json(self): return self._data


class AppWriteTests(unittest.TestCase):
    def setUp(self):
        self.env = isolated_app()
        self.project = {
            'core_write_status':'connected',
            'core_write_endpoint':'https://adrenalinerace.eu/wp-json/fresh-core/v1',
            'core_write_key_enc':'somecipher',
            'site_url':'https://adrenalinerace.eu'
        }
        self.action = {
            'action_type':'update_meta', 'id':1178,
            'target_id':'12345',
            'target_url':'https://adrenalinerace.eu/produkt/trec-whey-100-2275-g-3/',
            'proposed_json':json.dumps({'title':'Trec Whey 100'})
        }

    def test_write_payload_contains_exact_url(self):
        client=Mock(return_value=Response(200,{'success':True,'data':{'ok':True}}))
        self.env['requests']=SimpleNamespace(post=client)
        self.env['apply_seo_action'](self.project,self.action)
        payload=client.call_args.kwargs['json']
        self.assertEqual(payload['post_id'],12345)
        self.assertEqual(payload['target_url'],self.action['target_url'])
        self.assertEqual(payload['change_id'],'wb-1178')

    def test_missing_target_is_terminal(self):
        resp=Response(404,{'code':'fresh_core_seo_post','data':{'status':404}})
        self.env['requests']=SimpleNamespace(post=Mock(return_value=resp))
        with self.assertRaises(self.env['FreshCorePermanentError']):
            self.env['apply_seo_action'](self.project,self.action)

    def test_temporary_failure_is_retryable(self):
        resp=Response(503,{'code':'maintenance','data':{'status':503}})
        self.env['requests']=SimpleNamespace(post=Mock(return_value=resp))
        with self.assertRaises(ValueError) as err:
            self.env['apply_seo_action'](self.project,self.action)
        self.assertNotIsInstance(err.exception,self.env['FreshCorePermanentError'])

    def test_foreign_url_is_blocked_before_network(self):
        client=Mock()
        self.env['requests']=SimpleNamespace(post=client)
        self.action['target_url']='https://outside.example/p/12'
        with self.assertRaises(self.env['FreshCorePermanentError']):
            self.env['apply_seo_action'](self.project,self.action)
        client.assert_not_called()


if __name__=='__main__':
    unittest.main()
