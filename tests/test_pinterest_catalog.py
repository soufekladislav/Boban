"""Pinterest adapter: reuse one approved Woo snapshot, safe XML mapping."""
import unittest
from xml.etree import ElementTree as ET

import pinterest_catalog

G = '{http://base.google.com/ns/1.0}'


def example(**kwargs):
    data={
        'id':15,'type':'simple','title':'Pánská zimní bunda','description':'<p>Teplá &amp; pohodlná</p>',
        'url':'https://adrenalinerace.eu/produkt/bunda/',
        'image':'https://adrenalinerace.eu/wp-content/uploads/bunda.jpg',
        'price':'1190.00','regular_price':'1490.00','currency':'CZK',
        'stock_status':'instock','purchasable':True,'categories':[{'id':2,'name':'Outdoor'}],
        'brand':'Norway'
    }
    data.update(kwargs)
    return data


class PinterestCatalogTests(unittest.TestCase):
    def test_xml_has_required_fields_and_pinterest_availability(self):
        xml, report=pinterest_catalog.build_pinterest_feed('Adrenaline Race',
                                                           [example()],[],
                                                           'https://adrenalinerace.eu')
        root=ET.fromstring(xml)
        item=root.find('channel/item')
        self.assertEqual(report['exported'],1)
        self.assertEqual(item.find(G+'id').text,'15')
        self.assertEqual(item.find('title').text,'Pánská zimní bunda')
        self.assertEqual(item.find('description').text,'Teplá & pohodlná')
        self.assertEqual(item.find(G+'availability').text,'in stock')
        self.assertEqual(item.find(G+'price').text,'1490.00 CZK')
        self.assertEqual(item.find(G+'sale_price').text,'1190.00 CZK')

    def test_out_of_stock_and_backorder_not_claimed_in_stock(self):
        xml,report=pinterest_catalog.build_pinterest_feed(
            'Shop',[example(id=1,stock_status='outofstock'),example(id=2,stock_status='onbackorder')],
            [],'https://adrenalinerace.eu')
        items=ET.fromstring(xml).findall('channel/item')
        self.assertEqual([x.find(G+'availability').text for x in items],['out of stock','out of stock'])

    def test_variant_keeps_group_and_does_not_duplicate_parent(self):
        parent=example(id=8,type='variable')
        variant=example(variation_id=81,parent_id=8,id=None,title='Bunda vel. L',
                        url='https://adrenalinerace.eu/produkt/bunda/?attribute_pa_size=l')
        xml, report=pinterest_catalog.build_pinterest_feed('Shop',[parent],[variant],
                                                               'https://adrenalinerace.eu')
        item=ET.fromstring(xml).find('channel/item')
        self.assertEqual(report['exported'],1)
        self.assertEqual(item.find(G+'id').text,'81')
        self.assertEqual(item.find(G+'item_group_id').text,'8')

    def test_invalid_products_are_not_published(self):
        xml,report=pinterest_catalog.build_pinterest_feed(
            'Shop',[example(price='0.01'),example(id=16,image=None,images=[])],[],
            'https://adrenalinerace.eu')
        self.assertEqual(report['exported'],0)
        self.assertEqual(report['omitted'],2)
        self.assertEqual(len(ET.fromstring(xml).findall('channel/item')),0)

    def test_plain_text_strips_markup_and_unescapes_entities(self):
        self.assertEqual(pinterest_catalog.plain_text('<p>Outdoor &amp; běh <b>v lese</b></p>'),
                         'Outdoor & běh v lese')


if __name__=='__main__':
    unittest.main()
