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


def convert_google_xml(source_xml, project_name, existing_report=None):
    """Reuse the last published Google XML, only after the caller proves approval.

    Keep a previously approved snapshot usable during a new incomplete sync.
    Do not publish stale revisions or claim Pinterest API ingestion.
    """
    if len(source_xml) > 32 * 1024 * 1024:
        raise ValueError('Publikované Google XML překračuje bezpečnostní limit 32 MB.')
    try:
        root = ET.fromstring(source_xml)
    except ET.ParseError as exc:
        raise ValueError('Publikovaný Google XML není platný. Oprav zdrojový katalog.') from exc
    channel = root.find('channel') if root.tag == 'rss' else None
    if channel is None:
        raise ValueError('Chybí RSS kanál produktů.')
    heading = channel.find('title')
    if heading is not None:
        heading.text = project_name + ' – Pinterest produkty'
    items = channel.findall('item')
    if not items:
        raise ValueError('Publikovaný Google XML neobsahuje žádné položky.')
    seen = set()
    for item in items:
        ident = item.findtext('{'+GNS+'}id')
        link = item.findtext('link')
        image = item.findtext('{'+GNS+'}image_link')
        price = item.findtext('{'+GNS+'}price')
        if (not ident or ident in seen or not item.findtext('title') or
                not merchant_export.public_url(link) or
                not merchant_export.public_url(image) or not price):
            raise ValueError('Publikované Google XML obsahuje neplatný nebo duplicitní produkt.')
        seen.add(ident)
        description = item.find('description')
        if description is not None:
            description.text = plain_text(description.text)[:10000]
        availability = item.find('{'+GNS+'}availability')
        if availability is None or availability.text not in ('in_stock','out_of_stock','backorder'):
            raise ValueError('Zdrojový produkt nemá platnou dostupnost.')
        availability.text = {
            'in_stock': 'in stock', 'out_of_stock': 'out of stock',
            'backorder': 'out of stock'
        }[availability.text]
    result = dict(existing_report or {})
    result.update({
        'exported': len(items), 'format': 'PINTEREST_RSS_2.0',
        'country': 'CZ', 'locale': 'cs_CZ',
        'ingested_by_pinterest': False,
        'source': 'last_approved_google_snapshot'
    })
    result.setdefault('omitted', 0)
    result.setdefault('errors', [])
    result.setdefault('warnings', [])
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), result
