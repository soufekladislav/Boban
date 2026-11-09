import sqlite3
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import feed_workflow as flow
import merchant_export

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        flow.ensure_schema(self.db,'sqlite')
        self.parents=[{'id':1,'title':'Event','categories':[{'id':11,'parent':0,'name':'Akce'}]},
                      {'id':2,'title':'Tričko','type':'variable','categories':[{'id':12,'parent':0,'name':'Sport'}]},
                      {'id':3,'title':'Nářadí','type':'simple','categories':[{'id':13,'parent':11,'name':'Kurzy'}, {'id':12,'parent':0,'name':'Sport'}]}]
        self.variants=[{'variation_id':5,'parent_id':2},{'variation_id':6,'parent_id':2}]
    def tearDown(self):self.db.close()
    def test_persistent_exclusions_and_parent_priority(self):
        flow.set_exclusion(self.db,'sqlite',1,'category',11,True)
        flow.set_exclusion(self.db,'sqlite',1,'product',6,True)
        p,v,summary=flow.selected(self.parents,self.variants,flow.exclusions(self.db,1))
        self.assertEqual([x['id'] for x in p],[2])
        self.assertEqual([x['variation_id'] for x in v],[5])
        self.assertEqual(summary['excluded_parents'],2)
    def test_approval_state_and_revision(self):
        flow.update(self.db,'sqlite',8,'2026-11-06',mode='review',revision=1)
        self.assertEqual(flow.state(self.db,8)['revision'],1)
        flow.update(self.db,'sqlite',8,'2026-11-06',mode='running',approved=1)
        self.assertEqual(flow.state(self.db,8)['approved'],1)
    def test_google_feed_excludes_variable_parent(self):
        products=[{'id':1,'title':'Tričko','type':'variable','url':'https://a.test/t','image':'https://a.test/a.jpg', 'price':'100','currency':'CZK'},
                  {'id':2,'title':'Batoh','type':'simple','url':'https://a.test/b','image':'https://a.test/b.jpg', 'price':'200','currency':'CZK','purchasable':True}]
        variants=[{'variation_id':3,'parent_id':1,'title':'Tričko M','url':'https://a.test/t?size=m','image':'https://a.test/a.jpg','price':'120','currency':'CZK','stock_status':'instock'}]
        xml,report=merchant_export.build_google_feed('Test',products,variants,'https://a.test')
        self.assertEqual(report['exported'],2)
        self.assertNotIn(b'<g:id>1</g:id>',xml)

if __name__=='__main__':unittest.main()
