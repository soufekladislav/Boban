import unittest
import feed_workflow
import merchant_export


class MerchantCatalogRulesTests(unittest.TestCase):
    def test_full_taxonomy_excludes_child_even_when_parent_unassigned(self):
        parents=[dict(id=100,type='simple',categories=[{'id':13,'parent':12}],price='125.00')]
        taxonomy=[{'id':11,'parent':0},{'id':12,'parent':11},{'id':13,'parent':12}]
        p,v,r=feed_workflow.selected(parents,[],{'category':{11},'product':set()},categories=taxonomy)
        self.assertEqual(p,[])
        self.assertEqual(r['excluded_parents'],1)

    def test_excluded_variable_parent_cascades_to_variants(self):
        parents=[dict(id=100,type='variable',categories=[{'id':13,'parent':12}])]
        variants=[dict(variation_id=101,parent_id=100,price='300.00')]
        taxonomy=[{'id':11,'parent':0},{'id':12,'parent':11},{'id':13,'parent':12}]
        p,v,r=feed_workflow.selected(parents,variants,{'category':{11},'product':set()},categories=taxonomy)
        self.assertEqual((p,v),([],[]))
        self.assertEqual(r['excluded_variants'],1)

    def test_placeholder_price_is_not_exported(self):
        item=dict(id=100,type='simple',title='Event',url='https://example.com/product/',image='https://example.com/image.jpg',price='0.01',currency='CZK',stock_status='instock')
        content,report=merchant_export.build_google_feed('Shop',[item],[],'https://example.com')
        self.assertEqual(report['exported'],0)
        self.assertEqual(report['omitted'],1)
        self.assertIn('podezřelá cena',report['errors'][0]['problems'][0])
        self.assertNotIn(b'<item>',content)

    def test_legitimate_price_and_variant_group(self):
        item=dict(variation_id=101,parent_id=100,type='variation',title='Kolo L',url='https://example.com/product/?variation_id=101',image='https://example.com/image.jpg',price='25150',currency='CZK',stock_status='instock')
        content,report=merchant_export.build_google_feed('Shop',[],[item],'https://example.com')
        self.assertEqual(report['exported'],1)
        self.assertIn(b'item_group_id',content)

if __name__=='__main__':unittest.main()
