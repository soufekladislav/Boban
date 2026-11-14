"""Evidence-first project memory and analytical toolset for Boban (v0.9.14.0).

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
    """Deterministický obchodní mozek Bobana (v0.9.14.0).
    Místo hromadného generování SEO chyb vyhodnocuje 3 klíčové obchodní priority:
    1. Kontrola slepoty / měření (purchase, poptávky, košík)
    2. Rychlé prodejní příležitosti (Quick Wins v Search Console / GA4)
    3. Akvizice a rozvoj kanálů (např. Bing, katalogové feedy pro Viki)
    """
    tool = tool_for_question(question)
    ga4, gsrc = _snapshot(conn, project_id, 'ga4')
    gsc, ssrc = _snapshot(conn, project_id, 'search_console')
    
    project_row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    project = dict(project_row) if project_row else {}
    
    sources = [s for s in (gsrc, ssrc) if s]
    result = {'tool': tool, 'evidence_sources': sources, 'limitations': [], 'facts': {}}
    
    period = ga4.get('period') or {}
    current = ga4.get('current_total') or {}
    organic = ga4.get('current_organic') or {}
    
    result['facts']['ga4'] = {
        'period': period, 
        'sessions': current.get('sessions'), 
        'organic_sessions': organic.get('sessions'),
        'keyEvents': current.get('keyEvents'),
        'totalRevenue': current.get('totalRevenue')
    }
    result['facts']['gsc'] = {'period': gsc.get('period'), 'current': gsc.get('current') or {}}
    
    outcome_rows = conn.execute('SELECT outcome_type, status, test_record, amount, currency FROM analytics_business_outcomes WHERE project_id=? ORDER BY id DESC LIMIT 1000', (project_id,)).fetchall()
    verified_outcomes = [r for r in outcome_rows if r['test_record'] == 0]
    # An empty or test-only outcome table is missing evidence, not zero sales.
    real_orders = (sum(1 for r in verified_outcomes if r['outcome_type'] == 'order'
                       and r['status'] not in ('failed', 'cancelled', 'refunded', 'trash'))
                   if verified_outcomes else None)
    
    result['facts']['business_outcomes'] = {
        'source_connected_and_verified': bool(verified_outcomes),
        'real_orders': real_orders,
        'real_orders_in_loaded_sample': real_orders,
        'sample_complete': False,
    }

    business_initiatives = []
    
    if not verified_outcomes:
        business_initiatives.append({
            'priority': 1,
            'title': 'Zprovoznit a ověřit nákupní měření (Funnel)',
            'reason': 'Nemáme ověřený obchodní záznam o objednávkách nebo poptávkách. Neznamená to nula prodejů. Ověřme měření a propojení s obchodním zdrojem.',
            'action_needed': 'Zkontrolovat GA4 a GTM měření, ověřit průchodnost košíku.',
            'owner': 'Boban + Uživatel'
        })
    else:
        business_initiatives.append({
            'priority': 1,
            'title': 'Ověřené obchodní záznamy jsou dostupné',
            'reason': f'Ve vzorku posledních 1000 záznamů máme {real_orders} skutečných objednávek. Bez kontroly úplnosti a období to není celkový prodej.',
            'action_needed': 'Průběžně sledovat trend v čase.',
            'owner': 'Boban'
        })

    queries = (gsc.get('top_queries') or [])
    if queries:
        business_initiatives.append({
            'priority': 2,
            'title': 'Využít existující zobrazení (Quick Wins)',
            'reason': 'Našli jsme dotazy a stránky, které už lidi ve vyhledávání vidí, ale neproklikávají se na ně v dostatečné míře.',
            'action_needed': 'Upravit prodejní titulky a prolinkovat klíčové vstupní stránky.',
            'owner': 'Boban'
        })
    else:
        business_initiatives.append({
            'priority': 2,
            'title': 'Rozšířit organickou akvizici',
            'reason': 'Search Console zatím neposkytuje dostatek dat pro optimalizaci pozic.',
            'action_needed': 'Zkontrolovat sitemapu a indexaci stránek.',
            'owner': 'Boban'
        })

    business_initiatives.append({
            'priority': 3,
            'title': 'Rozšířit akviziční kanály (Bing / Zboží / Heureka)',
            'reason': 'Spoléhat se jen na Google nestačí. Zapojením Bingu (cez IndexNow) a srovnávačů přivedeme relevantní zákazníky rychleji.',
            'action_needed': 'Potvrdit propojení katalogů (Viki) a ověřit IndexNow.',
            'owner': 'Viki + Boban'
    })

    result['facts']['business_initiatives'] = business_initiatives
    result['next_steps'] = [{'priority': 'high', 'action': x['title'], 'why': x['reason'], 'needs_user': x['owner']} for x in business_initiatives]
    
    if not verified_outcomes: result['limitations'].insert(0, 'Chybí ověřený vzorek skutečných obchodních výsledků; počet objednávek je neznámý.')
    if not ga4: result['limitations'].append('GA4 snapshot není k dispozici.')
    if not gsc: result['limitations'].append('Search Console snapshot není k dispozici.')
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
    initiatives = facts.get('business_initiatives') or []
    
    pieces=['Zde jsou aktuální obchodní priority pro růst prodeje:']
    for idx, init in enumerate(initiatives, 1):
        pieces.append(f"{idx}. **{init.get('title')}**\n   - *Důvod:* {init.get('reason')}\n   - *Krok:* {init.get('action_needed')}")
        
    if ga.get('sessions') is not None:
        period=ga.get('period') or {}
        pieces.append('\n*GA4 souhrn:* {} relací ({} až {}).'.format(ga['sessions'],period.get('start','?'),period.get('end','?')))
        
    for limitation in (analysis.get('limitations') or [])[:3]: pieces.append('Omezení: '+limitation)
    pieces.append('\nAnalýza byla provedena nad uloženými daty; AI Engine není nyní dostupný.')
    return '\n\n'.join(pieces)