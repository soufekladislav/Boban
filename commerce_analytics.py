"""Read-only analytical foundation (0.9.13.17).

No external writes and no guessed orders. Supports MySQL/MariaDB and SQLite
through the application's existing qmark compatibility wrapper.
"""
import hashlib
import json
from datetime import datetime


def ensure_schema(conn, backend):
    if backend == 'mysql':
        ddl = [
            '''CREATE TABLE IF NOT EXISTS analytics_sync_runs (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, project_id BIGINT UNSIGNED NOT NULL,
              source VARCHAR(80) NOT NULL, status VARCHAR(24) NOT NULL,
              period_start VARCHAR(16), period_end VARCHAR(16), row_count INT DEFAULT 0,
              started_at VARCHAR(32) NOT NULL, finished_at VARCHAR(32), error_message TEXT,
              INDEX idx_analytics_sync (project_id,source,id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
            '''CREATE TABLE IF NOT EXISTS analytics_observations (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, project_id BIGINT UNSIGNED NOT NULL,
              source VARCHAR(80) NOT NULL, report_type VARCHAR(60) NOT NULL,
              period_start VARCHAR(16) NOT NULL, period_end VARCHAR(16) NOT NULL,
              dimension_key CHAR(64) NOT NULL, dimensions_json LONGTEXT NOT NULL,
              metrics_json LONGTEXT NOT NULL, captured_at VARCHAR(32) NOT NULL,
              UNIQUE KEY uq_analytics_observation (project_id,source,report_type,period_start,period_end,dimension_key),
              INDEX idx_analytics_obs_period (project_id,source,period_end)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
            '''CREATE TABLE IF NOT EXISTS analytics_business_outcomes (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, project_id BIGINT UNSIGNED NOT NULL,
              source VARCHAR(80) NOT NULL, external_id VARCHAR(150) NOT NULL,
              outcome_type VARCHAR(32) NOT NULL, occurred_at VARCHAR(32) NOT NULL,
              status VARCHAR(48) NOT NULL, test_record TINYINT DEFAULT NULL,
              amount DECIMAL(15,2) DEFAULT NULL, currency VARCHAR(8),
              source_medium VARCHAR(255), campaign VARCHAR(255),
              entity_external_id VARCHAR(160), source_payload LONGTEXT,
              observed_at VARCHAR(32) NOT NULL,
              UNIQUE KEY uq_analytics_outcome (project_id,source,external_id),
              INDEX idx_analytics_outcome_period (project_id,outcome_type,occurred_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
            '''CREATE TABLE IF NOT EXISTS analytics_entity_links (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, project_id BIGINT UNSIGNED NOT NULL,
              entity_type VARCHAR(32) NOT NULL, canonical_id VARCHAR(160) NOT NULL,
              provider VARCHAR(80) NOT NULL, provider_id VARCHAR(200) NOT NULL,
              linked_at VARCHAR(32) NOT NULL,
              UNIQUE KEY uq_analytics_link (project_id,entity_type,provider,provider_id),
              INDEX idx_analytics_canonical (project_id,entity_type,canonical_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci'''
        ]
    else:
        ddl = [
            '''CREATE TABLE IF NOT EXISTS analytics_sync_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
              source TEXT NOT NULL, status TEXT NOT NULL, period_start TEXT,period_end TEXT,
              row_count INTEGER DEFAULT 0,started_at TEXT NOT NULL,finished_at TEXT,error_message TEXT)''',
            'CREATE INDEX IF NOT EXISTS idx_analytics_sync ON analytics_sync_runs(project_id,source,id)',
            '''CREATE TABLE IF NOT EXISTS analytics_observations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
              source TEXT NOT NULL,report_type TEXT NOT NULL,period_start TEXT NOT NULL,period_end TEXT NOT NULL,
              dimension_key TEXT NOT NULL,dimensions_json TEXT NOT NULL,metrics_json TEXT NOT NULL,captured_at TEXT NOT NULL,
              UNIQUE(project_id,source,report_type,period_start,period_end,dimension_key))''',
            'CREATE INDEX IF NOT EXISTS idx_analytics_obs_period ON analytics_observations(project_id,source,period_end)',
            '''CREATE TABLE IF NOT EXISTS analytics_business_outcomes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL,
              source TEXT NOT NULL,external_id TEXT NOT NULL,outcome_type TEXT NOT NULL,occurred_at TEXT NOT NULL,
              status TEXT NOT NULL,test_record INTEGER,amount NUMERIC,currency TEXT,
              source_medium TEXT,campaign TEXT,entity_external_id TEXT,source_payload TEXT,
              observed_at TEXT NOT NULL,UNIQUE(project_id,source,external_id))''',
            'CREATE INDEX IF NOT EXISTS idx_analytics_outcome_period ON analytics_business_outcomes(project_id,outcome_type,occurred_at)',
            '''CREATE TABLE IF NOT EXISTS analytics_entity_links (
              id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL,entity_type TEXT NOT NULL,
              canonical_id TEXT NOT NULL,provider TEXT NOT NULL,provider_id TEXT NOT NULL,linked_at TEXT NOT NULL,
              UNIQUE(project_id,entity_type,provider,provider_id))''',
            'CREATE INDEX IF NOT EXISTS idx_analytics_canonical ON analytics_entity_links(project_id,entity_type,canonical_id)'
        ]
    for statement in ddl:
        conn.execute(statement)


def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def record_snapshot(conn, project_id, source, payload, backend, captured_at=None):
    """Materialize period-labeled reports. Replacing by natural keys is idempotent.
    Call inside the SAME DB transaction as the source snapshot.
    """
    ts = captured_at or datetime.now().isoformat(timespec='seconds')
    period = payload.get('period') or {}
    start, end = period.get('start'), period.get('end')
    if not start or not end:
        return 0
    buckets = {}
    if source == 'ga4':
        ext = payload.get('extended_reports') or {}
        reports = ('channels','sources','countries','devices','campaigns','commerce_events','items','daily_channels','daily_totals','landing_pages_all')
        for report in reports:
            rows = ext.get(report)
            if isinstance(rows,list):
                buckets[report] = rows
        for report, data in [('site_summary',payload.get('current_total')),('organic_summary',payload.get('current_organic'))]:
            if isinstance(data,dict): buckets[report] = [data]
    elif source == 'search_console':
        for report, key in [('queries','top_queries'),('pages','top_pages'),('query_pages','query_pages'),('daily','daily')]:
            rows=payload.get(key)
            if isinstance(rows,list): buckets[report]=rows
        if isinstance(payload.get('current'),dict): buckets['site_summary']=[payload['current']]
    else:
        return 0
    # Bound each report to guard against runaway DB growth on shared hosting.
    count=0
    for report, rows in buckets.items():
        for row in rows[:2500]:
            if not isinstance(row,dict):continue
            if source=='ga4':
                dims={k:v for k,v in row.items() if isinstance(v,str)}
                metrics={k:v for k,v in row.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
            else:
                dims={'keys':row.get('keys') or []}
                metrics={k:row[k] for k in ('clicks','impressions','ctr','position') if isinstance(row.get(k),(int,float))}
            if not metrics:continue
            pstart=pend=start
            if report in ('daily','daily_channels','daily_totals'):
                raw_date=dims.get('date') or (dims.get('keys') or [None])[0]
                raw_date=str(raw_date or '')
                if len(raw_date)==8 and raw_date.isdigit(): raw_date=raw_date[:4]+'-'+raw_date[4:6]+'-'+raw_date[6:]
                if len(raw_date)!=10 or raw_date[4]!='-': continue
                pstart=pend=raw_date
            else: pstart,pend=start,end
            dj=_json(dims); key=hashlib.sha256(dj.encode('utf-8')).hexdigest()
            params=(project_id,source,report,pstart,pend,key,dj,_json(metrics),ts)
            if backend=='mysql':
                conn.execute('''INSERT INTO analytics_observations(project_id,source,report_type,period_start,period_end,dimension_key,dimensions_json,metrics_json,captured_at)
                  VALUES(?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE metrics_json=VALUES(metrics_json),captured_at=VALUES(captured_at)''',params)
            else:
                conn.execute('''INSERT INTO analytics_observations(project_id,source,report_type,period_start,period_end,dimension_key,dimensions_json,metrics_json,captured_at)
                  VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id,source,report_type,period_start,period_end,dimension_key)
                  DO UPDATE SET metrics_json=excluded.metrics_json,captured_at=excluded.captured_at''',params)
            count+=1
    conn.execute('INSERT INTO analytics_sync_runs(project_id,source,status,period_start,period_end,row_count,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)',
                 (project_id,source,'completed',start,end,count,ts,ts))
    return count


def dashboard_rows(conn,project_id):
    """Only aggregated, non-personal read-only metadata for the managerial dashboard."""
    result={}
    for r in conn.execute('SELECT source,status,period_start,period_end,row_count,finished_at FROM analytics_sync_runs WHERE project_id=? ORDER BY id DESC LIMIT 100',(project_id,)).fetchall():
        if r['source'] not in result:result[r['source']]=dict(r)
    return result


def outcomes_summary(conn,project_id,start=None,end=None):
    """Treat absent integration as unknown, never as zero sales."""
    sql='SELECT outcome_type,status,test_record,amount,currency FROM analytics_business_outcomes WHERE project_id=?'
    params=[project_id]
    if start:sql+=' AND occurred_at>=?';params.append(start)
    if end:sql+=' AND occurred_at<?';params.append(end+'T23:59:59')
    rows=conn.execute(sql,params).fetchall()
    if not rows:return {'available':False,'orders':None,'leads':None,'revenue':None}
    actual=[r for r in rows if r['test_record']==0]
    orders=[r for r in actual if r['outcome_type']=='order' and r['status'] not in ('cancelled','failed','refunded','trash')]
    leads=[r for r in actual if r['outcome_type']=='lead' and r['status'] not in ('spam','cancelled','invalid')]
    return {'available':True,'orders':len(orders),'leads':len(leads),
            'revenue':sum(float(r['amount'] or 0) for r in orders) if orders else 0,
            'currency':orders[0]['currency'] if orders else None,
            'unclassified_test_rows':sum(1 for r in rows if r['test_record'] is None)}


def record_merchant_organic(conn, project_id, report, backend, captured_at=None):
    """Persist Merchant organic performance only (not paid media or attributed sales)."""
    ts=captured_at or datetime.now().isoformat(timespec='seconds')
    start,end=report.get('period_start'),report.get('period_end')
    if not start or not end:return 0
    dims={'marketing_method':'ORGANIC'}
    metrics={key:report[key] for key in ('clicks','impressions','ctr_percent')
             if isinstance(report.get(key),(int,float))}
    djson=_json(dims)
    natural=hashlib.sha256(djson.encode('utf-8')).hexdigest()
    params=(project_id,'merchant_center','organic_products',start,end,natural,djson,_json(metrics),ts)
    if backend=='mysql':
        conn.execute('''INSERT INTO analytics_observations(project_id,source,report_type,period_start,period_end,dimension_key,dimensions_json,metrics_json,captured_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE metrics_json=VALUES(metrics_json),captured_at=VALUES(captured_at)''',params)
    else:
        conn.execute('''INSERT INTO analytics_observations(project_id,source,report_type,period_start,period_end,dimension_key,dimensions_json,metrics_json,captured_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id,source,report_type,period_start,period_end,dimension_key)
            DO UPDATE SET metrics_json=excluded.metrics_json,captured_at=excluded.captured_at''',params)
    conn.execute('INSERT INTO analytics_sync_runs(project_id,source,status,period_start,period_end,row_count,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)',
                 (project_id,'merchant_center','completed',start,end,1,ts,ts))
    return 1
