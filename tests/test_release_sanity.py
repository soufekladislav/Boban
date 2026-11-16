"""Regression: live Jinja rendering, Pinterest fallback, Windows cron checkout."""
import hashlib
import unittest
from pathlib import Path

import jinja2
import merchant_export
import pinterest_catalog

ROOT = Path(__file__).resolve().parents[1]


class AdminRenderRegression(unittest.TestCase):
    def test_job_ledger_renders_real_dict_not_items_method(self):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(ROOT / 'templates')),
            autoescape=True
        )
        env.globals['url_for'] = lambda name, **kw: '/admin'
        data = {
            'items': [{
                'id':1178,'title':'Upravit SEO title produktu','purpose':'Zvýšit relevance',
                'project_name':'Adrenaline Race','project_id':3,
                'action_id':1178,'action_url':None,
                'stage':'Čeká','status':'queued','created_at':'2026-11-16T11:00:00',
                'started_at':None,'updated_at':None,'finished_at':None,
                'run_after':None
            }],
            'movement':{'message':'Fronta čeká na spuštění.'},
            'summary':{
                'active':1,'completed_15m':0,'last_completed':None,
                'last_started':None,'oldest_waiting':'2026-11-16T11:00:00'
            }
        }
        html=env.get_template('partials/job_ledger.html').render(
            job_monitor=data,job_monitor_admin=True,projects=[],jobs_filter_project=None,
            jobs_filter_status=None,job_monitor_url='/admin/jobs/status'
        )
        self.assertIn('Upravit SEO title produktu',html)
        self.assertIn('2026-11-16 11:00:00',html)
        self.assertIn('Fronta čeká',html)

    def test_empty_job_ledger_does_not_raise(self):
        env=jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT/'templates')))
        html=env.get_template('partials/job_ledger.html').render(
            job_monitor={'items':[], 'movement':{'message':'Prázdná fronta'},
                         'summary':{'active':0,'completed_15m':0,
                                    'last_completed':None,'last_started':None,
                                    'oldest_waiting':None}},
            job_monitor_admin=False
        )
        self.assertIn('žádné úlohy',html)


class PinterestApprovedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.product={
            'id':5,'type':'simple','title':'Zimní bunda','description':'<p>Outdoor &amp; sport</p>',
            'url':'https://example.org/produkt/bunda/',
            'image':'https://example.org/media/bunda.jpg',
            'price':'1234','currency':'CZK','stock_status':'instock',
            'purchasable':True
        }

    def test_convert_validated_published_google_feed(self):
        source,google=merchant_export.build_google_feed(
            'Adrenaline Race',[self.product],[],'https://example.org')
        output,report=pinterest_catalog.convert_google_xml(
            source,'Adrenaline Race',google
        )
        self.assertEqual(report['exported'],1)
        self.assertEqual(report['source'],'last_approved_google_snapshot')
        self.assertIn(b'in stock',output)
        from xml.etree import ElementTree as ET
        self.assertEqual(ET.fromstring(output).findtext('channel/item/description'),'Outdoor & sport')
        self.assertFalse(report['ingested_by_pinterest'])

    def test_empty_or_invalid_feed_is_rejected(self):
        with self.assertRaises(ValueError):
            pinterest_catalog.convert_google_xml(b'<html></html>','Shop')
        with self.assertRaises(ValueError):
            pinterest_catalog.convert_google_xml(b'not xml','Shop')

    def test_cron_scripts_forced_lf_in_desktop_checkout(self):
        attrs=(ROOT/'.gitattributes').read_text(encoding='utf-8')
        self.assertIn('*.sh text eol=lf',attrs)
        for name in ('run_boban_cron.sh','install_seo_worker_cron.sh'):
            script=(ROOT/'scripts'/name).read_bytes()
            self.assertNotIn(b'\r\n',script)


if __name__=='__main__':
    unittest.main()
