from pathlib import Path
import ast
import unittest
from jinja2 import Environment, FileSystemLoader
ROOT=Path(__file__).resolve().parents[1]

class MerchantUiLayout(unittest.TestCase):
    def test_connectors_only_account_linking(self):
        txt=(ROOT/'templates/connectors.html').read_text()
        segment=txt.split('id="merchant-center"',1)[1].split('connector-roadmap',1)[0]
        for forbidden in ('merchant_fetch_now','merchant_publish_feed','merchant_check','merchant_performance'):
            self.assertNotIn("url_for('"+forbidden+"'",segment)
        self.assertIn("url_for('merchant_choose_account'",segment)
        self.assertIn('merchant-platform',segment)
        self.assertEqual(txt.count('<div class="connector-grid">'),1)
        self.assertEqual(txt.count('id="merchant-center"'),1)
    def test_ecommerce_owns_actions_and_results(self):
        txt=(ROOT/'templates/ecommerce.html').read_text()
        for action in ('merchant_fetch_now','merchant_publish_feed','merchant_check','merchant_performance'):
            self.assertIn("url_for('"+action+"'",txt)
        self.assertIn('commerce-platform-grid',txt)
        self.assertIn('merchant_csrf',txt)
        self.assertIn('Znovu publikovat schválené XML',txt)
        self.assertIn('data-merchant-tab',txt)
        self.assertIn('merchant-pane-performance',txt)
    def test_routes_render_and_redirect_to_commerce(self):
        code=(ROOT/'app.py').read_text()
        ast.parse(code)
        self.assertIn('merchant_csrf=session[',code)
        for name in ('merchant_publish_feed','merchant_fetch_now','merchant_check','merchant_performance'):
            portion=code.split('def '+name+'(',1)[1].split('\n@app.route',1)[0]
            self.assertIn("url_for('ecommerce',project_id=project_id)",portion)
        env=Environment(loader=FileSystemLoader(str(ROOT/'templates')))
        env.get_template('ecommerce.html')
        env.get_template('connectors.html')
