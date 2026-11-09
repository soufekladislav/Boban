"""Evidence-first project memory and analytical toolset for Boban.

Read-only with respect to marketing platforms. Persistent notes are only facts
from local authoritative records or explicitly user-confirmed decisions.
"""
import json
import re
from datetime import datetime, timedelta


def ensure_schema(conn, backend):
    if backend == 'mysql':
        ddl = [
            '''CREATE TABLE IF NOT EXISTS advisor_memory (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, project_id BIGINT UNSIGNED NOT NULL,
              memory_key VARCHAR(190) NOT NULL, kind VARCHAR(32) NOT NULL,
              status VARCHAR(24) NOT NULL, statement TEXT NOT NULL,
              source_type VARCHAR(64) NOT NULL, source_ref VARCHAR(190) NULL,
              evidence_json LONGTEXT NULL, observed_at VARCHAR(32) NOT NULL,
              valid_until VARCHAR(32) NULL, updated_at VARCHAR(32) NOT NULL,
              UNIQUE KEY uq_advisor_memory (project_id,memory_key),
              INDEX idx_advisor_memory_project (project_id,status,updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
            '''CREATE TABLE IF NOT EXISTS advisor_analysis_runs (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, project_id BIGINT UNSIGNED NOT NULL,
              tool_name VARCHAR(80) NOT NULL, question TEXT NOT NULL,
              evidence_json LONGTEXT NOT NULL, result_json LONGTEXT NOT NULL,
              created_at VARCHAR(32) NOT NULL,
              INDEX idx_advisor_analysis (project_id,id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci'''
        ]
    else:
        ddl = [
            '''CREATE TABLE IF NOT EXISTS advisor_memory (
              id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL,
              memory_key TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,
              statement TEXT NOT NULL,source_type TEXT NOT NULL,source_ref TEXT,
              evidence_json TEXT,observed_at TEXT NOT NULL,valid_until TEXT,
              updated_at TEXT NOT NULL,UNIQUE(project_id,memory_key))''',
            'CREATE INDEX IF NOT EXISTS idx_advisor_memory_project ON advisor_memory(project_id,status,updated_at)',
            '''CREATE TABLE IF NOT EXISTS advisor_analysis_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL,
              tool_name TEXT NOT NULL,question TEXT NOT NULL,evidence_json TEXT NOT NULL,
              result_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS idx_advisor_analysis ON advisor_analysis_runs(project_id,id)'
        ]
    for sql in ddl: conn.execute(sql)


def _d(x):
    return dict(x) if x is not None else {}


def _decode(s):
    if isinstance(s,dict): return s
    try: return json.loads(s or '{}')
    except (TypeError,ValueError): return {}


def upsert_memory(conn, backend, project_id, key, kind, statement, source_type,
                  source_ref=None, evidence=None, status='verified', observed_at=None, valid_until=None):
    if status not in ('verified','hypothesis','decision','superseded'):
        raise ValueError('Unsupported memory status')
    ts = observed_at or datetime.now().isoformat(timespec='seconds')
    params=(project_id,key[:190],kind[:32],status,statement[:3000],source_type[:64],
            (source_ref or '')[:190],json.dumps(evidence or {},ensure_ascii=False,default=str),ts,valid_until,ts)
    if backend == 'mysql':
        conn.execute('''INSERT INTO advisor_memory
          (project_id,memory_key,kind,status,statement,source_type,source_ref,evidence_json,observed_at,valid_until,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE
          kind=VALUES(kind),status=VALUES(status),statement=VALUES(statement),
          source_type=VALUES(source_type),source_ref=VALUES(source_ref),
          evidence_json=VALUES(evidence_json),observed_at=VALUES(observed_at),
          valid_until=VALUES(valid_until),updated_at=VALUES(updated_at)''',params)
    else:
        conn.execute('''INSERT INTO advisor_memory
          (project_id,memory_key,kind,status,statement,source_type,source_ref,evidence_json,observed_at,valid_until,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id,memory_key) DO UPDATE SET
          kind=excluded.kind,status=excluded.status,statement=excluded.statement,
          source_type=excluded.source_type,source_ref=excluded.source_ref,
          evidence_json=excluded.evidence_json,observed_at=excluded.observed_at,
          valid_until=excluded.valid_until,updated_at=excluded.updated_at''',params)


def recent_memory(conn, project_id, limit=18, at=None):
    at=at or datetime.now().isoformat(timespec='seconds')
    rows=conn.execute('''SELECT memory_key,kind,status,statement,source_type,source_ref,
      evidence_json,observed_at,valid_until FROM advisor_memory WHERE project_id=?
      AND status!='superseded' ORDER BY updated_at DESC LIMIT ?''',(project_id,min(limit,50))).fetchall()
    out=[]
    for r in rows:
        d=_d(r); d['stale']=bool(d.get('valid_until') and d['valid_until'] < at)
        d['evidence']=_decode(d.pop('evidence_json',None))
        out.append(d)
    return out


def sync_project_facts(conn,backend,project_id):
    """Refresh only objective facts (project goal + current statuses), no inferred wins."""
    count=0
    p=conn.execute('SELECT business_goal,primary_conversion FROM projects WHERE id=?',(project_id,)).fetchone()
    if p and p['business_goal']:
        upsert_memory(conn,backend,project_id,'goal:primary','goal',str(p['business_goal']),
                      'projects',str(project_id),{'primary_conversion':p['primary_conversion']},'decision')
        count+=1
    rows=conn.execute('SELECT provider,status,updated_at FROM integrations WHERE project_id=?',(project_id,)).fetchall()
    for row in rows:
        provider=str(row['provider']); status=str(row['status'])
        # Connected is not equivalent to having working API data.
        upsert_memory(conn,backend,project_id,'integration:'+provider,'integration',
            f'{provider}: stav konektoru {status}; dostupnost dat se ověřuje zvlášť.',
            'integrations',provider,{'status':status,'updated_at':row['updated_at']},
            'verified',valid_until=(datetime.now()+timedelta(days=1)).isoformat(timespec='seconds'))
        count+=1
    return count


def tool_for_question(question):
    q=(question or '').lower()
    if re.search(r'objedn|nákup|nakup|poptáv|poptav|konverz|prodej|tržb|trzb',q): return 'conversion_reality'
    if re.search(r'klíčov|klicov|hledaj|vyhled|dotaz|poptávk',q): return 'search_demand'
    if re.search(r'katalog|merchant|heurek|meta|facebook|seznam|sklik|integrac|připoj|pripoj',q): return 'channel_readiness'
    if re.search(r'produkt|sortiment|kategori|stránk|strank|obsah',q): return 'landing_opportunities'
    return 'project_overview'


def _snapshot(conn,pid,source):
    row=conn.execute('''SELECT id,payload,captured_at FROM source_snapshots
      WHERE project_id=? AND provider=? ORDER BY id DESC LIMIT 1''',(pid,source)).fetchone()
    if not row:return {},None
    return _decode(row['payload']), {'source':source,'snapshot_id':row['id'],'captured_at':row['captured_at']}


def analyze(conn,project_id,question):
    """Deterministic bounded tool call; not an LLM-generated calculation."""
    tool=tool_for_question(question)
    ga4,gsrc=_snapshot(conn,project_id,'ga4')
    gsc,ssrc=_snapshot(conn,project_id,'search_console')
    sources=[s for s in (gsrc,ssrc) if s]
    result={'tool':tool,'evidence_sources':sources,'limitations':[], 'facts':{}}
    period=ga4.get('period') or {}; current=ga4.get('current_total') or {}; organic=ga4.get('current_organic') or {}
    result['facts']['ga4']={'period':period,'sessions':current.get('sessions'), 'organic_sessions':organic.get('sessions')}
    result['facts']['gsc']={'period':gsc.get('period'), 'current':gsc.get('current') or {}}
    if tool=='search_demand':
        result['facts']['queries']=(gsc.get('top_queries') or [])[:12]
        result['facts']['query_pages']=(gsc.get('query_pages') or [])[:12]
    elif tool=='landing_opportunities':
        result['facts']['landing_pages']=(ga4.get('extended_reports') or {}).get('landing_pages_all',[])[:15]
        result['facts']['gsc_pages']=(gsc.get('top_pages') or [])[:15]
        result['limitations'].append('URL lze porovnávat napříč systémy, jednotlivé dotazy nelze přiřadit k objednávkám.')
    elif tool=='channel_readiness':
        rows=conn.execute('SELECT provider,status,updated_at FROM integrations WHERE project_id=?',(project_id,)).fetchall()
        result['facts']['connections']=[_d(r) for r in rows]
        result['facts']['channels']=(ga4.get('extended_reports') or {}).get('channels',[])[:18]
        result['limitations'].append('Připojený katalog neznamená měřitelný přínos prodeje.')
    elif tool=='conversion_reality':
        outcome_rows=conn.execute('SELECT outcome_type,status,test_record,amount,currency FROM analytics_business_outcomes WHERE project_id=? ORDER BY id DESC LIMIT 1000',(project_id,)).fetchall()
        verified=[r for r in outcome_rows if r['test_record']==0]
        result['facts']['business_outcomes']={'source_connected_and_verified':bool(outcome_rows),
            'real_orders_in_loaded_sample':sum(1 for r in verified if r['outcome_type']=='order' and r['status'] not in ('failed','cancelled','refunded','trash')) if outcome_rows else None,
            'note':'Není to úplná statistika období; kontroluje jen dostupnost ověřených obchodních záznamů.'}
        result['facts']['events']=(ga4.get('extended_reports') or {}).get('commerce_events',[])[:20]
        if not outcome_rows:result['limitations'].append('Chybí ověřený čtecí zdroj objednávek/poptávek; nula v GA4 není důkaz nulového prodeje.')
    else:
        result['facts']['channels']=(ga4.get('extended_reports') or {}).get('channels',[])[:10]
        result['facts']['top_queries']=(gsc.get('top_queries') or [])[:8]
    # Evidence-backed prompts for investigation, not unsupported sales claims.
    next_steps=[]
    if tool=='conversion_reality' and not result['facts'].get('business_outcomes',{}).get('source_connected_and_verified'):
        next_steps.append({'priority':'high','action':'Zajistit ověřené souhrny skutečných objednávek/poptávek',
            'why':'Bez nich nelze dokázat obchodní přínos marketingu.',
            'needs_user':'Potvrdit zdroj dat a rozlišení testovacích záznamů.'})
    if tool=='search_demand':
        pages=result['facts'].get('query_pages') or []
        row=next((r for r in pages if (r.get('keys') or []) and (r.get('impressions') or 0)>0),None)
        if row:
            keys=row.get('keys') or []
            next_steps.append({'priority':'medium','action':'Prověřit nákupní záměr konkrétního dotazu',
                'query':str(keys[0])[:150],'page':str(keys[1])[:280] if len(keys)>1 else '',
                'why':'Dotaz a stránka jsou doloženy v Search Console; nejde o připsaný prodej.'})
    if tool=='channel_readiness' and not result['facts'].get('channels'):
        next_steps.append({'priority':'medium','action':'Ověřit měření katalogových návštěv v GA4',
            'why':'Aktivní feed sám nedokazuje návštěvy nebo objednávky.'})
    result['next_steps']=next_steps
    if not ga4:result['limitations'].append('GA4 snapshot není k dispozici.')
    if not gsc:result['limitations'].append('Search Console snapshot není k dispozici.')
    for src in sources:
        try:
            if datetime.now()-datetime.fromisoformat(src['captured_at'])>timedelta(days=2):
                result['limitations'].append('Starší snapshot: '+src['source']+' ('+str(src['captured_at'])+').')
        except (TypeError,ValueError):pass
    return result


def record_analysis(conn,pid,question,result,ts=None):
    ts=ts or datetime.now().isoformat(timespec='seconds')
    conn.execute('''INSERT INTO advisor_analysis_runs(project_id,tool_name,question,evidence_json,result_json,created_at)
      VALUES(?,?,?,?,?,?)''',(pid,result['tool'],question[:700],
      json.dumps(result.get('evidence_sources',[]),ensure_ascii=False),
      json.dumps(result,ensure_ascii=False,default=str)[:45000],ts))


def chat_context(conn,backend,pid,question):
    sync_project_facts(conn,backend,pid)
    result=analyze(conn,pid,question)
    record_analysis(conn,pid,question,result)
    memory=recent_memory(conn,pid,limit=20)
    conn.commit()
    return {'selected_tool':result['tool'],'analysis':result,'project_memory':memory,
            'evidence_policy':'Neuváděj neověřená čísla. Cituj zdroj, období a čerstvost. Rozlišuj fakta, hypotézy a rozhodnutí. Nevymýšlej realizace. Pokud data chybí, přesně řekni která a jak je získat. Náklady a marže zatím neznáme.'}


def fallback_answer(analysis):
    """Truthful Czech response when AI Engine is unavailable; never invent conversions."""
    facts=analysis.get('facts') or {}
    ga=facts.get('ga4') or {}
    pieces=['Z dostupných dat mohu potvrdit:']
    if ga.get('sessions') is not None:
        period=ga.get('period') or {}
        pieces.append('GA4: {} relací ({} až {}).'.format(ga['sessions'],period.get('start','?'),period.get('end','?')))
    else:pieces.append('Spolehlivý počet relací GA4 nyní nemám.')
    if analysis.get('tool')=='conversion_reality':
        outcome=facts.get('business_outcomes') or {}
        if not outcome.get('source_connected_and_verified'):
            pieces.append('Skutečné objednávky a poptávky nejsou ověřeně napojené. Neznamená to nula prodejů.')
    elif analysis.get('tool')=='search_demand':
        queries=facts.get('queries') or []
        if queries:
            row=queries[0];keys=row.get('keys') or []
            pieces.append('Nejvýše v načteném výpisu Search Console: {} ({} impresí, {} kliknutí).'.format(
                (keys[0] if keys else 'bez dotazu'),row.get('impressions','?'),row.get('clicks','?')))
    elif analysis.get('tool')=='channel_readiness':
        connections=facts.get('connections') or []
        if connections:
            pieces.append('Stavy konektorů: '+', '.join(str(x.get('provider'))+'='+str(x.get('status')) for x in connections[:8])+'.')
    for limitation in (analysis.get('limitations') or [])[:3]:pieces.append('Omezení: '+limitation)
    for step in (analysis.get('next_steps') or [])[:2]:pieces.append('Další ověření: '+step.get('action','')+'.')
    pieces.append('Analýza byla provedena nad uloženými daty; AI Engine není nyní dostupný.')
    return '\n\n'.join(pieces)
