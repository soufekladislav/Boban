"""Regression: second project without an approved feed must not produce HTTP 500."""
import ast
import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parents[1] / 'app.py'

class MerchantPublishPreconditionTests(unittest.TestCase):
    def test_feed_and_account_preconditions_are_inside_try(self):
        tree = ast.parse(APP.read_text(encoding='utf8'))
        fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'merchant_publish_feed')
        outer_try = next(x for x in fn.body if isinstance(x, ast.Try))
        names = {n.func.id for stmt in outer_try.body for n in ast.walk(stmt)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn('merchant_feed_address', names)
        self.assertIn('merchant_api', names)
        self.assertTrue(any(isinstance(h.type, ast.Tuple) and any(isinstance(x, ast.Name) and x.id == 'ValueError' for x in h.type.elts)
                            for h in outer_try.handlers))

    def test_original_merchant_account_and_source_reuse_unchanged(self):
        import merchant_connector as m
        self.assertEqual(m.account_name('778399976'), 'accounts/778399976')
        self.assertEqual(m.find_existing_source([{'name':'accounts/1/dataSources/2',
            'primaryProductDataSource':{}, 'fileInput':{'fetchSettings':{'fetchUri':'https://x.test/xml'}}}],
            'https://x.test/xml')['name'], 'accounts/1/dataSources/2')

if __name__ == '__main__': unittest.main()
