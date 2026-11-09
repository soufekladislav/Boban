"""Conservative Seznam Nákupy category resolver.

Matches Woo category paths only against the official Seznam category list.
Never manufactures a CATEGORYTEXT or assumes a partial/ambiguous category is valid.
"""
import json
import re
import unicodedata
from pathlib import Path


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', value).strip().casefold()


def category_paths(payload):
    """Accept flat paths, nested API objects, or an already-exported list of strings."""
    out = set()
    def walk(obj, ancestors=()):
        if isinstance(obj, str):
            if '|' in obj:out.add(' | '.join(part.strip() for part in obj.split('|') if part.strip()))
            return
        if isinstance(obj, list):
            for x in obj:walk(x, ancestors)
            return
        if not isinstance(obj,dict):return
        for key in ('path','fullPath','full_path','categoryPath','category_path'):
            val=obj.get(key)
            if isinstance(val,str) and '|' in val:out.add(' | '.join(x.strip() for x in val.split('|') if x.strip()))
            if isinstance(val,list) and all(isinstance(x,str) for x in val) and len(val)>1:
                out.add(' | '.join(x.strip() for x in val if x.strip()))
        label = next((obj[k] for k in ('name','title','label') if isinstance(obj.get(k),str) and obj[k].strip()),None)
        chain=ancestors+(label,) if label else ancestors
        if len(chain)>1:out.add(' | '.join(chain))
        for key,val in obj.items():
            if key in ('children','categories','subcategories','items','nodes'):
                walk(val,chain)
        # API can return category paths keyed by ID; traverse such values too.
        if not label:
            for key,val in obj.items():
                if key not in ('children','categories','subcategories','items','nodes') and isinstance(val,(list,dict)):
                    walk(val,ancestors)
    walk(payload)
    return sorted(out)


class Resolver:
    def __init__(self, paths=(), overrides=None):
        self.paths=sorted(set(p.strip() for p in paths if isinstance(p,str) and p.strip()))
        self.full={normalized(p):p for p in self.paths}
        self.leaves={}
        for p in self.paths:self.leaves.setdefault(normalized(p.split('|')[-1]),set()).add(p)
        self.overrides={str(k):v for k,v in (overrides or {}).items()}

    def resolve(self, woo_path, category_ids=()):
        for ident in category_ids:
            configured=self.overrides.get(str(ident))
            if configured and normalized(configured) in self.full:return self.full[normalized(configured)],'override'
        key=normalized(woo_path)
        if key in self.full:return self.full[key],'exact'
        # Safe only if the leaf category name has *one* official meaning.
        leaf=normalized(str(woo_path or '').split('|')[-1])
        matches=self.leaves.get(leaf,set())
        if len(matches)==1:return next(iter(matches)),'unique-leaf'
        return None,'ambiguous' if len(matches)>1 else 'unmapped'


def load_local(path):
    p=Path(path)
    if not p.is_file():return Resolver(), 'missing'
    try:
        raw=json.loads(p.read_text(encoding='utf-8'))
        if isinstance(raw,dict) and 'official_categories' in raw:
            return Resolver(category_paths(raw['official_categories']),raw.get('overrides')), 'loaded'
        return Resolver(category_paths(raw)), 'loaded'
    except (OSError,ValueError,TypeError):return Resolver(),'invalid'


def resolver_from_official_cache(cache_file, max_age_seconds=7*86400):
    """Refresh official taxonomy opportunistically, reuse prior known-good snapshot.

    Fixed upstream URL; no user-controlled fetch target. A failed refresh never
    changes the already published product XML.
    """
    import time
    import urllib.request
    cache=Path(cache_file)
    current, status=load_local(cache)
    if status == 'loaded' and cache.stat().st_mtime + max_age_seconds >= time.time():
        return current, 'cache'
    try:
        request=urllib.request.Request('https://www.zbozi.cz/static/categories.json', headers={'User-Agent':'WebBooster-Feed-Validator/1.0'})
        with urllib.request.urlopen(request, timeout=5) as response:
            data=response.read(8_000_001)
        if len(data)>8_000_000:raise ValueError('Taxonomie přesahuje povolený limit')
        payload=json.loads(data)
        paths=category_paths(payload)
        if len(paths)<100:raise ValueError('Neúplná oficiální taxonomie')
        cache.parent.mkdir(parents=True,exist_ok=True)
        tmp=cache.with_name(cache.name+'.tmp')
        tmp.write_text(json.dumps({'official_categories':paths},ensure_ascii=False),encoding='utf-8')
        tmp.replace(cache)
        return Resolver(paths),'refreshed'
    except (OSError,ValueError,TimeoutError,TypeError):
        return current, status if status=='loaded' else 'unavailable'
