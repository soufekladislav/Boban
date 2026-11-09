import unittest
from xml.etree import ElementTree as ET
from zbozi_export import build_zbozi_feed,NS
from zbozi_categories import Resolver,category_paths

class QualityTests(unittest.TestCase):
    def product(self, **kw):
        p={'id':1,'type':'simple','title':'Batoh NILS 20 l','url':'https://example.cz/p/1','image':'https://example.cz/pic.jpg','price':'499','currency':'CZK','stock_status':'instock','purchasable':True,'categories':[{'id':3,'name':'Batohy'}]}
        p.update(kw);return p
    def rows(self,xml):return ET.fromstring(xml).findall(f'{{{NS}}}SHOPITEM')
    def val(self,row,tag):return row.findtext(f'{{{NS}}}{tag}')
    def test_duplicate_title_is_not_published_twice(self):
        xml,report=build_zbozi_feed([self.product(),self.product(id=2)],[])
        self.assertEqual(len(self.rows(xml)),1)
        self.assertEqual(report['duplicate_title_count'],1)
    def test_real_variant_attributes_distinguish_names(self):
        parent=self.product(id=10,type='variable',title='Tričko NILS')
        variants=[self.product(id=11,variation_id=11,parent_id=10,title='Tričko NILS',variant_attributes={'Velikost':'M'}),self.product(id=12,variation_id=12,parent_id=10,title='Tričko NILS',variant_attributes={'Velikost':'L'})]
        xml,report=build_zbozi_feed([parent],variants)
        self.assertEqual(report['exported'],2)
        self.assertEqual([self.val(x,'PRODUCTNAME') for x in self.rows(xml)],['Tričko NILS – Velikost: M','Tričko NILS – Velikost: L'])
    def test_official_category_only_when_unique(self):
        r=Resolver(['Sport | Turistika | Batohy','Dům | Úložné boxy'])
        xml,report=build_zbozi_feed([self.product()],[],category_resolver=r)
        self.assertEqual(self.val(self.rows(xml)[0],'CATEGORYTEXT'),'Sport | Turistika | Batohy')
        self.assertEqual(report['unmapped_category_count'],0)
    def test_unmapped_does_not_pretend_mapped(self):
        r=Resolver(['Sport | Turistika | Batohy','Dům | Batohy'])
        xml,report=build_zbozi_feed([self.product()],[],category_resolver=r)
        self.assertEqual(report['unmapped_category_count'],1)
        self.assertEqual(self.val(self.rows(xml)[0],'CATEGORYTEXT'),'Batohy')
    def test_real_shipping_only(self):
        xml,report=build_zbozi_feed([self.product()],[],shipping_rules=[{'id':'ZASILKOVNA','price':'79','cod_price':'109'}])
        row=self.rows(xml)[0]
        self.assertEqual(self.val(row.find(f'{{{NS}}}DELIVERY'),'DELIVERY_PRICE'),'79.00')
        self.assertEqual(report['missing_shipping_count'],0)
    def test_without_shipping_warnings_not_fake(self):
        xml,report=build_zbozi_feed([self.product()],[])
        self.assertIsNone(self.rows(xml)[0].find(f'{{{NS}}}DELIVERY'))
        self.assertEqual(report['missing_shipping_count'],1)
    def test_multiple_categories_prefers_verified_deeper_match(self):
        r=Resolver(['Sport | Batohy','Sport | Turistika | Outdoorové batohy'])
        p=self.product(categories=[{'id':3,'name':'Nezařazené'},{'id':4,'name':'Outdoorové batohy'}])
        xml,report=build_zbozi_feed([p],[],category_resolver=r)
        self.assertEqual(self.val(self.rows(xml)[0],'CATEGORYTEXT'),'Sport | Turistika | Outdoorové batohy')
        self.assertEqual(report['unmapped_category_count'],0)
    def test_zero_shipping_price_is_explicit(self):
        xml,report=build_zbozi_feed([self.product()],[],shipping_rules=[{'id':'ZASILKOVNA','price':'0.00'}])
        row=self.rows(xml)[0]
        delivery=row.find(f'{{{NS}}}DELIVERY')
        self.assertEqual(self.val(delivery,'DELIVERY_PRICE'),'0')
        self.assertEqual(report['missing_shipping_count'],0)
    def test_extra_images_are_real_and_deduplicated(self):
        p=self.product(images=['https://example.cz/pic.jpg','https://example.cz/side.jpg','https://example.cz/side.jpg'])
        xml,_=build_zbozi_feed([p],[])
        row=self.rows(xml)[0]
        self.assertEqual([e.text for e in row.findall(f'{{{NS}}}IMGURL_ALTERNATIVE')],['https://example.cz/side.jpg'])
    def test_eprel_is_included_only_when_provided(self):
        xml,_=build_zbozi_feed([self.product(raw={'eprel_id':'123456'})],[])
        self.assertEqual(self.val(self.rows(xml)[0],'EPREL_ID'),'123456')
        xml,_=build_zbozi_feed([self.product()],[])
        self.assertIsNone(self.val(self.rows(xml)[0],'EPREL_ID'))
    def test_category_shapes(self):
        p={'categories':[{'name':'Sport','children':[{'name':'Cyklistika','children':[{'name':'Kola'}]}]}]}
        self.assertIn('Sport | Cyklistika | Kola',category_paths(p))
if __name__=='__main__':unittest.main()
