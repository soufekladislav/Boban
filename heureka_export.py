"""Pure Heureka.cz feed builder. No external calls or made-up stock/delivery promises.

A single selection yields identical ITEM_ID values in product and availability XML.
Availability is deliberately conservative: only explicit positive stock counts are
eligible, and only if the merchant has confirmed prompt dispatch capability.
"""
from decimal import Decimal
from html import unescape
from xml.etree import ElementTree as ET
import re
from merchant_export import money, public_url, product_rows


def _text(parent, tag, value):
    if value is not None and str(value).strip():
        ET.SubElement(parent, tag).text = str(value).strip()


def _stock_count(product):
    raw = product.get('raw') or {}
    value = product.get('stock_quantity')
    if value is None:
        value = raw.get('stock_quantity')
    if value is None:
        return None
    try:
        count = int(value)
        return count if float(value) == count and count > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _category(product, parent=None, taxonomy=None):
    """Use parent categories for Woo variations, and the complete known category path.

    Taxonomy is a Woo category tree, not an invented Heureka taxonomy mapping.
    """
    taxonomy_by_id = {}
    for node in taxonomy or []:
        try:
            taxonomy_by_id[int(node['id'])] = node
        except (KeyError, ValueError, TypeError):
            continue
    cats = (product.get('categories') or []) or ((parent or {}).get('categories') or [])
    for cat in cats:
        if not isinstance(cat, dict):
            val = str(cat).strip()
            if val:return val[:250]
            continue
        val = str(cat.get('name') or cat.get('title') or '').strip()
        try: node_id=int(cat.get('id') or cat.get('term_id') or 0)
        except (ValueError,TypeError):node_id=0
        if node_id and node_id in taxonomy_by_id:
            parts=[];seen=set();current=node_id
            while current and current not in seen and current in taxonomy_by_id:
                seen.add(current);node=taxonomy_by_id[current]
                name=str(node.get('name') or node.get('title') or '').strip()
                if name:parts.append(name)
                try:current=int(node.get('parent') or 0)
                except (TypeError,ValueError):break
            if parts:return ' | '.join(reversed(parts))[:250]
        if val:return val[:250]
    return None


def _delivery_days(item, parent=None, confirmed_default=None):
    """Only explicit shipping lead times; unknown delivery must remain unknown."""
    for source in (item, item.get('raw') or {}, parent or {}, (parent or {}).get('raw') or {}):
        for key in ('heureka_delivery_days','dispatch_days','delivery_days'):
            if key in source and source[key] is not None and str(source[key]).strip():
                try:
                    days=int(str(source[key]).strip())
                    if 0 <= days <= 90:return days
                except (ValueError,TypeError):pass
    if confirmed_default is not None:
        try:
            days=int(confirmed_default)
            if 0 <= days <= 90:return days
        except (ValueError,TypeError):pass
    return None


def _is_size_only_apparel(category,attrs):
    """Heureka ITEMGROUP_ID is permitted only for apparel/footwear size variants."""
    if not category:return False
    c=category.casefold()
    if not any(x in c for x in ('obuv','oblečení','oděvy','boty','trička','kalhoty','bundy')):return False
    keys=[k.casefold().strip() for k,_ in attrs]
    return bool(keys) and all(k in ('velikost','size','eu velikost','velikost obuvi') for k in keys)


def _attributes(product):
    attrs = product.get('variant_attributes') or {}
    if isinstance(attrs,dict):
        return [(str(k)[:80],str(v)[:160]) for k,v in attrs.items() if v is not None and str(v).strip()]
    return []


def build_heureka_feeds(parents, variants, *, confirmed_fast_dispatch=False, taxonomy=None, default_delivery_days=None):
    shop = ET.Element('SHOP')
    availability = ET.Element('item_list')
    errors = []
    warnings = []
    seen = set()
    count = 0
    stocked = 0
    missing_category = 0
    missing_delivery = 0
    parent_by_id = {str(p.get("id")):p for p in parents if p.get("id") is not None}
    # Use only the approved selection; never duplicate variable parents.
    for item, parent_id in product_rows(parents,variants):
        ident = str(item.get('variation_id') or item.get('id') or '').strip()
        title = str(item.get('title') or '').strip()
        currency = str(item.get('currency') or '').upper()
        link = item.get('url')
        image = item.get('image') or (item.get('images') or [None])[0]
        price = money(item.get('price'))
        problems = []
        if not ident or not re.fullmatch(r'[A-Za-z0-9_/-]{1,36}',ident) or ident in seen:
            problems.append('neplatné či duplicitní ITEM_ID')
        if not title: problems.append('chybí PRODUCTNAME')
        if not public_url(link): problems.append('chybí URL produktu')
        if not price or Decimal(price) <= Decimal('0.01'): problems.append('neplatná nebo podezřelá cena')
        if currency != 'CZK': problems.append('Heureka.cz vyžaduje cenu v CZK')
        if item.get('purchasable') is False: problems.append('produkt není koupitelný')
        if (item.get('raw') or {}).get('virtual') is True or (item.get('raw') or {}).get('downloadable') is True:
            problems.append('virtuální nebo digitální produkt není pro zbožový srovnávač vhodný')
        if item.get('stock_status') == 'outofstock': problems.append('vyprodaný produkt')
        if problems:
            errors.append({'id':ident,'problems':problems})
            continue
        seen.add(ident)
        parent=parent_by_id.get(str(parent_id)) if parent_id is not None else None
        category=_category(item,parent,taxonomy)
        delivery=_delivery_days(item,parent,default_delivery_days)
        row = ET.SubElement(shop,'SHOPITEM')
        _text(row,'ITEM_ID',ident)
        _text(row,'PRODUCTNAME',title[:200])
        desc=unescape(re.sub(r'<[^>]*>', ' ', str(item.get('description') or title)))
        _text(row,'DESCRIPTION',' '.join(desc.split())[:15000])
        _text(row,'URL',link)
        if public_url(image): _text(row,'IMGURL',image)
        else: warnings.append({'id':ident,'problem':'chybí obrázek'})
        _text(row,'PRICE_VAT',price)
        _text(row,'CATEGORYTEXT',category)
        if not category: missing_category += 1
        if delivery is not None: _text(row,'DELIVERY_DATE',delivery)
        else: missing_delivery += 1
        _text(row,'MANUFACTURER',item.get('brand'))
        _text(row,'EAN',item.get('gtin'))
        if parent_id is not None:
            attrs=_attributes(item)
            if _is_size_only_apparel(category,attrs): _text(row,'ITEMGROUP_ID',str(parent_id))
            for key,val in attrs:
                param=ET.SubElement(row,'PARAM')
                _text(param,'PARAM_NAME',key)
                _text(param,'VAL',val)
        count += 1
        qty = _stock_count(item)
        if confirmed_fast_dispatch and item.get('stock_status') == 'instock' and qty:
            stock_row=ET.SubElement(availability,'item',{'id':ident})
            _text(stock_row,'stock_quantity',qty)
            stocked += 1
    if missing_category: warnings.append({'id':'kategorie','problem':f'CATEGORYTEXT chybí u {missing_category} nabídek; zkontroluj zdrojovou Woo kategorii.'})
    if missing_delivery: warnings.append({'id':'expedice','problem':f'DELIVERY_DATE chybí u {missing_delivery} nabídek; nastav ověřenou dobu expedice v konektoru Heureky.'})
    if not confirmed_fast_dispatch:
        warnings.append({'id':'dostupnost','problem':'Neověřená expedice do 2 dnů: skladové položky nebyly označeny jako okamžitě expedovatelné.'})
    if confirmed_fast_dispatch and count and not stocked:
        warnings.append({'id':'dostupnost','problem':'Nenalezeny ověřené kladné skladové počty. Dostupnostní feed zůstává bez položek.'})
    return (
        ET.tostring(shop,encoding='utf-8',xml_declaration=True),
        ET.tostring(availability,encoding='utf-8',xml_declaration=True),
        {'exported':count,'omitted':len(errors),'availability_count':stocked,
         'errors':errors[:100],'warnings':warnings[:100],
         'availability_ready':bool(confirmed_fast_dispatch and stocked),
         'missing_category_count':missing_category,'missing_delivery_count':missing_delivery}
    )
