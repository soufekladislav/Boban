"""Seznam Nakupy direct XML from one approved product selection.

No Woo reads, invented shipping costs, guessed categories or fabricated variants.
"""
from collections import Counter
from decimal import Decimal
from html import unescape
from xml.etree import ElementTree as ET
import re
from merchant_export import product_rows, public_url, money
from heureka_export import _category, _attributes, _delivery_days
from zbozi_categories import Resolver, normalized

NS = "http://www.zbozi.cz/ns/offer/1.0"
ET.register_namespace('', NS)
def tag(name):return '{'+NS+'}'+name
def field(row, name, value):
    if value is not None and str(value).strip():
        ET.SubElement(row, tag(name)).text=str(value).strip()


def unique_variant_title(item, parent, baseline):
    """Keep factual name; append actual size/color/model attributes, not arbitrary IDs."""
    attrs=_attributes(item)
    parts=[]
    for name,val in attrs:
        value=str(val).strip()
        if value and not re.search(r'(?<!\w)'+re.escape(normalized(value))+r'(?!\w)', normalized(baseline)):
            parts.append(f'{name}: {value}')
    return baseline + (' – ' + ', '.join(parts) if parts else '')


def build_zbozi_feed(parents, variants, *, taxonomy=None, default_delivery_days=None,
                     category_resolver=None, shipping_rules=None):
    shop=ET.Element(tag('SHOP'))
    parent_by_id={str(p.get('id')):p for p in parents if p.get('id') is not None}
    errors=[];warnings=[];seen=set();seen_titles=set();count=0
    missing_ean=0;missing_category=0;unmapped_category=0;unknown_dispatch=0;missing_shipping=0
    changed_variant_titles=0; duplicate_titles=0
    resolver=category_resolver or Resolver()
    for item,parent_id in product_rows(parents,variants):
        ident=str(item.get('variation_id') or item.get('id') or '').strip()
        title=str(item.get('title') or '').strip()
        parent=parent_by_id.get(str(parent_id)) if parent_id is not None else None
        if parent_id is not None and title:
            refined=unique_variant_title(item,parent,title)
            if refined!=title:changed_variant_titles+=1
            title=refined
        link=item.get('url')
        image=item.get('image') or (item.get('images') or [None])[0]
        price=money(item.get('price'))
        problems=[]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,36}',ident) or ident in seen:problems.append('chybné nebo duplicitní ITEM_ID')
        if not title:problems.append('chybí PRODUCTNAME')
        title=title[:200]
        title_key=normalized(title)
        if title and title_key in seen_titles:
            problems.append('duplicitní PRODUCTNAME – bez skutečných rozlišujících atributů nepublikovat')
            duplicate_titles+=1
        if not public_url(link):problems.append('chybí URL')
        if not public_url(image):problems.append('chybí IMGURL')
        if not price or Decimal(price)<=Decimal('0.01'):problems.append('chybí nebo podezřelá cena')
        if str(item.get('currency') or '').upper()!='CZK':problems.append('měna není CZK')
        if item.get('purchasable') is False:problems.append('produkt není koupitelný')
        if item.get('stock_status')=='outofstock':problems.append('produkt není dostupný')
        raw=item.get('raw') or {}
        if raw.get('virtual') is True or raw.get('downloadable') is True:problems.append('digitální/virtuální produkt')
        if problems:
            errors.append({'id':ident,'problems':problems});continue
        seen.add(ident); seen_titles.add(title_key)
        woo_category=_category(item,parent,taxonomy)
        cats=(item.get('categories') or (parent or {}).get('categories') or [])
        cat_ids=[cat.get('id') for cat in cats if isinstance(cat,dict) and cat.get('id')]
        # Woo products can belong to multiple categories. Evaluate ALL assigned
        # paths rather than only the first (often a generic parent category).
        # Only exact official / unique-leaf matches are considered verified.
        candidates=[]
        for cat in cats:
            woo_path=_category({'categories':[cat]},None,taxonomy)
            if woo_path:
                matched,source=resolver.resolve(woo_path,[cat.get('id')] if isinstance(cat,dict) else [])
                if matched:
                    priority={'override':3,'exact':2,'unique-leaf':1}.get(source,0)
                    candidates.append((priority,matched.count('|'),matched))
        if not candidates and woo_category:
            matched,source=resolver.resolve(woo_category,cat_ids)
            if matched:candidates.append(({'override':3,'exact':2,'unique-leaf':1}.get(source,0),matched.count('|'),matched))
        category=max(candidates)[2] if candidates else None
        if not category:
            unmapped_category+=1
            category=woo_category # fallback, explicitly flagged as NOT verified
        if not category:missing_category+=1
        delivery=_delivery_days(item,parent,default_delivery_days)
        if delivery is None:
            delivery=-1;unknown_dispatch+=1
        row=ET.SubElement(shop,tag('SHOPITEM'))
        field(row,'ITEM_ID',ident)
        field(row,'PRODUCTNAME',title)
        field(row,'PRODUCT',title[:200])
        description=unescape(re.sub(r'<[^>]*>',' ',str(item.get('description') or (parent or {}).get('description') or title)))
        field(row,'DESCRIPTION',' '.join(description.split())[:15000])
        field(row,'URL',link)
        field(row,'IMGURL',image)
        # Only distinct, actual product photos from WooCommerce; no placeholder shots.
        extra_seen={image}
        for extra in (item.get('images') or (parent or {}).get('images') or []):
            if len(extra_seen)>=21:break
            if public_url(extra) and extra not in extra_seen:
                field(row,'IMGURL_ALTERNATIVE',extra)
                extra_seen.add(extra)
        field(row,'PRICE_VAT',price)
        field(row,'DELIVERY_DATE',delivery)
        if category:field(row,'CATEGORYTEXT',category[:500])
        brand=item.get('brand') or (parent or {}).get('brand')
        field(row,'MANUFACTURER',brand)
        if brand:field(row,'BRAND',brand)
        sku=item.get('sku')
        if sku and str(sku).strip():field(row,'PRODUCTNO',str(sku)[:100])
        # EPREL is mandatory only for products in the regulated categories.
        # Never fabricate this identifier for unrelated sports goods.
        for eprel in (raw.get('eprel_id') or [] if isinstance(raw.get('eprel_id'),list) else [raw.get('eprel_id')]):
            if eprel is not None and re.fullmatch(r'\d+',str(eprel).strip()):field(row,'EPREL_ID',eprel)
        ean=item.get('gtin')
        if ean:field(row,'EAN',ean)
        else:missing_ean+=1
        if parent_id is not None:
            field(row,'ITEMGROUP_ID',str(parent_id))
            for name,value in _attributes(item):
                sub=ET.SubElement(row,tag('PARAM'))
                field(sub,'PARAM_NAME',name)
                field(sub,'VAL',value)
        shipping_count=0
        for rule in shipping_rules or []:
            if not isinstance(rule,dict):continue
            delivery_id=str(rule.get('id') or '').strip()
            delivery_price=money(rule.get('price')) if rule.get('price') is not None else None
            if str(rule.get('price')) in ('0','0.0','0.00'):delivery_price='0'
            if not delivery_id or delivery_price is None:continue
            shipping=ET.SubElement(row,tag('DELIVERY'))
            field(shipping,'DELIVERY_ID',delivery_id)
            field(shipping,'DELIVERY_PRICE',delivery_price)
            cod=rule.get('cod_price')
            if cod is not None:
                cod_value=money(cod) if str(cod) not in ('0','0.0','0.00') else '0'
                if cod_value:field(shipping,'DELIVERY_PRICE_COD',cod_value)
            shipping_count+=1
        if not shipping_count:missing_shipping+=1
        count+=1
    if missing_category:warnings.append({'id':'category-missing','problem':f'CATEGORYTEXT chybí u {missing_category} nabídek.'})
    if unmapped_category:warnings.append({'id':'category-unmapped','problem':f'{unmapped_category} nabídek nemá kategorii ověřenou podle oficiálního stromu Seznamu; Woo název je jen záložní.'})
    if missing_ean:warnings.append({'id':'ean','problem':f'EAN chybí u {missing_ean} nabídek; nevymýšlet identifikátory.'})
    if unknown_dispatch:warnings.append({'id':'delivery-date','problem':f'{unknown_dispatch} nabídek má neznámou expedici (-1); doplň ověřené lhůty.'})
    if missing_shipping:warnings.append({'id':'shipping','problem':f'{missing_shipping} nabídek nemá v XML potvrzené dopravce/ceny (DELIVERY); nastav dopravu v Centru prodejce nebo ověřená pravidla pro XML.'})
    if duplicate_titles:warnings.append({'id':'titles','problem':f'{duplicate_titles} duplicitních PRODUCTNAME nepředáno; potřebují skutečné rozlišující údaje.'})
    return ET.tostring(shop,encoding='utf-8',xml_declaration=True),{
        'exported':count,'omitted':len(errors),'errors':errors[:100], 'warnings':warnings[:100],
        'missing_category_count':missing_category,'unmapped_category_count':unmapped_category,
        'missing_ean_count':missing_ean,'unknown_dispatch_count':unknown_dispatch,
        'missing_shipping_count':missing_shipping,'duplicate_title_count':duplicate_titles,
        'variant_titles_enriched':changed_variant_titles,
        'category_mapping_available':bool(resolver.paths),
    }
