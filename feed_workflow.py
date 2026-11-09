"""Deterministic, portable product distribution workflow.

Temporary ownership: WebBooster/Boban. No AI, no WooCommerce writes, no provider credentials.
Designed to be extracted unchanged to Viki behind Fresh Key.
"""
import json
from collections import Counter


def ensure_schema(conn, backend):
    if backend == 'mysql':
        statements = [
          """CREATE TABLE IF NOT EXISTS catalog_workflows (project_id BIGINT UNSIGNED PRIMARY KEY, mode VARCHAR(24) NOT NULL DEFAULT 'idle', approved TINYINT NOT NULL DEFAULT 0, approved_at VARCHAR(32), revision INT NOT NULL DEFAULT 0, published_revision INT NOT NULL DEFAULT 0, interval_minutes INT NOT NULL DEFAULT 60, last_error TEXT, updated_at VARCHAR(32)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
          """CREATE TABLE IF NOT EXISTS catalog_exclusions (project_id BIGINT UNSIGNED NOT NULL, kind VARCHAR(24) NOT NULL, entity_id BIGINT UNSIGNED NOT NULL, PRIMARY KEY(project_id,kind,entity_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        ]
    else:
        statements = [
          """CREATE TABLE IF NOT EXISTS catalog_workflows (project_id INTEGER PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'idle', approved INTEGER NOT NULL DEFAULT 0, approved_at TEXT, revision INTEGER NOT NULL DEFAULT 0, published_revision INTEGER NOT NULL DEFAULT 0, interval_minutes INTEGER NOT NULL DEFAULT 60, last_error TEXT, updated_at TEXT)""",
          """CREATE TABLE IF NOT EXISTS catalog_exclusions (project_id INTEGER NOT NULL, kind TEXT NOT NULL, entity_id INTEGER NOT NULL, PRIMARY KEY(project_id,kind,entity_id))""",
        ]
    for stmt in statements: conn.execute(stmt)
    conn.commit()


def state(conn, project_id):
    row=conn.execute('SELECT * FROM catalog_workflows WHERE project_id=?',(project_id,)).fetchone()
    return dict(row) if row else {'project_id':project_id,'mode':'idle','approved':0,'revision':0,'published_revision':0,'interval_minutes':60,'last_error':None}


def update(conn, backend, project_id, timestamp, **values):
    allowed={'mode','approved','approved_at','revision','published_revision','interval_minutes','last_error'}
    values={k:v for k,v in values.items() if k in allowed}
    values['updated_at']=timestamp
    if backend=='mysql':
        conn.execute('INSERT IGNORE INTO catalog_workflows(project_id,updated_at) VALUES(?,?)',(project_id,timestamp))
    else:
        conn.execute('INSERT OR IGNORE INTO catalog_workflows(project_id,updated_at) VALUES(?,?)',(project_id,timestamp))
    fields=', '.join(k+'=?' for k in values)
    conn.execute('UPDATE catalog_workflows SET '+fields+' WHERE project_id=?',tuple(values.values())+(project_id,))
    conn.commit()


def exclusions(conn, project_id):
    rows=conn.execute('SELECT kind,entity_id FROM catalog_exclusions WHERE project_id=?',(project_id,)).fetchall()
    out={'category':set(),'product':set()}
    for row in rows:
        if row['kind'] in out:out[row['kind']].add(int(row['entity_id']))
    return out


def set_exclusion(conn,backend,project_id,kind,ident,excluded):
    if kind not in ('category','product') or int(ident)<=0:raise ValueError('Neplatná výjimka katalogu')
    if excluded:
        sql='INSERT IGNORE' if backend=='mysql' else 'INSERT OR IGNORE'
        conn.execute(sql+' INTO catalog_exclusions(project_id,kind,entity_id) VALUES(?,?,?)',(project_id,kind,int(ident)))
    else:
        conn.execute('DELETE FROM catalog_exclusions WHERE project_id=? AND kind=? AND entity_id=?',(project_id,kind,int(ident)))
    conn.commit()


def product_category_ids(product):
    out=set()
    for cat in product.get('categories') or []:
        try:
            ident=int(cat.get('id') or cat.get('term_id') or 0) if isinstance(cat,dict) else 0
            if ident:out.add(ident)
        except (TypeError,ValueError):pass
    return out


def category_tree(products):
    found={}
    for p in products:
        for cat in p.get('categories') or []:
            if not isinstance(cat,dict):continue
            try:
                ident=int(cat.get('id') or cat.get('term_id') or 0)
                parent=int(cat.get('parent') or cat.get('parent_id') or 0)
            except (ValueError,TypeError):continue
            if ident>0:
                found[ident]={'id':ident,'name':str(cat.get('name') or cat.get('title') or 'Kategorie '+str(ident))[:120], 'parent':parent,'count':0}
    for p in products:
        for ident in product_category_ids(p):
            if ident in found:found[ident]['count']+=1
    return sorted(found.values(),key=lambda c:(c['parent']!=0,c['parent'],c['name'].lower()))


def excluded_category_ids(categories, chosen):
    all_excluded=set(chosen); child_map={}
    for c in categories: child_map.setdefault(c['parent'],[]).append(c['id'])
    stack=list(chosen)
    while stack:
        for child in child_map.get(stack.pop(),[]):
            if child not in all_excluded:all_excluded.add(child);stack.append(child)
    return all_excluded


def selected(parents,variants,excluded, categories=None):
    """Any excluded category wins (even with several assigned categories).
    Unknown categories never imply inclusion for unpublished products.
    Parents excluded -> their variants excluded. No variants for unsynced parents.
    """
    cats=excluded_category_ids(categories if categories is not None else category_tree(parents),excluded['category'])
    parent_ids={int(p['id']) for p in parents if int(p.get('id') or 0)>0}
    reject={int(p['id']) for p in parents if int(p.get('id') or 0) in excluded['product'] or product_category_ids(p)&cats or (p.get('raw') or {}).get('status') in ('draft','private','trash','pending')}
    filtered=[p for p in parents if int(p.get('id') or 0) not in reject]
    filtered_variants=[v for v in variants if int(v.get('parent_id') or 0) in parent_ids and int(v.get('parent_id') or 0) not in reject and int(v.get('variation_id') or 0) not in excluded['product'] and (v.get('raw') or {}).get('status') not in ('draft','private','trash')]
    return filtered,filtered_variants,{'excluded_parents':len(parents)-len(filtered),'excluded_variants':len(variants)-len(filtered_variants)}


def preview_counts(parents,variants,excluded):
    p,v,details=selected(parents,variants,excluded)
    return {'parents':len(p),'variants':len(v),**details}
