"""Meta Catalog Graph API wrapper. Secrets never appear in URL/log/error.
Do not create extra product feeds or items: bind the already registered feed.
"""
import os
import json
from urllib.parse import urlencode
import requests

VERSION=os.getenv('META_GRAPH_VERSION','v25.0')
BASE='https://graph.facebook.com/'
OAUTH='https://www.facebook.com/'

class MetaAPIError(ValueError):pass

def configured():
    return bool(os.getenv('META_APP_ID') and os.getenv('META_APP_SECRET'))

def oauth_url(state,redirect_uri):
    if not configured():raise MetaAPIError('Meta App ID/Secret chybí.')
    q=urlencode({'client_id':os.environ['META_APP_ID'],'redirect_uri':redirect_uri,
                 'state':state,'scope':'catalog_management,business_management','response_type':'code'})
    return OAUTH+VERSION+'/dialog/oauth?'+q

def exchange_code(code,redirect_uri):
    r=requests.get(BASE+VERSION+'/oauth/access_token',params={'client_id':os.environ['META_APP_ID'],
        'client_secret':os.environ['META_APP_SECRET'],'redirect_uri':redirect_uri,'code':code},timeout=15)
    if r.status_code!=200:raise MetaAPIError('Meta OAuth odmítl výměnu kódu (HTTP %s).'%r.status_code)
    value=r.json().get('access_token')
    if not value:raise MetaAPIError('Meta nevrátil přístupový token.')
    # Exchange short-lived user token for a long-lived one where supported.
    # Meta may still revoke or expire it: do not imply permanent connection.
    try:
        lr=requests.get(BASE+VERSION+'/oauth/access_token',params={
            'grant_type':'fb_exchange_token','client_id':os.environ['META_APP_ID'],
            'client_secret':os.environ['META_APP_SECRET'],'fb_exchange_token':value},timeout=15)
        if lr.status_code==200:
            longer=lr.json().get('access_token')
            if longer:value=longer
    except (requests.RequestException,ValueError):
        pass
    return value

def call(method,path,token,params=None,data=None):
    if method not in ('GET','POST') or not path or path.startswith('/') or '://' in path or '?' in path:
        raise MetaAPIError('Neplatná cesta Meta API.')
    if not token:raise MetaAPIError('Chybí autorizace Meta.')
    url=BASE+VERSION+'/'+path
    try:
        r=requests.request(method,url,params=params,data=data,headers={'Authorization':'Bearer '+token},timeout=20)
    except requests.RequestException as exc:raise MetaAPIError('Meta API není dostupné: '+type(exc).__name__)
    if r.status_code>=400:
        try:
            e=r.json().get('error') or {}
            code=e.get('code','?');sub=e.get('error_subcode','?')
        except Exception:code=sub='?'
        raise MetaAPIError('Meta API HTTP %s (kód %s, podkód %s). Zkontroluj oprávnění a katalog.'%(r.status_code,code,sub))
    try:return r.json()
    except ValueError:raise MetaAPIError('Meta vrátila neplatnou odpověď.')

def catalog(token,cid):
    if not str(cid).isdigit():raise MetaAPIError('Neplatné ID katalogu.')
    return call('GET',str(cid),token,params={'fields':'id,name,product_count'})

def feeds(token,cid):
    if not str(cid).isdigit():raise MetaAPIError('Neplatné ID katalogu.')
    resp=call('GET',str(cid)+'/product_feeds',token,params={'fields':'id,name,schedule','limit':100})
    return resp.get('data',[])

def match_feed(items,expected_path):
    # Match by the URL we already control; never bind random primary feed.
    for entry in items:
        schedule=entry.get('schedule') or {}
        if isinstance(schedule,str):
            try:schedule=json.loads(schedule)
            except ValueError:schedule={}
        if expected_path and expected_path in str(schedule.get('url') or ''):return entry
    return None

def trigger_upload(token,feed_id,url):
    if not str(feed_id).isdigit() or not url.startswith('https://'):
        raise MetaAPIError('Chybí správný zdroj nebo HTTPS URL.')
    return call('POST',str(feed_id)+'/uploads',token,data={'url':url})

def uploads(token,feed_id):
    if not str(feed_id).isdigit():raise MetaAPIError('Neplatné ID zdroje.')
    result=call('GET',str(feed_id)+'/uploads',token,params={'fields':'id,start_time,end_time,num_detected_items,num_invalid_items,num_deleted_items,num_persisted_items,error_count,warning_count','limit':5})
    return result.get('data',[])


def upload_errors(token, upload_id, limit=5):
    """Read-only sample of non-secret upload diagnostic issues."""
    if not str(upload_id).isdigit():
        raise MetaAPIError('Neplatné ID importu.')
    response=call('GET',str(upload_id)+'/errors',token,params={
        'fields':'id,summary,description,severity,total_count',
        'limit':max(1,min(int(limit),10))})
    return [{'summary':str(e.get('summary') or '')[:300],
             'severity':str(e.get('severity') or '')[:30],
             'total_count':e.get('total_count')} for e in response.get('data',[])]
