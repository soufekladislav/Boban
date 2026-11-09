import unittest
from xml.etree import ElementTree as ET
from meta_export import build_meta_feed
from merchant_export import GNS

class MetaFeedTests(unittest.TestCase):
    def item(self, **kwargs):
        x=dict(id=1,type='simple',title='Sportovní batoh',description='<p>Popis produktu</p>',url='https://eshop.example/batoh',image='https://eshop.example/a.jpg',images=['https://eshop.example/a.jpg','https://eshop.example/b.jpg'],price='350',currency='CZK',brand='NILS',gtin='5901234567890',stock_status='instock',purchasable=True)
        x.update(kwargs)
        return x
    def test_required_fields(self):
        xml, r = build_meta_feed('Test', [self.item()], [], 'https://eshop.example')
        row=ET.fromstring(xml).find('channel/item')
        for key in ['id','price','condition','availability','image_link','brand']:
            self.assertIsNotNone(row.find('{%s}%s' % (GNS,key)))
        self.assertEqual(row.findtext('{%s}availability'%GNS),'in stock')
        self.assertEqual(r['exported'],1)
    def test_parent_not_duplicated_and_variation_group(self):
        p=self.item(type='variable',id=40)
        v=self.item(id=41,variation_id=41,parent_id=40,variant_attributes={'Barva':'modrá'})
        xml,r=build_meta_feed('Test',[p],[v],'https://eshop.example')
        rows=ET.fromstring(xml).findall('channel/item')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].findtext('{%s}item_group_id'%GNS),'40')
    def test_invalid_price_and_missing_image(self):
        _,r=build_meta_feed('Test',[self.item(price='0.01'),self.item(id=2,image='',images=[])],[],'https://eshop.example')
        self.assertEqual(r['exported'],0)
        self.assertEqual(r['omitted'],2)
    def test_no_guessed_brand(self):
        xml,r=build_meta_feed('Test',[self.item(brand='',gtin='')],[],'https://eshop.example')
        self.assertIsNone(ET.fromstring(xml).find('channel/item'))
        self.assertEqual(r['omitted'],1)
