import unittest
from xml.etree import ElementTree as ET
from zbozi_export import build_zbozi_feed, NS

class ZboziExportTests(unittest.TestCase):
    def setup_item(self, **changes):
        item={'id':123,'type':'simple','title':'Batoh 20L','url':'https://example.cz/batoh','image':'https://example.cz/img.jpg','price':'499','currency':'CZK','stock_status':'instock','purchasable':True,'categories':[{'id':1,'name':'Outdoor'}]}
        item.update(changes)
        return item
    def test_xml_namespace_required_tags_and_unknown_delivery(self):
        xml,r=build_zbozi_feed([self.setup_item()],[])
        root=ET.fromstring(xml); n={'z':NS}; item=root.find('z:SHOPITEM',n)
        self.assertEqual(root.tag,'{%s}SHOP'%NS)
        self.assertEqual(item.findtext('z:DELIVERY_DATE',namespaces=n),'-1')
        self.assertEqual(r['exported'],1)
    def test_variants_without_parent_offer(self):
        parent=self.setup_item(id=101,type='variable')
        variant=self.setup_item(id=202,variation_id=202,parent_id=101,variant_attributes={'Barva':'modrá'})
        xml,r=build_zbozi_feed([parent],[variant]);root=ET.fromstring(xml);n={'z':NS}
        self.assertEqual(len(root.findall('z:SHOPITEM',n)),1)
        self.assertEqual(root.find('z:SHOPITEM',n).findtext('z:ITEMGROUP_ID',namespaces=n),'101')
    def test_duplicate_and_invalid_prices(self):
        xml,r=build_zbozi_feed([self.setup_item(),self.setup_item(),self.setup_item(id=5,price='0.01')],[])
        self.assertEqual(r['exported'],1)
        self.assertEqual(r['omitted'],2)
    def test_dispatch_verified(self):
        xml,r=build_zbozi_feed([self.setup_item()],[],default_delivery_days=3)
        item=ET.fromstring(xml).find('{%s}SHOPITEM'%NS)
        self.assertEqual(item.findtext('{%s}DELIVERY_DATE'%NS),'3')
    def test_missing_image_blocks_offer(self):
        _,r=build_zbozi_feed([self.setup_item(image='')],[])
        self.assertEqual(r['exported'],0)
