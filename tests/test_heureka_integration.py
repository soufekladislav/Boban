from pathlib import Path
import ast
import unittest
from jinja2 import Environment,FileSystemLoader
root=Path(__file__).resolve().parents[1]

class HeurekaIntegration(unittest.TestCase):
    def test_routes_and_public_feeds_exist(self):
        text=(root/'app.py').read_text()
        ast.parse(text)
        for item in ('def catalog_publish_heureka','def ecommerce_heureka_build','def catalog_heureka_public','def catalog_heureka_availability_public','def heureka_connector_save','fast_dispatch_confirmed','catalog_publish_heureka(project_id)'):
            self.assertIn(item,text)
    def test_templates_compile(self):
        env=Environment(loader=FileSystemLoader(str(root/'templates')))
        env.get_template('ecommerce.html')
        env.get_template('connectors.html')
    def test_connector_does_not_manage_feed_export(self):
        text=(root/'templates/connectors.html').read_text().split('id="heureka-connector"',1)[1].split('connector-roadmap',1)[0]
        self.assertIn('heureka_connector_save',text)
        self.assertNotIn('ecommerce_heureka_build',text)
    def test_ecommerce_has_both_feeds(self):
        text=(root/'templates/ecommerce.html').read_text()
        self.assertIn('catalog_heureka_public',text)
        self.assertIn('catalog_heureka_availability_public',text)
        self.assertIn('ecommerce_heureka_build',text)
        self.assertIn('commerce-platform-grid',text)
if __name__=='__main__':unittest.main()
