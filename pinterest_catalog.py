"""Pinterest RSS 2.0 retail catalog adapter built on the approved Google feed.

No second product store, no API credentials, no network calls. Pinterest uses
space-separated availability values whereas Google Merchant uses underscores.
"""
from html import unescape
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
import merchant_export

GNS = merchant_export.GNS


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value):
    parser = _TextOnly()
    parser.feed(str(value or ''))
    parser.close()
    return ' '.join(unescape(' '.join(parser.parts)).split())


def build_pinterest_feed(project_name, parents, variants, site_url):
    """Reuse one validated product selection and adapt it to Pinterest fields.

    Invalid product rows are omitted by the shared Google validator. No fallback
    to invented prices, SKUs, availability or product attributes.
    """
    xml, report = merchant_export.build_google_feed(project_name, parents, variants, site_url)
    root = ET.fromstring(xml)
    channel = root.find('channel')
    if channel is None:
        raise ValueError('Chybí RSS kanál s produkty.')
    title = channel.find('title')
    if title is not None:
        title.text = project_name + ' – Pinterest produkty'
    warnings = list(report.get('warnings') or [])
    for item in channel.findall('item'):
        description = item.find('description')
        if description is not None:
            description.text = plain_text(description.text)[:10000]
        availability = item.find('{'+GNS+'}availability')
        if availability is not None:
            availability.text = {
                'in_stock': 'in stock', 'out_of_stock': 'out of stock',
                'backorder': 'out of stock',
            }.get(availability.text, 'out of stock')
        ident = item.find('{'+GNS+'}id')
        key = ident.text if ident is not None else ''
        img = item.find('{'+GNS+'}image_link')
        if img is not None and img.text:
            warnings.append({
                'id': key, 'problem': 'Rozlišení a poměr obrázku se bez přístupu k obrázku neověřují; Pinterest doporučuje svislé produktové fotografie.'
            }) if len(warnings) < 30 else None
    report['warnings'] = warnings[:100]
    report['format'] = 'PINTEREST_RSS_2.0'
    report['country'] = 'CZ'
    report['locale'] = 'cs_CZ'
    report['ingested_by_pinterest'] = False
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), report
