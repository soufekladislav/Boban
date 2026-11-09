"""Google Merchant Center connector for WebBooster.

Only communicates with official merchantapi.googleapis.com endpoints. The approved
XML file generated elsewhere is the sole product data source. Never submits
individual products or writes WooCommerce data. No API call is made at import.
"""
from datetime import date, timedelta
import re
from urllib.parse import urlencode

MERCHANT_SCOPE = 'https://www.googleapis.com/auth/content'
BASE = 'https://merchantapi.googleapis.com'
ACCOUNT_RE = re.compile(r'^accounts/([0-9]+)$')
SOURCE_RE = re.compile(r'^accounts/([0-9]+)/dataSources/([0-9]+)$')


def account_name(value):
    value = str(value or '').strip()
    if value.isdigit(): value = 'accounts/' + value
    if not ACCOUNT_RE.fullmatch(value): raise ValueError('Neplatné Merchant account ID.')
    return value


def source_name(value, account):
    value = str(value or '').strip()
    match = SOURCE_RE.fullmatch(value)
    if not match or 'accounts/' + match.group(1) != account_name(account):
        raise ValueError('Datový zdroj nepatří vybranému Merchant účtu.')
    return value


def list_accounts(api):
    out=[]; cursor=''
    for _ in range(10):
        url=BASE+'/accounts/v1/accounts?pageSize=100'
        if cursor:url+='&'+urlencode({'pageToken':cursor})
        result=api('GET',url)
        out.extend({'name':account_name(r.get('name')),'label':str(r.get('accountName') or r.get('name') or '')[:130]}
                   for r in result.get('accounts',[]) if ACCOUNT_RE.fullmatch(str(r.get('name') or '')))
        cursor=result.get('nextPageToken') or ''
        if not cursor:break
    return out


def list_sources(api,account):
    account=account_name(account)
    out=[];cursor=''
    for _ in range(10):
        url=f'{BASE}/datasources/v1/{account}/dataSources?pageSize=100'
        if cursor:url+='&'+urlencode({'pageToken':cursor})
        response=api('GET',url)
        out.extend(r for r in response.get('dataSources',[]) if SOURCE_RE.fullmatch(str(r.get('name') or '')))
        cursor=response.get('nextPageToken') or ''
        if not cursor:break
    return out


def find_existing_source(sources,feed_url):
    return next((x for x in sources if x.get('fileInput',{}).get('fetchSettings',{}).get('fetchUri')==feed_url and 'primaryProductDataSource' in x),None)


def create_source(api,account,feed_url,title,language='cs',country='CZ'):
    account=account_name(account)
    if not feed_url.startswith('https://'):
        raise ValueError('Google feed musí být dostupný přes HTTPS.')
    if not re.fullmatch(r'[a-z]{2}',language) or not re.fullmatch(r'[A-Z]{2}',country):
        raise ValueError('Neplatný jazyk nebo země feedu.')
    payload={
        'displayName':str(title)[:150],
        'primaryProductDataSource':{'channel':'ONLINE_PRODUCTS','contentLanguage':language,'feedLabel':country,'countries':[country]},
        'fileInput':{'fetchSettings':{'enabled':True,'frequency':'FREQUENCY_DAILY',
          'timeOfDay':{'hours':3},'timeZone':'Europe/Prague','fetchUri':feed_url}}
    }
    return api('POST',f'{BASE}/datasources/v1/{account}/dataSources',payload)


def fetch_source(api,source,account):
    name=source_name(source,account)
    return api('POST',f'{BASE}/datasources/v1/{name}:fetch',{})


def file_status(api,source,account):
    name=source_name(source,account)
    return api('GET',f'{BASE}/datasources/v1/{name}/fileUploads/latest')


def aggregate_status(api,account):
    account=account_name(account)
    url=f'{BASE}/issueresolution/v1/{account}/aggregateProductStatuses?pageSize=50'
    data=api('GET',url)
    return (data.get('aggregateProductStatuses') or [])[:50]


def performance(api,account,days=28):
    account=account_name(account)
    end=date.today()-timedelta(days=1)
    start=end-timedelta(days=days-1)
    sql=("SELECT date, marketing_method, clicks, impressions "
         "FROM product_performance_view "
         f"WHERE date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}' "
         "AND marketing_method = 'ORGANIC' ORDER BY date DESC")
    out=[]; cursor=''
    for _ in range(4):
        body={'query':sql,'pageSize':100}
        if cursor:body['pageToken']=cursor
        result=api('POST',f'{BASE}/reports/v1/{account}/reports:search',body)
        out.extend(x.get('productPerformanceView') or {} for x in result.get('results',[]))
        cursor=result.get('nextPageToken') or ''
        if not cursor:break
    clicks=sum(int(r.get('clicks') or 0) for r in out)
    impressions=sum(int(r.get('impressions') or 0) for r in out)
    return {'period_start':start.isoformat(),'period_end':end.isoformat(),'clicks':clicks,
            'impressions':impressions,'ctr_percent':round(100*clicks/impressions,2) if impressions else 0,
            'daily':out[:100], 'complete':not bool(cursor)}
