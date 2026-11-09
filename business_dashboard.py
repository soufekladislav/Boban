"""Read-only business reporting helpers for Boban statistics.

Never infer sales/leads from GA4 events or attribute individual Google queries to orders.
"""
from datetime import date, datetime, timezone
from urllib.parse import urlsplit, unquote
from collections import defaultdict
import re


def parse_date(value):
    try:
        s=str(value or '')[:10]
        return date.fromisoformat(s)
    except (ValueError,TypeError):
        return None


def freshness(snapshot, today=None, threshold_days=3):
    if not snapshot: return {'state':'missing','age_days':None,'message':'Zdroj dosud neposkytl data.'}
    reference = today or datetime.now(timezone.utc).date()
    end=parse_date(snapshot.get('period_end'))
    captured=parse_date(snapshot.get('captured_at'))
    if not end or not captured:
        return {'state':'unknown','age_days':None,'message':'Chybí datum měření nebo synchronizace.'}
    age=max(0,(reference-end).days)
    sync_age=max(0,(reference-captured).days)
    if age>threshold_days or sync_age>threshold_days:
        return {'state':'stale','age_days':age,'message':f'Zastaralá data: období skončilo před {age} dny, poslední synchronizace před {sync_age} dny.'}
    return {'state':'fresh','age_days':age,'message':f'Data zpracována před {sync_age} dny; období končí {end.isoformat()}.'}


def business_mode(project):
    """Primary conversion determines the main funnel; secondary metrics stay accessible."""
    def read(k):
        try:return str(project[k] or '')
        except (KeyError,IndexError,TypeError):return ''
    primary=read('primary_conversion').strip().lower()
    if primary in {'lead','generate_lead','form_submit','contact','phone_click','qualified_lead','inquiry'}:
        return 'lead'
    return 'shop'


def normalize_path(url):
    text=str(url or '').strip()
    if not text:return '/'
    parsed=urlsplit(text if '://' in text else 'https://placeholder.invalid/'+text.lstrip('/'))
    path=unquote(parsed.path or '/').lower()
    path=re.sub(r'/+', '/',path)
    return path.rstrip('/') or '/'


def page_type(url):
    path=normalize_path(url)
    if re.search(r'/(produkt|product|produkty)/',path):return 'product'
    if re.search(r'/(product-category|kategorie-produktu|kategorie)/',path):return 'category'
    if re.search(r'/(blog|clanky|magazin|novinky|article)/',path):return 'article'
    if re.search(r'/(sluzby|sluzba|services|service)/',path):return 'service'
    if re.search(r'/(kontakt|contact|poptavka|request)/',path):return 'contact'
    return 'other'


def page_summary(ga4, gsc, max_rows=30):
    """Join *page-level* GSC and GA4 by normalized path. Never join query-level data to users/sales."""
    ga_rows=((ga4 or {}).get('extended_reports') or {}).get('landing_pages_all') or []
    gsc_rows=(gsc or {}).get('top_pages') or []
    result={}
    for row in ga_rows:
        path=normalize_path(row.get('landingPagePlusQueryString'))
        rec=result.setdefault(path,{'path':path,'type':page_type(path),'sessions':None,'engaged':None,'clicks':None,'impressions':None})
        rec['sessions']=(rec['sessions'] or 0)+int(row.get('sessions') or 0)
        rec['engaged']=(rec['engaged'] or 0)+int(row.get('engagedSessions') or 0)
    for row in gsc_rows:
        keys=row.get('keys') or []
        if not keys:continue
        path=normalize_path(keys[0]);rec=result.setdefault(path,{'path':path,'type':page_type(path),'sessions':None,'engaged':None,'clicks':None,'impressions':None})
        rec['clicks']=(rec['clicks'] or 0)+int(row.get('clicks') or 0)
        rec['impressions']=(rec['impressions'] or 0)+int(row.get('impressions') or 0)
    return sorted(result.values(),key=lambda x:(x['sessions'] or 0,x['clicks'] or 0),reverse=True)[:max_rows]


def query_page_samples(gsc, max_rows=15):
    rows=(gsc or {}).get('query_pages') or []
    result=[]
    for row in rows:
        keys=row.get('keys') or []
        if len(keys)<2:continue
        result.append({'query':keys[0],'path':normalize_path(keys[1]),'type':page_type(keys[1]),
                       'clicks':int(row.get('clicks') or 0),'impressions':int(row.get('impressions') or 0)})
    return sorted(result,key=lambda r:(r['clicks'],r['impressions']),reverse=True)[:max_rows]


def funnel_steps(mode,ga4,outcomes):
    ga=ga4 or {};ext=ga.get('extended_reports') or {};total=ga.get('current_total') or {}
    events={str(r.get('eventName')):int(r.get('eventCount') or 0) for r in ext.get('commerce_events') or []}
    has_events=isinstance(ext.get('commerce_events'),list) and not ext.get('commerce_events_error')
    visits=round(float(total['sessions'])) if total.get('sessions') is not None else None
    if mode=='lead':
        specs=[('Návštěvy',visits,'GA4 · relace'),('Zájem o služby',None,'Vyžaduje definici stránek služeb'),
               ('Odeslání formuláře',events.get('form_submit') if has_events else None,'GA4 · počet událostí'),
               ('Událost poptávky',events.get('generate_lead') if has_events else None,'GA4 · počet událostí'),
               ('Potvrzená poptávka',outcomes.get('leads') if outcomes.get('available') else None,'Potvrzený zdroj poptávek')]
    else:
        specs=[('Návštěvy',visits,'GA4 · relace'),('Zobrazení produktu',events.get('view_item') if has_events else None,'GA4 · události, ne unikátní lidé'),
               ('Přidání do košíku',events.get('add_to_cart') if has_events else None,'GA4 · události'),
               ('Zahájení pokladny',events.get('begin_checkout') if has_events else None,'GA4 · události'),
               ('Skutečné objednávky',outcomes.get('orders') if outcomes.get('available') else None,'WooCommerce · ověřené objednávky')]
    return [{'label':label,'value':value,'source':source,'measured':value is not None} for label,value,source in specs]


def analytics_quality(latest,runs,today=None):
    items=[]
    for key,label,days in [('ga4','GA4',3),('search_console','Search Console',5)]:
        status=freshness(latest.get(key),today=today,threshold_days=days)
        items.append({'source':label,'status':status['state'],'message':status['message'],
                      'period_end':(latest.get(key) or {}).get('period_end') or '—'})
    return items
