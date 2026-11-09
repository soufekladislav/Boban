"""Meta Commerce Manager RSS 2.0 primary data feed from approved cached catalog.
No API credentials or Woo reads. Reject missing required data instead of inventing it.
"""
from decimal import Decimal
from html import unescape
import re
from xml.etree import ElementTree as ET
from merchant_export import GNS, g, field, product_rows, public_url, money

ET.register_namespace('g', GNS)


def clean_description(value):
    text = unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))
    return ' '.join(text.split())[:9000]


def build_meta_feed(project_name, parents, variants, site_url):
    rss = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = project_name + ' – katalog'
    ET.SubElement(channel, 'link').text = site_url
    ET.SubElement(channel, 'description').text = 'Schválené produktové nabídky e-shopu'
    parent_map = {str(p.get('id')): p for p in parents}
    seen = set()
    report = {'exported': 0, 'omitted': 0, 'variant_count': 0, 'missing_brand_count': 0,
              'errors': [], 'warnings': []}
    for product, parent_id in product_rows(parents, variants):
        parent = parent_map.get(str(parent_id)) if parent_id else None
        ident = str(product.get('variation_id') or product.get('id') or '').strip()
        title = str(product.get('title') or (parent or {}).get('title') or '').strip()[:200]
        desc = clean_description(product.get('description') or (parent or {}).get('description') or title)
        url = product.get('url') or (parent or {}).get('url')
        images = product.get('images') or (parent or {}).get('images') or []
        image = product.get('image') or (images[0] if images else None) or (parent or {}).get('image')
        price = money(product.get('price'))
        currency = str(product.get('currency') or (parent or {}).get('currency') or '').upper().strip()
        brand = str(product.get('brand') or (parent or {}).get('brand') or '').strip()
        gtin = str(product.get('gtin') or (parent or {}).get('gtin') or '').strip()
        mpn = str(product.get('sku') or (parent or {}).get('sku') or '').strip()
        issues = []
        if not ident or ident in seen or len(ident) > 100: issues.append('chybějící/duplicitní ID')
        if not title: issues.append('chybí title')
        if not desc: issues.append('chybí description')
        if not public_url(url): issues.append('chybí link')
        if not public_url(image): issues.append('chybí image_link')
        if not price or Decimal(price) <= Decimal('0.01'): issues.append('chybí reálná cena')
        if not re.fullmatch(r'[A-Z]{3}', currency): issues.append('chybí měna')
        if not (brand or gtin or mpn): issues.append('chybí výrobce i identifikátory')
        if product.get('purchasable') is False: issues.append('nelze zakoupit')
        if (product.get('raw') or {}).get('virtual') or (product.get('raw') or {}).get('downloadable'):
            issues.append('virtuální/digitální položka vyžaduje samostatné posouzení')
        if issues:
            report['omitted'] += 1
            if len(report['errors']) < 100: report['errors'].append({'id': ident, 'problems': issues})
            continue
        seen.add(ident)
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = title
        ET.SubElement(item, 'link').text = url
        ET.SubElement(item, 'description').text = desc
        field(item, 'id', ident)
        regular = money(product.get('regular_price') or (product.get('raw') or {}).get('regular_price'))
        if regular and Decimal(regular) > Decimal(price):
            field(item, 'price', regular + ' ' + currency)
            field(item, 'sale_price', price + ' ' + currency)
        else:
            field(item, 'price', price + ' ' + currency)
        field(item, 'condition', 'new')
        stock = str(product.get('stock_status') or (parent or {}).get('stock_status') or '')
        field(item, 'availability', 'in stock' if stock == 'instock' else 'out of stock')
        field(item, 'image_link', image)
        distinct = {image}
        for extra in images:
            if len(distinct) >= 11: break
            if public_url(extra) and extra not in distinct:
                field(item, 'additional_image_link', extra)
                distinct.add(extra)
        if brand: field(item, 'brand', brand)
        elif gtin: field(item, 'gtin', gtin)
        elif mpn: field(item, 'mpn', mpn)
        if brand:
            if gtin: field(item, 'gtin', gtin)
            elif mpn: field(item, 'mpn', mpn)
        if not brand:
            report['missing_brand_count'] += 1
        if parent_id:
            field(item, 'item_group_id', str(parent_id))
            report['variant_count'] += 1
            for key, value in (product.get('variant_attributes') or {}).items():
                label = str(key).lower()
                if not value: continue
                if 'barva' in label or 'color' in label: field(item, 'color', value)
                elif 'velikost' in label or 'size' in label: field(item, 'size', value)
                elif 'materiál' in label or 'material' in label: field(item, 'material', value)
        categories = product.get('categories') or (parent or {}).get('categories') or []
        if categories:
            c = categories[0]
            name = (c.get('name') or c.get('title')) if isinstance(c, dict) else str(c)
            if name: field(item, 'product_type', name)
        report['exported'] += 1
    if report['missing_brand_count']:
        report['warnings'].append({'id': 'brand', 'problem': str(report['missing_brand_count']) + ' nabídek nemá značku; použity pouze skutečné výrobní identifikátory.'})
    # Meta Commerce Manager limits each input line to 5,242,880 bytes.
    # ElementTree.tostring() alone serializes the whole RSS as one line.
    # Indent before serializing so each item/field is on its own line.
    ET.indent(rss, space='  ')
    output = ET.tostring(rss, encoding='utf-8', xml_declaration=True)
    if max(map(len, output.splitlines()), default=0) > 5_242_880:
        raise ValueError('Meta XML obsahuje řádek delší než 5 MB')
    return output, report
