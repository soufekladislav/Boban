import sys
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heureka_export import build_heureka_feeds


def product(**kw):
    d=dict(id=5,type='simple',title='Testový batoh',url='https://example.cz/batoh/',price='100',currency='CZK',
           stock_status='instock',stock_quantity=8,image='https://example.cz/b.jpg',categories=[{'name':'Outdoor'}],purchasable=True)
    d.update(kw);return d

class HeurekaTests(unittest.TestCase):
    def test_product_and_availability_use_same_id(self):
        p,a,r=build_heureka_feeds([product()],[],confirmed_fast_dispatch=True)
        self.assertEqual(ET.fromstring(p).findtext('SHOPITEM/ITEM_ID'),'5')
        self.assertEqual(ET.fromstring(a).find('item').attrib['id'],'5')
        self.assertEqual(r['availability_count'],1)
    def test_without_confirmation_no_stock_claim(self):
        _,a,r=build_heureka_feeds([product()],[])
        self.assertEqual(len(ET.fromstring(a)),0)
        self.assertFalse(r['availability_ready'])
    def test_unknown_stock_not_in_availability(self):
        _,a,r=build_heureka_feeds([product(stock_quantity=None)],[],confirmed_fast_dispatch=True)
        self.assertEqual(len(ET.fromstring(a)),0)
        self.assertEqual(r['exported'],1)
    def test_variable_parent_not_exported_and_variants_grouped(self):
        parent=product(id=20,type='variable')
        var=product(id=None,variation_id=30,parent_id=20,title='Batoh – modrý',variant_attributes={'Barva':'Modrá'})
        p,a,r=build_heureka_feeds([parent],[var],confirmed_fast_dispatch=True)
        root=ET.fromstring(p)
        self.assertEqual(len(root),1)
        self.assertEqual(root.findtext('SHOPITEM/ITEM_ID'),'30')
        self.assertIsNone(root.findtext('SHOPITEM/ITEMGROUP_ID'))
        self.assertEqual(r['exported'],1)
    def test_placeholder_and_outofstock_excluded(self):
        p,_,r=build_heureka_feeds([product(price='0.01'),product(id=6,stock_status='outofstock')],[])
        self.assertEqual(len(ET.fromstring(p)),0)
        self.assertEqual(r['omitted'],2)
    def test_no_virtual_services(self):
        p,_,r=build_heureka_feeds([product(raw={'virtual':True})],[])
        self.assertEqual(len(ET.fromstring(p)),0)
        self.assertEqual(r['omitted'],1)
    def test_no_duplicate_id(self):
        p,_,r=build_heureka_feeds([product(),product()],[])
        self.assertEqual(len(ET.fromstring(p)),1)
        self.assertEqual(r['omitted'],1)
    def test_variant_inherits_parent_category_and_full_path(self):
        p=product(id=20,type='variable',categories=[{'id':8,'name':'Rakety'}])
        v=product(id=None,variation_id=30,parent_id=20,categories=[],title='Raketa modrá')
        taxonomy=[{'id':7,'parent':0,'name':'Sport'},{'id':8,'parent':7,'name':'Rakety'}]
        xml,_,report=build_heureka_feeds([p],[v],taxonomy=taxonomy)
        self.assertEqual(ET.fromstring(xml).findtext('SHOPITEM/CATEGORYTEXT'),'Sport | Rakety')
        self.assertEqual(report['missing_category_count'],0)
    def test_explicit_delivery_and_unknown_default(self):
        xml,_,r=build_heureka_feeds([product()],[])
        self.assertIsNone(ET.fromstring(xml).findtext('SHOPITEM/DELIVERY_DATE'))
        self.assertEqual(r['missing_delivery_count'],1)
        xml,_,r=build_heureka_feeds([product()],[],default_delivery_days=3)
        self.assertEqual(ET.fromstring(xml).findtext('SHOPITEM/DELIVERY_DATE'),'3')
        self.assertEqual(r['missing_delivery_count'],0)
    def test_apparel_size_only_group(self):
        p=product(id=20,type='variable',categories=[{'name':'Obuv'}])
        v=product(id=None,variation_id=30,parent_id=20,categories=[],variant_attributes={'Velikost':'42'})
        xml,_,_=build_heureka_feeds([p],[v])
        self.assertEqual(ET.fromstring(xml).findtext('SHOPITEM/ITEMGROUP_ID'),'20')
    def test_no_parent_ean_inheritance(self):
        p=product(id=20,type='variable',gtin='5901234567890')
        v=product(id=None,variation_id=30,parent_id=20,categories=[],gtin=None)
        xml,_,_=build_heureka_feeds([p],[v])
        self.assertIsNone(ET.fromstring(xml).findtext('SHOPITEM/EAN'))
if __name__=='__main__':unittest.main()
