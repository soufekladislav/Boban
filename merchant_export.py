"""Google Merchant XML export. Pure deterministic mapping; never makes network requests.
Only publicly available catalogue fields are exported. Missing/invalid items are omitted
and returned as structured diagnostics, not silently invented.
"""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
import re

GNS = 'http://base.google.com/ns/1.0'
ET.register_namespace('g', GNS)

def g(name):
    return '{'+GNS+'}'+name

def field(parent, tag, value):
    if value is not None and str(value).strip():
        ET.SubElement(parent, g(tag)).text = str(value).strip()

def public_url(value):
    if not isinstance(value,str): return False
    try:
        x=urlsplit(value)
        return x.scheme in ('https','http') and bool(x.hostname) and not x.username and not x.password
    except ValueError:return False

def money(value):
    try:
        d=Decimal(str(value).strip())
        return format(d.quantize(Decimal('0.01')),'f') if d.is_finite() and d>0 else None
    except (InvalidOperation,ValueError):return None

def product_rows(parents, variants):
    # Variants are separate sellable items. Variable parents must not be duplicated.
    for item in parents:
        if item.get('type') == 'variable': continue
        yield item, None
    for item in variants:
        yield item, item.get('parent_id')

def build_google_feed(project_name, parents, variants, site_url):
    rss=ET.Element('rss',{'version':'2.0'})
    channel=ET.SubElement(rss,'channel')
    ET.SubElement(channel,'title').text=project_name+' – produkty'
    ET.SubElement(channel,'link').text=site_url
    ET.SubElement(channel,'description').text='Automatický produktový export WebBooster'
    errors=[]; warnings=[]; seen=set(); count=0
    for product,parent_id in product_rows(parents,variants):
        ident=product.get('variation_id') or product.get('id')
        ident=str(ident or '').strip()
        title=str(product.get('title') or '').strip()
        link=product.get('url')
        img=(product.get('image') or (product.get('images') or [None])[0])
        currency=str(product.get('currency') or '').strip().upper()
        price=money(product.get('price'))
        flags=[]
        if not ident or ident in seen:flags.append('duplicitní nebo chybějící ID')
        if not title:flags.append('chybí název')
        if not public_url(link):flags.append('chybí veřejný odkaz')
        if not public_url(img):flags.append('chybí obrázek')
        if not price:flags.append('neplatná cena')
        elif Decimal(price)<=Decimal('0.01'):
            # 0.01 is a common placeholder on events. Never publish it as retail price.
            flags.append('podezřelá cena 0,01 – ověř cenu ve WooCommerce')
        if not re.fullmatch(r'[A-Z]{3}',currency):flags.append('neplatná měna')
        if product.get('purchasable') is False:flags.append('produkt nelze koupit')
        if flags:
            errors.append({'id':ident,'problems':flags})
            continue
        seen.add(ident)
        row=ET.SubElement(channel,'item')
        ET.SubElement(row,'title').text=title
        ET.SubElement(row,'link').text=link
        ET.SubElement(row,'description').text=str(product.get('description') or title)[:4500]
        field(row,'id',ident)
        regular=money(product.get('regular_price') or (product.get('raw') or {}).get('regular_price'))
        if regular and Decimal(regular)>Decimal(price):
            field(row,'price',regular+' '+currency)
            field(row,'sale_price',price+' '+currency)
        else:
            field(row,'price',price+' '+currency)
        field(row,'condition','new')
        stock=product.get('stock_status')
        field(row,'availability', 'in_stock' if stock=='instock' else 'backorder' if stock=='onbackorder' else 'out_of_stock')
        field(row,'image_link',img)
        for extra in (product.get('images') or [])[1:11]:
            if public_url(extra) and extra != img:field(row,'additional_image_link',extra)
        if parent_id:
            field(row,'item_group_id',str(parent_id))
            attr=product.get('variant_attributes') or {}
            for key, value in attr.items():
                normalized=str(key).lower()
                if ('color' in normalized or 'barva' in normalized) and value:field(row,'color',value)
                elif ('size' in normalized or 'velikost' in normalized) and value:field(row,'size',value)
                elif ('material' in normalized or 'materiál' in normalized) and value:field(row,'material',value)
        if product.get('sku'):field(row,'custom_label_0',str(product['sku'])[:100])
        gtin=str(product.get('gtin') or '').strip()
        brand=str(product.get('brand') or '').strip()
        if gtin:field(row,'gtin',gtin)
        if brand:field(row,'brand',brand)
        if not gtin and not brand:
            # Missing data does NOT prove identifiers do not exist. Do not make
            # the unsupported identifier_exists=no claim on behalf of merchants.
            warnings.append({'id':ident,'problem':'Chybí GTIN i značka. Doplň identifikátory od výrobce; automaticky netvrdíme, že neexistují.'})
        cats=product.get('categories') or []
        if cats:
            c=cats[0];cat=(c.get('name') or c.get('title') or '') if isinstance(c,dict) else str(c)
            if cat:field(row,'product_type',cat)
        count+=1
    xml=ET.tostring(rss,encoding='utf-8',xml_declaration=True)
    return xml,{'exported':count,'omitted':len(errors),'errors':errors[:100],'warnings':warnings[:100]}
