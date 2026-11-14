import os
import json
import sqlite3
import pymysql
from pymysql.cursors import DictCursor
import hashlib
import hmac
import platform
import sys
import base64
import ipaddress
import socket
import re
import secrets
import time
import subprocess
import uuid
import smtplib
import ssl
from email.message import EmailMessage
from functools import wraps
from datetime import datetime, timedelta, date
from pathlib import Path
from urllib.parse import urlparse, urlencode, quote, unquote

import requests
import merchant_export
import heureka_export
import zbozi_export
import meta_export
import meta_graph
import zbozi_categories
import zbozi_fenix
import merchant_connector
import merchant_registration
import feed_workflow
import commerce_analytics
import business_dashboard
import advisor_intelligence
import worker_runtime
import sync_schedule
import contextlib
import fcntl
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import fresh_key_client as fresh_key

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "webbooster.db")
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
DB_BACKEND = "mysql" if DATABASE_URL.startswith(("mysql://", "mysql+pymysql://", "mariadb://")) else "sqlite"
APP_VERSION = "0.9.13.24"
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8"))
COMMERCE_PAGE_SIZE = max(10, min(50, int(os.getenv("COMMERCE_PAGE_SIZE", "25"))))
COMMERCE_BATCH_PAGES = max(1, min(3, int(os.getenv("COMMERCE_BATCH_PAGES", "2"))))
COMMERCE_BATCH_SECONDS = max(4.0, min(20.0, float(os.getenv("COMMERCE_BATCH_SECONDS", "9"))))
CATALOG_FEED_DIR = Path(os.getenv("CATALOG_FEED_DIR", str(BASE_DIR / "generated_feeds"))).resolve()
CATALOG_MAX_EXPORT_ROWS = max(100, min(50000, int(os.getenv("CATALOG_MAX_EXPORT_ROWS", "10000"))))
CRAWL_LIMIT = max(1, min(100, int(os.getenv("CRAWL_LIMIT", "25"))))
AI_BATCH_LIMIT = max(1, min(50, int(os.getenv("AI_BATCH_LIMIT", "20"))))
GSC_QUERY_LIMIT = max(100, min(2000, int(os.getenv("GSC_QUERY_LIMIT", "750"))))
GSC_QUERY_PAGE_LIMIT = max(250, min(5000, int(os.getenv("GSC_QUERY_PAGE_LIMIT", "1500"))))
SOURCE_SNAPSHOT_KEEP = max(14, min(365, int(os.getenv("SOURCE_SNAPSHOT_KEEP", "90"))))
PAGESPEED_API_KEY = (os.getenv("PAGESPEED_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
CORE_WRITE_TIMEOUT = max(8, min(60, int(os.getenv("CORE_WRITE_TIMEOUT", "18"))))
WORKER_STALE_SECONDS = max(60, int(os.getenv("WORKER_STALE_SECONDS", "180")))
WORKER_POLL_SECONDS = max(5, int(os.getenv("WORKER_POLL_SECONDS", "10")))
USER_AGENT = os.getenv(
    "WEBBOOSTER_USER_AGENT",
    "Fresh-Web-Booster/0.8.5 (+https://webbooster.freshcrackers.cz)"
)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-change-me")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Nejdřív se prosím přihlas."


class User(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.email = row["email"]
        self.name = row["name"]
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        self.role = str(row["system_role"] or "visitor") if "system_role" in keys else "visitor"
        self.account_status = str(row["account_status"] or "active") if "account_status" in keys else "active"
        self.paid_access_status = str(row["paid_access_status"] or "none") if "paid_access_status" in keys else "none"

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_active(self):
        return self.account_status == "active"

    @property
    def can_edit(self):
        if self.account_status != "active":
            return False
        return self.role == "admin" or (self.role == "editor" and self.paid_access_status in {"active", "manual"})

    @property
    def is_visitor(self):
        return self.role == "visitor"


def _mysql_config():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL není nastavená.")
    parsed = urlparse(DATABASE_URL.replace("mysql+pymysql://", "mysql://", 1).replace("mariadb://", "mysql://", 1))
    if not parsed.hostname or not parsed.path.strip("/"):
        raise RuntimeError("DATABASE_URL musí obsahovat server a název databáze.")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
    }


class MySQLCompatConnection:
    def __init__(self):
        self._conn = pymysql.connect(**_mysql_config())

    @staticmethod
    def _sql(sql):
        # PyMySQL uses Python %-formatting for bound parameters.
        # Escape literal percent signs first, then translate SQLite-style
        # qmark placeholders to PyMySQL %s placeholders. This keeps queries
        # such as LIKE 'seo_%' from being interpreted as format strings.
        return sql.replace("%", "%%").replace("?", "%s")

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        # Do not invoke PyMySQL's interpolation machinery for statements
        # without parameters. For parameterized statements use the safe
        # qmark compatibility conversion above.
        if params:
            cur.execute(self._sql(sql), params)
        else:
            cur.execute(sql)
        return cur

    def executescript(self, script):
        for statement in [x.strip() for x in script.split(";") if x.strip()]:
            self.execute(statement)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def db():
    if DB_BACKEND == "mysql":
        return MySQLCompatConnection()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now():
    return datetime.now().isoformat(timespec="seconds")


def ensure_chat_threads():
    """Safe additive table: chat titles and message boundaries; no changes to existing messages."""
    conn = db()
    if DB_BACKEND == "mysql":
        conn.execute("""CREATE TABLE IF NOT EXISTS chat_threads (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            title VARCHAR(180) NOT NULL,
            start_message_id BIGINT UNSIGNED NOT NULL DEFAULT 1,
            end_message_id BIGINT UNSIGNED NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_chat_threads_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS chat_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL, title TEXT NOT NULL,
            start_message_id INTEGER NOT NULL DEFAULT 1,
            end_message_id INTEGER, created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_threads_project ON chat_threads(project_id,id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS assistant_settings (
      setting_key VARCHAR(80) PRIMARY KEY,
      setting_value TEXT NOT NULL
    )""")
    conn.commit(); conn.close()


def ensure_marketing_knowledge():
    """Additive global/project library; existing static articles stay intact."""
    conn=db()
    if DB_BACKEND == "mysql":
        conn.execute("""CREATE TABLE IF NOT EXISTS marketing_knowledge (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          project_id BIGINT UNSIGNED NULL,
          category VARCHAR(100) NOT NULL,
          title VARCHAR(220) NOT NULL,
          summary TEXT NOT NULL,
          content TEXT NOT NULL,
          source_url TEXT NULL,
          created_by BIGINT UNSIGNED NULL,
          created_at VARCHAR(32) NOT NULL,
          updated_at VARCHAR(32) NOT NULL,
          INDEX idx_knowledge_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_read (
          project_id BIGINT UNSIGNED PRIMARY KEY,
          read_key_enc TEXT NOT NULL,
          checked_at VARCHAR(32) NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS marketing_knowledge (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
          category TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
          content TEXT NOT NULL, source_url TEXT, created_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_project ON marketing_knowledge(project_id,id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_read (
          project_id INTEGER PRIMARY KEY, read_key_enc TEXT NOT NULL, checked_at TEXT)""")
    if DB_BACKEND == "mysql":
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_products (
          project_id BIGINT UNSIGNED NOT NULL, product_id BIGINT UNSIGNED NOT NULL,
          payload_json LONGTEXT NOT NULL, synced_at VARCHAR(32) NOT NULL,
          PRIMARY KEY (project_id,product_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_sync (
          project_id BIGINT UNSIGNED PRIMARY KEY, next_page INT NOT NULL DEFAULT 1,
          total INT NOT NULL DEFAULT 0, synced_count INT NOT NULL DEFAULT 0,
          sync_started_at VARCHAR(32) NULL, last_error TEXT NULL,
          finished_at VARCHAR(32) NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_products (
          project_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
          payload_json TEXT NOT NULL, synced_at TEXT NOT NULL,
          PRIMARY KEY (project_id,product_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_sync (
          project_id INTEGER PRIMARY KEY, next_page INTEGER NOT NULL DEFAULT 1,
          total INTEGER NOT NULL DEFAULT 0, synced_count INTEGER NOT NULL DEFAULT 0,
          sync_started_at TEXT, last_error TEXT, finished_at TEXT)""")
    if DB_BACKEND == "mysql":
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_variants (
            project_id BIGINT UNSIGNED NOT NULL, variation_id BIGINT UNSIGNED NOT NULL,
            payload_json LONGTEXT NOT NULL, synced_at VARCHAR(32) NOT NULL,
            PRIMARY KEY(project_id,variation_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_variant_sync (
            project_id BIGINT UNSIGNED PRIMARY KEY, next_page INT NOT NULL DEFAULT 1,
            total INT NOT NULL DEFAULT 0, synced_count INT NOT NULL DEFAULT 0,
            last_error TEXT NULL, finished_at VARCHAR(32) NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_google_feeds (
            project_id BIGINT UNSIGNED PRIMARY KEY, feed_token VARCHAR(100) NOT NULL UNIQUE,
            generated_at VARCHAR(32) NULL, exported_count INT NOT NULL DEFAULT 0,
            omitted_count INT NOT NULL DEFAULT 0, report_json LONGTEXT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_variants (
            project_id INTEGER NOT NULL,variation_id INTEGER NOT NULL,payload_json TEXT NOT NULL,
            synced_at TEXT NOT NULL,PRIMARY KEY(project_id,variation_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_core_variant_sync (
            project_id INTEGER PRIMARY KEY,next_page INTEGER NOT NULL DEFAULT 1,
            total INTEGER NOT NULL DEFAULT 0,synced_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,finished_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_google_feeds (
            project_id INTEGER PRIMARY KEY,feed_token TEXT NOT NULL UNIQUE,
            generated_at TEXT,exported_count INTEGER NOT NULL DEFAULT 0,
            omitted_count INTEGER NOT NULL DEFAULT 0,report_json TEXT)""")
    conn.commit();conn.close()


def library_rows(project_id=None, q='', limit=120):
    conn=db()
    criteria="(project_id IS NULL OR project_id=?)" if project_id is not None else "project_id IS NULL"
    params=[project_id] if project_id is not None else []
    if q:
        criteria+=" AND (LOWER(title) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(content) LIKE ? OR LOWER(category) LIKE ?)"
        params.extend(['%'+q.lower()+'%']*4)
    rows=conn.execute("SELECT * FROM marketing_knowledge WHERE "+criteria+" ORDER BY updated_at DESC,id DESC LIMIT ?", tuple(params+[limit])).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def knowledge_context_for_chat(project_id, text, limit=4):
    """Deterministic keyword retrieval, short citations, no fabricated sources."""
    entries=[]
    for slug, a in SEO_KNOWLEDGE.items():
        entries.append({'title':a['title'], 'summary':a['summary'], 'body':' '.join(t for _,t in a.get('sections',[])),
                        'url':url_for('knowledge_article',project_id=project_id,slug=slug), 'scope':'vestavěná'})
    for a in library_rows(project_id,limit=250):
        entries.append({'title':a['title'], 'summary':a['summary'], 'body':a['content'][:3000],
                        'url':url_for('knowledge_article',project_id=project_id,slug='db-'+str(a['id'])),
                        'scope':'projekt' if a['project_id'] else 'sdílená'})
    terms=set(re.findall(r'[^\W_]{4,}',(text or '').lower(),re.UNICODE))
    scored=[]
    for item in entries:
        title=item['title'].lower(); summary=item['summary'].lower(); body=item['body'].lower()
        score=sum(6 if term in title else 3 if term in summary else 1 if term in body else 0 for term in terms)
        if score:scored.append((score,item))
    scored.sort(key=lambda item:item[0],reverse=True)
    return [{'title':a['title'],'summary':a['summary'][:500],'excerpt':a['body'][:900],
             'url':a['url'],'scope':a['scope']} for _,a in scored[:limit]]


def core_catalog_read(project, key, page=1, per_page=100):
    """Fetch a validated, bounded page via existing Fresh Core access credential."""
    page=max(1,int(page)); per_page=max(1,min(100,int(per_page)))
    base=safe_http_url((project['site_url'] or '').rstrip('/')+'/wp-json/fresh-core/v1/commerce/catalog')
    result=requests.get(base,params={'page':page,'per_page':per_page},
             headers={'X-Fresh-Core-Key':key,'Accept':'application/json','User-Agent':USER_AGENT},
             timeout=(5,HTTP_TIMEOUT),allow_redirects=False)
    if result.status_code in (401,403):
        raise ValueError('Čtecí oprávnění Fresh Core není platné nebo REST přístup blokuje ochrana webu (HTTP '+str(result.status_code)+').')
    if result.status_code != 200:
        raise ValueError('Fresh Core katalog odpověděl HTTP '+str(result.status_code))
    try: payload=result.json()
    except ValueError: raise ValueError('Fresh Core vrátil neplatný JSON.')
    data=payload.get('data',payload) if isinstance(payload,dict) else {}
    if not isinstance(data,dict) or not isinstance(data.get('items'),list) or not isinstance(data.get('available'),bool):
        raise ValueError('Neočekávaný formát katalogových dat.')
    if data.get('ok') is False:
        raise ValueError('Fresh Core oznámil chybu katalogu.')
    if data['available'] is False:
        raise ValueError('WooCommerce není dostupný nebo není aktivní.')
    if int(data.get('page',page))!=page: raise ValueError('Neshoda stránkování katalogu.')
    if len(data['items'])>per_page: raise ValueError('Katalog překročil požadovanou velikost stránky.')
    return data


def core_catalog_summary(project_id):
    conn=db()
    rec=conn.execute('SELECT checked_at FROM project_core_read WHERE project_id=?',(project_id,)).fetchone()
    sync=conn.execute('SELECT * FROM project_core_sync WHERE project_id=?',(project_id,)).fetchone()
    stored=conn.execute('SELECT COUNT(*) AS n FROM project_core_products WHERE project_id=?',(project_id,)).fetchone()
    conn.close()
    out={'authorized':bool(rec),'connected':bool(rec),'checked_at':rec['checked_at'] if rec else None,
         'cached_products':int(stored['n']) if stored else 0}
    if sync:
        out.update({k:sync[k] for k in ('next_page','total','synced_count','sync_started_at','last_error','finished_at')})
    return out


def normalize_core_product(item):
    """Canonical source-preserving product model; no invented GTIN or variant SKUs."""
    if not isinstance(item,dict): raise ValueError('Produkt není objekt.')
    ident=int(item.get('product_id') or 0)
    if ident<=0:raise ValueError('Produkt bez platného ID.')
    attrs=item.get('attributes') if isinstance(item.get('attributes'),list) else []
    images=[u for u in [item.get('image'),*(item.get('gallery') or [])] if isinstance(u,str) and u.startswith(('https://','http://'))]
    return {'id':ident,'type':str(item.get('type') or ''),'sku':str(item.get('sku') or ''),
            'title':str(item.get('title') or ''),'url':str(item.get('url') or ''),
            'description':str(item.get('description') or item.get('excerpt') or ''), 'price':str(item.get('price') or ''),
            'currency':str(item.get('currency') or ''),'stock_status':str(item.get('stock_status') or ''),
            'images':list(dict.fromkeys(images)), 'categories':item.get('categories') or [],
            'attributes':attrs,'modified':item.get('modified'),
            'source_has_variants':item.get('type')=='variable',
            'variant_details_available':False,'gtin':(item.get('identifiers') or {}).get('gtin'),'brand':(item.get('identifiers') or {}).get('brand'),
            'purchasable':item.get('purchasable'),
            'raw':item}


def core_catalog_batch(project_id, project, key, reset=False, pages=3):
    """Bounded batch sync. Resume next page explicitly to avoid giant request timeouts.
    On reset, cached products are removed only after the first page succeeds.
    """
    conn=db(); state=conn.execute('SELECT next_page FROM project_core_sync WHERE project_id=?',(project_id,)).fetchone();conn.close()
    first_page=1 if reset or not state else int(state['next_page'])
    if first_page<1:return {'complete':True,'processed':0}
    processed=0; total=0; next_page=first_page; started=time.monotonic()
    for page in range(first_page,first_page+max(1,min(int(pages),COMMERCE_BATCH_PAGES))):
        if page > first_page and time.monotonic()-started>=COMMERCE_BATCH_SECONDS: break
        data=core_catalog_read(project,key,page=page,per_page=COMMERCE_PAGE_SIZE)
        total=max(0,int(data.get('total',0)))
        normalized=[normalize_core_product(i) for i in data['items']]
        conn=db()
        try:
            if reset and page==1:
                conn.execute('DELETE FROM project_core_products WHERE project_id=?',(project_id,))
            for item in normalized:
                encoded=json.dumps(item,ensure_ascii=False)
                if DB_BACKEND=='mysql':
                    conn.execute('INSERT INTO project_core_products(project_id,product_id,payload_json,synced_at) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json),synced_at=VALUES(synced_at)',(project_id,item['id'],encoded,now()))
                else:
                    conn.execute('INSERT OR REPLACE INTO project_core_products(project_id,product_id,payload_json,synced_at) VALUES(?,?,?,?)',(project_id,item['id'],encoded,now()))
            processed+=len(normalized)
            has_more=bool(data.get('has_more',page<int(data.get('total_pages',0))))
            next_page=page+1 if has_more else 0
            new_count=conn.execute('SELECT COUNT(*) AS n FROM project_core_products WHERE project_id=?',(project_id,)).fetchone()['n']
            if DB_BACKEND=='mysql':
                conn.execute('INSERT INTO project_core_sync(project_id,next_page,total,synced_count,sync_started_at,last_error,finished_at) VALUES(?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE next_page=VALUES(next_page),total=VALUES(total),synced_count=VALUES(synced_count),last_error=VALUES(last_error),finished_at=VALUES(finished_at)',(project_id,next_page,total,new_count,now(),None,now() if not has_more else None))
            else:
                conn.execute('INSERT OR REPLACE INTO project_core_sync(project_id,next_page,total,synced_count,sync_started_at,last_error,finished_at) VALUES(?,?,?,?,?,?,?)',(project_id,next_page,total,new_count,now(),None,now() if not has_more else None))
            conn.execute('UPDATE project_core_read SET checked_at=? WHERE project_id=?',(now(),project_id))
            conn.commit()
        finally:conn.close()
        if not has_more:break
    return {'complete':next_page==0,'processed':processed,'total':total,'next_page':next_page}


def communication_settings():
    defaults = {"tone":"friendly", "address":"informal", "instructions":"Piš česky, přátelsky a srozumitelně. Buď odborný, ale nevystavuj odbornost na odiv. Vysvětluj trpělivě, nelži o provedené práci a respektuj schvalování změn."}
    conn=db()
    for row in conn.execute("SELECT setting_key,setting_value FROM assistant_settings WHERE setting_key IN ('tone','address','instructions')").fetchall():
        defaults[row['setting_key']]=row['setting_value']
    conn.close()
    return defaults


# Smart Workspace: curated, server-rendered card types. No arbitrary HTML generated by AI.
SMART_CARD_REGISTRY = {
    "goal": {"title": "Obchodní cíl", "topics": ["goal", "sales", "general"]},
    "performance": {"title": "Výkon a návštěvnost", "topics": ["seo", "sales", "general"]},
    "tasks": {"title": "Úkoly a schvalování", "topics": ["tasks", "general"]},
    "integrations": {"title": "Připojení a měření", "topics": ["catalog", "sales", "general"]},
    "catalog": {"title": "Produktové katalogy", "topics": ["catalog"]},
    "seo": {"title": "SEO diagnostika", "topics": ["seo"]},
    "plan": {"title": "Dnešní plán", "topics": ["tasks", "general"]},
}
SMART_CARD_DEFAULT = ["goal", "performance", "tasks", "integrations", "seo", "catalog", "plan"]
SMART_NAV = ("goals", "seo", "tasks", "results", "connectors")


def smart_card_settings():
    conn=db()
    row=conn.execute("SELECT setting_value FROM assistant_settings WHERE setting_key=?", ("smart_cards",)).fetchone()
    conn.close()
    try:
        parsed=json.loads(row["setting_value"]) if row else SMART_CARD_DEFAULT
    except (ValueError, TypeError, KeyError):
        parsed=SMART_CARD_DEFAULT
    return [x for x in parsed if isinstance(x,str) and x in SMART_CARD_REGISTRY] or SMART_CARD_DEFAULT


def smart_topic(text):
    text=(text or "").lower()
    patterns={
      "catalog": ("katalog", "merchant", "heurek", "zboží.cz", "zbozi.cz", "feed", "produkty do google", "shopping", "meta catalog"),
      "sales": ("prodej", "objednáv", "objednav", "konver", "tržb", "trzb", "checkout", "nákup", "nakup", "zákazník", "zakaznik"),
      "seo": ("seo", "indexac", "vyhledáv", "vyhledav", "title", "meta description", "search console", "pozic", "alt text"),
      "tasks": ("úkol", "ukol", "front", "schvál", "schval", "proved", "hotov", "plán", "plan", "pracuj"),
      "goal": ("cíl", "cil", "strateg", "priorit"),
    }
    for topic,words in patterns.items():
        if any(x in text for x in words): return topic
    return "general"


def smart_cards_for(topic):
    enabled=smart_card_settings()
    relevant=[k for k in enabled if topic in SMART_CARD_REGISTRY[k]["topics"]]
    return (relevant+[k for k in enabled if k not in relevant])[:5]


def smart_selected_cards(topic, requested=None):
    # The model may select existing cards only. No arbitrary HTML, URLs or card definitions.
    allowed=smart_card_settings()
    chosen=[key for key in (requested or []) if isinstance(key,str) and key in allowed]
    chosen=list(dict.fromkeys(chosen))
    return (chosen+[key for key in smart_cards_for(topic) if key not in chosen])[:5]


def smart_workspace_context(project_id, project=None, topic="general", cards_override=None):
    project=project or project_for_user(project_id)
    gsc=latest_source_snapshot(project_id,"search_console")
    ga4=latest_source_snapshot(project_id,"ga4")
    progress=project_progress_summary(project_id,gsc,ga4)
    return {"smart_cards":smart_selected_cards(topic,cards_override), "smart_topic":topic,
            "smart_strategy":project_strategy(project), "smart_progress":progress,
            "smart_scorecard":seo_scorecard(project_id), "smart_advisor":advisor_state(project_id),
            "smart_queue":queue_summary(project_id), "smart_gsc":gsc, "smart_ga4":ga4,
            "smart_project":project, "smart_core_connected":project["core_write_status"]=="connected"}


def smart_workspace_html(project_id, topic, cards_override=None):
    context=smart_workspace_context(project_id,topic=topic,cards_override=cards_override)
    return render_template("partials/smart_cards.html", **context)


def chat_thread_list(project_id):
    conn = db()
    threads = conn.execute("SELECT * FROM chat_threads WHERE project_id=? ORDER BY id DESC LIMIT 80", (project_id,)).fetchall()
    if not threads:
        p = conn.execute("SELECT chat_cutoff FROM projects WHERE id=?", (project_id,)).fetchone()
        cutoff = p["chat_cutoff"] if p else None
        if cutoff:
            first = conn.execute("SELECT MIN(id) AS first_id FROM messages WHERE project_id=? AND created_at>=?", (project_id, cutoff)).fetchone()
        else:
            first = conn.execute("SELECT MIN(id) AS first_id FROM messages WHERE project_id=?", (project_id,)).fetchone()
        start = first["first_id"] if first and first["first_id"] is not None else 1
        conn.execute("INSERT INTO chat_threads(project_id,title,start_message_id,created_at) VALUES(?,?,?,?)",(project_id,"Hlavní konverzace",start,now()))
        conn.commit()
        threads = conn.execute("SELECT * FROM chat_threads WHERE project_id=? ORDER BY id DESC LIMIT 80",(project_id,)).fetchall()
    conn.close()
    return [dict(row) for row in threads]


def iso_is_future(value):
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value)) > datetime.now()
    except Exception:
        return False


def _table_columns(conn, table):
    if DB_BACKEND == "mysql":
        safe = re.sub(r"[^a-zA-Z0-9_]", "", table)
        return {r["Field"] for r in conn.execute(f"SHOW COLUMNS FROM `{safe}`").fetchall()}
    return {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _ensure_column(conn, table, definition):
    name = definition.split()[0].strip('`"')
    if name not in _table_columns(conn, table):
        safe = re.sub(r"[^a-zA-Z0-9_]", "", table)
        if DB_BACKEND == "mysql":
            # SQLite-oriented definitions used by old migrations are valid enough after these adaptations.
            definition = definition.replace(" INTEGER", " BIGINT").replace(" REAL", " DOUBLE")
            conn.execute(f"ALTER TABLE `{safe}` ADD COLUMN {definition}")
        else:
            conn.execute(f'ALTER TABLE "{safe}" ADD COLUMN {definition}')


def _mysql_schema_statements():
    return [
        """CREATE TABLE IF NOT EXISTS users (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at VARCHAR(32) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS projects (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT UNSIGNED NOT NULL,
            name VARCHAR(255) NOT NULL,
            site_url TEXT NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'waiting',
            health_score INT NOT NULL DEFAULT 0,
            created_at VARCHAR(32) NOT NULL,
            updated_at VARCHAR(32) NOT NULL,
            last_snapshot LONGTEXT NULL,
            core_manifest_url TEXT NULL,
            core_site_url TEXT NULL,
            core_version VARCHAR(50) NULL,
            core_last_sync VARCHAR(32) NULL,
            core_manifest_json LONGTEXT NULL,
            core_snapshot_json LONGTEXT NULL,
            core_write_endpoint TEXT NULL,
            core_write_key_enc LONGTEXT NULL,
            core_write_status VARCHAR(40) DEFAULT 'disconnected',
            seo_url_count INT DEFAULT 0,
            open_issue_count INT DEFAULT 0,
            chat_cutoff VARCHAR(32) NULL,
            INDEX idx_projects_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS messages (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            user_id BIGINT UNSIGNED NOT NULL,
            role VARCHAR(40) NOT NULL,
            body LONGTEXT NOT NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_messages_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS activities (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            kind VARCHAR(60) NOT NULL,
            title VARCHAR(255) NOT NULL,
            detail LONGTEXT NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_activities_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS snapshots (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            payload LONGTEXT NOT NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_snapshots_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS integrations (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            provider VARCHAR(80) NOT NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'seo',
            status VARCHAR(40) NOT NULL DEFAULT 'disconnected',
            config_json LONGTEXT NULL,
            last_sync VARCHAR(32) NULL,
            created_at VARCHAR(32) NOT NULL,
            updated_at VARCHAR(32) NOT NULL,
            secret_enc LONGTEXT NULL,
            scope TEXT NULL,
            account_label VARCHAR(255) NULL,
            UNIQUE KEY uq_integrations_project_provider (project_id,provider)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS audits (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            source VARCHAR(80) NOT NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'seo',
            status VARCHAR(40) NOT NULL,
            score INT NULL,
            summary_json LONGTEXT NULL,
            started_at VARCHAR(32) NOT NULL,
            finished_at VARCHAR(32) NULL,
            INDEX idx_audits_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS issues (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            audit_id BIGINT UNSIGNED NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'seo',
            source VARCHAR(80) NOT NULL DEFAULT 'audit',
            category VARCHAR(60) NOT NULL,
            severity VARCHAR(40) NOT NULL,
            code VARCHAR(120) NOT NULL,
            title VARCHAR(255) NOT NULL,
            detail LONGTEXT NULL,
            target_url TEXT NULL,
            entity_id VARCHAR(100) NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'open',
            first_seen VARCHAR(32) NOT NULL,
            last_seen VARCHAR(32) NOT NULL,
            kind VARCHAR(40) NOT NULL DEFAULT 'warning',
            fingerprint VARCHAR(64) NULL,
            snoozed_until VARCHAR(32) NULL,
            decision_note LONGTEXT NULL,
            decision_at VARCHAR(32) NULL,
            decision_by BIGINT UNSIGNED NULL,
            context_json LONGTEXT NULL,
            resolved_by_action_id BIGINT UNSIGNED NULL,
            recheck_after VARCHAR(32) NULL,
            INDEX idx_issues_project_status (project_id,status),
            INDEX idx_issues_project_code (project_id,code),
            UNIQUE KEY uq_issues_fingerprint (project_id,source,fingerprint)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS actions (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'seo',
            action_type VARCHAR(80) NOT NULL,
            target_type VARCHAR(80) NULL,
            target_id VARCHAR(100) NULL,
            target_url TEXT NULL,
            reason LONGTEXT NULL,
            before_json LONGTEXT NULL,
            proposed_json LONGTEXT NULL,
            result_json LONGTEXT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'draft',
            expected_metric VARCHAR(100) NULL,
            measurement_window_days INT NOT NULL DEFAULT 28,
            created_at VARCHAR(32) NOT NULL,
            approved_at VARCHAR(32) NULL,
            applied_at VARCHAR(32) NULL,
            measured_at VARCHAR(32) NULL,
            baseline_metrics_json LONGTEXT NULL,
            impact_json LONGTEXT NULL,
            expected_outcome LONGTEXT NULL,
            verification_json LONGTEXT NULL,
            verified_at VARCHAR(32) NULL,
            completed_at VARCHAR(32) NULL,
            issue_id BIGINT UNSIGNED NULL,
            ai_proposal_json LONGTEXT NULL,
            user_edited_at VARCHAR(32) NULL,
            snoozed_until VARCHAR(32) NULL,
            dismissed_at VARCHAR(32) NULL,
            INDEX idx_actions_project_status (project_id,status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS action_revisions (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            action_id BIGINT UNSIGNED NOT NULL,
            project_id BIGINT UNSIGNED NOT NULL,
            author_type VARCHAR(40) NOT NULL,
            values_json LONGTEXT NOT NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_action_revisions_action (action_id,id),
            INDEX idx_action_revisions_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS metric_points (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            action_id BIGINT UNSIGNED NULL,
            channel VARCHAR(40) NOT NULL,
            source VARCHAR(80) NOT NULL,
            metric VARCHAR(100) NOT NULL,
            dimension TEXT NULL,
            value DOUBLE NULL,
            captured_at VARCHAR(32) NOT NULL,
            INDEX idx_metric_project (project_id,captured_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS source_snapshots (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            provider VARCHAR(80) NOT NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'seo',
            period_start VARCHAR(32) NULL,
            period_end VARCHAR(32) NULL,
            payload LONGTEXT NOT NULL,
            captured_at VARCHAR(32) NOT NULL,
            INDEX idx_snapshots_project_provider (project_id,provider,captured_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS engine_runs (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NULL,
            task_type VARCHAR(160) NOT NULL,
            status VARCHAR(40) NOT NULL,
            http_status INT NULL,
            run_id VARCHAR(255) NULL,
            provider VARCHAR(100) NULL,
            model VARCHAR(160) NULL,
            latency_ms INT NULL,
            cost_usd DOUBLE NULL,
            error_text LONGTEXT NULL,
            response_meta_json LONGTEXT NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_engine_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS jobs (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NULL,
            user_id BIGINT UNSIGNED NULL,
            action_id BIGINT UNSIGNED NULL,
            group_id VARCHAR(64) NULL,
            job_type VARCHAR(100) NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'queued',
            attempts INT NOT NULL DEFAULT 0,
            max_attempts INT NOT NULL DEFAULT 3,
            payload_json LONGTEXT NULL,
            result_json LONGTEXT NULL,
            run_after VARCHAR(32) NULL,
            locked_at VARCHAR(32) NULL,
            started_at VARCHAR(32) NULL,
            finished_at VARCHAR(32) NULL,
            updated_at VARCHAR(32) NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_jobs_status (status,run_after),
            INDEX idx_jobs_group (group_id),
            INDEX idx_jobs_action (action_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT UNSIGNED NOT NULL,
            project_id BIGINT UNSIGNED NULL,
            level VARCHAR(30) NOT NULL DEFAULT 'info',
            kind VARCHAR(60) NOT NULL DEFAULT 'system',
            title VARCHAR(255) NOT NULL,
            body LONGTEXT NULL,
            url TEXT NULL,
            is_read TINYINT(1) NOT NULL DEFAULT 0,
            snoozed_until VARCHAR(32) NULL,
            dismissed_at VARCHAR(32) NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_notifications_user (user_id,is_read,id),
            INDEX idx_notifications_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS workers (
            name VARCHAR(80) NOT NULL PRIMARY KEY,
            status VARCHAR(40) NOT NULL DEFAULT 'idle',
            last_seen VARCHAR(32) NULL,
            detail_json LONGTEXT NULL,
            updated_at VARCHAR(32) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS project_members (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            user_id BIGINT UNSIGNED NOT NULL,
            role VARCHAR(40) NOT NULL DEFAULT 'editor',
            relationship VARCHAR(24) NOT NULL DEFAULT 'member',
            status VARCHAR(40) NOT NULL DEFAULT 'active',
            invited_by BIGINT UNSIGNED NULL,
            created_at VARCHAR(32) NOT NULL,
            updated_at VARCHAR(32) NOT NULL,
            UNIQUE KEY uq_project_members (project_id,user_id),
            INDEX idx_project_members_user (user_id,status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS project_invitations (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            email VARCHAR(255) NOT NULL,
            role VARCHAR(40) NOT NULL DEFAULT 'editor',
            relationship VARCHAR(24) NOT NULL DEFAULT 'member',
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            invited_by BIGINT UNSIGNED NULL,
            created_at VARCHAR(32) NOT NULL,
            updated_at VARCHAR(32) NOT NULL,
            UNIQUE KEY uq_project_invitations (project_id,email),
            INDEX idx_project_invitations_email (email,status),
            INDEX idx_project_invitations_project (project_id,status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS access_requests (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT UNSIGNED NOT NULL,
            requested_role VARCHAR(40) NOT NULL DEFAULT 'editor',
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            note LONGTEXT NULL,
            created_at VARCHAR(32) NOT NULL,
            decided_at VARCHAR(32) NULL,
            decided_by BIGINT UNSIGNED NULL,
            INDEX idx_access_requests_status (status,id),
            INDEX idx_access_requests_user (user_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS automation_rules (
            rule_key VARCHAR(80) NOT NULL PRIMARY KEY,
            name VARCHAR(190) NOT NULL,
            description LONGTEXT NULL,
            enabled TINYINT(1) NOT NULL DEFAULT 1,
            interval_hours INT NOT NULL DEFAULT 24,
            config_json LONGTEXT NULL,
            updated_at VARCHAR(32) NOT NULL,
            updated_by BIGINT UNSIGNED NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS automation_state (
            project_id BIGINT UNSIGNED NOT NULL,
            rule_key VARCHAR(80) NOT NULL,
            last_run VARCHAR(32) NULL,
            last_status VARCHAR(40) NULL,
            last_error LONGTEXT NULL,
            updated_at VARCHAR(32) NOT NULL,
            PRIMARY KEY (project_id,rule_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS system_settings (
            setting_key VARCHAR(120) NOT NULL PRIMARY KEY,
            value_json LONGTEXT NULL,
            secret_enc LONGTEXT NULL,
            updated_at VARCHAR(32) NOT NULL,
            updated_by BIGINT UNSIGNED NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS email_outbox (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT UNSIGNED NULL,
            project_id BIGINT UNSIGNED NULL,
            to_email VARCHAR(320) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            body LONGTEXT NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'queued',
            attempts INT NOT NULL DEFAULT 0,
            last_error LONGTEXT NULL,
            created_at VARCHAR(32) NOT NULL,
            sent_at VARCHAR(32) NULL,
            INDEX idx_email_outbox_status (status,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    ]


def init_db():
    conn = db()
    if DB_BACKEND == "mysql":
        for statement in _mysql_schema_statements():
            conn.execute(statement)
        conn.execute("""CREATE TABLE IF NOT EXISTS search_performance (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            source VARCHAR(40) NOT NULL DEFAULT 'search_console',
            query_text VARCHAR(768) NULL,
            page_url TEXT NULL,
            country VARCHAR(16) NULL,
            device VARCHAR(32) NULL,
            clicks DOUBLE NOT NULL DEFAULT 0,
            impressions DOUBLE NOT NULL DEFAULT 0,
            ctr DOUBLE NOT NULL DEFAULT 0,
            position DOUBLE NOT NULL DEFAULT 0,
            period_start VARCHAR(16) NOT NULL,
            period_end VARCHAR(16) NOT NULL,
            captured_at VARCHAR(32) NOT NULL,
            INDEX idx_search_perf_project_period (project_id,period_end),
            INDEX idx_search_perf_project_query (project_id,query_text(190))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        conn.execute("""CREATE TABLE IF NOT EXISTS operator_plans (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            project_id BIGINT UNSIGNED NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'active',
            strategy_json LONGTEXT NULL,
            plan_json LONGTEXT NOT NULL,
            generated_at VARCHAR(32) NOT NULL,
            updated_at VARCHAR(32) NOT NULL,
            INDEX idx_operator_plans_project (project_id,id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        conn.commit()
        existing_user_columns = _table_columns(conn, "users")
        roles_are_new = "system_role" not in existing_user_columns
        for definition in (
            "system_role VARCHAR(40) NOT NULL DEFAULT 'visitor'",
            "account_status VARCHAR(40) NOT NULL DEFAULT 'active'",
            "paid_access_status VARCHAR(40) NOT NULL DEFAULT 'none'",
            "last_login_at VARCHAR(32)",
            "email_alerts TINYINT(1) NOT NULL DEFAULT 1"
        ):
            _ensure_column(conn, "users", definition)
        admin_email = (os.getenv("WEBBOOSTER_ADMIN_EMAIL") or "soufek@freshcrackers.cz").strip().lower()
        if roles_are_new:
            legacy_users = conn.execute("SELECT id,email FROM users").fetchall()
            for legacy_user in legacy_users:
                owns = conn.execute("SELECT id FROM projects WHERE user_id=? LIMIT 1", (legacy_user["id"],)).fetchone()
                role = "admin" if str(legacy_user["email"] or "").lower() == admin_email else ("editor" if owns else "visitor")
                paid = "active" if role in {"admin", "editor"} else "none"
                conn.execute("UPDATE users SET system_role=?,paid_access_status=? WHERE id=?", (role, paid, legacy_user["id"]))
        conn.execute("UPDATE users SET system_role='admin',paid_access_status='active',account_status='active' WHERE LOWER(email)=?", (admin_email,))
        for definition in (
            "chat_cutoff VARCHAR(32)",
            "business_goal LONGTEXT",
            "primary_conversion VARCHAR(190)",
            "priority_topics LONGTEXT",
            "brand_terms LONGTEXT",
            "boban_mode VARCHAR(40) NOT NULL DEFAULT 'specialist'",
            "boban_cadence VARCHAR(40) NOT NULL DEFAULT 'twice_weekly'",
            "last_operator_run VARCHAR(32)"
        ):
            _ensure_column(conn, "projects", definition)
        for definition in (
            "meta_json LONGTEXT",
        ):
            _ensure_column(conn, "messages", definition)
        for definition in (
            "snoozed_until VARCHAR(32)", "decision_note LONGTEXT", "decision_at VARCHAR(32)", "decision_by BIGINT", "context_json LONGTEXT",
            "resolved_by_action_id BIGINT", "recheck_after VARCHAR(32)",
        ):
            _ensure_column(conn, "issues", definition)
        for definition in (
            "snoozed_until VARCHAR(32)", "dismissed_at VARCHAR(32)",
        ):
            _ensure_column(conn, "notifications", definition)
        for definition in (
            "user_id BIGINT", "action_id BIGINT", "group_id VARCHAR(64)",
            "attempts INT NOT NULL DEFAULT 0", "max_attempts INT NOT NULL DEFAULT 3",
            "locked_at VARCHAR(32)", "updated_at VARCHAR(32)",
        ):
            _ensure_column(conn, "jobs", definition)
        for definition in (
            "job_group_id VARCHAR(64)", "last_error LONGTEXT", "issue_id BIGINT",
            "ai_proposal_json LONGTEXT", "user_edited_at VARCHAR(32)",
            "snoozed_until VARCHAR(32)", "dismissed_at VARCHAR(32)",
            "provider VARCHAR(80) NOT NULL DEFAULT 'fresh_core'", "operation VARCHAR(100)",
        ):
            _ensure_column(conn, "actions", definition)
        conn.execute("UPDATE actions SET provider='fresh_core' WHERE provider IS NULL OR provider='' ")
        conn.execute("UPDATE actions SET operation=action_type WHERE operation IS NULL OR operation='' ")
        conn.execute("UPDATE actions SET ai_proposal_json=proposed_json WHERE ai_proposal_json IS NULL AND proposed_json IS NOT NULL")
        # 0.8.5 repair: MySQL already had project_members/project_invitations from
        # older releases, so CREATE TABLE IF NOT EXISTS did not add the new
        # relationship column.  Ensure it explicitly before any Propojení page
        # queries those tables.
        _ensure_column(conn, "project_members", "relationship VARCHAR(24) NOT NULL DEFAULT 'member'")
        _ensure_column(conn, "project_invitations", "relationship VARCHAR(24) NOT NULL DEFAULT 'member'")
        for owner in conn.execute("SELECT id,user_id FROM projects").fetchall():
            conn.execute("""INSERT INTO project_members(project_id,user_id,role,status,invited_by,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE role=IF(role='owner','owner',VALUES(role)),status='active',updated_at=VALUES(updated_at)""",
                         (owner["id"], owner["user_id"], "owner", "active", owner["user_id"], now(), now()))
        default_rules = [
            ("core_sync", "Fresh Core synchronizace", "Načte změny webu a udržuje Bobanův kontext aktuální.", 1, 1),
            ("search_console_sync", "Search Console", "Aktualizuje dotazy, pozice, imprese a kliknutí.", 1, 12),
            ("ga4_sync", "Google Analytics 4", "Aktualizuje návštěvnost a obchodní výsledky.", 1, 12),
            ("pagespeed_crux_sync", "PageSpeed + CrUX", "Kontroluje technický výkon a Core Web Vitals.", 1, 24),
            ("gtm_sync", "GTM audit", "Kontroluje stav měření v Google Tag Manageru v read-only režimu.", 1, 24),
            ("seo_crawl", "SEO crawler", "Pravidelně obnoví technický crawler audit webu.", 1, 168),
            ("operator_cycle", "Boban Operator", "Vyhodnotí obchodní cíl a připraví bezpečné SEO zásahy ke schválení. Nic automaticky nepublikuje.", 1, 84),
        ]
        for rule in default_rules:
            conn.execute("""INSERT INTO automation_rules(rule_key,name,description,enabled,interval_hours,config_json,updated_at,updated_by)
                            VALUES(?,?,?,?,?,?,?,NULL) ON DUPLICATE KEY UPDATE name=VALUES(name),description=VALUES(description)""",
                         (*rule, "{}", now()))
        conn.commit()
        conn.close()
        return

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        site_url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'waiting',
        health_score INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_snapshot TEXT,
        chat_cutoff TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        body TEXT NOT NULL,
        meta_json TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS integrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'seo',
        status TEXT NOT NULL DEFAULT 'disconnected',
        config_json TEXT,
        last_sync TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id, provider)
    );
    CREATE TABLE IF NOT EXISTS audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'seo',
        status TEXT NOT NULL,
        score INTEGER,
        summary_json TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        audit_id INTEGER,
        channel TEXT NOT NULL DEFAULT 'seo',
        source TEXT NOT NULL DEFAULT 'audit',
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        code TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT,
        target_url TEXT,
        entity_id TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        snoozed_until TEXT,
        decision_note TEXT,
        decision_at TEXT,
        decision_by INTEGER,
        context_json TEXT,
        resolved_by_action_id INTEGER,
        recheck_after TEXT
    );
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        channel TEXT NOT NULL DEFAULT 'seo',
        action_type TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        target_url TEXT,
        reason TEXT,
        before_json TEXT,
        proposed_json TEXT,
        result_json TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        expected_metric TEXT,
        measurement_window_days INTEGER NOT NULL DEFAULT 28,
        created_at TEXT NOT NULL,
        approved_at TEXT,
        applied_at TEXT,
        measured_at TEXT,
        issue_id INTEGER,
        ai_proposal_json TEXT,
        user_edited_at TEXT,
        snoozed_until TEXT,
        dismissed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS action_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        author_type TEXT NOT NULL,
        values_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS metric_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        action_id INTEGER,
        channel TEXT NOT NULL,
        source TEXT NOT NULL,
        metric TEXT NOT NULL,
        dimension TEXT,
        value REAL,
        captured_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS source_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'seo',
        period_start TEXT,
        period_end TEXT,
        payload TEXT NOT NULL,
        captured_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS engine_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        task_type TEXT NOT NULL,
        status TEXT NOT NULL,
        http_status INTEGER,
        run_id TEXT,
        provider TEXT,
        model TEXT,
        latency_ms INTEGER,
        cost_usd REAL,
        error_text TEXT,
        response_meta_json TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        user_id INTEGER,
        action_id INTEGER,
        group_id TEXT,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        payload_json TEXT,
        result_json TEXT,
        run_after TEXT,
        locked_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        updated_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        project_id INTEGER,
        level TEXT NOT NULL DEFAULT 'info',
        kind TEXT NOT NULL DEFAULT 'system',
        title TEXT NOT NULL,
        body TEXT,
        url TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        snoozed_until TEXT,
        dismissed_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS workers (
        name TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'idle',
        last_seen TEXT,
        detail_json TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS project_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'editor',
        relationship TEXT NOT NULL DEFAULT 'member',
        status TEXT NOT NULL DEFAULT 'active',
        invited_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS project_invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        email TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'editor',
        relationship TEXT NOT NULL DEFAULT 'member',
        status TEXT NOT NULL DEFAULT 'pending',
        invited_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id,email)
    );
    CREATE TABLE IF NOT EXISTS access_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        requested_role TEXT NOT NULL DEFAULT 'editor',
        status TEXT NOT NULL DEFAULT 'pending',
        note TEXT,
        created_at TEXT NOT NULL,
        decided_at TEXT,
        decided_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS automation_rules (
        rule_key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        interval_hours INTEGER NOT NULL DEFAULT 24,
        config_json TEXT,
        updated_at TEXT NOT NULL,
        updated_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS automation_state (
        project_id INTEGER NOT NULL,
        rule_key TEXT NOT NULL,
        last_run TEXT,
        last_status TEXT,
        last_error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(project_id,rule_key)
    );
    CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY,
        value_json TEXT,
        secret_enc TEXT,
        updated_at TEXT NOT NULL,
        updated_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS email_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        project_id INTEGER,
        to_email TEXT NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        sent_at TEXT
    );
    """)

    conn.execute("""CREATE TABLE IF NOT EXISTS search_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'search_console',
        query_text TEXT,
        page_url TEXT,
        country TEXT,
        device TEXT,
        clicks REAL NOT NULL DEFAULT 0,
        impressions REAL NOT NULL DEFAULT 0,
        ctr REAL NOT NULL DEFAULT 0,
        position REAL NOT NULL DEFAULT 0,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        captured_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS operator_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        strategy_json TEXT,
        plan_json TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")

    existing_user_columns = _table_columns(conn, "users")
    roles_are_new = "system_role" not in existing_user_columns
    for definition in (
        "system_role TEXT NOT NULL DEFAULT 'visitor'", "account_status TEXT NOT NULL DEFAULT 'active'",
        "paid_access_status TEXT NOT NULL DEFAULT 'none'", "last_login_at TEXT", "email_alerts INTEGER NOT NULL DEFAULT 1"
    ):
        _ensure_column(conn, "users", definition)
    admin_email = (os.getenv("WEBBOOSTER_ADMIN_EMAIL") or "soufek@freshcrackers.cz").strip().lower()
    if roles_are_new:
        for legacy_user in conn.execute("SELECT id,email FROM users").fetchall():
            owns = conn.execute("SELECT id FROM projects WHERE user_id=? LIMIT 1", (legacy_user["id"],)).fetchone()
            role = "admin" if str(legacy_user["email"] or "").lower() == admin_email else ("editor" if owns else "visitor")
            paid = "active" if role in {"admin", "editor"} else "none"
            conn.execute("UPDATE users SET system_role=?,paid_access_status=? WHERE id=?", (role, paid, legacy_user["id"]))
    conn.execute("UPDATE users SET system_role='admin',paid_access_status='active',account_status='active' WHERE LOWER(email)=?", (admin_email,))

    for definition in (
        "core_manifest_url TEXT", "core_site_url TEXT", "core_version TEXT", "core_last_sync TEXT",
        "core_manifest_json TEXT", "core_snapshot_json TEXT", "core_write_endpoint TEXT",
        "core_write_key_enc TEXT", "core_write_status TEXT DEFAULT 'disconnected'",
        "seo_url_count INTEGER DEFAULT 0", "open_issue_count INTEGER DEFAULT 0", "chat_cutoff TEXT",
        "business_goal TEXT", "primary_conversion TEXT", "priority_topics TEXT", "brand_terms TEXT",
        "boban_mode TEXT DEFAULT 'specialist'", "boban_cadence TEXT DEFAULT 'twice_weekly'", "last_operator_run TEXT",
    ):
        _ensure_column(conn, "projects", definition)
    for definition in (
        "source TEXT NOT NULL DEFAULT 'audit'", "kind TEXT NOT NULL DEFAULT 'warning'", "fingerprint TEXT",
        "snoozed_until TEXT", "decision_note TEXT", "decision_at TEXT", "decision_by INTEGER", "context_json TEXT",
        "resolved_by_action_id INTEGER", "recheck_after TEXT",
    ):
        _ensure_column(conn, "issues", definition)
    for definition in ("secret_enc TEXT", "scope TEXT", "account_label TEXT"):
        _ensure_column(conn, "integrations", definition)
    for definition in (
        "baseline_metrics_json TEXT", "impact_json TEXT", "expected_outcome TEXT",
        "verification_json TEXT", "verified_at TEXT", "completed_at TEXT", "job_group_id TEXT", "last_error TEXT",
        "issue_id INTEGER", "ai_proposal_json TEXT", "user_edited_at TEXT", "snoozed_until TEXT", "dismissed_at TEXT",
        "provider TEXT NOT NULL DEFAULT 'fresh_core'", "operation TEXT",
    ):
        _ensure_column(conn, "actions", definition)
    conn.execute("UPDATE actions SET provider='fresh_core' WHERE provider IS NULL OR provider='' ")
    conn.execute("UPDATE actions SET operation=action_type WHERE operation IS NULL OR operation='' ")
    _ensure_column(conn, "project_members", "relationship TEXT NOT NULL DEFAULT 'member'")
    _ensure_column(conn, "project_invitations", "relationship TEXT NOT NULL DEFAULT 'member'")
    _ensure_column(conn, "messages", "meta_json TEXT")
    for definition in ("snoozed_until TEXT", "dismissed_at TEXT"):
        _ensure_column(conn, "notifications", definition)
    for definition in (
        "user_id INTEGER", "action_id INTEGER", "group_id TEXT",
        "attempts INTEGER NOT NULL DEFAULT 0", "max_attempts INTEGER NOT NULL DEFAULT 3",
        "locked_at TEXT", "updated_at TEXT",
    ):
        _ensure_column(conn, "jobs", definition)

    conn.execute("UPDATE actions SET ai_proposal_json=proposed_json WHERE ai_proposal_json IS NULL AND proposed_json IS NOT NULL")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_issues_project_status ON issues(project_id,status)",
        "CREATE INDEX IF NOT EXISTS idx_issues_project_code ON issues(project_id,code)",
        "CREATE INDEX IF NOT EXISTS idx_actions_project_status ON actions(project_id,status)",
        "CREATE INDEX IF NOT EXISTS idx_action_revisions_action ON action_revisions(action_id,id)",
        "CREATE INDEX IF NOT EXISTS idx_snapshots_project_provider ON source_snapshots(project_id,provider,captured_at)",
        "CREATE INDEX IF NOT EXISTS idx_engine_project ON engine_runs(project_id,id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status,run_after)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_group ON jobs(group_id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_action ON jobs(action_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,is_read,id)",
        "CREATE INDEX IF NOT EXISTS idx_search_perf_project_period ON search_performance(project_id,period_end)",
        "CREATE INDEX IF NOT EXISTS idx_search_perf_project_query ON search_performance(project_id,query_text)",
        "CREATE INDEX IF NOT EXISTS idx_operator_plans_project ON operator_plans(project_id,id)",
        "CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id,status)",
        "CREATE INDEX IF NOT EXISTS idx_access_requests_status ON access_requests(status,id)",
        "CREATE INDEX IF NOT EXISTS idx_email_outbox_status ON email_outbox(status,id)",
    ):
        conn.execute(sql)
    for owner in conn.execute("SELECT id,user_id FROM projects").fetchall():
        conn.execute("INSERT OR IGNORE INTO project_members(project_id,user_id,role,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (owner["id"], owner["user_id"], "owner", "active", owner["user_id"], now(), now()))
    default_rules = [
        ("core_sync", "Fresh Core synchronizace", "Načte změny webu a udržuje Bobanův kontext aktuální.", 1, 1),
        ("search_console_sync", "Search Console", "Aktualizuje dotazy, pozice, imprese a kliknutí.", 1, 12),
        ("ga4_sync", "Google Analytics 4", "Aktualizuje návštěvnost a obchodní výsledky.", 1, 12),
        ("pagespeed_crux_sync", "PageSpeed + CrUX", "Kontroluje technický výkon a Core Web Vitals.", 1, 24),
        ("gtm_sync", "GTM audit", "Kontroluje stav měření v Google Tag Manageru v read-only režimu.", 1, 24),
        ("seo_crawl", "SEO crawler", "Pravidelně obnoví technický crawler audit webu.", 1, 168),
        ("operator_cycle", "Boban Operator", "Vyhodnotí obchodní cíl a připraví bezpečné SEO zásahy ke schválení. Nic automaticky nepublikuje.", 1, 84),
    ]
    for rule in default_rules:
        conn.execute("INSERT OR IGNORE INTO automation_rules(rule_key,name,description,enabled,interval_hours,config_json,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,NULL)", (*rule, "{}", now()))
        conn.execute("UPDATE automation_rules SET name=?,description=? WHERE rule_key=?", (rule[1], rule[2], rule[0]))
    conn.commit()
    conn.close()


init_db()
# Additive, idempotent analytical schema; keeps legacy tables and catalogue untouched.
_conn_analytics=db()
try:
    commerce_analytics.ensure_schema(_conn_analytics, DB_BACKEND)
    advisor_intelligence.ensure_schema(_conn_analytics, DB_BACKEND)
    sync_schedule.ensure_schema(_conn_analytics, DB_BACKEND)
    _conn_analytics.commit()
finally:
    _conn_analytics.close()
_conn_catalog=db()
feed_workflow.ensure_schema(_conn_catalog,DB_BACKEND)
if DB_BACKEND == 'mysql':
    _conn_catalog.execute("""CREATE TABLE IF NOT EXISTS project_heureka_feeds (
      project_id BIGINT UNSIGNED PRIMARY KEY, feed_token VARCHAR(100) NOT NULL UNIQUE,
      generated_at VARCHAR(32), exported_count INT NOT NULL DEFAULT 0,
      availability_count INT NOT NULL DEFAULT 0, report_json LONGTEXT,
      fast_dispatch_confirmed TINYINT NOT NULL DEFAULT 0,
      shop_registered TINYINT NOT NULL DEFAULT 0, last_error TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
else:
    _conn_catalog.execute("""CREATE TABLE IF NOT EXISTS project_heureka_feeds (
      project_id INTEGER PRIMARY KEY, feed_token TEXT NOT NULL UNIQUE,
      generated_at TEXT, exported_count INTEGER NOT NULL DEFAULT 0,
      availability_count INTEGER NOT NULL DEFAULT 0, report_json TEXT,
      fast_dispatch_confirmed INTEGER NOT NULL DEFAULT 0,
      shop_registered INTEGER NOT NULL DEFAULT 0, last_error TEXT)""")
# Heureka-specific optional shipping promise. Preserve existing installs and accounts.
try:
    if DB_BACKEND == 'mysql':
        _cols = _conn_catalog.execute('SHOW COLUMNS FROM project_heureka_feeds').fetchall()
        _names = {str(r['Field']) for r in _cols}
    else:
        _cols = _conn_catalog.execute('PRAGMA table_info(project_heureka_feeds)').fetchall()
        _names = {str(r['name']) for r in _cols}
    if 'default_delivery_days' not in _names:
        _conn_catalog.execute('ALTER TABLE project_heureka_feeds ADD COLUMN default_delivery_days INTEGER NULL')
except Exception:
    raise RuntimeError('Nelze ověřit či rozšířit nastavení Heureka expedice.')
# Separate output state, shared approved catalog. Existing Google/Heureka tables untouched.
if DB_BACKEND == 'mysql':
    _conn_catalog.execute("""CREATE TABLE IF NOT EXISTS project_zbozi_feeds (
      project_id BIGINT UNSIGNED PRIMARY KEY, feed_token VARCHAR(100) NOT NULL UNIQUE,
      generated_at VARCHAR(32), exported_count INT NOT NULL DEFAULT 0, report_json LONGTEXT,
      default_delivery_days INTEGER NULL, last_error TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
else:
    _conn_catalog.execute("""CREATE TABLE IF NOT EXISTS project_zbozi_feeds (
      project_id INTEGER PRIMARY KEY, feed_token TEXT NOT NULL UNIQUE,
      generated_at TEXT, exported_count INTEGER NOT NULL DEFAULT 0, report_json TEXT,
      default_delivery_days INTEGER NULL, last_error TEXT)""")
# Meta catalog: separate public feed state; never modify Google/Heureka/Zbozi.
if DB_BACKEND == 'mysql':
    _conn_catalog.execute("""CREATE TABLE IF NOT EXISTS project_meta_feeds (
      project_id BIGINT UNSIGNED PRIMARY KEY, feed_token VARCHAR(100) NOT NULL UNIQUE,
      generated_at VARCHAR(32), exported_count INT NOT NULL DEFAULT 0,
      report_json LONGTEXT, catalog_id VARCHAR(100),
      catalog_confirmed TINYINT NOT NULL DEFAULT 0, last_error TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
else:
    _conn_catalog.execute("""CREATE TABLE IF NOT EXISTS project_meta_feeds (
      project_id INTEGER PRIMARY KEY, feed_token TEXT NOT NULL UNIQUE,
      generated_at TEXT, exported_count INTEGER NOT NULL DEFAULT 0,
      report_json TEXT, catalog_id TEXT,
      catalog_confirmed INTEGER NOT NULL DEFAULT 0, last_error TEXT)""")
# Meta Graph API connection state. Secrets are encrypted using the app SECRET_KEY.
try:
    if DB_BACKEND == 'mysql':
        _meta_cols={str(x['Field']) for x in _conn_catalog.execute('SHOW COLUMNS FROM project_meta_feeds').fetchall()}
    else:
        _meta_cols={str(x['name']) for x in _conn_catalog.execute('PRAGMA table_info(project_meta_feeds)').fetchall()}
    for _meta_field,_meta_type in [('api_token_cipher','LONGTEXT' if DB_BACKEND=='mysql' else 'TEXT'),
                                   ('api_feed_id','VARCHAR(100)' if DB_BACKEND=='mysql' else 'TEXT'),
                                   ('api_status','VARCHAR(40)' if DB_BACKEND=='mysql' else 'TEXT'),
                                   ('api_last_result','LONGTEXT' if DB_BACKEND=='mysql' else 'TEXT'),
                                   ('api_checked_at','VARCHAR(40)' if DB_BACKEND=='mysql' else 'TEXT')]:
        if _meta_field not in _meta_cols:
            _conn_catalog.execute('ALTER TABLE project_meta_feeds ADD COLUMN '+_meta_field+' '+_meta_type+' NULL')
except Exception as _meta_error:
    raise RuntimeError('Nelze rozšířit stav Meta Graph API: '+str(_meta_error))
# Zbozi shipping rules: optional user-confirmed delivery for ALL exported items.
# Never invent carrier, price, COD or per-item availability.
try:
    if DB_BACKEND == 'mysql':
        _columns = {str(r['Field']) for r in _conn_catalog.execute('SHOW COLUMNS FROM project_zbozi_feeds').fetchall()}
    else:
        _columns = {str(r['name']) for r in _conn_catalog.execute('PRAGMA table_info(project_zbozi_feeds)').fetchall()}
    if 'shipping_rules_json' not in _columns:
        _conn_catalog.execute('ALTER TABLE project_zbozi_feeds ADD COLUMN shipping_rules_json TEXT NULL')
except Exception:
    raise RuntimeError('Nelze rozšířit nastavení dopravy Zboží.cz.')
_conn_catalog.commit()
_conn_catalog.close()
ensure_chat_threads()
ensure_marketing_knowledge()


@login_manager.user_loader
def load_user(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return User(row) if row else None


@app.before_request
def enforce_account_status():
    if current_user.is_authenticated and getattr(current_user, "account_status", "active") != "active":
        logout_user()
        if request.endpoint not in {"login", "index", "static"}:
            flash("Tento účet je deaktivovaný.", "error")
            return redirect(url_for("login"))


def _row_get_value(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def editor_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "can_edit", False):
            flash("Tato funkce je dostupná editorům. Můžeš požádat o placený přístup.", "warning")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapped


def project_access_role(project_id, user_id=None):
    user_id = int(user_id or current_user.id)
    if current_user.is_authenticated and int(current_user.id) == user_id and getattr(current_user, "is_admin", False):
        return "admin"
    conn = db()
    project = conn.execute("SELECT user_id FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        conn.close(); return None
    if int(project["user_id"]) == user_id:
        conn.close(); return "owner"
    row = conn.execute("SELECT role,status FROM project_members WHERE project_id=? AND user_id=?", (project_id, user_id)).fetchone()
    conn.close()
    if row and row["status"] == "active":
        return _access_role(str(row["role"] or "viewer"))
    return None


def can_manage_project_access(project_id):
    role=project_access_role(project_id)
    # Sharing and Fresh Key are free project-administration capabilities and do
    # not depend on AI credits or Boban's paid editing entitlement.
    return role in {"admin", "owner", "manager"}


def project_for_user(project_id):
    role = project_access_role(project_id)
    if not role:
        abort(404)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if role == "viewer":
            abort(403)
        linking_endpoint = str(request.endpoint or "").startswith(("project_access", "fresh_key"))
        if not getattr(current_user, "can_edit", False) and not (linking_endpoint and role in {"admin", "owner", "manager"}):
            abort(403)
    conn = db(); row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    if not row:
        abort(404)
    return row


def accessible_projects(user_id, sidebar=False):
    fields = "p.id,p.name,p.site_url,p.status,p.health_score,p.updated_at,p.seo_url_count,p.open_issue_count" if sidebar else "p.*"
    conn = db()
    rows = conn.execute(
        f"""SELECT DISTINCT {fields}, CASE WHEN p.user_id=? THEN 'owner' ELSE pm.role END AS access_role
            FROM projects p LEFT JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=? AND pm.status='active'
            WHERE p.user_id=? OR pm.user_id=? ORDER BY p.updated_at DESC,p.id DESC""",
        (user_id, user_id, user_id, user_id)
    ).fetchall()
    conn.close(); return rows


def automation_rule(rule_key):
    conn=db(); row=conn.execute("SELECT * FROM automation_rules WHERE rule_key=?", (rule_key,)).fetchone(); conn.close()
    return row


def automation_rule_enabled(rule_key):
    row=automation_rule(rule_key)
    return bool(row and int(row["enabled"] or 0))


def automation_rule_due(project_id, rule_key, fallback_hours=24):
    rule=automation_rule(rule_key)
    if not rule or not int(rule["enabled"] or 0): return False
    hours=max(1, int(rule["interval_hours"] or fallback_hours))
    conn=db(); state=conn.execute("SELECT last_run,last_status FROM automation_state WHERE project_id=? AND rule_key=?", (project_id,rule_key)).fetchone(); conn.close()
    if not state or not state["last_run"]: return True
    if str(state["last_status"] or "") == "failed": hours=min(hours,1)
    try: return datetime.now()-datetime.fromisoformat(str(state["last_run"])) >= timedelta(hours=hours)
    except Exception: return True


def mark_automation_run(project_id, rule_key, status="completed", error=None):
    ts=now(); conn=db()
    params=(project_id,rule_key,ts,status,str(error or "")[:4000] or None,ts)
    if DB_BACKEND=="mysql":
        conn.execute("""INSERT INTO automation_state(project_id,rule_key,last_run,last_status,last_error,updated_at) VALUES(?,?,?,?,?,?)
                        ON DUPLICATE KEY UPDATE last_run=VALUES(last_run),last_status=VALUES(last_status),last_error=VALUES(last_error),updated_at=VALUES(updated_at)""", params)
    else:
        conn.execute("""INSERT INTO automation_state(project_id,rule_key,last_run,last_status,last_error,updated_at) VALUES(?,?,?,?,?,?)
                        ON CONFLICT(project_id,rule_key) DO UPDATE SET last_run=excluded.last_run,last_status=excluded.last_status,last_error=excluded.last_error,updated_at=excluded.updated_at""", params)
    conn.commit(); conn.close()


def project_automation_allowed(project_id):
    conn=db()
    rows=conn.execute("""SELECT u.system_role,u.account_status,u.paid_access_status
                         FROM projects p JOIN users u ON u.id=p.user_id WHERE p.id=?
                         UNION ALL
                         SELECT u.system_role,u.account_status,u.paid_access_status
                         FROM project_members pm JOIN users u ON u.id=pm.user_id
                         WHERE pm.project_id=? AND pm.status='active' AND pm.role IN ('owner','editor')""", (project_id,project_id)).fetchall()
    conn.close()
    return any(r["account_status"] == "active" and r["system_role"] in {"admin","editor"} and r["paid_access_status"] in {"active","manual"} for r in rows)


def get_system_setting(key, default=None):
    conn=db(); row=conn.execute("SELECT value_json,secret_enc FROM system_settings WHERE setting_key=?", (key,)).fetchone(); conn.close()
    if not row: return default
    try: value=json.loads(row["value_json"] or "null")
    except Exception: value=default
    if isinstance(value, dict) and row["secret_enc"]:
        value=dict(value); value["password"] = decrypt_secret(row["secret_enc"])
    return value if value is not None else default


def set_system_setting(key, value, secret=None, user_id=None):
    ts=now(); conn=db(); payload=json.dumps(value, ensure_ascii=False)
    secret_enc=encrypt_secret(secret) if secret is not None else None
    existing=conn.execute("SELECT setting_key,secret_enc FROM system_settings WHERE setting_key=?", (key,)).fetchone()
    if secret is None and existing: secret_enc=existing["secret_enc"]
    params=(key,payload,secret_enc,ts,user_id)
    if DB_BACKEND=="mysql":
        conn.execute("""INSERT INTO system_settings(setting_key,value_json,secret_enc,updated_at,updated_by) VALUES(?,?,?,?,?)
                        ON DUPLICATE KEY UPDATE value_json=VALUES(value_json),secret_enc=VALUES(secret_enc),updated_at=VALUES(updated_at),updated_by=VALUES(updated_by)""", params)
    else:
        conn.execute("""INSERT INTO system_settings(setting_key,value_json,secret_enc,updated_at,updated_by) VALUES(?,?,?,?,?)
                        ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,secret_enc=excluded.secret_enc,updated_at=excluded.updated_at,updated_by=excluded.updated_by""", params)
    conn.commit(); conn.close()


def smtp_config():
    return get_system_setting("smtp", {}) or {}


def send_email_message(to_email, subject, body):
    conf=smtp_config()
    if not conf.get("enabled"):
        raise ValueError("E-mailový účet není v administraci zapnutý.")
    host=str(conf.get("host") or "").strip(); port=int(conf.get("port") or 587); username=str(conf.get("username") or "").strip(); password=str(conf.get("password") or "")
    from_email=str(conf.get("from_email") or username).strip(); from_name=str(conf.get("from_name") or "Boban • Web Booster").strip(); security=str(conf.get("security") or "starttls")
    if not host or not from_email: raise ValueError("Chybí SMTP server nebo odesílatel.")
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=f"{from_name} <{from_email}>" if from_name else from_email; msg["To"]=to_email; msg.set_content(body)
    context=ssl.create_default_context()
    if security=="ssl":
        server=smtplib.SMTP_SSL(host,port,timeout=15,context=context)
    else:
        server=smtplib.SMTP(host,port,timeout=15)
        if security=="starttls": server.starttls(context=context)
    try:
        if username: server.login(username,password)
        server.send_message(msg)
    finally:
        try: server.quit()
        except Exception: pass
    return True


def queue_notification_email(user_id, project_id, subject, body):
    conf=smtp_config()
    if not conf.get("enabled") or not conf.get("notification_enabled"): return None
    conn=db(); user=conn.execute("SELECT email,email_alerts FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or not int(user["email_alerts"] or 0): conn.close(); return None
    cur=conn.execute("INSERT INTO email_outbox(user_id,project_id,to_email,subject,body,status,attempts,created_at) VALUES(?,?,?,?,?,'queued',0,?)", (user_id,project_id,user["email"],subject,body,now()))
    conn.commit(); oid=cur.lastrowid; conn.close(); return oid


def normalize_host(url):
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _host_is_public(host):
    if not host:
        return False
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        raw = info[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local or
            ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            return False
    return True


def safe_http_url(url):
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Konektor musí používat veřejnou HTTPS URL.")
    if not _host_is_public(parsed.hostname):
        raise ValueError("URL nesměřuje na veřejný web.")
    return parsed.geturl()


def fetch_json(url, expected_host=None):
    url = safe_http_url(url)
    if expected_host and normalize_host(url) != normalize_host("https://" + expected_host):
        raise ValueError("Soubor konektoru je na jiné doméně než manifest.")
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
        allow_redirects=True,
    )
    r.raise_for_status()
    if normalize_host(r.url) != normalize_host(url):
        raise ValueError("Konektor přesměroval na jinou doménu.")
    return r.json()


def fetch_html(url, expected_host):
    url = safe_http_url(url)
    if normalize_host(url) != normalize_host("https://" + expected_host):
        raise ValueError("Crawler zůstává pouze na doméně projektu.")
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=HTTP_TIMEOUT,
        allow_redirects=True,
    )
    # Allow www/non-www normalization, but not foreign domains.
    if normalize_host(r.url) != normalize_host(url):
        raise ValueError("URL přesměrovala mimo doménu projektu.")
    return r


def _fernet():
    secret = os.getenv("SECRET_KEY", "")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def add_activity(conn, project_id, kind, title, detail=""):
    conn.execute(
        "INSERT INTO activities(project_id,kind,title,detail,created_at) VALUES(?,?,?,?,?)",
        (project_id, kind, title, detail, now())
    )


def upsert_integration(conn, project_id, provider, channel, status, config, last_sync=None):
    ts = now()
    params = (
        project_id, provider, channel, status,
        json.dumps(config or {}, ensure_ascii=False),
        last_sync, ts, ts
    )
    if DB_BACKEND == "mysql":
        conn.execute(
            """
            INSERT INTO integrations(project_id,provider,channel,status,config_json,last_sync,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON DUPLICATE KEY UPDATE
              channel=VALUES(channel), status=VALUES(status), config_json=VALUES(config_json),
              last_sync=VALUES(last_sync), updated_at=VALUES(updated_at)
            """,
            params,
        )
    else:
        conn.execute(
            """
            INSERT INTO integrations(project_id,provider,channel,status,config_json,last_sync,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id,provider) DO UPDATE SET
              channel=excluded.channel,
              status=excluded.status,
              config_json=excluded.config_json,
              last_sync=excluded.last_sync,
              updated_at=excluded.updated_at
            """,
            params,
        )



CONNECTOR_CATALOG = [
    {
        "id": "fresh_core",
        "name": "Fresh Core",
        "group": "Web",
        "status": "active",
        "purpose": "Struktura WordPressu, SEO data a bezpečné provádění schválených změn.",
        "needs": "Manifest URL + volitelný write key",
    },
    {
        "id": "search_console",
        "name": "Google Search Console",
        "group": "Vyhledávání",
        "status": "active",
        "purpose": "Imprese, kliknutí, CTR, průměrná pozice, dotazy a vstupní stránky z Googlu.",
        "needs": "Google OAuth",
    },
    {
        "id": "ga4",
        "name": "Google Analytics 4",
        "group": "Návštěvnost",
        "status": "active",
        "purpose": "Návštěvy, zdroje, události a konverze. Pomůže měřit, zda SEO/PPC přivádí správné návštěvníky.",
        "needs": "Google OAuth + GA4 property",
    },
    {
        "id": "gtm",
        "name": "Google Tag Manager",
        "group": "Měření",
        "status": "active",
        "purpose": "Kontrola měřicích značek, konverzí a datové vrstvy. Později i řízené změny měření.",
        "needs": "Google OAuth + GTM container",
    },
    {
        "id": "business_profile",
        "name": "Google Business Profile",
        "group": "Lokální vyhledávání",
        "status": "planned",
        "purpose": "Výkon firemního profilu, hledané dotazy, zobrazení a lokální viditelnost.",
        "needs": "Google OAuth + přístup k profilu",
    },
    {
        "id": "pagespeed_crux",
        "name": "PageSpeed / Chrome UX Report",
        "group": "Výkon webu",
        "status": "active",
        "purpose": "Core Web Vitals a reálná uživatelská data o rychlosti. Pomůže spojit technické změny s UX a organickým výkonem.",
        "needs": "Google API / veřejná URL",
    },
    {
        "id": "merchant_center",
        "name": "Google Merchant Center",
        "group": "E-commerce",
        "status": "active",
        "purpose": "Produkty, diagnostika feedu a výkon Shopping ploch. Relevantní hlavně pro e-shopy.",
        "needs": "Google OAuth + Merchant Center účet",
    },
    {
        "id": "bing_webmaster",
        "name": "Bing Webmaster Tools",
        "group": "Vyhledávání",
        "status": "planned",
        "purpose": "Bing crawl, indexace, klíčová slova, odkazy a URL submission.",
        "needs": "Microsoft/Bing OAuth",
    },
    {
        "id": "seznam_webmaster",
        "name": "Seznam Webmaster / IndexNow",
        "group": "Vyhledávání",
        "status": "planned",
        "purpose": "Data SeznamBota, indexace a rychlé hlášení změněných URL přes IndexNow.",
        "needs": "Seznam Webmaster/API nebo IndexNow key",
    },
    {
        "id": "google_ads",
        "name": "Google Ads",
        "group": "PPC",
        "status": "planned",
        "purpose": "Plánování, náklady, kampaně, klíčová slova, konverze a ROAS.",
        "needs": "Google OAuth + Google Ads API access",
    },
    {
        "id": "sklik",
        "name": "Sklik",
        "group": "PPC",
        "status": "planned",
        "purpose": "České PPC kampaně a data Skliku pro společné vyhodnocení SEO + placené návštěvnosti.",
        "needs": "Sklik API",
    },
    {
        "id": "microsoft_ads",
        "name": "Microsoft Advertising",
        "group": "PPC",
        "status": "planned",
        "purpose": "Placené kampaně v Microsoft/Bing ekosystému a společné vyhodnocení s Bing Webmaster daty.",
        "needs": "Microsoft OAuth + Advertising API access",
    },
    {
        "id": "meta_ads",
        "name": "Meta Ads",
        "group": "PPC / social",
        "status": "planned",
        "purpose": "Kampaně, náklady a konverze z Facebooku a Instagramu jako další placený kanál.",
        "needs": "Meta OAuth + Marketing API access",
    },
    {
        "id": "clarity",
        "name": "Microsoft Clarity",
        "group": "Chování návštěvníků",
        "status": "planned",
        "purpose": "Doplňkový kontext chování návštěvníků, heatmap a UX problémů tam, kde bude dostupné vhodné API/export.",
        "needs": "Clarity projekt / dostupné API",
    },
]



# --- SEO knowledge base -----------------------------------------------------
# The knowledge base intentionally separates verified public guidance from
# Boban's own recommendations. Ranking algorithms are not public; we explain
# mechanisms and controllable signals without pretending to know secret weights.
SEO_KNOWLEDGE = {
    "jak-funguje-google": {
        "title": "Jak funguje Google Search",
        "category": "Vyhledávače",
        "summary": "Google nejdřív stránku objeví a stáhne, potom ji může zařadit do indexu a teprve při dotazu rozhoduje, zda je relevantní pro konkrétního člověka.",
        "sections": [
            ("1. Objevení a crawl", "Googlebot nachází URL hlavně přes odkazy, sitemapu a další známé zdroje. Stránka musí být veřejně dostupná a crawler nesmí být blokovaný."),
            ("2. Indexace", "HTTP 200 a dostupnost nejsou zárukou indexace. Google musí obsah umět zpracovat a rozhodnout, že má smysl ho do indexu zařadit."),
            ("3. Relevance a zobrazení", "Pro konkrétní dotaz Google skládá mnoho signálů. Pomáhá srozumitelný title, hlavní nadpis, text stránky, odkazy, struktura, obrázky a užitečný obsah pro člověka."),
            ("4. Co Boban umí ovlivnit", "Technickou dostupnost, metadata, strukturu obsahu, interní odkazy, obrázky a měření výkonu. Neumím slíbit konkrétní pozici; po změně měřím skutečný dopad."),
        ],
        "sources": [
            ("Google Search Essentials", "https://developers.google.com/search/docs/essentials"),
            ("Google SEO Starter Guide", "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"),
        ],
    },
    "jak-funguje-seznam": {
        "title": "Jak funguje Seznam.cz Vyhledávání",
        "category": "Vyhledávače",
        "summary": "SeznamBot prochází web, hledá nové a změněné stránky a Seznam Webmaster ukazuje základní stav crawlu a indexace.",
        "sections": [
            ("SeznamBot", "Seznam používá vlastního crawlera SeznamBot. URL může najít přes odkazy; změny lze hlásit i přes Seznam Webmaster a IndexNow."),
            ("Indexace", "Robots.txt řídí crawl, noindex indexaci. Pokud nechceš stránku ve výsledcích, je důležité použít správný indexační mechanismus."),
            ("Klíčová slova", "Seznam výslovně uvádí, že meta tag keywords pro relevanci nepoužívá. Důležitý je skutečný titulek a obsah stránky."),
            ("Co budeme měřit", "Po připojení Seznam Webmasteru budeme porovnávat navštívené URL, indexované URL, chyby a změny po zásazích Bobana."),
        ],
        "sources": [
            ("SeznamBot", "https://o-seznam.cz/napoveda/vyhledavani/seznambot/"),
            ("Seznam Webmaster", "https://o-seznam.cz/napoveda/vyhledavani/seznam-webmaster/"),
            ("Nejčastější dotazy Seznam", "https://o-seznam.cz/napoveda/vyhledavani/nejcastejsi-dotazy/"),
        ],
    },
    "jak-funguje-bing": {
        "title": "Jak funguje Bing a Microsoft vyhledávání",
        "category": "Vyhledávače",
        "summary": "Bing staví na stejném základu: discovery, crawl, indexace, srozumitelný obsah, interní odkazy a důvěryhodné externí signály.",
        "sections": [
            ("Discovery", "Bing doporučuje sitemapu, crawlable interní odkazy a pro rychlé hlášení změn IndexNow."),
            ("Obsah a struktura", "Pomáhá jasný title, meta description, logická hierarchie nadpisů, HTML struktura a obsah zaměřený na jedno hlavní téma."),
            ("Autorita", "Bing popisuje kvalitní přirozené odkazy jako důležitý signál. Množství samo o sobě není cíl; problematická jsou link farmy a manipulativní nákupy odkazů."),
            ("Bing + Copilot", "Microsoft výslovně spojuje kvalitní crawl/indexaci a srozumitelnost obsahu také s viditelností v AI/grounding zkušenostech."),
        ],
        "sources": [
            ("Bing Webmaster Guidelines", "https://www.bing.com/webmasters/help/webmaster-guidelines-30fba23a"),
            ("Bing Link Building", "https://www.bing.com/webmasters/help/link-building-7a3f99b7"),
        ],
    },
    "technicke-seo": {
        "title": "Technické SEO: může robot web vůbec správně zpracovat?",
        "category": "Technické SEO",
        "summary": "Technické SEO řeší dostupnost a jednoznačnost webu: HTTP stav, indexaci, canonical, robots, sitemapu, renderování, rychlost a strukturu URL.",
        "sections": [
            ("Priorita", "Nejdřív řeším věci, které mohou stránku úplně vyřadit z vyhledávání: chyby serveru, blokace crawlera, nechtěný noindex a špatné přesměrování."),
            ("Canonical a duplicity", "Canonical pomáhá určit preferovanou URL. Je důležitý hlavně tam, kde podobný obsah může existovat na více adresách."),
            ("Výkon webu", "Rychlost, stabilita layoutu a použitelnost mají vliv na UX. Budeme je měřit přes PageSpeed/CrUX, ne odhadovat z pocitu."),
            ("Pokrytí auditu", "Skóre je věrohodné jen podle toho, kolik URL a kontrol jsme opravdu provedli. Proto Boban od v0.7.0 ukazuje i pokrytí auditu."),
        ],
        "sources": [
            ("Google Search technical requirements", "https://developers.google.com/search/docs/essentials/technical"),
            ("Bing Webmaster Guidelines", "https://www.bing.com/webmasters/help/webmaster-guidelines-30fba23a"),
        ],
    },
    "obsahove-seo": {
        "title": "Obsahové SEO: odpovídá stránka tomu, co člověk hledá?",
        "category": "Obsahové SEO",
        "summary": "Obsahové SEO není vyplnění jednoho políčka. Kontrolujeme title, H1, text, záměr stránky, duplicity, obrázky, interní prolinkování a návaznost na dotazy z vyhledávání.",
        "sections": [
            ("Title a H1", "Mají jasně popsat téma stránky. Nemusí být totožné, ale neměly by si významově odporovat."),
            ("Meta description", "Je hlavně návrh textu pro snippet a CTR. Vyhledávač může použít jiný úryvek z obsahu, takže ji nehodnotíme jako magický ranking faktor."),
            ("Klíčová slova", "Neřešíme meta keywords. Řešíme skutečný jazyk uživatelů: dotazy, témata a formulace, které patří přirozeně do title, H1, textu, ALT a anchor textů."),
            ("Užitečnost", "Obsah musí splnit účel stránky. Boban bude postupně spojovat audit s dotazy a výkonem ze Search Console, aby nedoporučoval text jen podle délky."),
        ],
        "sources": [
            ("Google Search Essentials", "https://developers.google.com/search/docs/essentials"),
            ("Google title links", "https://developers.google.com/search/docs/appearance/title-link"),
            ("Google SEO Starter Guide", "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"),
        ],
    },
    "odkazy-autorita": {
        "title": "Interní odkazy, externí odkazy a autorita",
        "category": "Autorita a odkazy",
        "summary": "Interní odkazy řídíme sami. Zpětné odkazy z cizích webů jsou externí signál a Boban je nebude předstírat bez dat.",
        "sections": [
            ("Interní odkazy", "Pomáhají crawlerům objevovat stránky a uživatelům chápat souvislosti. Boban hledá stránky s chudým prolinkováním a později bude umět navrhnout konkrétní zdrojové stránky a anchor text."),
            ("Externí odkazy z našeho webu", "Odkaz na důvěryhodný zdroj může doplnit kontext. Neexistuje ale povinný počet externích odkazů na stránku."),
            ("Zpětné odkazy", "To jsou odkazy z cizích webů k nám. Boban může hledat příležitosti, ale autoritu nebude skórovat bez spolehlivého backlink zdroje."),
            ("Co nedoporučuji", "Link farmy, masové nákupy a umělé výměny odkazů. Cílem jsou relevantní odkazy, které dávají smysl i bez SEO."),
        ],
        "sources": [
            ("Google SEO Starter Guide – links", "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"),
            ("Bing Link Building", "https://www.bing.com/webmasters/help/link-building-7a3f99b7"),
        ],
    },
    "seo-titulky-popisy": {
        "title": "SEO title a meta description",
        "category": "Obsahové SEO",
        "summary": "Title pomáhá popsat stránku a je důležitý pro podobu výsledku. Description ovlivňuje hlavně kvalitu snippetu a proklik, ale vyhledávač ji nemusí použít doslova.",
        "sections": [
            ("Title", "Každá důležitá indexovatelná stránka má mít vlastní, srozumitelný a konkrétní title. Duplicitní title zhoršují rozlišení stránek."),
            ("Description", "Popisuj skutečný obsah stránky a důvod ke kliknutí. Nevkládej tvrzení, která na stránce nejsou."),
            ("Bobanův workflow", "Připravím návrh, ty ho můžeš ručně upravit, potom teprve změnu publikuji a ověřím ve veřejném HTML."),
        ],
        "sources": [
            ("Google title links", "https://developers.google.com/search/docs/appearance/title-link"),
            ("Google SEO Starter Guide", "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"),
        ],
    },
    "obrazky-alt": {
        "title": "Obrázky a ALT text",
        "category": "Obsahové SEO",
        "summary": "ALT popisuje význam obrázku tam, kde ho uživatel nevidí, a pomáhá přístupnosti i porozumění obrázku ve vyhledávání.",
        "sections": [
            ("Kdy ALT doplnit", "U informačního obrázku popiš stručně jeho význam v kontextu stránky. U čistě dekorativních prvků je často správný prázdný ALT."),
            ("Čemu se vyhnout", "Nevkládej seznam klíčových slov. ALT má popsat obrázek, ne být skrytý SEO text."),
            ("Automatizace", "Boban umí připravit ALT podle obrázku a kontextu stránky, návrh můžeš upravit a teprve po schválení ho Fresh Core zapíše do WordPressu."),
        ],
        "sources": [
            ("Google Search Essentials", "https://developers.google.com/search/docs/essentials"),
            ("Google SEO Starter Guide", "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"),
        ],
    },
    "indexace-canonical": {
        "title": "Indexace, noindex a canonical",
        "category": "Technické SEO",
        "summary": "Crawl, indexace a canonical nejsou totéž. Boban proto odděluje, zda robot stránku načte, zda smí být v indexu a která URL je preferovaná.",
        "sections": [
            ("robots.txt", "Primárně řídí crawl přístup. Samotné blokování crawlu není totéž jako noindex."),
            ("noindex", "Říká vyhledávači, že stránku nemá zařadit do výsledků. U každého noindex proto kontrolujeme, zda je záměrný."),
            ("canonical", "Pomáhá konsolidovat signály u duplicitních nebo velmi podobných URL. Není náhradou za správné přesměrování při skutečném přesunu URL."),
        ],
        "sources": [
            ("Google Search technical requirements", "https://developers.google.com/search/docs/essentials/technical"),
            ("Seznam indexing control", "https://o-seznam.cz/napoveda/vyhledavani/en/indexing-control/"),
        ],
    },
}

ISSUE_KNOWLEDGE_MAP = {
    "crawl_failed": "technicke-seo", "http_error": "technicke-seo", "slow_response": "technicke-seo", "very_slow_response": "technicke-seo",
    "noindex": "indexace-canonical", "rendered_noindex": "indexace-canonical",
    "canonical_missing": "indexace-canonical", "rendered_canonical_missing": "indexace-canonical",
    "seo_title_missing": "seo-titulky-popisy", "rendered_title_missing": "seo-titulky-popisy",
    "duplicate_seo_title": "seo-titulky-popisy", "duplicate_rendered_title": "seo-titulky-popisy",
    "meta_description_missing": "seo-titulky-popisy", "rendered_description_missing": "seo-titulky-popisy",
    "duplicate_meta_description": "seo-titulky-popisy", "duplicate_rendered_description": "seo-titulky-popisy",
    "seo_title_length": "seo-titulky-popisy", "meta_description_length": "seo-titulky-popisy",
    "h1_missing": "obsahove-seo", "multiple_h1": "obsahove-seo", "thin_content": "obsahove-seo",
    "missing_alt": "obrazky-alt", "image_alt_missing": "obrazky-alt",
    "low_internal_links": "odkazy-autorita", "sample_no_internal_inlinks": "odkazy-autorita",
}


def integration_row(project_id, provider):
    conn = db()
    row = conn.execute(
        "SELECT * FROM integrations WHERE project_id=? AND provider=?",
        (project_id, provider)
    ).fetchone()
    conn.close()
    return row


def integration_config(row):
    if not row or not row["config_json"]:
        return {}
    try:
        return json.loads(row["config_json"])
    except Exception:
        return {}


def update_integration_secret(project_id, provider, secret_payload, scope="", account_label=""):
    conn = db()
    row = conn.execute(
        "SELECT id FROM integrations WHERE project_id=? AND provider=?",
        (project_id, provider)
    ).fetchone()
    if not row:
        upsert_integration(conn, project_id, provider, "seo", "connected", {}, now())
    conn.execute(
        "UPDATE integrations SET secret_enc=?, scope=?, account_label=?, updated_at=? WHERE project_id=? AND provider=?",
        (
            encrypt_secret(json.dumps(secret_payload, ensure_ascii=False)),
            scope, account_label, now(), project_id, provider
        )
    )
    conn.commit()
    conn.close()


def integration_secret(project_id, provider):
    row = integration_row(project_id, provider)
    if not row or not row["secret_enc"]:
        return {}
    raw = decrypt_secret(row["secret_enc"])
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters"
GA4_READ_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GA4_EDIT_SCOPE = "https://www.googleapis.com/auth/analytics.edit"
GTM_READ_SCOPE = "https://www.googleapis.com/auth/tagmanager.readonly"
MERCHANT_SCOPE = merchant_connector.MERCHANT_SCOPE
GOOGLE_SERVICE_SCOPES = {
    "search_console": [GSC_SCOPE],
    "ga4": [GA4_READ_SCOPE, GA4_EDIT_SCOPE],
    "gtm": [GTM_READ_SCOPE],
    "merchant_center": [MERCHANT_SCOPE],
    "google_stack": [GSC_SCOPE, GA4_READ_SCOPE, GA4_EDIT_SCOPE, GTM_READ_SCOPE],
}


def google_oauth_ready():
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET") and os.getenv("GOOGLE_REDIRECT_URI"))


def google_scopes_for(service):
    return GOOGLE_SERVICE_SCOPES.get(service, GOOGLE_SERVICE_SCOPES["google_stack"])


def google_refresh_access(project_id, provider="search_console"):
    creds = integration_secret(project_id, provider)
    if not creds:
        raise ValueError("Google účet není připojen.")
    expires_at = float(creds.get("expires_at") or 0)
    if creds.get("access_token") and expires_at > time.time() + 300:
        return creds["access_token"]
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        raise ValueError("Chybí Google refresh token. Připoj Google účet znovu.")
    r = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=max(HTTP_TIMEOUT, 20),
    )
    if r.status_code >= 300:
        # Google OAuth returns a non-secret error identifier (e.g. invalid_grant).
        # Never include error_description, response body or credentials in logs/UI.
        try:
            oauth_error = str((r.json() or {}).get('error') or '')
        except (ValueError, TypeError, AttributeError):
            oauth_error = ''
        permitted = {'invalid_grant', 'invalid_client', 'unauthorized_client',
                     'invalid_request', 'unsupported_grant_type', 'invalid_scope'}
        safe = oauth_error if oauth_error in permitted else 'nezjistena_pricina'
        hint = ('Obnov připojení Google v Konektorech.' if safe == 'invalid_grant'
                else 'Zkontroluj konfiguraci Google OAuth klienta.' if safe == 'invalid_client'
                else 'Prověř Google OAuth připojení a oprávnění.')
        raise ValueError(f"Google token refresh selhal: HTTP {r.status_code} ({safe}). {hint}")
    data = r.json()
    creds["access_token"] = data.get("access_token")
    creds["expires_at"] = time.time() + int(data.get("expires_in") or 3600)
    if data.get("scope"):
        creds["scope"] = data["scope"]
    update_integration_secret(project_id, provider, creds, creds.get("scope", ""))
    return creds["access_token"]


def google_api_request(method, url, token, payload=None, expected=(200, 201, 204)):
    r = requests.request(
        method.upper(), url,
        json=payload if payload is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=max(HTTP_TIMEOUT, 20),
    )
    if r.status_code not in expected and r.status_code >= 300:
        raise ValueError(f"Google API {method.upper()} selhalo: HTTP {r.status_code}: {r.text[:500]}")
    if not r.content:
        return {}
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:2000]}


def google_api_get(url, token):
    return google_api_request("GET", url, token)


def google_api_post(url, token, payload):
    return google_api_request("POST", url, token, payload)


def google_exchange_code(project_id, code, service="google_stack"):
    if not google_oauth_ready():
        raise ValueError("Google OAuth není nakonfigurovaný v .env.")
    old = (integration_secret(project_id, "merchant_center") if service == "merchant_center" else (integration_secret(project_id, "search_console") or integration_secret(project_id, "ga4") or integration_secret(project_id, "gtm")))
    token_resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI"),
            "grant_type": "authorization_code",
        },
        timeout=max(HTTP_TIMEOUT, 20),
    )
    if token_resp.status_code >= 300:
        raise ValueError(f"Google OAuth token selhal: HTTP {token_resp.status_code}: {token_resp.text[:300]}")
    token_data = token_resp.json()
    return {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token") or old.get("refresh_token"),
        "expires_at": time.time() + int(token_data.get("expires_in") or 3600),
        "scope": token_data.get("scope") or " ".join(google_scopes_for(service)),
        "token_type": token_data.get("token_type", "Bearer"),
    }


def choose_search_console_property(site_url, properties):
    host = normalize_host(site_url)
    candidates = []
    for row in properties:
        prop = str(row.get("siteUrl") or "")
        score = 0
        if prop.startswith("sc-domain:"):
            if normalize_host("https://" + prop.split(":", 1)[1]) == host:
                score = 100
        elif normalize_host(prop) == host:
            score = 90
            if prop.rstrip("/") == site_url.rstrip("/"):
                score = 95
        if score:
            candidates.append((score, prop))
    return sorted(candidates, reverse=True)[0][1] if candidates else ""


def search_console_property_permission(properties, selected):
    row = next((x for x in properties or [] if str(x.get("siteUrl") or "") == str(selected or "")), {})
    return str(row.get("permissionLevel") or "")


def search_console_can_write(properties, selected, scope_text):
    permission = search_console_property_permission(properties, selected)
    return GSC_SCOPE in str(scope_text or "").split() and permission in {"siteOwner", "siteFullUser"}


def connect_search_console_with_creds(project_id, creds):
    token = creds.get("access_token")
    if not token:
        raise ValueError("Google nepředal access token.")
    sites_payload = google_api_get("https://www.googleapis.com/webmasters/v3/sites", token)
    properties = sites_payload.get("siteEntry") or []
    conn = db(); project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    if not project:
        raise ValueError("Projekt nebyl nalezen.")
    selected = choose_search_console_property(project["site_url"], properties)
    config = {
        "available_properties": properties,
        "selected_property": selected,
        "selected_permission": search_console_property_permission(properties, selected),
        "property_count": len(properties),
        "domain_verified": search_console_domain_verified(project["site_url"], selected),
        "write_enabled": search_console_can_write(properties, selected, creds.get("scope")),
    }
    status = "connected" if selected else "needs_selection"
    conn = db()
    upsert_integration(conn, project_id, "search_console", "seo", status, config, now())
    add_activity(conn, project_id, "connector", "Google Search Console připojena",
                 f"Nalezeno {len(properties)} properties." + (f" Vybrána {selected}." if selected else " Vyber property ručně."))
    conn.commit(); conn.close()
    update_integration_secret(project_id, "search_console", creds, creds.get("scope", ""))
    return config


def ga4_property_summaries(token):
    data = google_api_get("https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200", token)
    out = []
    for account in data.get("accountSummaries") or []:
        for prop in account.get("propertySummaries") or []:
            out.append({
                "property": prop.get("property"),
                "displayName": prop.get("displayName") or prop.get("property"),
                "canEdit": bool(prop.get("canEdit")),
                "account": account.get("account"),
                "accountDisplayName": account.get("displayName"),
            })
    return out



def ga4_data_streams(token, property_name):
    property_name = str(property_name or "").strip()
    if not property_name:
        return []
    if not property_name.startswith("properties/"):
        property_name = "properties/" + property_name
    data = google_api_get(
        f"https://analyticsadmin.googleapis.com/v1beta/{property_name}/dataStreams?pageSize=200",
        token
    )
    out = []
    for stream in data.get("dataStreams") or []:
        web = stream.get("webStreamData") if isinstance(stream.get("webStreamData"), dict) else {}
        default_uri = str(web.get("defaultUri") or "")
        out.append({
            "name": stream.get("name"),
            "displayName": stream.get("displayName") or stream.get("name"),
            "type": stream.get("type") or "",
            "defaultUri": default_uri,
            "measurementId": web.get("measurementId") or "",
            "host": normalize_host(default_uri) if default_uri else "",
        })
    return out


def ga4_property_domain_info(token, property_name, site_url):
    project_host = normalize_host(site_url)
    try:
        streams = ga4_data_streams(token, property_name)
    except Exception as exc:
        return {
            "streams": [], "web_streams": [], "domain_match": False,
            "verified_host": "", "measurement_ids": [], "stream_error": str(exc)[:300]
        }
    web_streams = [x for x in streams if x.get("defaultUri")]
    matching = [x for x in web_streams if x.get("host") == project_host]
    return {
        "streams": streams,
        "web_streams": web_streams,
        "domain_match": bool(matching),
        "verified_host": matching[0].get("host") if matching else "",
        "verified_uri": matching[0].get("defaultUri") if matching else "",
        "measurement_ids": [x.get("measurementId") for x in matching if x.get("measurementId")],
        "stream_hosts": sorted({x.get("host") for x in web_streams if x.get("host")}),
        "stream_error": "",
    }


def _ga4_name_match_score(row, site_url):
    host = normalize_host(site_url)
    stem = host.split(".")[0] if host else ""
    text = " ".join([
        str(row.get("displayName") or ""),
        str(row.get("accountDisplayName") or ""),
        str(row.get("property") or ""),
    ]).lower()
    score = 0
    if host and host in text:
        score += 100
    if stem and len(stem) >= 4 and stem in text:
        score += 35
    return score


def prepare_ga4_properties(token, properties, site_url):
    """Verify likely GA4 properties against their actual web data stream.

    We deliberately avoid calling dataStreams.list for every property on very
    large agency accounts. Name/account matching narrows the candidates first;
    manual selection verifies any other property on demand.
    """
    rows = [dict(x) for x in (properties or [])]
    rows.sort(key=lambda x: (_ga4_name_match_score(x, site_url), str(x.get("displayName") or "")), reverse=True)
    likely = [x for x in rows if _ga4_name_match_score(x, site_url) > 0][:8]
    if not likely and len(rows) <= 8:
        likely = rows[:]
    verified_property = ""
    for row in likely:
        info = ga4_property_domain_info(token, row.get("property"), site_url)
        row.update({
            "domainVerified": bool(info.get("domain_match")),
            "verifiedUri": info.get("verified_uri") or "",
            "streamHosts": info.get("stream_hosts") or [],
            "measurementIds": info.get("measurement_ids") or [],
            "streamChecked": True,
        })
        if info.get("domain_match") and not verified_property:
            verified_property = str(row.get("property") or "")
    # Non-checked rows are still available under the advanced selector.
    for row in rows:
        row.setdefault("domainVerified", False)
        row.setdefault("verifiedUri", "")
        row.setdefault("streamHosts", [])
        row.setdefault("measurementIds", [])
        row.setdefault("streamChecked", False)
    return rows, verified_property


def ga4_selected_config(token, selected_row, site_url):
    info = ga4_property_domain_info(token, selected_row.get("property"), site_url)
    selected = dict(selected_row or {})
    selected.update({
        "domainVerified": bool(info.get("domain_match")),
        "verifiedUri": info.get("verified_uri") or "",
        "streamHosts": info.get("stream_hosts") or [],
        "measurementIds": info.get("measurement_ids") or [],
        "streamChecked": True,
    })
    return selected


def search_console_domain_verified(site_url, selected_property):
    prop = str(selected_property or "").strip()
    host = normalize_host(site_url)
    if prop.startswith("sc-domain:"):
        return normalize_host("https://" + prop.split(":", 1)[1]) == host
    return normalize_host(prop) == host if prop else False


SPAM_QUERY_PATTERNS = (
    "apk", "casino", "slot", "judi", "gacor", "togel", "mahjong", "taruhan",
    "betting", "jackpot", "bonus login", "game android", "mod apk", "unduh",
    "putar", "spin", "poker", "sportsbook",
)


def _project_topic_text(project):
    parts = [str(project["name"] or ""), str(project["site_url"] or "")]
    try:
        for item in seo_items_from_snapshot(project_snapshot(project))[:60]:
            parts.extend([
                str(item.get("wp_title") or item.get("title") or ""),
                str(item.get("excerpt") or ""),
            ])
    except Exception:
        pass
    return " ".join(parts).lower()


def search_spam_anomaly(gsc_payload, project=None):
    rows = (gsc_payload.get("top_queries") or []) if gsc_payload else []
    suspicious = []
    topic_text = _project_topic_text(project) if project is not None else ""
    total_imp = sum(float(r.get("impressions") or 0) for r in rows)
    total_clicks = sum(float(r.get("clicks") or 0) for r in rows)
    for row in rows:
        keys = row.get("keys") or []
        query = str(keys[0] if keys else "").strip()
        q = query.lower()
        # Do not alarm a site whose own content clearly belongs to that topic.
        matched = [p for p in SPAM_QUERY_PATTERNS if p in q and p not in topic_text]
        if matched:
            suspicious.append({
                "query": query,
                "matches": matched,
                "clicks": float(row.get("clicks") or 0),
                "impressions": float(row.get("impressions") or 0),
                "position": float(row.get("position") or 0),
            })
    spam_imp = sum(x["impressions"] for x in suspicious)
    spam_clicks = sum(x["clicks"] for x in suspicious)
    imp_share = spam_imp / total_imp if total_imp else 0
    click_share = spam_clicks / total_clicks if total_clicks else 0
    level = "ok"
    if suspicious:
        level = "warning"
    if len(suspicious) >= 3 or imp_share >= 0.20 or click_share >= 0.20:
        level = "critical"
    return {
        "level": level,
        "count": len(suspicious),
        "queries": sorted(suspicious, key=lambda x: (x["clicks"], x["impressions"]), reverse=True)[:12],
        "impression_share": imp_share,
        "click_share": click_share,
    }


def data_trust_summary(project, gsc_payload, ga4_payload, gsc_config, ga4_config):
    project_host = normalize_host(project["site_url"])
    trust = {
        "project_host": project_host,
        "gsc_domain_verified": search_console_domain_verified(project["site_url"], gsc_config.get("selected_property")),
        "ga4_domain_verified": bool(ga4_config.get("selected_domain_verified")),
        "ga4_verified_uri": ga4_config.get("selected_verified_uri") or "",
        "ga4_measurement_ids": ga4_config.get("selected_measurement_ids") or [],
        "ga4_runtime_host_share": None,
        "ga4_runtime_hosts": [],
        "gsc_ga4_ratio": None,
        "cross_source_status": "unknown",
        "spam": search_spam_anomaly(gsc_payload or {}, project),
    }
    if ga4_payload:
        hosts = ga4_payload.get("hostnames") or []
        total = sum(float(x.get("sessions") or 0) for x in hosts)
        own = sum(float(x.get("sessions") or 0) for x in hosts if normalize_host("https://" + str(x.get("hostName") or "")) == project_host)
        trust["ga4_runtime_hosts"] = hosts[:10]
        if total > 0:
            trust["ga4_runtime_host_share"] = own / total

    if gsc_payload and ga4_payload:
        clicks = float((gsc_payload.get("current") or {}).get("clicks") or 0)
        aligned = ga4_payload.get("organic_gsc_aligned") or ga4_payload.get("current_organic") or ga4_payload.get("current") or {}
        sessions = float(aligned.get("sessions") or 0)
        if clicks >= 20:
            ratio = sessions / clicks if clicks else None
            trust["gsc_ga4_ratio"] = ratio
            if ratio is not None and (ratio < 0.25 or ratio > 2.5):
                trust["cross_source_status"] = "warning"
            else:
                trust["cross_source_status"] = "ok"
    return trust


def period_label(payload):
    period = (payload or {}).get("period") or {}
    start = str(period.get("start") or "")
    end = str(period.get("end") or "")
    def _fmt(v):
        try:
            d = date.fromisoformat(v)
            return f"{d.day}. {d.month}. {d.year}"
        except Exception:
            return v
    return f"{_fmt(start)} – {_fmt(end)}" if start and end else ""


def _pct_change(current, previous):
    try:
        current = float(current or 0); previous = float(previous or 0)
    except Exception:
        return None
    if previous == 0:
        return None
    return (current - previous) / previous * 100.0


def _sparkline(rows, metric, width=800, height=180, invert=False):
    values = []
    for row in rows or []:
        try:
            values.append(float(row.get(metric) or 0))
        except Exception:
            values.append(0.0)
    if not values:
        return {"points": "", "min": 0, "max": 0, "count": 0}
    low, high = min(values), max(values)
    span = high - low or 1.0
    usable_h = height - 24
    usable_w = width - 24
    pts = []
    total = max(len(values) - 1, 1)
    for idx, value in enumerate(values):
        x = 12 + usable_w * idx / total
        ratio = (value - low) / span
        y = 12 + usable_h * (ratio if invert else (1.0 - ratio))
        pts.append(f"{x:.1f},{y:.1f}")
    return {"points": " ".join(pts), "min": low, "max": high, "count": len(values)}


def project_progress_summary(project_id, gsc=None, ga4=None):
    gsc = gsc or latest_source_snapshot(project_id, "search_console")
    ga4 = ga4 or latest_source_snapshot(project_id, "ga4")
    conn = db()
    counts = conn.execute(
        """SELECT
             SUM(CASE WHEN status IN ('verified','completed') THEN 1 ELSE 0 END) done_count,
             SUM(CASE WHEN status IN ('draft','approved','failed') THEN 1 ELSE 0 END) todo_count,
             SUM(CASE WHEN status IN ('queued','pending','applied') THEN 1 ELSE 0 END) running_count,
             SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) measured_count,
             COUNT(*) total_count
           FROM actions WHERE project_id=?""",
        (project_id,)
    ).fetchone()
    recent = conn.execute(
        """SELECT id,action_type,target_url,proposed_json,status,verified_at,completed_at,applied_at,impact_json
           FROM actions WHERE project_id=? AND status IN ('verified','completed')
           ORDER BY COALESCE(completed_at,verified_at,applied_at,created_at) DESC,id DESC LIMIT 12""",
        (project_id,)
    ).fetchall()
    first_applied = conn.execute(
        "SELECT MIN(applied_at) first_applied FROM actions WHERE project_id=? AND applied_at IS NOT NULL",
        (project_id,)
    ).fetchone()
    conn.close()

    counts = dict(counts) if counts else {}
    first_applied = dict(first_applied) if first_applied else {}
    recent_done = []
    for row in recent:
        try:
            proposed = json.loads(row["proposed_json"] or "{}")
        except Exception:
            proposed = {}
        try:
            impact = json.loads(row["impact_json"] or "{}") if row["impact_json"] else {}
        except Exception:
            impact = {}
        recent_done.append({
            "id": int(row["id"]),
            "action_type": str(row["action_type"] or ""),
            "target_url": str(row["target_url"] or ""),
            "fields": list(proposed.keys()),
            "status": str(row["status"] or ""),
            "finished_at": row["completed_at"] or row["verified_at"] or row["applied_at"],
            "impact": impact,
        })

    cur = (gsc or {}).get("current") or {}; prev = (gsc or {}).get("previous") or {}
    ins = (gsc or {}).get("insights") or {}; ranks = ins.get("ranks") or {}; prev_ranks = ins.get("previous_ranks") or {}
    top10 = int(ranks.get("top3") or 0) + int(ranks.get("top10") or 0)
    prev_top10 = int(prev_ranks.get("top3") or 0) + int(prev_ranks.get("top10") or 0)
    org = (ga4 or {}).get("current_organic") or (ga4 or {}).get("current") or {}
    org_prev = (ga4 or {}).get("previous_organic") or (ga4 or {}).get("previous") or {}
    daily = []
    for row in (gsc or {}).get("daily") or []:
        keys = row.get("keys") or []
        daily.append({
            "date": str(keys[0] if keys else ""),
            "clicks": float(row.get("clicks") or 0),
            "impressions": float(row.get("impressions") or 0),
            "ctr": float(row.get("ctr") or 0),
            "position": float(row.get("position") or 0),
        })
    return {
        "work": {
            "done": int(counts.get("done_count") or 0),
            "todo": int(counts.get("todo_count") or 0),
            "running": int(counts.get("running_count") or 0),
            "measured": int(counts.get("measured_count") or 0),
            "total": int(counts.get("total_count") or 0),
        },
        "recent_done": recent_done,
        "first_applied": first_applied.get("first_applied"),
        "kpis": {
            "clicks": {"current": float(cur.get("clicks") or 0), "previous": float(prev.get("clicks") or 0), "pct": _pct_change(cur.get("clicks"), prev.get("clicks"))},
            "impressions": {"current": float(cur.get("impressions") or 0), "previous": float(prev.get("impressions") or 0), "pct": _pct_change(cur.get("impressions"), prev.get("impressions"))},
            "ctr": {"current": float(cur.get("ctr") or 0), "previous": float(prev.get("ctr") or 0), "points": (float(cur.get("ctr") or 0) - float(prev.get("ctr") or 0)) * 100.0},
            "position": {"current": float(cur.get("position") or 0), "previous": float(prev.get("position") or 0), "delta": float(prev.get("position") or 0) - float(cur.get("position") or 0)},
            "top10": {"current": top10, "previous": prev_top10, "delta": top10 - prev_top10},
            "organic_sessions": {"current": float(org.get("sessions") or 0), "previous": float(org_prev.get("sessions") or 0), "pct": _pct_change(org.get("sessions"), org_prev.get("sessions"))},
        },
        "daily": daily,
        "clicks_chart": _sparkline(daily, "clicks"),
        "position_chart": _sparkline(daily, "position", invert=True),
    }

def connect_ga4_with_creds(project_id, creds):
    token = creds.get("access_token")
    if not token:
        raise ValueError("Google nepředal access token.")
    properties = ga4_property_summaries(token)
    conn = db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not project:
        raise ValueError("Projekt nebyl nalezen.")

    properties, selected = prepare_ga4_properties(token, properties, project["site_url"])
    selected_row = next((x for x in properties if x.get("property") == selected), None)
    config = {
        "available_properties": properties,
        "selected_property": selected,
        "property_count": len(properties),
        "selected_can_edit": bool((selected_row or {}).get("canEdit")),
        "selected_domain_verified": bool((selected_row or {}).get("domainVerified")),
        "selected_verified_uri": (selected_row or {}).get("verifiedUri") or "",
        "selected_measurement_ids": (selected_row or {}).get("measurementIds") or [],
        "selected_stream_hosts": (selected_row or {}).get("streamHosts") or [],
        "write_enabled": (
            GA4_EDIT_SCOPE in str(creds.get("scope") or "").split()
            and bool((selected_row or {}).get("canEdit"))
            and bool((selected_row or {}).get("domainVerified"))
        ),
    }
    status = "connected" if selected else ("needs_selection" if properties else "no_property")
    conn = db()
    upsert_integration(conn, project_id, "ga4", "analytics", status, config, now())
    if selected:
        detail = f"Nalezeno {len(properties)} GA4 properties. Doménou ověřena {selected}."
    else:
        detail = f"Nalezeno {len(properties)} GA4 properties. Nenašel jsem bezpečnou shodu web streamu s doménou; vyber property ručně."
    add_activity(conn, project_id, "connector", "Google Analytics 4 připojena", detail)
    conn.commit(); conn.close()
    update_integration_secret(project_id, "ga4", creds, creds.get("scope", ""))
    return config


def search_console_connect_from_code(project_id, code):
    creds = google_exchange_code(project_id, code, "search_console")
    return connect_search_console_with_creds(project_id, creds)


def gsc_query(token, property_url, start_date, end_date, dimensions=None, row_limit=1000):
    encoded = quote(property_url, safe="")
    url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded}/searchAnalytics/query"
    payload = {"startDate": start_date, "endDate": end_date, "rowLimit": min(int(row_limit), 25000)}
    if dimensions:
        payload["dimensions"] = dimensions
    return google_api_post(url, token, payload)


def gsc_metric_row(row):
    return {
        "keys": row.get("keys") or [],
        "clicks": float(row.get("clicks") or 0),
        "impressions": float(row.get("impressions") or 0),
        "ctr": float(row.get("ctr") or 0),
        "position": float(row.get("position") or 0),
    }


def search_performance_insights(current_queries, previous_queries, query_pages):
    current_map = {str((r.get("keys") or [""])[0]): r for r in current_queries if (r.get("keys") or [""])[0]}
    previous_map = {str((r.get("keys") or [""])[0]): r for r in previous_queries if (r.get("keys") or [""])[0]}
    compared = []
    for query, row in current_map.items():
        prev = previous_map.get(query)
        item = {"query": query, **{k: row.get(k) for k in ("clicks","impressions","ctr","position")}}
        if prev:
            item["position_change"] = float(prev.get("position") or 0) - float(row.get("position") or 0)
            item["click_change"] = float(row.get("clicks") or 0) - float(prev.get("clicks") or 0)
            item["impression_change"] = float(row.get("impressions") or 0) - float(prev.get("impressions") or 0)
        else:
            item["position_change"] = None
            item["click_change"] = None
            item["impression_change"] = None
        compared.append(item)
    gainers = sorted([x for x in compared if x.get("position_change") is not None and x["position_change"] >= 1.0], key=lambda x:(x["position_change"],x.get("impressions",0)), reverse=True)[:20]
    decliners = sorted([x for x in compared if x.get("position_change") is not None and x["position_change"] <= -1.0], key=lambda x:(x["position_change"],-x.get("impressions",0)))[:20]
    opportunities = []
    low_ctr = []
    for item in compared:
        pos = float(item.get("position") or 0); imp = float(item.get("impressions") or 0); ctr = float(item.get("ctr") or 0)
        if imp >= 20 and 4 <= pos <= 20:
            item2 = dict(item)
            item2["opportunity_score"] = round(imp * max(0.15, (21.0-pos)/17.0) * max(0.35, 1.0-ctr), 1)
            opportunities.append(item2)
        if imp >= 20 and 1 <= pos <= 10 and ctr < 0.02:
            low_ctr.append(item)
    opportunities = sorted(opportunities, key=lambda x:x["opportunity_score"], reverse=True)[:30]
    low_ctr = sorted(low_ctr, key=lambda x:x.get("impressions",0), reverse=True)[:20]
    by_query = {}
    for row in query_pages:
        keys = row.get("keys") or []
        if len(keys) < 2: continue
        query, page = str(keys[0]), str(keys[1])
        by_query.setdefault(query, []).append({"page": page, **{k:row.get(k) for k in ("clicks","impressions","ctr","position")}})
    cannibalization = []
    for query, pages in by_query.items():
        meaningful = [x for x in pages if float(x.get("impressions") or 0) >= 10]
        if len(meaningful) >= 2:
            cannibalization.append({"query":query,"pages":sorted(meaningful,key=lambda x:x.get("impressions",0),reverse=True)[:4],"impressions":sum(float(x.get("impressions") or 0) for x in meaningful)})
    cannibalization.sort(key=lambda x:x["impressions"], reverse=True)

    # Attach the strongest landing page to query-level insights. This lets the
    # operator turn Search Console opportunities into concrete WordPress work
    # instead of stopping at a recommendation.
    for bucket in (gainers, decliners, opportunities, low_ctr):
        for item in bucket:
            pages = sorted(by_query.get(str(item.get("query") or ""), []), key=lambda x: float(x.get("impressions") or 0), reverse=True)
            if pages:
                item["primary_page"] = pages[0].get("page") or ""
                item["primary_page_metrics"] = pages[0]

    def rank_counts(rows):
        counts = {"top3":0,"top10":0,"top20":0,"top50":0,"beyond50":0}
        for row in rows:
            pos = float(row.get("position") or 0)
            if pos <= 0: continue
            if pos <= 3: counts["top3"] += 1
            elif pos <= 10: counts["top10"] += 1
            elif pos <= 20: counts["top20"] += 1
            elif pos <= 50: counts["top50"] += 1
            else: counts["beyond50"] += 1
        return counts
    ranks = rank_counts(current_queries)
    previous_ranks = rank_counts(previous_queries)
    return {"ranks":ranks,"previous_ranks":previous_ranks,"opportunities":opportunities,"low_ctr":low_ctr,"gainers":gainers,"decliners":decliners,"new_queries":[x for x in compared if x["query"] not in previous_map][:30],"lost_queries":[q for q in previous_map.keys() if q not in current_map][:30],"cannibalization":cannibalization[:20]}


def trim_analytics_history(conn, project_id, provider, keep_snapshots=None):
    """Bound connector history without touching action/baseline history.

    Detailed connector snapshots are useful for trends, but an always-on 12h sync
    must not grow the database forever. Keep the newest snapshots per provider and
    trim normalized Search Console rows older than ~180 days.
    """
    keep = int(keep_snapshots or SOURCE_SNAPSHOT_KEEP)
    old = conn.execute(
        "SELECT id FROM source_snapshots WHERE project_id=? AND provider=? ORDER BY id DESC LIMIT 10000 OFFSET ?",
        (project_id, provider, keep)
    ).fetchall()
    ids = [int(r["id"]) for r in old]
    if ids:
        marks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM source_snapshots WHERE id IN ({marks})", ids)
    if provider == "search_console":
        cutoff = (date.today() - timedelta(days=180)).isoformat()
        conn.execute(
            "DELETE FROM search_performance WHERE project_id=? AND source='search_console' AND period_end<?",
            (project_id, cutoff)
        )


def sync_search_console(project_id):
    integ = integration_row(project_id, "search_console")
    if not integ: raise ValueError("Search Console není připojena.")
    config = integration_config(integ); property_url = config.get("selected_property")
    if not property_url: raise ValueError("Vyber Search Console property.")
    token = google_refresh_access(project_id, "search_console")
    end = date.today() - timedelta(days=3); start = end - timedelta(days=27); prev_end = start - timedelta(days=1); prev_start = prev_end - timedelta(days=27); daily_start = end - timedelta(days=89)
    current = gsc_metric_row((gsc_query(token, property_url, start.isoformat(), end.isoformat()).get("rows") or [{}])[0])
    previous = gsc_metric_row((gsc_query(token, property_url, prev_start.isoformat(), prev_end.isoformat()).get("rows") or [{}])[0])
    query_rows = [gsc_metric_row(r) for r in (gsc_query(token, property_url, start.isoformat(), end.isoformat(), ["query"], GSC_QUERY_LIMIT).get("rows") or [])]
    previous_query_rows = [gsc_metric_row(r) for r in (gsc_query(token, property_url, prev_start.isoformat(), prev_end.isoformat(), ["query"], GSC_QUERY_LIMIT).get("rows") or [])]
    page_rows = [gsc_metric_row(r) for r in (gsc_query(token, property_url, start.isoformat(), end.isoformat(), ["page"], GSC_QUERY_LIMIT).get("rows") or [])]
    query_page_rows = [gsc_metric_row(r) for r in (gsc_query(token, property_url, start.isoformat(), end.isoformat(), ["query","page"], GSC_QUERY_PAGE_LIMIT).get("rows") or [])]
    daily_rows = [gsc_metric_row(r) for r in (gsc_query(token, property_url, daily_start.isoformat(), end.isoformat(), ["date"], 120).get("rows") or [])]
    daily_rows.sort(key=lambda r: str((r.get("keys") or [""])[0]))
    insights = search_performance_insights(query_rows, previous_query_rows, query_page_rows)
    payload = {"property":property_url,"period":{"start":start.isoformat(),"end":end.isoformat()},"previous_period":{"start":prev_start.isoformat(),"end":prev_end.isoformat()},"trend_period":{"start":daily_start.isoformat(),"end":end.isoformat()},"current":current,"previous":previous,"top_queries":query_rows,"previous_queries":previous_query_rows,"top_pages":page_rows,"query_pages":query_page_rows,"daily":daily_rows,"insights":insights}
    conn=db(); ts=now(); payload["captured_at"] = ts
    conn.execute("INSERT INTO source_snapshots(project_id,provider,channel,period_start,period_end,payload,captured_at) VALUES(?,?,?,?,?,?,?)",(project_id,"search_console","seo",start.isoformat(),end.isoformat(),json.dumps(payload,ensure_ascii=False),ts))
    conn.execute("DELETE FROM search_performance WHERE project_id=? AND source='search_console' AND period_start=? AND period_end=?",(project_id,start.isoformat(),end.isoformat()))
    for row in query_rows:
        keys=row.get("keys") or []
        conn.execute("INSERT INTO search_performance(project_id,source,query_text,page_url,clicks,impressions,ctr,position,period_start,period_end,captured_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(project_id,"search_console",str(keys[0]) if keys else None,None,row["clicks"],row["impressions"],row["ctr"],row["position"],start.isoformat(),end.isoformat(),ts))
    for metric in ("clicks","impressions","ctr","position"):
        conn.execute("INSERT INTO metric_points(project_id,channel,source,metric,dimension,value,captured_at) VALUES(?,?,?,?,?,?,?)",(project_id,"seo","search_console",metric,"site",float(current.get(metric) or 0),ts))
    config["last_period"] = payload["period"]
    config["selected_permission"] = search_console_property_permission(config.get("available_properties") or [], property_url)
    project_row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    config["domain_verified"] = search_console_domain_verified(project_row["site_url"], property_url) if project_row else False
    config["write_enabled"] = search_console_can_write(config.get("available_properties") or [], property_url, integration_secret(project_id,"search_console").get("scope"))
    upsert_integration(conn,project_id,"search_console","seo","connected",config,ts)
    add_activity(conn,project_id,"data","Search Console synchronizována",f"{int(current['clicks'])} kliknutí, {int(current['impressions'])} impresí; {len(query_rows)} dotazů v analytickém vzorku.")
    trim_analytics_history(conn, project_id, "search_console")
    commerce_analytics.record_snapshot(conn, project_id, "search_console", payload, DB_BACKEND, ts)
    conn.commit(); conn.close(); refresh_action_impacts(project_id,payload); return payload


def latest_source_snapshot(project_id, provider):
    conn=db(); row=conn.execute("SELECT * FROM source_snapshots WHERE project_id=? AND provider=? ORDER BY id DESC LIMIT 1",(project_id,provider)).fetchone(); conn.close()
    if not row: return {}
    try: return json.loads(row["payload"])
    except Exception: return {}


def page_metrics_from_gsc(payload, target_url):
    if not payload or not target_url: return {}
    target=target_url.rstrip("/")
    for row in payload.get("top_pages") or []:
        keys=row.get("keys") or []
        if keys and str(keys[0]).rstrip("/")==target: return {k:row.get(k) for k in ("clicks","impressions","ctr","position")}
    return {}


def refresh_action_impacts(project_id, current_gsc=None):
    current_gsc=current_gsc or latest_source_snapshot(project_id,"search_console")
    if not current_gsc: return
    conn=db(); actions=conn.execute("SELECT * FROM actions WHERE project_id=? AND status IN ('applied','verified','completed') AND baseline_metrics_json IS NOT NULL",(project_id,)).fetchall()
    for action in actions:
        try: baseline=json.loads(action["baseline_metrics_json"] or "{}")
        except Exception: baseline={}
        current=page_metrics_from_gsc(current_gsc,action["target_url"])
        if not baseline or not current: continue
        impact={}
        for metric in ("clicks","impressions","ctr","position"):
            b=baseline.get(metric); c=current.get(metric)
            if b is None or c is None: continue
            impact[metric]={"before":b,"current":c,"delta":c-b,"delta_pct":((c-b)/b*100.0) if b not in (0,0.0) else None}
        impact["measured_at"]=now(); new_status=action["status"]
        try:
            applied=datetime.fromisoformat(action["applied_at"]) if action["applied_at"] else None
            if applied and datetime.now()>=applied+timedelta(days=int(action["measurement_window_days"] or 28)): new_status="completed"
        except Exception: pass
        conn.execute("UPDATE actions SET impact_json=?,measured_at=?,status=?,completed_at=CASE WHEN ?='completed' THEN COALESCE(completed_at,?) ELSE completed_at END WHERE id=?",(json.dumps(impact,ensure_ascii=False),now(),new_status,new_status,now(),action["id"]))
    conn.commit(); conn.close()


def ga4_run_report(token, property_name, start_date, end_date, dimensions=None, metrics=None, limit=100, dimension_filter=None):
    property_name=str(property_name or "").strip()
    if not property_name.startswith("properties/"): property_name="properties/"+property_name
    payload={"dateRanges":[{"startDate":start_date,"endDate":end_date}],"metrics":[{"name":x} for x in (metrics or ["sessions","activeUsers","engagedSessions","keyEvents","totalRevenue"])],"limit":str(limit)}
    if dimensions: payload["dimensions"]=[{"name":x} for x in dimensions]
    if dimension_filter: payload["dimensionFilter"]=dimension_filter
    return google_api_post(f"https://analyticsdata.googleapis.com/v1beta/{property_name}:runReport",token,payload)


def ga4_rows(data):
    dims=[x.get("name") for x in data.get("dimensionHeaders") or []]; mets=[x.get("name") for x in data.get("metricHeaders") or []]; out=[]
    for row in data.get("rows") or []:
        item={}
        for i,v in enumerate(row.get("dimensionValues") or []):
            if i<len(dims): item[dims[i]]=v.get("value")
        for i,v in enumerate(row.get("metricValues") or []):
            if i<len(mets):
                try: item[mets[i]]=float(v.get("value") or 0)
                except Exception: item[mets[i]]=v.get("value")
        out.append(item)
    return out


def sync_ga4(project_id):
    integ = integration_row(project_id, "ga4")
    if not integ:
        raise ValueError("Google Analytics 4 není připojena.")
    config = integration_config(integ)
    prop = config.get("selected_property")
    if not prop:
        raise ValueError("Vyber GA4 property.")
    token = google_refresh_access(project_id, "ga4")

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=27)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=27)
    organic_filter = {
        "filter": {
            "fieldName": "sessionDefaultChannelGroup",
            "stringFilter": {"matchType": "EXACT", "value": "Organic Search", "caseSensitive": False}
        }
    }
    metrics = ["sessions", "activeUsers", "engagedSessions", "keyEvents", "totalRevenue"]

    total_cur_rows = ga4_rows(ga4_run_report(token, prop, start.isoformat(), end.isoformat(), metrics=metrics, limit=1))
    total_prev_rows = ga4_rows(ga4_run_report(token, prop, prev_start.isoformat(), prev_end.isoformat(), metrics=metrics, limit=1))
    org_cur_rows = ga4_rows(ga4_run_report(token, prop, start.isoformat(), end.isoformat(), metrics=metrics, limit=1, dimension_filter=organic_filter))
    org_prev_rows = ga4_rows(ga4_run_report(token, prop, prev_start.isoformat(), prev_end.isoformat(), metrics=metrics, limit=1, dimension_filter=organic_filter))

    current_total = total_cur_rows[0] if total_cur_rows else {k: 0 for k in metrics}
    previous_total = total_prev_rows[0] if total_prev_rows else {k: 0 for k in metrics}
    current_organic = org_cur_rows[0] if org_cur_rows else {k: 0 for k in metrics}
    previous_organic = org_prev_rows[0] if org_prev_rows else {k: 0 for k in metrics}

    landing = ga4_rows(ga4_run_report(
        token, prop, start.isoformat(), end.isoformat(),
        dimensions=["landingPagePlusQueryString"], metrics=metrics, limit=100,
        dimension_filter=organic_filter
    ))
    events = ga4_rows(ga4_run_report(
        token, prop, start.isoformat(), end.isoformat(),
        dimensions=["eventName"], metrics=["eventCount", "keyEvents"], limit=100,
        dimension_filter=organic_filter
    ))
    hostnames = ga4_rows(ga4_run_report(
        token, prop, start.isoformat(), end.isoformat(),
        dimensions=["hostName"], metrics=["sessions", "activeUsers"], limit=50
    ))

    organic_gsc_aligned = {}
    gsc = latest_source_snapshot(project_id, "search_console")
    gsc_period = (gsc or {}).get("period") or {}
    if gsc_period.get("start") and gsc_period.get("end"):
        aligned_rows = ga4_rows(ga4_run_report(
            token, prop, gsc_period["start"], gsc_period["end"],
            metrics=metrics, limit=1, dimension_filter=organic_filter
        ))
        organic_gsc_aligned = aligned_rows[0] if aligned_rows else {k: 0 for k in metrics}

    # Extra read-only business reporting; failures must not break the proven GA4 sync.
    extended = {}
    optional_reports = (
        ('channels', ['sessionDefaultChannelGroup'], ['sessions','activeUsers','engagedSessions','totalRevenue']),
        ('sources', ['sessionSourceMedium'], ['sessions','activeUsers','totalRevenue']),
        ('countries', ['country'], ['sessions','activeUsers']),
        ('devices', ['deviceCategory'], ['sessions','activeUsers']),
        ('campaigns', ['sessionCampaignName'], ['sessions','totalRevenue']),
        ('commerce_events', ['eventName'], ['eventCount']),
        ('items', ['itemId','itemName'], ['itemsViewed','itemsAddedToCart','itemsPurchased','itemRevenue']),
        ('daily_channels', ['date','sessionDefaultChannelGroup'], ['sessions','activeUsers','engagedSessions']),
        ('daily_totals', ['date'], ['sessions','activeUsers','engagedSessions']),
        ('landing_pages_all', ['landingPagePlusQueryString'], ['sessions','activeUsers','engagedSessions']),
    )
    for report_key, dimensions, report_metrics in optional_reports:
        try:
            extended[report_key] = ga4_rows(ga4_run_report(
                token, prop, start.isoformat(), end.isoformat(),
                dimensions=dimensions, metrics=report_metrics, limit=250
            ))
        except Exception as exc:
            extended[report_key] = []
            extended[report_key+'_error'] = str(exc)[:240]

    payload = {
        "property": prop,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        # Compatibility: older UI treated current/previous as Organic Search.
        "current": current_organic,
        "previous": previous_organic,
        "current_total": current_total,
        "previous_total": previous_total,
        "current_organic": current_organic,
        "previous_organic": previous_organic,
        "organic_gsc_aligned": organic_gsc_aligned,
        "landing_pages": landing,
        "events": events,
        "hostnames": hostnames,
        "extended_reports": extended,
        "segment": "Organic Search",
    }

    conn = db()
    ts = now()
    conn.execute(
        "INSERT INTO source_snapshots(project_id,provider,channel,period_start,period_end,payload,captured_at) VALUES(?,?,?,?,?,?,?)",
        (project_id, "ga4", "analytics", start.isoformat(), end.isoformat(), json.dumps(payload, ensure_ascii=False), ts)
    )
    for metric in metrics:
        conn.execute(
            "INSERT INTO metric_points(project_id,channel,source,metric,dimension,value,captured_at) VALUES(?,?,?,?,?,?,?)",
            (project_id, "analytics", "ga4", metric, "all_traffic", float(current_total.get(metric) or 0), ts)
        )
        conn.execute(
            "INSERT INTO metric_points(project_id,channel,source,metric,dimension,value,captured_at) VALUES(?,?,?,?,?,?,?)",
            (project_id, "analytics", "ga4", metric, "organic_search", float(current_organic.get(metric) or 0), ts)
        )

    config["last_period"] = payload["period"]
    # Re-check the currently selected stream before calling the connector trustworthy.
    conn2 = db()
    project = conn2.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn2.close()
    selected_row = next((x for x in config.get("available_properties") or [] if str(x.get("property") or "") == str(prop)), {})
    if project:
        checked = ga4_selected_config(token, selected_row or {"property": prop}, project["site_url"])
        config["selected_domain_verified"] = bool(checked.get("domainVerified"))
        config["selected_verified_uri"] = checked.get("verifiedUri") or ""
        config["selected_measurement_ids"] = checked.get("measurementIds") or []
        config["selected_stream_hosts"] = checked.get("streamHosts") or []
    config["write_enabled"] = (
        GA4_EDIT_SCOPE in str(integration_secret(project_id, "ga4").get("scope") or "").split()
        and bool(config.get("selected_can_edit"))
        and bool(config.get("selected_domain_verified"))
    )
    upsert_integration(conn, project_id, "ga4", "analytics", "connected", config, ts)
    add_activity(
        conn, project_id, "data", "Google Analytics 4 synchronizována",
        f"Celý web: {int(current_total.get('activeUsers') or 0)} aktivních uživatelů. "
        f"Organic Search: {int(current_organic.get('sessions') or 0)} sessions, "
        f"{float(current_organic.get('keyEvents') or 0):.0f} klíčových událostí."
    )
    trim_analytics_history(conn, project_id, "ga4")
    commerce_analytics.record_snapshot(conn, project_id, "ga4", payload, DB_BACKEND, ts)
    conn.commit()
    conn.close()
    return payload


def gsc_sitemaps(project_id):
    integ=integration_row(project_id,"search_console"); config=integration_config(integ); prop=config.get("selected_property")
    if not prop: return []
    token=google_refresh_access(project_id,"search_console"); encoded=quote(prop,safe="")
    return google_api_get(f"https://www.googleapis.com/webmasters/v3/sites/{encoded}/sitemaps",token).get("sitemap") or []


def inspect_search_console_url(project_id, inspection_url):
    integ=integration_row(project_id,"search_console"); config=integration_config(integ); prop=config.get("selected_property")
    if not prop: raise ValueError("Vyber Search Console property.")
    token=google_refresh_access(project_id,"search_console")
    return google_api_post("https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",token,{"inspectionUrl":inspection_url,"siteUrl":prop,"languageCode":"cs-CZ"})


def create_connector_action(project_id, provider, operation, proposal, reason, expected_outcome, target_url="", target_id=""):
    conn=db(); proposal_json=json.dumps(proposal or {},ensure_ascii=False)
    cur=conn.execute("""INSERT INTO actions(project_id,channel,action_type,target_type,target_id,target_url,reason,before_json,proposed_json,ai_proposal_json,status,expected_metric,expected_outcome,provider,operation,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(project_id,"analytics" if provider=="ga4" else "seo","connector_action",provider,str(target_id or ""),target_url,reason,"{}",proposal_json,proposal_json,"draft",provider,expected_outcome,provider,operation,now()))
    aid=cur.lastrowid; save_action_revision(conn,project_id,aid,"boban",proposal); add_activity(conn,project_id,"action",f"{provider} změna připravena",f"Úkol #{aid}; {operation}; čeká na kontrolu."); conn.commit(); conn.close(); return aid


def apply_connector_action(project, action):
    provider=str(action["provider"] or "fresh_core"); operation=str(action["operation"] or ""); proposal=json.loads(action["proposed_json"] or "{}")
    if provider=="search_console":
        integ=integration_row(project["id"],"search_console"); config=integration_config(integ); prop=config.get("selected_property")
        if not prop: raise ValueError("Search Console property není vybraná.")
        token=google_refresh_access(project["id"],"search_console"); encoded_prop=quote(prop,safe=""); sitemap=str(proposal.get("sitemap_url") or "").strip()
        if operation in {"submit_sitemap","delete_sitemap"}:
            if not sitemap.startswith(("https://","http://")): raise ValueError("Sitemap URL není platná.")
            endpoint=f"https://www.googleapis.com/webmasters/v3/sites/{encoded_prop}/sitemaps/{quote(sitemap,safe='')}"
            if operation=="submit_sitemap": google_api_request("PUT",endpoint,token,expected=(200,204)); return {"success":True,"provider":"search_console","operation":operation,"sitemap_url":sitemap}
            google_api_request("DELETE",endpoint,token,expected=(200,204)); return {"success":True,"provider":"search_console","operation":operation,"sitemap_url":sitemap}
    if provider=="ga4":
        integ=integration_row(project["id"],"ga4"); config=integration_config(integ); prop=str(config.get("selected_property") or "")
        if not prop: raise ValueError("GA4 property není vybraná.")
        token=google_refresh_access(project["id"],"ga4")
        if operation=="create_key_event":
            event_name=str(proposal.get("event_name") or "").strip(); counting=str(proposal.get("counting_method") or "ONCE_PER_EVENT")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}",event_name): raise ValueError("Název GA4 eventu musí začínat písmenem a používat jen písmena, číslice a podtržítko.")
            data=google_api_post(f"https://analyticsadmin.googleapis.com/v1beta/{prop}/keyEvents",token,{"eventName":event_name,"countingMethod":counting}); return {"success":True,"provider":"ga4","operation":operation,"key_event":data}
    raise ValueError(f"Operace {provider}/{operation} není povolená.")


def verify_connector_action(project, action, result=None):
    provider=str(action["provider"] or ""); operation=str(action["operation"] or ""); proposal=json.loads(action["proposed_json"] or "{}"); verification={"checked_at":now(),"provider_confirmed":False,"rendered_confirmed":False,"checks":{},"note":""}
    if provider=="search_console" and operation in {"submit_sitemap","delete_sitemap"}:
        sitemap=str(proposal.get("sitemap_url") or "").strip(); paths={str(x.get("path") or "") for x in gsc_sitemaps(project["id"])}; present=sitemap in paths; expected=(operation=="submit_sitemap"); ok=present==expected; verification.update({"provider_confirmed":ok,"rendered_confirmed":ok,"checks":{"sitemap":ok},"note":"Search Console potvrzuje požadovaný stav sitemap." if ok else "Search Console zatím nepotvrdila požadovaný stav sitemap."}); return verification
    if provider=="ga4" and operation=="create_key_event":
        integ=integration_row(project["id"],"ga4"); config=integration_config(integ); prop=str(config.get("selected_property") or ""); token=google_refresh_access(project["id"],"ga4"); data=google_api_get(f"https://analyticsadmin.googleapis.com/v1beta/{prop}/keyEvents?pageSize=200",token); name=str(proposal.get("event_name") or ""); found=any(str(x.get("eventName") or "")==name for x in data.get("keyEvents") or []); verification.update({"provider_confirmed":found,"rendered_confirmed":found,"checks":{"key_event":found},"note":"GA4 potvrzuje klíčovou událost." if found else "GA4 zatím klíčovou událost nevrátila."}); return verification
    return verification


def action_provider_ready(project, action):
    provider = str(action["provider"] or "fresh_core") if "provider" in action.keys() else "fresh_core"
    if provider in {"", "fresh_core"}:
        ready = bool(project["core_write_status"] == "connected")
        return ready, "" if ready else "Fresh Core write bridge není připojen."
    integ = integration_row(project["id"], provider)
    if not integ or integ["status"] != "connected":
        return False, f"Konektor {provider} není připojen."
    config = integration_config(integ)
    if not config.get("write_enabled"):
        return False, f"Konektor {provider} nemá oprávnění k zápisu. Připoj Google účet znovu s oprávněním pro změny."
    return True, ""


def apply_action(project, action):
    provider=str(action["provider"] or "fresh_core") if "provider" in action.keys() else "fresh_core"
    return apply_seo_action(project,action) if provider in {"","fresh_core"} else apply_connector_action(project,action)


def verify_action(project, action, result=None):
    provider=str(action["provider"] or "fresh_core") if "provider" in action.keys() else "fresh_core"
    return verify_action_on_web(project,action,result) if provider in {"","fresh_core"} else verify_connector_action(project,action,result)


# --- v0.7.3 performance + measurement connectors ---------------------------

def pagespeed_ready():
    return bool(PAGESPEED_API_KEY)


def _cwv_status(metric, value):
    if value is None:
        return "no_data"
    try:
        value = float(value)
    except Exception:
        return "no_data"
    if metric == "lcp":
        return "good" if value <= 2500 else ("needs_improvement" if value <= 4000 else "poor")
    if metric == "inp":
        return "good" if value <= 200 else ("needs_improvement" if value <= 500 else "poor")
    if metric == "cls":
        return "good" if value <= 0.1 else ("needs_improvement" if value <= 0.25 else "poor")
    return "unknown"


def _pagespeed_strategy(url, strategy="mobile"):
    if not pagespeed_ready():
        raise ValueError("PageSpeed/CrUX API key není nastavený. Doplň PAGESPEED_API_KEY nebo GOOGLE_API_KEY do .env.")
    r = requests.get(
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        params={"url": url, "strategy": strategy.lower(), "category": "performance", "key": PAGESPEED_API_KEY},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=max(HTTP_TIMEOUT, 45),
    )
    if r.status_code >= 300:
        raise ValueError(f"PageSpeed Insights selhal: HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    lighthouse = data.get("lighthouseResult") or {}
    audits = lighthouse.get("audits") or {}
    perf = ((lighthouse.get("categories") or {}).get("performance") or {}).get("score")
    def audit_value(*names):
        for name in names:
            row = audits.get(name) or {}
            if row.get("numericValue") is not None:
                return float(row.get("numericValue"))
        return None
    return {
        "strategy": strategy,
        "performance_score": round(float(perf) * 100) if perf is not None else None,
        "lab": {
            "lcp_ms": audit_value("largest-contentful-paint"),
            "cls": audit_value("cumulative-layout-shift"),
            "tbt_ms": audit_value("total-blocking-time"),
            "fcp_ms": audit_value("first-contentful-paint"),
            "speed_index_ms": audit_value("speed-index"),
        },
        "analysis_utc": lighthouse.get("fetchTime") or "",
        "final_url": lighthouse.get("finalUrl") or data.get("id") or url,
    }


def _crux_origin(origin):
    if not pagespeed_ready():
        raise ValueError("CrUX API key není nastavený.")
    payload = {
        "origin": origin.rstrip("/"),
        "metrics": ["largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift"],
    }
    r = requests.post(
        f"https://chromeuxreport.googleapis.com/v1/records:queryRecord?key={quote(PAGESPEED_API_KEY, safe='')}",
        json=payload,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json"},
        timeout=max(HTTP_TIMEOUT, 30),
    )
    if r.status_code == 404:
        return {"available": False, "reason": "CrUX pro tento origin zatím nemá dost reálných dat."}
    if r.status_code >= 300:
        raise ValueError(f"CrUX API selhalo: HTTP {r.status_code}: {r.text[:300]}")
    data = r.json(); record = data.get("record") or {}; metrics = record.get("metrics") or {}
    def p75(name):
        value = ((metrics.get(name) or {}).get("percentiles") or {}).get("p75")
        try: return float(value)
        except Exception: return None
    lcp = p75("largest_contentful_paint")
    inp = p75("interaction_to_next_paint")
    cls = p75("cumulative_layout_shift")
    return {
        "available": True,
        "lcp_ms": lcp, "inp_ms": inp, "cls": cls,
        "status": {"lcp": _cwv_status("lcp", lcp), "inp": _cwv_status("inp", inp), "cls": _cwv_status("cls", cls)},
        "collection_period": record.get("collectionPeriod") or {},
    }


def sync_pagespeed_crux(project_id):
    conn = db(); project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    if not project:
        raise ValueError("Projekt nebyl nalezen.")
    site_url = str(project["site_url"] or "").rstrip("/") + "/"
    mobile = _pagespeed_strategy(site_url, "mobile")
    desktop = _pagespeed_strategy(site_url, "desktop")
    parsed = urlparse(site_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    crux = _crux_origin(origin)
    payload = {"url": site_url, "origin": origin, "mobile": mobile, "desktop": desktop, "crux": crux, "captured_at": now()}
    conn = db(); ts = now()
    conn.execute("INSERT INTO source_snapshots(project_id,provider,channel,period_start,period_end,payload,captured_at) VALUES(?,?,?,?,?,?,?)",
                 (project_id, "pagespeed_crux", "seo", None, None, json.dumps(payload, ensure_ascii=False), ts))
    upsert_integration(conn, project_id, "pagespeed_crux", "seo", "connected", {"url": site_url, "api_key_configured": True}, ts)
    add_activity(conn, project_id, "data", "PageSpeed + CrUX aktualizováno",
                 f"Mobile Lighthouse {mobile.get('performance_score') if mobile.get('performance_score') is not None else '—'}/100; CrUX {'má data' if crux.get('available') else 'bez dat'}.")
    trim_analytics_history(conn, project_id, "pagespeed_crux")
    conn.commit(); conn.close()
    return payload


def gtm_accounts(token):
    data = google_api_get("https://tagmanager.googleapis.com/tagmanager/v2/accounts", token)
    return data.get("account") or []


def gtm_containers(token, accounts):
    out = []
    for account in accounts or []:
        path = str(account.get("path") or "")
        if not path:
            aid = str(account.get("accountId") or "")
            path = f"accounts/{aid}" if aid else ""
        if not path:
            continue
        try:
            data = google_api_get(f"https://tagmanager.googleapis.com/tagmanager/v2/{path}/containers", token)
        except Exception:
            continue
        for c in data.get("container") or []:
            row = dict(c)
            row["accountName"] = account.get("name") or account.get("accountId") or ""
            row["accountPath"] = path
            out.append(row)
    return out


def _gtm_candidate_score(row, site_url):
    host = normalize_host(site_url); stem = host.split(".")[0] if host else ""
    text = " ".join([str(row.get("name") or ""), str(row.get("publicId") or ""), str(row.get("accountName") or "")]).lower()
    contexts = [str(x).lower() for x in (row.get("usageContext") or [])]
    score = 10 if "web" in contexts else 0
    if host and host in text: score += 100
    if stem and len(stem) >= 4 and stem in text: score += 35
    return score


def connect_gtm_with_creds(project_id, creds):
    token = creds.get("access_token")
    if not token:
        raise ValueError("Google nepředal access token.")
    conn = db(); project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    accounts = gtm_accounts(token); containers = gtm_containers(token, accounts)
    containers.sort(key=lambda x: (_gtm_candidate_score(x, project["site_url"]), str(x.get("name") or "")), reverse=True)
    web = [x for x in containers if "web" in [str(v).lower() for v in (x.get("usageContext") or [])]]
    selected = ""
    if len(web) == 1:
        selected = str(web[0].get("path") or "")
    elif containers and _gtm_candidate_score(containers[0], project["site_url"]) >= 35:
        selected = str(containers[0].get("path") or "")
    config = {"available_containers": containers, "selected_container": selected, "container_count": len(containers), "read_only": True}
    conn = db(); upsert_integration(conn, project_id, "gtm", "analytics", "connected" if selected else "needs_selection", config, now())
    add_activity(conn, project_id, "connector", "Google Tag Manager připojen", f"Nalezeno {len(containers)} kontejnerů. Zápis je v 0.7.3 záměrně vypnutý.")
    conn.commit(); conn.close()
    update_integration_secret(project_id, "gtm", creds, creds.get("scope", ""))
    return config


def sync_gtm(project_id):
    integ = integration_row(project_id, "gtm")
    if not integ:
        raise ValueError("Google Tag Manager není připojen.")
    config = integration_config(integ); path = str(config.get("selected_container") or "")
    if not path:
        raise ValueError("Vyber GTM kontejner.")
    token = google_refresh_access(project_id, "gtm")
    workspaces = google_api_get(f"https://tagmanager.googleapis.com/tagmanager/v2/{path}/workspaces", token).get("workspace") or []
    workspace = next((x for x in workspaces if str(x.get("name") or "").lower() == "default workspace"), None) or (workspaces[0] if workspaces else None)
    if not workspace:
        raise ValueError("GTM kontejner nemá dostupný workspace.")
    wpath = str(workspace.get("path") or "")
    tags = google_api_get(f"https://tagmanager.googleapis.com/tagmanager/v2/{wpath}/tags", token).get("tag") or []
    triggers = google_api_get(f"https://tagmanager.googleapis.com/tagmanager/v2/{wpath}/triggers", token).get("trigger") or []
    variables = google_api_get(f"https://tagmanager.googleapis.com/tagmanager/v2/{wpath}/variables", token).get("variable") or []
    blob = json.dumps({"tags": tags, "triggers": triggers, "variables": variables}, ensure_ascii=False).lower()
    ids = sorted(set(re.findall(r"(?:g-[a-z0-9]{6,}|aw-[0-9]{6,}|gtm-[a-z0-9]+)", blob, flags=re.I)))
    signals = {
        "ga4_like": len(re.findall(r"ga4|google analytics|googletag|google tag", blob)),
        "google_ads_like": len(re.findall(r"google ads|conversion linker|aw-[0-9]", blob)),
        "forms_like": len(re.findall(r"form|lead|submit|generate_lead", blob)),
        "phone_like": len(re.findall(r"tel:|phone|telefon|call", blob)),
        "purchase_like": len(re.findall(r"purchase|transaction|ecommerce|begin_checkout", blob)),
    }
    findings = []
    if not tags:
        findings.append({"level": "warning", "title": "GTM workspace neobsahuje žádné tagy", "detail": "Měření může být nasazené mimo GTM, nebo kontejner není správný."})
    if signals["ga4_like"] == 0:
        findings.append({"level": "info", "title": "V GTM nevidím zjevný GA4 tag", "detail": "GA4 může být nasazena jiným způsobem. Boban to nebude označovat jako chybu bez dalšího ověření."})
    if signals["forms_like"] == 0:
        findings.append({"level": "opportunity", "title": "Nevidím zjevné měření formulářů / leadů", "detail": "Pokud je poptávka obchodní cíl webu, prověříme měření konverze."})
    payload = {"container": path, "container_public_id": next((x.get("publicId") for x in config.get("available_containers") or [] if x.get("path") == path), ""),
               "workspace": workspace, "counts": {"tags": len(tags), "triggers": len(triggers), "variables": len(variables)},
               "measurement_ids": ids, "signals": signals, "findings": findings,
               "tags": [{"name": x.get("name"), "type": x.get("type"), "tagId": x.get("tagId")} for x in tags[:200]], "captured_at": now()}
    conn = db(); ts=now(); conn.execute("INSERT INTO source_snapshots(project_id,provider,channel,period_start,period_end,payload,captured_at) VALUES(?,?,?,?,?,?,?)",
        (project_id, "gtm", "analytics", None, None, json.dumps(payload, ensure_ascii=False), ts))
    config["last_workspace"] = wpath; config["read_only"] = True
    upsert_integration(conn, project_id, "gtm", "analytics", "connected", config, ts)
    add_activity(conn, project_id, "data", "GTM audit dokončen", f"{len(tags)} tagů, {len(triggers)} triggerů, {len(variables)} proměnných. Bez zápisu.")
    trim_analytics_history(conn, project_id, "gtm")
    conn.commit(); conn.close(); return payload


AI_ACTIONABLE_CODES = {
    "seo_title_missing",
    "meta_description_missing",
    "rendered_title_missing",
    "rendered_description_missing",
    "duplicate_seo_title",
    "duplicate_rendered_title",
    "duplicate_meta_description",
    "duplicate_rendered_description",
    "seo_title_length",
    "meta_description_length",
    "canonical_missing",
    "rendered_canonical_missing",
    "image_alt_missing",
    "missing_alt",
}

AI_METADATA_CODES = {
    "seo_title_missing", "meta_description_missing", "rendered_title_missing", "rendered_description_missing",
    "duplicate_seo_title", "duplicate_rendered_title", "duplicate_meta_description", "duplicate_rendered_description",
    "seo_title_length", "meta_description_length",
}
TITLE_ACTION_CODES = {
    "seo_title_missing", "rendered_title_missing", "duplicate_seo_title", "duplicate_rendered_title", "seo_title_length",
}
DESCRIPTION_ACTION_CODES = {
    "meta_description_missing", "rendered_description_missing", "duplicate_meta_description", "duplicate_rendered_description", "meta_description_length",
}
DETERMINISTIC_ACTION_CODES = {"canonical_missing", "rendered_canonical_missing"}
IMAGE_ACTION_CODES = {"image_alt_missing"}


def seo_item_map(project):
    snapshot = project_snapshot(project)
    return {str(x.get("id")): x for x in seo_items_from_snapshot(snapshot) if x.get("id") is not None}


def image_item_map(project):
    out = {}
    for page in seo_items_from_snapshot(project_snapshot(project)):
        page_url = str(page.get("url") or "")
        for image in page.get("images") or []:
            image_id = str(image.get("id") or "")
            if not image_id:
                continue
            # The same attachment can occur on several pages. Keep the first page
            # as the verification target; the ALT value itself is attachment-level.
            out.setdefault(image_id, {"image": image, "page": page, "page_url": page_url})
    return out


def _media_url_key(value):
    try:
        parsed = urlparse(str(value or ""))
        path = unquote(parsed.path or "").lower()
        path = re.sub(r"-\d+x\d+(?=\.[a-z0-9]+$)", "", path)
        return path.rstrip("/")
    except Exception:
        return str(value or "").split("?", 1)[0].lower().rstrip("/")


def _issue_context(row):
    try:
        raw = row["context_json"] if "context_json" in row.keys() else None
    except Exception:
        raw = None
    try:
        return json.loads(raw or "{}") if raw else {}
    except Exception:
        return {}


def resolve_core_image(project, image_url):
    """Resolve a rendered image URL to a WordPress attachment through Fresh Core.

    This is intentionally a read-like lookup behind the already configured write
    bridge. It lets the crawler discover an image first and Boban still prepare a
    safe attachment-level ALT action later.
    """
    if not image_url or project["core_write_status"] != "connected":
        return {}
    base = (project["core_write_endpoint"] or "").rstrip("/")
    key = decrypt_secret(project["core_write_key_enc"])
    if not base or not key:
        return {}
    try:
        r = requests.post(
            base + "/media/resolve",
            json={"image_url": image_url},
            headers={"X-Fresh-Core-Write-Key": key, "User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=(5, min(CORE_WRITE_TIMEOUT, 20)),
        )
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {}
        if r.status_code >= 300 or not data.get("success"):
            return {}
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _extract_engine_payload(data):
    if isinstance(data, dict):
        # Chat-first responses may intentionally carry executable metadata next
        # to the human answer. Preserve that envelope instead of unwrapping only
        # the answer string. Other engine tasks keep the legacy unwrapping below.
        if ("strategy_update" in data or "command" in data) and any(k in data for k in ("answer", "text", "message", "content")):
            return data
        for key in ("result", "output", "content", "text", "answer", "response", "payload"):
            if key in data:
                value = data[key]
                if isinstance(value, (dict, list)):
                    return _extract_engine_payload(value)
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except Exception:
                        m = re.search(r"```(?:json)?\s*(.*?)```", value, re.S | re.I)
                        if m:
                            try:
                                return json.loads(m.group(1))
                            except Exception:
                                pass
                        brace = re.search(r"(\{.*\})", value, re.S)
                        if brace:
                            try:
                                return json.loads(brace.group(1))
                            except Exception:
                                pass
                        return value
        if "data" in data:
            return _extract_engine_payload(data["data"])
    return data


def _engine_meta(raw):
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    if not usage and isinstance(data.get("usage"), dict):
        usage = data.get("usage")
    return {
        "run_id": raw.get("run_id") or raw.get("id") or data.get("run_id") or data.get("id"),
        "provider": raw.get("provider") or data.get("provider"),
        "model": raw.get("model") or data.get("model"),
        "cost_usd": raw.get("cost_usd") or data.get("cost_usd") or usage.get("cost_usd") or usage.get("cost"),
        "usage": usage or None,
    }


def _record_engine_run(project_id, task_type, status, http_status=None, latency_ms=None, raw=None, error_text=None):
    meta = _engine_meta(raw)
    try:
        conn = db()
        conn.execute(
            """INSERT INTO engine_runs(project_id,task_type,status,http_status,run_id,provider,model,latency_ms,cost_usd,error_text,response_meta_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id, task_type, status, http_status, meta.get("run_id"), meta.get("provider"), meta.get("model"),
                latency_ms, meta.get("cost_usd"), error_text,
                json.dumps({k: v for k, v in meta.items() if k != "cost_usd"}, ensure_ascii=False), now()
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def call_fresh_ai_engine(project, task_type, prompt, context, max_cost_usd=0.50):
    base = (os.getenv("FRESH_AI_ENGINE_URL") or "").rstrip("/")
    key = os.getenv("FRESH_AI_ENGINE_API_KEY") or ""
    if not base or not key:
        raise ValueError("Fresh AI Engine není nakonfigurovaný v .env.")
    payload = {
        "source": "webbooster",
        "project_id": f"webbooster:{project['id']}",
        "task_type": task_type,
        "quality": "balanced",
        "prompt": prompt,
        "context": context,
        "max_cost_usd": max_cost_usd,
    }
    started = time.perf_counter()
    try:
        r = requests.post(
            base + "/v1/engine/run",
            json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
            timeout=max(HTTP_TIMEOUT, 30),
        )
    except Exception as exc:
        latency = int((time.perf_counter() - started) * 1000)
        _record_engine_run(project["id"], task_type, "network_error", latency_ms=latency, error_text=str(exc))
        raise ValueError(f"Fresh AI Engine není dostupný: {exc}") from exc

    latency = int((time.perf_counter() - started) * 1000)
    try:
        raw = r.json()
    except Exception:
        raw = {"raw": r.text[:3000]}

    if r.status_code >= 300:
        _record_engine_run(project["id"], task_type, "http_error", http_status=r.status_code, latency_ms=latency, raw=raw, error_text=r.text[:1000])
        raise ValueError(f"Fresh AI Engine vrátil HTTP {r.status_code}: {r.text[:500]}")

    _record_engine_run(project["id"], task_type, "completed", http_status=r.status_code, latency_ms=latency, raw=raw)
    return _extract_engine_payload(raw)


def expected_outcome_for_changes(changes, action_type="update_meta"):
    fields = set(changes or {})
    parts = []
    if action_type == "update_image_alt" or "alt" in fields:
        parts.append("Smysluplný ALT text zlepší přístupnost obrázku a dá vyhledávačům přesnější kontext obrázku i stránky.")
    if "title" in fields:
        parts.append("Přesnější title má lépe vystihnout téma stránky a může zlepšit relevanci i proklikovost ve výsledcích vyhledávání.")
    if "description" in fields:
        parts.append("Srozumitelnější meta description má zlepšit podobu úryvku ve vyhledávači a může zvýšit CTR.")
    if "canonical" in fields:
        parts.append("Nastavím pouze canonical na preferovanou URL. SEO title ani meta description se tím nemění; cílem je omezit nejasnosti u duplicitních adres.")
    if "noindex" in fields or "nofollow" in fields:
        parts.append("Změna indexačních pravidel má upravit, jak vyhledávače stránku zpracují; výsledek je nutné ověřit crawlerem.")
    return " ".join(parts) or "Očekáváme odstranění konkrétního SEO problému; technické provedení ověří Web Booster a výkon změří analytika."


def save_action_revision(conn, project_id, action_id, author_type, values):
    conn.execute(
        "INSERT INTO action_revisions(action_id,project_id,author_type,values_json,created_at) VALUES(?,?,?,?,?)",
        (action_id, project_id, author_type, json.dumps(values or {}, ensure_ascii=False), now())
    )


def create_or_merge_action(project_id, target_id, target_url, changes, reason, before=None, expected_metric="search_console",
                           expected_outcome=None, issue_id=None, action_type="update_meta", target_type="wordpress_post"):
    """Reuse an editable Boban proposal for the same target instead of piling up duplicates.

    User edits always win for fields already present. Boban may add newly discovered
    fields (for example description after title) to the same draft.
    """
    target_id = str(target_id)
    conn = db()
    existing = conn.execute(
        """SELECT * FROM actions
           WHERE project_id=? AND target_type=? AND target_id=? AND action_type=?
             AND status IN ('draft','approved','failed')
           ORDER BY id DESC LIMIT 1""",
        (project_id, target_type, target_id, action_type)
    ).fetchone()
    if existing:
        try:
            current = json.loads(existing["proposed_json"] or "{}")
        except Exception:
            current = {}
        try:
            ai_current = json.loads(existing["ai_proposal_json"] or "{}")
        except Exception:
            ai_current = {}
        user_edited = bool(existing["user_edited_at"])
        merged = dict(current)
        ai_merged = dict(ai_current)
        changed = False
        for field, value in (changes or {}).items():
            ai_merged[field] = value
            # Once a user edited the card, keep their existing values and only
            # add fields that are not yet present.
            if field not in merged or not user_edited:
                if merged.get(field) != value:
                    merged[field] = value
                    changed = True
        if changed or set((changes or {}).keys()) - set(current.keys()):
            conn.execute(
                """UPDATE actions
                   SET proposed_json=?,ai_proposal_json=?,reason=?,expected_outcome=?,
                       issue_id=COALESCE(issue_id,?),status='draft',last_error=NULL
                   WHERE id=?""",
                (
                    json.dumps(merged, ensure_ascii=False),
                    json.dumps(ai_merged, ensure_ascii=False),
                    reason,
                    expected_outcome or expected_outcome_for_changes(merged, action_type),
                    issue_id,
                    existing["id"],
                )
            )
            save_action_revision(conn, project_id, existing["id"], "boban", ai_merged)
            add_activity(
                conn, project_id, "action", "SEO návrh doplněn",
                f"Úkol #{existing['id']} jsem doplnil o další související změny místo vytváření duplicitního úkolu."
            )
        conn.commit()
        action_id = int(existing["id"])
        conn.close()
        return action_id

    # If the same target is already being published/verified and the new request
    # does not add a new field, point to the existing task instead of duplicating it.
    inflight = conn.execute(
        """SELECT * FROM actions
           WHERE project_id=? AND target_type=? AND target_id=? AND action_type=?
             AND status IN ('queued','pending','applied','verified')
           ORDER BY id DESC LIMIT 1""",
        (project_id, target_type, target_id, action_type)
    ).fetchone()
    if inflight:
        try:
            inflight_values = json.loads(inflight["proposed_json"] or "{}")
        except Exception:
            inflight_values = {}
        if set((changes or {}).keys()).issubset(set(inflight_values.keys())):
            action_id = int(inflight["id"])
            conn.close()
            return action_id

    recent_done = conn.execute(
        """SELECT * FROM actions
           WHERE project_id=? AND target_type=? AND target_id=? AND action_type=?
             AND status IN ('verified','completed')
           ORDER BY id DESC LIMIT 1""",
        (project_id, target_type, target_id, action_type)
    ).fetchone()
    if recent_done:
        stamp = recent_done["verified_at"] or recent_done["completed_at"] or recent_done["applied_at"] or recent_done["created_at"]
        try:
            is_recent = bool(stamp and datetime.fromisoformat(str(stamp)) >= datetime.now() - timedelta(days=30))
        except Exception:
            is_recent = False
        if is_recent:
            try:
                previous_changes = json.loads(recent_done["proposed_json"] or "{}")
            except Exception:
                previous_changes = {}
            same_values = all(
                json.dumps(previous_changes.get(k), sort_keys=True, ensure_ascii=False) == json.dumps(v, sort_keys=True, ensure_ascii=False)
                for k, v in (changes or {}).items()
            )
            same_issue = bool(issue_id and recent_done["issue_id"] and int(recent_done["issue_id"]) == int(issue_id))
            if same_values or same_issue:
                action_id = int(recent_done["id"])
                conn.close()
                return action_id
    conn.close()
    return create_action(
        project_id, target_id, target_url, changes, reason, before=before,
        expected_metric=expected_metric, expected_outcome=expected_outcome,
        issue_id=issue_id, action_type=action_type, target_type=target_type
    )


def create_action(project_id, target_id, target_url, changes, reason, before=None, expected_metric="search_console",
                  expected_outcome=None, issue_id=None, action_type="update_meta", target_type="wordpress_post"):
    conn = db()
    proposal_json = json.dumps(changes, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO actions(project_id,channel,action_type,target_type,target_id,target_url,reason,before_json,proposed_json,ai_proposal_json,status,expected_metric,expected_outcome,issue_id,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            project_id, "seo", action_type, target_type, str(target_id), target_url,
            reason, json.dumps(before or {}, ensure_ascii=False), proposal_json, proposal_json,
            "draft", expected_metric, expected_outcome or expected_outcome_for_changes(changes, action_type), issue_id, now()
        )
    )
    action_id = cur.lastrowid
    save_action_revision(conn, project_id, action_id, "boban", changes)
    label = "obrázek" if action_type == "update_image_alt" else "WordPress stránka"
    add_activity(conn, project_id, "action", "SEO úkol připraven", f"Úkol #{action_id}; {label} ID {target_id}. Čeká na tvoji kontrolu a schválení.")
    conn.commit()
    conn.close()
    return action_id


def _ai_page_context(url, project_site_url):
    if not url:
        return {}
    try:
        host = urlparse(project_site_url).hostname or ""
        r = fetch_html(url, host)
        soup = BeautifulSoup(r.text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        h1 = " ".join(x.get_text(" ", strip=True) for x in soup.find_all("h1")[:3])
        text = " ".join(soup.get_text(" ", strip=True).split())
        return {
            "rendered_title": soup.title.get_text(" ", strip=True) if soup.title else "",
            "h1": h1,
            "text_excerpt": text[:3500],
        }
    except Exception as exc:
        return {"context_error": str(exc)[:300]}


def _find_proposal_items(value):
    if isinstance(value, list):
        if value and all(isinstance(x, dict) for x in value):
            return value
        for item in value:
            found = _find_proposal_items(item)
            if found:
                return found
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return items
        for key in ("result", "data", "output", "response", "content", "payload"):
            if key in value:
                found = _find_proposal_items(value[key])
                if found:
                    return found
    if isinstance(value, str):
        try:
            return _find_proposal_items(json.loads(value))
        except Exception:
            return []
    return []


def ai_prepare_issue_actions(project, issue_rows, auto_apply=False):
    issue_rows = [r for r in issue_rows if r["code"] in AI_ACTIONABLE_CODES]
    if not issue_rows:
        raise ValueError("Vybrané body zatím nejdou bezpečně připravit.")
    issue_rows = issue_rows[:AI_BATCH_LIMIT]

    # When the user asks Boban to solve one metadata problem on a page, include
    # the other open publishable metadata/indexing findings for the same page.
    # This avoids creating separate title/description/canonical cards for one URL.
    selected_page_ids = sorted({
        str(r["entity_id"] or "") for r in issue_rows
        if r["code"] not in IMAGE_ACTION_CODES and r["code"] != "missing_alt" and str(r["entity_id"] or "").isdigit()
    })
    if selected_page_ids:
        conn = db()
        entity_marks = ",".join("?" for _ in selected_page_ids)
        sibling_codes = sorted(AI_METADATA_CODES | DETERMINISTIC_ACTION_CODES)
        code_marks = ",".join("?" for _ in sibling_codes)
        siblings = conn.execute(
            f"""SELECT * FROM issues
                WHERE project_id=? AND status='open'
                  AND entity_id IN ({entity_marks})
                  AND code IN ({code_marks})
                ORDER BY id""",
            [project["id"], *selected_page_ids, *sibling_codes]
        ).fetchall()
        conn.close()
        merged_rows = {int(r["id"]): r for r in issue_rows}
        for r in siblings:
            merged_rows[int(r["id"])] = r
        issue_rows = list(merged_rows.values())

    items_map = seo_item_map(project)
    images_map = image_item_map(project)
    created = []

    # One page = one proposal. If the same page is missing both title and
    # description, Boban prepares one coherent task instead of two competing tasks.
    page_groups = {}
    image_rows = []
    for row in issue_rows:
        if row["code"] in IMAGE_ACTION_CODES or row["code"] == "missing_alt":
            image_rows.append(row)
            continue
        if not str(row["entity_id"] or "").isdigit():
            continue
        page_groups.setdefault(str(row["entity_id"]), []).append(row)

    ai_page_contexts = []
    page_plan = {}
    for post_id, rows in page_groups.items():
        item = items_map.get(post_id, {})
        seo = item.get("seo") or {}
        codes = {r["code"] for r in rows}
        changes = {}
        required_fields = []
        if codes & TITLE_ACTION_CODES:
            required_fields.append("title")
        if codes & DESCRIPTION_ACTION_CODES:
            required_fields.append("description")
        if codes & DETERMINISTIC_ACTION_CODES:
            page_url = str(item.get("url") or rows[0]["target_url"] or "").strip()
            if page_url:
                changes["canonical"] = page_url
        page_plan[post_id] = {"rows": rows, "item": item, "changes": changes, "required_fields": required_fields}
        if required_fields:
            page_url = str(item.get("url") or rows[0]["target_url"] or "")
            ai_page_contexts.append({
                "post_id": post_id,
                "issue_ids": [r["id"] for r in rows],
                "issue_codes": sorted(codes),
                "required_fields": required_fields,
                "url": page_url,
                "page_role": item.get("page_role") or "",
                "wp_title": item.get("wp_title") or item.get("title") or "",
                "current_title": seo.get("title") or "",
                "current_description": seo.get("description") or "",
                "fallback_description": seo.get("fallback_description") or "",
                "word_count": item.get("word_count") or 0,
                "page_context": _ai_page_context(page_url, project["site_url"]),
            })

    proposals_by_post = {}
    if ai_page_contexts:
        prompt = (
            "Jsi Boban, SEO specialista. Připrav finální návrhy SEO metadat pro uvedené WordPress stránky. "
            "Vrať pouze JSON objekt {\"items\":[...]} bez markdownu. Každá položka musí obsahovat post_id a changes. "
            "V changes vrať pouze pole uvedená v required_fields (title a/nebo description). "
            "Pokud stránka potřebuje obě pole, navrhni je společně tak, aby si obsahově odpovídala. "
            "Title piš přirozeně česky, konkrétně a bez keyword stuffingu. Description stručně vysvětli hodnotu stránky. "
            "Vždy používej správnou českou diakritiku a Unicode. Nevymýšlej tvrzení, která nejsou v dodaném kontextu. "
            "Když nemáš dost podkladů pro konkrétní pole, vynech ho. Volitelně přidej expected_outcome."
        )
        result = call_fresh_ai_engine(
            project, "seo_metadata_optimize", prompt,
            {"site_url": project["site_url"], "items": ai_page_contexts}, max_cost_usd=0.75,
        )
        for proposal in _find_proposal_items(result):
            if isinstance(proposal, dict):
                proposals_by_post[str(proposal.get("post_id") or "")] = proposal

    for post_id, plan in page_plan.items():
        changes = dict(plan["changes"])
        proposal = proposals_by_post.get(post_id) or {}
        ai_changes = proposal.get("changes") if isinstance(proposal.get("changes"), dict) else {}
        for field in plan["required_fields"]:
            value = str(ai_changes.get(field) or "").strip()
            if value:
                changes[field] = value
        if not changes:
            continue
        rows = plan["rows"]
        item = plan["item"]
        created.append(create_or_merge_action(
            project["id"], post_id, str(item.get("url") or rows[0]["target_url"] or ""), changes,
            "Boban připravil jeden společný návrh pro: " + ", ".join(sorted({r["title"] for r in rows})),
            before=item.get("seo") or {}, expected_outcome=str(proposal.get("expected_outcome") or "").strip() or None,
            issue_id=rows[0]["id"], action_type="update_meta", target_type="wordpress_post",
        ))

    # Image ALT tasks can originate either from Fresh Core (attachment id known)
    # or from the rendered crawler (image URL known). For crawler findings we
    # resolve the URL through Fresh Core before creating a publishable action.
    if image_rows:
        prepared_images = []
        seen_attachments = set()
        for row in image_rows:
            context = _issue_context(row)
            mapped = images_map.get(str(row["entity_id"])) or {}
            image = mapped.get("image") or {}
            page = mapped.get("page") or {}
            attachment_id = str(row["entity_id"] or "") if str(row["entity_id"] or "").isdigit() else ""
            page_url = str(mapped.get("page_url") or context.get("page_url") or row["target_url"] or "")

            if not image:
                image_url = str(context.get("image_url") or "")
                resolved = resolve_core_image(project, image_url)
                rid = str(resolved.get("attachment_id") or resolved.get("id") or "")
                item = resolved.get("item") if isinstance(resolved.get("item"), dict) else {}
                if rid.isdigit():
                    attachment_id = rid
                    image = item or {
                        "id": int(rid), "url": image_url, "filename": context.get("filename") or "",
                        "alt": context.get("current_alt") or "", "caption": context.get("caption") or "",
                        "title": context.get("image_title") or "",
                    }
            if not attachment_id.isdigit() or not image or attachment_id in seen_attachments:
                continue
            seen_attachments.add(attachment_id)
            prepared_images.append({"row": row, "attachment_id": attachment_id, "image": image, "page": page, "page_url": page_url, "context": context})

        image_contexts = []
        for entry in prepared_images:
            image = entry["image"]
            page = entry["page"]
            context = entry["context"]
            image_contexts.append({
                "issue_id": entry["row"]["id"],
                "attachment_id": entry["attachment_id"],
                "image_url": image.get("url") or context.get("image_url") or "",
                "filename": image.get("filename") or context.get("filename") or "",
                "current_alt": image.get("alt") or context.get("current_alt") or "",
                "caption": image.get("caption") or context.get("caption") or "",
                "image_title": image.get("title") or context.get("image_title") or "",
                "page_url": entry["page_url"],
                "page_title": page.get("wp_title") or context.get("page_title") or "",
                "page_excerpt": page.get("excerpt") or context.get("page_excerpt") or context.get("nearby_text") or "",
            })
        if image_contexts:
            prompt = (
                "Jsi Boban, SEO specialista se zaměřením na přístupnost obrázků. Pro každý obrázek navrhni ALT text. "
                "Vrať pouze JSON {\"items\":[{\"attachment_id\":123,\"alt\":\"...\"}]}. "
                "ALT popiš věcně podle dostupného kontextu stránky a obrázku, česky, s diakritikou, obvykle jednou krátkou větou nebo frází. "
                "Nepřidávej slova jako obrázek/fotografie, pokud nejsou významově potřeba, a nepoužívej keyword stuffing. "
                "Nevymýšlej detaily, které z kontextu neznáš. Pokud z dat nelze smysluplný ALT určit, položku vynech."
            )
            result = call_fresh_ai_engine(
                project, "seo_image_alt_optimize", prompt,
                {"site_url": project["site_url"], "items": image_contexts}, max_cost_usd=0.50,
            )
            by_attachment = {str(x.get("attachment_id") or ""): x for x in _find_proposal_items(result) if isinstance(x, dict)}
            for entry in prepared_images:
                row = entry["row"]
                image = entry["image"]
                attachment_id = entry["attachment_id"]
                proposal = by_attachment.get(attachment_id) or {}
                alt = str(proposal.get("alt") or "").strip()
                if not alt:
                    continue
                page_url = entry["page_url"]
                before = {
                    "alt": image.get("alt") or "", "image_url": image.get("url") or entry["context"].get("image_url") or "",
                    "filename": image.get("filename") or entry["context"].get("filename") or "", "page_url": page_url,
                }
                created.append(create_or_merge_action(
                    project["id"], attachment_id, page_url, {"alt": alt},
                    f"Boban připravil ALT text pro {before.get('filename') or 'obrázek'}.",
                    before=before, expected_metric="accessibility", issue_id=row["id"],
                    action_type="update_image_alt", target_type="wordpress_attachment",
                ))

    if not created:
        raise ValueError("Boban pro vybrané položky nepřipravil bezpečně použitelnou změnu.")

    applied = 0
    if auto_apply:
        queued = queue_seo_apply_jobs(project["id"], created)
        applied = queued["count"]
    return created, applied


def grouped_findings(project_id, category=None, kind=None, pillar=None):
    conn = db()
    params = [project_id]
    where = "project_id=? AND status='open'"
    if pillar in PILLAR_CATEGORIES and PILLAR_CATEGORIES.get(pillar):
        categories = sorted(PILLAR_CATEGORIES[pillar])
        marks = ",".join("?" for _ in categories)
        where += f" AND category IN ({marks})"
        params.extend(categories)
    elif category:
        where += " AND category=?"
        params.append(category)
    if kind:
        where += " AND kind=?"
        params.append(kind)
    rows = conn.execute(
        f"""
        SELECT source,code,category,kind,
               CASE MIN(CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END)
                    WHEN 1 THEN 'critical' WHEN 2 THEN 'high' WHEN 3 THEN 'medium' ELSE 'low' END AS severity,
               MIN(title) AS title, MIN(detail) AS detail, COUNT(*) AS count
        FROM issues
        WHERE {where}
        GROUP BY source,code,category,kind
        ORDER BY
            CASE kind WHEN 'error' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
            CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
            count DESC
        """,
        params
    ).fetchall()
    conn.close()
    return rows


def finding_rows(project_id, code, source=None, limit=500):
    conn = db()
    if source:
        rows = conn.execute(
            "SELECT * FROM issues WHERE project_id=? AND status='open' AND code=? AND source=? ORDER BY id DESC LIMIT ?",
            (project_id, code, source, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM issues WHERE project_id=? AND status='open' AND code=? ORDER BY id DESC LIMIT ?",
            (project_id, code, limit)
        ).fetchall()
    conn.close()
    return rows


def expire_snoozes(project_id=None):
    conn = db()
    params = [now()]
    where = "snoozed_until IS NOT NULL AND snoozed_until<=?"
    if project_id is not None:
        where += " AND project_id=?"
        params.append(project_id)
    conn.execute(f"UPDATE issues SET status='stale',snoozed_until=NULL WHERE status='snoozed' AND {where}", params)
    conn.execute(f"UPDATE actions SET status='draft',snoozed_until=NULL WHERE status='snoozed' AND {where}", params)
    conn.commit(); conn.close()


def suppressed_issue_count(project_id):
    conn = db()
    row = conn.execute(
        "SELECT COUNT(*) c FROM issues WHERE project_id=? AND status IN ('snoozed','dismissed')",
        (project_id,)
    ).fetchone()
    conn.close()
    return int(row["c"] if row else 0)


def hidden_issue_rows(project_id, limit=500):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM issues WHERE project_id=? AND status IN ('snoozed','dismissed') ORDER BY decision_at DESC,id DESC LIMIT ?",
        (project_id, limit)
    ).fetchall()
    conn.close()
    return rows


def count_by_kind(project_id):
    result = {"error": 0, "warning": 0, "opportunity": 0}
    conn = db()
    rows = conn.execute(
        "SELECT kind,COUNT(*) c FROM issues WHERE project_id=? AND status='open' GROUP BY kind",
        (project_id,)
    ).fetchall()
    conn.close()
    for row in rows:
        result[row["kind"] or "warning"] = int(row["c"])
    return result


def category_scores(project_id):
    return seo_scorecard(project_id).get("categories", {})



def reconcile_project_state(project_id):
    """Clean obvious leftovers without deleting history.

    - closes linked findings already verified by Boban
    - hides duplicate pending tasks when the exact same proposal is already finished
    """
    conn = db()
    done = conn.execute(
        "SELECT * FROM actions WHERE project_id=? AND status IN ('verified','completed') ORDER BY id DESC",
        (project_id,)
    ).fetchall()
    for a in done:
        verified_at = a["verified_at"] or a["applied_at"] or a["completed_at"] or now()
        if a["issue_id"]:
            conn.execute(
                "UPDATE issues SET status='resolved' WHERE project_id=? AND id=? AND status='open' AND last_seen<=?",
                (project_id, a["issue_id"], verified_at)
            )
        conn.execute(
            """UPDATE actions SET status='dismissed',dismissed_at=COALESCE(dismissed_at,?)
               WHERE project_id=? AND id<>? AND status IN ('draft','approved','failed')
                 AND COALESCE(target_url,'')=COALESCE(?, '')
                 AND COALESCE(proposed_json,'')=COALESCE(?, '')""",
            (now(), project_id, a["id"], a["target_url"], a["proposed_json"])
        )
    conn.commit(); conn.close()


def score_interpretation(score):
    score = float(score or 0)
    if score >= 90:
        return {
            "label": "Silný základ, ale ne hotové SEO",
            "tone": "excellent",
            "target": "Skóre nad 90 znamená, že v právě měřených oblastech nevidím zásadní rezervy. Není to příslib pozice a bez vysokého pokrytí auditu ani potvrzení, že je celý web čistý."
        }
    if score >= 75:
        return {
            "label": "Dobrý základ s konkrétními rezervami",
            "tone": "good",
            "target": "Web není v kritickém stavu, ale stále má měřitelné technické nebo obsahové rezervy. Prioritou jsou problémy s velkým rozsahem a stránky s obchodním významem."
        }
    if score >= 55:
        return {
            "label": "Výrazný prostor ke zlepšení",
            "tone": "warning",
            "target": "SEO základ má více nedostatků. Nejdřív odstraníme technické překážky a potom systematicky doplníme obsah, metadata, obrázky a interní prolinkování."
        }
    return {
        "label": "Slabý SEO základ",
        "tone": "bad",
        "target": "Web má zásadní rezervy nebo velmi nízké pokrytí auditu. Nejdřív potřebuji ověřit technickou dostupnost a odstranit největší chyby; až potom má smysl ladit detaily."
    }


def advisor_state(project_id):
    pconn = db()
    p = pconn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    pending = pconn.execute(
        "SELECT COUNT(*) c FROM actions WHERE project_id=? AND status IN ('draft','approved','failed','queued','pending')", (project_id,)
    ).fetchone()["c"]
    done = pconn.execute(
        "SELECT COUNT(*) c FROM actions WHERE project_id=? AND status IN ('applied','verified','completed')", (project_id,)
    ).fetchone()["c"]
    pconn.close()
    kinds = count_by_kind(project_id)
    findings = grouped_findings(project_id)[:5]
    scorecard = seo_scorecard(project_id)
    work_plan = latest_operator_plan(project_id)
    weakest = min(
        (("technical", scorecard.get("technical", 0)), ("content", scorecard.get("content", 0))),
        key=lambda kv: kv[1]
    )
    labels = {"technical": "technickém SEO", "content": "obsahovém SEO"}
    suggestions = []
    qstate = queue_summary(project_id)
    wstate = worker_state()
    if qstate.get("total"):
        suggestions.append({"label": f"Sledovat {qstate['count']} rozpracovaných úkolů", "url": url_for("actions", project_id=project_id, view="todo"), "primary": True})
    if kinds.get("error"):
        suggestions.append({"label": f"Vyřešit {kinds['error']} chyb", "url": url_for("seo", project_id=project_id, kind="error"), "primary": True})
    if pending:
        suggestions.append({"label": f"Projít {pending} návrhů", "url": url_for("actions", project_id=project_id, view="todo"), "primary": not suggestions})
    if kinds.get("warning"):
        suggestions.append({"label": f"Projít {kinds['warning']} varování", "url": url_for("seo", project_id=project_id, kind="warning"), "primary": not suggestions})
    if kinds.get("opportunity"):
        suggestions.append({"label": f"Vybrat z {kinds['opportunity']} příležitostí", "url": url_for("seo", project_id=project_id, kind="opportunity"), "primary": not suggestions})
    if not latest_source_snapshot(project_id, "search_console"):
        suggestions.append({"label": "Připojit Search Console", "url": url_for("connectors", project_id=project_id), "primary": False})

    coverage = scorecard.get("coverage", {})
    strategy = project_strategy(p) if p else {}
    if p and p["status"] != "connected":
        opening = "Nejdřív mi připoj Fresh Core. Pak uvidím strukturu webu a připravím konkrétní audit místo obecných rad."
    elif not strategy.get("business_goal"):
        opening = (
            "Než budu dál vyrábět další SEO úkoly, potřebuji znát obchodní cíl webu. "
            "Napiš mi ho normálně do chatu — třeba že chceš více poptávek, objednávek nebo registrací — a já si podle něj přepočítám priority."
        )
        suggestions.insert(0, {"label": "Nastavit obchodní cíl v chatu", "url": f"/projects/{project_id}#boban-chat", "primary": True})
    elif qstate.get("total"):
        if wstate.get("healthy"):
            opening = f"Pracuji na {qstate['count']} úkolech. Klidně pokračuj v práci; jednotlivé změny publikuji, ověřím a výsledek ti pošlu do oznámení."
        else:
            opening = f"Mám ve frontě {qstate['count']} úkolů, ale automatické zpracování teď neběží. Zkusím worker znovu spustit a pokud se nerozběhne, označím to jako problém k zásahu."
    elif kinds.get("error"):
        opening = f"Teď bych neřešil kosmetiku. Vidím {kinds['error']} potvrzených chyb a SEO připravenost je {scorecard['overall']}/100. Začnu problémy, které mohou ovlivnit crawl, indexaci nebo podobu výsledku."
    elif pending:
        opening = f"Mám připravených {pending} návrhů. Než něco publikuji, můžeš každý návrh upravit. Pak změnu provedu a ověřím ve veřejném HTML."
    else:
        top_plan = (work_plan.get("items") or [])[:3]
        if top_plan:
            titles = "; ".join(str(x.get("title") or "") for x in top_plan)
            goal = (work_plan.get("strategy") or {}).get("business_goal") or "zvýšit relevantní organickou návštěvnost a obchodní výsledek"
            opening = (
                f"Jdeme na to. Můj cíl pro tenhle web je {goal}. Prošel jsem dostupná data a teď bych šel v tomto pořadí: {titles}. "
                f"Z pracovního plánu umím {int(work_plan.get('boban_count') or 0)} priorit rozpracovat sám; u {int(work_plan.get('help_count') or 0)} budu potřebovat tvoje rozhodnutí nebo externí zásah."
            )
        else:
            opening = (
                f"SEO připravenost hodnotím {scorecard['overall']}/100 při pokrytí auditu {coverage.get('overall',0)} %. "
                f"Nejslabší část je {labels.get(weakest[0], weakest[0])} ({weakest[1]}/100). "
                f"Mám {kinds.get('warning',0)} varování a {kinds.get('opportunity',0)} příležitostí; vybral bych ty s největším rozsahem a obchodním významem."
            )
    return {
        "opening": opening,
        "suggestions": suggestions[:4],
        "pending": int(pending),
        "done": int(done),
        "findings": [dict(x) for x in findings],
        "score": score_interpretation(scorecard.get("overall", 0)),
        "scorecard": scorecard,
        "work_plan": work_plan,
    }


def boban_value_summary(project_id):
    """A factual sales/progress summary: work, proof, measured impact, next step."""
    conn = db()
    done = conn.execute(
        "SELECT * FROM actions WHERE project_id=? AND status IN ('applied','verified','completed') ORDER BY id DESC",
        (project_id,)
    ).fetchall()
    pending = conn.execute(
        "SELECT COUNT(*) c FROM actions WHERE project_id=? AND status IN ('draft','approved','failed','queued','pending')",
        (project_id,)
    ).fetchone()["c"]
    verified = 0
    measured = 0
    positive = 0
    for row in done:
        try:
            verification = json.loads(row["verification_json"] or "{}")
        except Exception:
            verification = {}
        if verification.get("rendered_confirmed"):
            verified += 1
        try:
            impact = json.loads(row["impact_json"] or "{}")
        except Exception:
            impact = {}
        metric_rows = [v for k, v in impact.items() if k != "measured_at" and isinstance(v, dict) and v.get("delta") is not None]
        if metric_rows:
            measured += 1
            # A lower average position is an improvement; higher clicks,
            # impressions or CTR are improvements.
            is_positive = False
            for metric, val in impact.items():
                if not isinstance(val, dict) or val.get("delta") is None:
                    continue
                delta = float(val.get("delta") or 0)
                if (metric == "position" and delta < 0) or (metric != "position" and delta > 0):
                    is_positive = True
            if is_positive:
                positive += 1
    top = conn.execute(
        """SELECT code,title,COUNT(*) c FROM issues WHERE project_id=? AND status='open'
           GROUP BY code,title ORDER BY
           CASE MIN(CASE kind WHEN 'error' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END) WHEN 1 THEN 1 WHEN 2 THEN 2 ELSE 3 END,
           COUNT(*) DESC LIMIT 1""",
        (project_id,)
    ).fetchone()
    conn.close()

    if measured:
        impact_text = f"U {measured} dokončených úkolů už mám měření po změně. U {positive} z nich vidím pozitivní posun alespoň v jednom sledovaném ukazateli."
    elif latest_source_snapshot(project_id, "search_console"):
        impact_text = "Search Console je připojená. U novějších změn ještě sbírám dostatečné období, takže výsledek nechci předčasně přikrášlovat."
    else:
        impact_text = "Dopad zatím nemohu poctivě připsat změnám, protože chybí Search Console nebo dostatečné období po publikaci."
    next_text = f"Mám {int(pending)} připravených nebo rozpracovaných úkolů."
    if top:
        next_text += f" Největší otevřená skupina: {top['title']} ({int(top['c'])} URL)."
    done_text = (
        f"Dokončil jsem {len(done)} SEO změn; {verified} z nich už mám potvrzených i ve veřejném HTML."
        if done else
        "Zatím nemám dokončenou změnu. Jakmile první návrh publikuješ, budu tady držet jeho stav i výsledek."
    )
    proof_text = (
        f"U {verified} změn mám jasný technický důkaz: Fresh Core změnu provedl a crawler ji našel ve výsledném HTML."
        if verified else
        "Na první technický důkaz čekám. Po publikaci ověřím zápis ve Fresh Core i skutečné veřejné HTML."
    )
    return {
        "done_count": len(done),
        "verified_count": verified,
        "measured_count": measured,
        "positive_count": positive,
        "done_text": done_text,
        "impact_text": impact_text,
        "proof_text": proof_text,
        "next_text": next_text,
    }


def select_core_file(manifest, names):
    files = manifest.get("files") or []
    wanted = {n.lower() for n in names}
    for f in files:
        rel = str(f.get("file") or "").lower()
        if rel in wanted:
            return f
    return None


def fetch_core_bundle(manifest_url, project_site_url):
    manifest = fetch_json(manifest_url)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest nemá očekávaný JSON formát.")

    core_version = str(manifest.get("fresh_core_version") or "")
    site = manifest.get("site") or {}
    core_site_url = str(site.get("url") or "").strip()
    if not core_version or not core_site_url or not isinstance(manifest.get("files"), list):
        raise ValueError("Toto nevypadá jako Fresh Core statický manifest.")

    if normalize_host(core_site_url) != normalize_host(project_site_url):
        raise ValueError(
            f"Manifest patří webu {core_site_url}, ale projekt je {project_site_url}."
        )

    manifest_host = urlparse(manifest_url).hostname
    snapshot = {
        "manifest": manifest,
        "structure": None,
        "diagnostics": None,
        "seo": None,
    }

    for key, names in (
        ("structure", ["structure.json"]),
        ("diagnostics", ["diagnostics.json"]),
        ("seo", ["seo/index.json", "seo.json"]),
    ):
        ref = select_core_file(manifest, names)
        if ref and ref.get("url"):
            try:
                snapshot[key] = fetch_json(str(ref["url"]), expected_host=manifest_host)
            except Exception as exc:
                snapshot[key] = {"_error": str(exc)}

    return manifest, snapshot


def seo_items_from_snapshot(snapshot):
    seo = snapshot.get("seo") or {}
    if "_error" in seo:
        return []
    if isinstance(seo.get("items"), list):
        return seo["items"]
    data = seo.get("data")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return []


SYSTEM_POST_TYPES = {"elementor_library", "e-landing-page", "wp_template", "wp_template_part", "wp_navigation", "attachment", "revision", "nav_menu_item"}


def is_seo_candidate(row):
    if str(row.get("status") or "") != "publish":
        return False
    if str(row.get("post_type") or "") in SYSTEM_POST_TYPES:
        return False
    url = str(row.get("url") or "")
    if not url.startswith(("http://", "https://")):
        return False
    parsed = urlparse(url)
    if "elementor_library" in parsed.query:
        return False
    return True


def seo_candidate_items(snapshot):
    return [row for row in seo_items_from_snapshot(snapshot) if is_seo_candidate(row)]



def issue(severity, code, title, detail="", target_url="", entity_id="", category="technical", kind="warning", context=None):
    return {
        "severity": severity,
        "code": code,
        "title": title,
        "detail": detail,
        "target_url": target_url,
        "entity_id": str(entity_id or ""),
        "category": category,
        "kind": kind,
        "context": context or {},
    }


# v0.7.0: conservative scoring. The old model effectively ignored opportunities
# and divided tiny penalties by the full URL count, so large sites often looked
# like 100/100 even when metadata, ALT text, headings or content were missing.
# The new model scores two things we can actually measure today:
#   1) technical SEO (crawl/indexing)
#   2) content SEO (metadata/content/images/internal linking)
# External authority/backlinks are deliberately NOT guessed until a backlink
# data source is connected.
PILLAR_CATEGORIES = {
    "technical": {"technical", "indexing"},
    "content": {"metadata", "content", "images"},
    "authority": {"links"},
}

# Families prevent double-penalizing the same underlying problem when Fresh Core
# reports the CMS state and the crawler reports the rendered HTML state.
SCORE_FAMILIES = {
    "crawl_access": {"pillar": "technical", "max_penalty": 38, "codes": {"crawl_failed", "http_error"}},
    "indexability": {"pillar": "technical", "max_penalty": 32, "codes": {"noindex", "rendered_noindex"}},
    "canonical_cms": {"pillar": "technical", "max_penalty": 4, "codes": {"canonical_missing"}},
    "canonical_rendered": {"pillar": "technical", "max_penalty": 18, "codes": {"rendered_canonical_missing"}},
    "response_speed": {"pillar": "technical", "max_penalty": 14, "codes": {"slow_response", "very_slow_response"}},
    "title_missing": {"pillar": "content", "max_penalty": 28, "codes": {"seo_title_missing", "rendered_title_missing"}},
    "description_missing": {"pillar": "content", "max_penalty": 22, "codes": {"meta_description_missing", "rendered_description_missing"}},
    "title_duplicate": {"pillar": "content", "max_penalty": 24, "codes": {"duplicate_seo_title", "duplicate_rendered_title"}},
    "description_duplicate": {"pillar": "content", "max_penalty": 14, "codes": {"duplicate_meta_description", "duplicate_rendered_description"}},
    "title_quality": {"pillar": "content", "max_penalty": 8, "codes": {"seo_title_length"}},
    "description_quality": {"pillar": "content", "max_penalty": 6, "codes": {"meta_description_length"}},
    "heading": {"pillar": "content", "max_penalty": 18, "codes": {"h1_missing", "multiple_h1"}},
    "thin_content": {"pillar": "content", "max_penalty": 20, "codes": {"thin_content"}},
    "image_alt": {"pillar": "content", "max_penalty": 16, "codes": {"missing_alt", "image_alt_missing"}},
    "internal_links": {"pillar": "content", "max_penalty": 18, "codes": {"no_internal_links", "low_internal_links", "sample_no_internal_inlinks"}},
}
SCORE_CODE_TO_FAMILY = {
    code: family for family, cfg in SCORE_FAMILIES.items() for code in cfg["codes"]
}
SCORE_KIND_FACTOR = {"error": 1.00, "warning": 0.90, "opportunity": 0.75}
SCORE_SEVERITY_FACTOR = {"critical": 1.00, "high": 0.95, "medium": 0.85, "low": 0.65}

# Backward-compatible labels used by a few templates/routes. These are not used
# to compute the new overall score.
CATEGORY_WEIGHTS = {
    "technical": 0.25, "indexing": 0.20, "metadata": 0.20,
    "content": 0.15, "links": 0.10, "images": 0.10,
}


def issue_fingerprint(source, item):
    raw = "|".join([
        str(source or ""),
        str(item.get("code") or ""),
        str(item.get("target_url") or "").rstrip("/"),
        str(item.get("entity_id") or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_value(row, key, default=None):
    try:
        if isinstance(row, sqlite3.Row):
            return row[key] if key in row.keys() else default
        return row.get(key, default)
    except Exception:
        return default


def _latest_crawl_coverage(conn, project_id, url_count):
    row = conn.execute(
        "SELECT summary_json FROM audits WHERE project_id=? AND source='crawler' AND status='completed' ORDER BY id DESC LIMIT 1",
        (project_id,)
    ).fetchone()
    pages_checked = 0
    if row:
        try:
            payload = json.loads(row["summary_json"] or "{}")
            pages_checked = int(payload.get("pages_checked") or 0)
        except Exception:
            pages_checked = 0
    denominator = max(int(url_count or 0), 1)
    return {
        "pages_checked": min(pages_checked, denominator),
        "url_count": int(url_count or 0),
        "ratio": max(0.0, min(1.0, pages_checked / denominator)),
    }


def _family_penalties(rows, url_count):
    denominator = max(int(url_count or 0), 1)
    buckets = {}
    fallback = {"technical": 0.0, "content": 0.0}
    for row in rows:
        code = str(_row_value(row, "code", "") or "")
        category = str(_row_value(row, "category", "technical") or "technical")
        kind = str(_row_value(row, "kind", "warning") or "warning")
        severity = str(_row_value(row, "severity", "medium") or "medium")
        target = str(_row_value(row, "target_url", "") or _row_value(row, "entity_id", "") or code)
        family = SCORE_CODE_TO_FAMILY.get(code)
        factor = SCORE_KIND_FACTOR.get(kind, 0.85) * SCORE_SEVERITY_FACTOR.get(severity, 0.80)
        if family:
            item = buckets.setdefault(family, {"targets": set(), "max_factor": 0.0})
            item["targets"].add(target)
            item["max_factor"] = max(item["max_factor"], factor)
        else:
            pillar = "technical" if category in PILLAR_CATEGORIES["technical"] else "content"
            # Unknown findings still count. We intentionally keep this modest
            # so a newly added check cannot collapse the whole score overnight.
            fallback[pillar] += 2.5 * factor

    penalties = {"technical": fallback["technical"], "content": fallback["content"]}
    family_detail = {}
    for family, item in buckets.items():
        cfg = SCORE_FAMILIES[family]
        prevalence = min(1.0, len(item["targets"]) / denominator)
        # sqrt makes a widespread problem hurt early instead of becoming almost
        # invisible on large sites. Opportunities are no longer free points.
        penalty = float(cfg["max_penalty"]) * (prevalence ** 0.5) * item["max_factor"]
        penalties[cfg["pillar"]] += penalty
        family_detail[family] = {
            "affected": len(item["targets"]),
            "prevalence": prevalence,
            "penalty": round(penalty, 1),
        }
    return penalties, family_detail


def score_breakdown_from_rows(rows, url_count, crawl_ratio=0.0):
    penalties, family_detail = _family_penalties(rows, url_count)
    technical_raw = max(0.0, 100.0 - penalties["technical"])
    content_raw = max(0.0, 100.0 - penalties["content"])

    # A tiny crawler sample must never be presented as a perfect technical
    # audit. Low crawl coverage caps the confidence-adjusted technical score.
    # At 0% coverage the maximum is 72; at 100% coverage the cap disappears.
    technical_confidence_factor = 0.72 + 0.28 * max(0.0, min(1.0, crawl_ratio))
    technical = round(technical_raw * technical_confidence_factor)

    # Fresh Core gives site-wide CMS metadata, so content coverage starts much
    # higher. Rendered headings/ALT/link checks still improve as crawl grows.
    content_confidence_factor = 0.94 + 0.06 * max(0.0, min(1.0, crawl_ratio))
    content = round(content_raw * content_confidence_factor)

    # We explicitly exclude external authority from the numeric score until we
    # have a reliable backlink data source. Guessing authority would be worse
    # than displaying "bez dat".
    overall = round(technical * 0.50 + content * 0.50)

    legacy = {
        "technical": technical,
        "indexing": technical,
        "metadata": content,
        "content": content,
        "links": content,
        "images": content,
    }
    return overall, legacy, {
        "overall": overall,
        "technical": technical,
        "technical_raw": round(technical_raw),
        "content": content,
        "content_raw": round(content_raw),
        "authority": None,
        "family_detail": family_detail,
    }


def seo_scorecard(project_id, conn=None):
    own = conn is None
    conn = conn or db()
    project = conn.execute("SELECT seo_url_count,health_score FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        if own:
            conn.close()
        return {
            "overall": 0, "technical": 0, "content": 0, "authority": None,
            "coverage": {"overall": 0, "crawler": 0, "pages_checked": 0, "url_count": 0},
            "categories": {k: 0 for k in CATEGORY_WEIGHTS}, "family_detail": {},
        }
    url_count = int(project["seo_url_count"] or 0)
    if url_count <= 0:
        card = {
            "overall": 0, "technical": 0, "technical_raw": 0, "content": 0, "content_raw": 0, "authority": None,
            "categories": {k: 0 for k in CATEGORY_WEIGHTS}, "family_detail": {},
            "coverage": {"overall": 0, "crawler": 0, "pages_checked": 0, "url_count": 0},
        }
        if own:
            conn.close()
        return card
    rows = conn.execute(
        "SELECT source,category,severity,kind,code,target_url,entity_id FROM issues WHERE project_id=? AND status='open'",
        (project_id,)
    ).fetchall()
    crawl = _latest_crawl_coverage(conn, project_id, url_count)
    overall, categories, detail = score_breakdown_from_rows(rows, url_count, crawl["ratio"])
    # Coverage is deliberately conservative: CMS checks cover the whole SEO
    # inventory, crawler/rendered checks cover only crawled URLs.
    overall_coverage = round((0.45 + 0.55 * crawl["ratio"]) * 100) if url_count else 0
    card = {
        **detail,
        "categories": categories,
        "coverage": {
            "overall": overall_coverage,
            "crawler": round(crawl["ratio"] * 100),
            "pages_checked": crawl["pages_checked"],
            "url_count": crawl["url_count"],
        },
    }
    if own:
        conn.close()
    return card


def recompute_project_score(project_id, conn=None):
    own = conn is None
    conn = conn or db()
    project = conn.execute("SELECT seo_url_count FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        if own:
            conn.close()
        return 0, {}
    if int(project["seo_url_count"] or 0) <= 0:
        conn.execute("UPDATE projects SET health_score=0,open_issue_count=0,updated_at=? WHERE id=?", (now(), project_id))
        if own:
            conn.commit(); conn.close()
        return 0, {k: 0 for k in CATEGORY_WEIGHTS}
    rows = conn.execute(
        "SELECT source,category,severity,kind,code,target_url,entity_id FROM issues WHERE project_id=? AND status='open'",
        (project_id,)
    ).fetchall()
    crawl = _latest_crawl_coverage(conn, project_id, int(project["seo_url_count"] or 0))
    overall, categories, _detail = score_breakdown_from_rows(rows, project["seo_url_count"] or 0, crawl["ratio"])
    open_count = conn.execute(
        "SELECT COUNT(*) c FROM issues WHERE project_id=? AND status='open'",
        (project_id,)
    ).fetchone()["c"]
    conn.execute(
        "UPDATE projects SET health_score=?, open_issue_count=?, updated_at=? WHERE id=?",
        (overall, int(open_count), now(), project_id)
    )
    if own:
        conn.commit()
        conn.close()
    return overall, categories


def core_seo_audit(snapshot):
    items = seo_candidate_items(snapshot)
    issues = []
    title_seen = {}
    desc_seen = {}
    intended_noindex_roles = {"woocommerce_cart", "woocommerce_checkout", "woocommerce_myaccount"}

    for row in items:
        if str(row.get("status")) != "publish":
            continue
        url = str(row.get("url") or "")
        entity_id = row.get("id")
        seo = row.get("seo") or {}
        title = str(seo.get("title") or "").strip()
        desc = str(seo.get("description") or "").strip()
        canonical = str(seo.get("canonical") or "").strip()
        noindex = bool(seo.get("noindex"))
        word_count = int(row.get("word_count") or 0)

        if not title and not noindex:
            issues.append(issue(
                "medium", "seo_title_missing", "SEO title není nastavený přímo v CMS",
                "Web může stále zobrazovat správný <title> z výchozího názvu. Crawler ověří výsledné HTML.",
                url, entity_id, "metadata", "opportunity"
            ))
        elif title:
            title_seen.setdefault(title.lower(), []).append((url, entity_id))
            if len(title) < 20 or len(title) > 65:
                issues.append(issue(
                    "low", "seo_title_length", "SEO title má neobvyklou délku",
                    f"Title má {len(title)} znaků. Není to automatická chyba, ale stojí za kontrolu, zda je konkrétní, čitelný a nepůsobí useknutě nebo příliš obecně.",
                    url, entity_id, "metadata", "opportunity"
                ))

        if not desc and not noindex:
            issues.append(issue(
                "medium", "meta_description_missing", "Meta description není nastavená přímo v CMS",
                "Vyhledávač si může vytvořit vlastní úryvek. Boban může připravit cílený popis pro důležité stránky.",
                url, entity_id, "metadata", "opportunity"
            ))
        elif desc:
            desc_seen.setdefault(desc.lower(), []).append((url, entity_id))
            if len(desc) < 70 or len(desc) > 180:
                issues.append(issue(
                    "low", "meta_description_length", "Meta description má neobvyklou délku",
                    f"Description má {len(desc)} znaků. Vyhledávač ji může přepsat; beru to jako příležitost zkontrolovat srozumitelnost a hodnotu snippetu, ne jako tvrdé pravidlo.",
                    url, entity_id, "metadata", "opportunity"
                ))

        if not canonical and not noindex:
            issues.append(issue(
                "low", "canonical_missing", "Canonical není nastavený přímo v CMS",
                "To samo o sobě ještě není chyba. Crawler ověří, zda canonical vzniká ve výsledném HTML.",
                url, entity_id, "indexing", "opportunity"
            ))

        page_role = str(row.get("page_role") or "")
        if noindex and page_role not in intended_noindex_roles:
            issues.append(issue(
                "medium", "noindex", "Stránka je označena noindex",
                "Noindex říká vyhledávači, aby stránku nezařazoval do výsledků. Ověř, že je to záměr.",
                url, entity_id, "indexing", "warning"
            ))

        # Fresh Core 0.4.4 maps used WordPress/Elementor images to attachment IDs,
        # so Boban can prepare an actual ALT fix instead of sending the user to WordPress.
        for image in row.get("images") or []:
            image_id = image.get("id")
            if not image_id or not image.get("used", True):
                continue
            if not str(image.get("alt") or "").strip():
                filename = str(image.get("filename") or image.get("title") or "obrázek")
                issues.append(issue(
                    "low", "image_alt_missing", "Obrázek nemá ALT text",
                    f"{filename}: Boban může připravit ALT text podle obsahu stránky a po schválení ho zapsat přes Fresh Core.",
                    url, image_id, "images", "opportunity"
                ))

        if word_count and word_count < 180 and not noindex:
            issues.append(issue(
                "low", "thin_content", "Velmi krátký obsah",
                f"Obsah má přibližně {word_count} slov. U důležitých vstupních stránek může být příliš stručný.",
                url, entity_id, "content", "opportunity"
            ))

    for _, rows in title_seen.items():
        if len(rows) > 1:
            for url, entity_id in rows:
                issues.append(issue(
                    "medium", "duplicate_seo_title", "Stejný SEO title používá více URL",
                    f"Stejný explicitní title používá {len(rows)} URL. Crawler ověří výsledný stav.",
                    url, entity_id, "metadata", "warning"
                ))

    for _, rows in desc_seen.items():
        if len(rows) > 1:
            for url, entity_id in rows:
                issues.append(issue(
                    "low", "duplicate_meta_description", "Stejná meta description používá více URL",
                    f"Stejný popis používá {len(rows)} URL.",
                    url, entity_id, "metadata", "opportunity"
                ))
    return items, issues


def crawl_page(url, site_host):
    started = time.perf_counter()
    r = fetch_html(url, site_host)
    response_ms = int((time.perf_counter() - started) * 1000)
    result = {
        "url": url,
        "final_url": r.url,
        "status_code": r.status_code,
        "bytes": len(r.content),
        "response_ms": response_ms,
        "title": "",
        "description": "",
        "canonical": "",
        "robots": "",
        "h1_count": 0,
        "missing_alt": 0,
        "missing_alt_images": [],
        "internal_links": 0,
        "external_links": 0,
        "internal_link_urls": [],
    }
    ctype = r.headers.get("content-type", "")
    if "text/html" not in ctype:
        return result

    soup = BeautifulSoup(r.text, "html.parser")
    if soup.title and soup.title.string:
        result["title"] = soup.title.string.strip()

    desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if desc:
        result["description"] = str(desc.get("content") or "").strip()

    can = soup.find("link", attrs={"rel": lambda v: v and "canonical" in [str(x).lower() for x in (v if isinstance(v, list) else [v])]})
    if can:
        result["canonical"] = str(can.get("href") or "").strip()

    robots = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    if robots:
        result["robots"] = str(robots.get("content") or "").strip()

    result["h1_count"] = len(soup.find_all("h1"))
    missing_images = []
    seen_image_urls = set()
    for img in soup.find_all("img"):
        if str(img.get("alt") or "").strip():
            continue
        raw_src = str(img.get("src") or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or "").strip()
        if not raw_src:
            srcset = str(img.get("srcset") or "").strip()
            if srcset:
                raw_src = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
        if not raw_src or raw_src.startswith("data:"):
            continue
        image_url = requests.compat.urljoin(url, raw_src)
        if image_url in seen_image_urls:
            continue
        seen_image_urls.add(image_url)
        nearby = ""
        try:
            parent = img.find_parent(["figure", "a", "div", "p"])
            nearby = " ".join((parent.get_text(" ", strip=True) if parent else "").split())[:280]
        except Exception:
            nearby = ""
        missing_images.append({
            "image_url": image_url,
            "filename": urlparse(image_url).path.rsplit("/", 1)[-1],
            "alt_attribute_present": img.has_attr("alt"),
            "nearby_text": nearby,
        })
    result["missing_alt_images"] = missing_images
    result["missing_alt"] = len(missing_images)

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        parsed = urlparse(requests.compat.urljoin(url, href))
        if parsed.scheme not in {"http", "https"}:
            continue
        if normalize_host(parsed.geturl()) == normalize_host(url):
            result["internal_links"] += 1
            normalized = parsed._replace(fragment="").geturl().rstrip("/")
            if normalized and normalized not in result["internal_link_urls"]:
                result["internal_link_urls"].append(normalized)
        else:
            result["external_links"] += 1

    return result



def crawler_audit(project, seo_items):
    issues = []
    results = []
    site_host = urlparse(project["site_url"]).hostname or ""
    core_image_keys = set()
    for core_page in seo_items:
        for core_image in core_page.get("images") or []:
            key = _media_url_key(core_image.get("url") or "")
            if key and core_image.get("id"):
                core_image_keys.add(key)

    published = [row for row in seo_items if is_seo_candidate(row) and row.get("url")]
    published.sort(key=lambda r: (
        bool((r.get("seo") or {}).get("noindex")),
        0 if str(r.get("url") or "").rstrip("/") == str(project["site_url"]).rstrip("/") else 1,
        int(r.get("id") or 0)
    ))
    candidates = published[:CRAWL_LIMIT]

    title_seen = {}
    desc_seen = {}

    for row in candidates:
        url = str(row["url"])
        expected_noindex = bool((row.get("seo") or {}).get("noindex"))
        try:
            page = crawl_page(url, site_host)
            page["entity_id"] = str(row.get("id") or "")
            page["expected_noindex"] = expected_noindex
            results.append(page)
        except Exception as exc:
            issues.append(issue(
                "high", "crawl_failed", "Crawler stránku nedokázal načíst",
                str(exc), url, row.get("id"), "technical", "error"
            ))
            continue

        code = int(page["status_code"])
        if code >= 400:
            issues.append(issue(
                "critical" if code >= 500 else "high", "http_error", f"HTTP {code}",
                "Veřejná URL vrací chybový HTTP stav.", url, row.get("id"), "technical", "error"
            ))

        response_ms = int(page.get("response_ms") or 0)
        if code < 400 and response_ms >= 3000:
            issues.append(issue(
                "high", "very_slow_response", "Velmi pomalá odezva stránky",
                f"Crawler čekal přibližně {response_ms/1000:.1f} s. Jde o orientační serverovou odezvu z Web Boosteru, ne o Core Web Vitals; pro přesné UX měření připojíme PageSpeed/CrUX.",
                url, row.get("id"), "technical", "warning"
            ))
        elif code < 400 and response_ms >= 1500:
            issues.append(issue(
                "low", "slow_response", "Pomalejší odezva stránky",
                f"Crawler čekal přibližně {response_ms/1000:.1f} s. Ber to jako signál k prověření; přesný uživatelský výkon budeme měřit přes PageSpeed/CrUX.",
                url, row.get("id"), "technical", "opportunity"
            ))

        rendered_noindex = "noindex" in page["robots"].lower()
        indexable = not (expected_noindex or rendered_noindex)

        if not page["title"] and indexable:
            issues.append(issue(
                "critical", "rendered_title_missing", "Ve výsledném HTML chybí <title>",
                "Title je základní název stránky pro vyhledávače i kartu prohlížeče.",
                url, row.get("id"), "metadata", "error"
            ))
        elif page["title"] and indexable:
            title_seen.setdefault(page["title"].lower(), []).append((url, row.get("id")))

        if not page["description"] and indexable:
            issues.append(issue(
                "medium", "rendered_description_missing", "Ve výsledném HTML chybí meta description",
                "Meta description často tvoří text pod výsledkem ve vyhledávači. Google ji může nahradit vlastním úryvkem.",
                url, row.get("id"), "metadata", "warning"
            ))
        elif page["description"] and indexable:
            desc_seen.setdefault(page["description"].lower(), []).append((url, row.get("id")))

        if page["h1_count"] == 0 and indexable:
            issues.append(issue(
                "medium", "h1_missing", "Chybí hlavní nadpis H1",
                "H1 pomáhá návštěvníkovi i vyhledávači rychle pochopit hlavní téma stránky.",
                url, row.get("id"), "content", "warning"
            ))
        elif page["h1_count"] > 1 and indexable:
            issues.append(issue(
                "low", "multiple_h1", "Na stránce je více H1",
                f"Nalezeno {page['h1_count']} nadpisů H1. Není to automaticky chyba, ale stojí za kontrolu.",
                url, row.get("id"), "content", "opportunity"
            ))

        if page["missing_alt"] > 0:
            for image_info in page.get("missing_alt_images") or []:
                image_url = str(image_info.get("image_url") or "")
                if _media_url_key(image_url) in core_image_keys:
                    # Fresh Core already emitted the attachment-level finding,
                    # which is more precise and directly publishable.
                    continue
                filename = str(image_info.get("filename") or "obrázek")
                issues.append(issue(
                    "low", "missing_alt", "Obrázek bez ALT textu",
                    f"{filename}: ve výsledném HTML nemá smysluplný ALT. Boban se ho pokusí přiřadit k médiu ve WordPressu a připravit konkrétní návrh.",
                    url, "img-" + hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:24], "images", "opportunity",
                    context={
                        "image_url": image_url, "filename": filename, "page_url": url,
                        "page_title": page.get("title") or "", "nearby_text": image_info.get("nearby_text") or "",
                        "alt_attribute_present": bool(image_info.get("alt_attribute_present")),
                    }
                ))

        if indexable and page["internal_links"] < 2:
            issues.append(issue(
                "low", "low_internal_links", "Stránka téměř neodkazuje na další obsah webu",
                f"Ve výsledném HTML jsem našel jen {page['internal_links']} interních odkazů. U důležitých stránek stojí za kontrolu navigace a kontextové prolinkování.",
                url, row.get("id"), "links", "opportunity"
            ))

        if not page["canonical"] and indexable:
            issues.append(issue(
                "medium", "rendered_canonical_missing", "Ve výsledném HTML chybí canonical",
                "Canonical pomáhá určit preferovanou URL, pokud může stejný obsah existovat na více adresách.",
                url, row.get("id"), "indexing", "warning"
            ))

        if rendered_noindex and not expected_noindex:
            issues.append(issue(
                "high", "rendered_noindex", "Výsledné HTML obsahuje neočekávaný noindex",
                page["robots"], url, row.get("id"), "indexing", "error"
            ))

    # Sampled internal-link graph. This is deliberately labelled as a sample:
    # a URL can have links from pages outside the current crawl window.
    crawled_urls = {str(p.get("final_url") or p.get("url") or "").split("#", 1)[0].rstrip("/") for p in results}
    inbound = {u: 0 for u in crawled_urls if u}
    for page in results:
        for linked in page.get("internal_link_urls") or []:
            key = str(linked).split("#", 1)[0].rstrip("/")
            if key in inbound:
                inbound[key] += 1
    home = str(project["site_url"] or "").rstrip("/")
    by_url = {str(p.get("final_url") or p.get("url") or "").rstrip("/"): p for p in results}
    for target, cnt in inbound.items():
        if not target or target == home or cnt > 0:
            continue
        page = by_url.get(target) or {}
        if page.get("expected_noindex") or "noindex" in str(page.get("robots") or "").lower():
            continue
        issues.append(issue(
            "low", "sample_no_internal_inlinks", "Ve vzorku crawleru na stránku nevede interní odkaz",
            "V aktuálně procházeném vzorku jsem nenašel žádnou jinou stránku, která by na tuto URL odkazovala. Není to důkaz osiřelé stránky, ale je to dobrý kandidát na kontrolu interního prolinkování.",
            target, page.get("entity_id"), "links", "opportunity"
        ))

    for _, rows in title_seen.items():
        if len(rows) > 1:
            for url, entity_id in rows:
                issues.append(issue(
                    "high", "duplicate_rendered_title", "Duplicitní výsledný title",
                    f"Stejný výsledný title mají {len(rows)} indexovatelné crawlované URL.",
                    url, entity_id, "metadata", "error"
                ))
    for _, rows in desc_seen.items():
        if len(rows) > 1:
            for url, entity_id in rows:
                issues.append(issue(
                    "medium", "duplicate_rendered_description", "Duplicitní výsledná meta description",
                    f"Stejnou výslednou description mají {len(rows)} indexovatelné crawlované URL.",
                    url, entity_id, "metadata", "warning"
                ))
    return results, issues



def persist_audit(project_id, source, summary, issues, replace_open=True):
    conn = db()
    started = now()
    cur = conn.execute(
        "INSERT INTO audits(project_id,source,channel,status,score,summary_json,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)",
        (project_id, source, "seo", "completed", 0, json.dumps(summary, ensure_ascii=False), started, now())
    )
    audit_id = cur.lastrowid

    conn.execute(
        "UPDATE issues SET status='stale' WHERE project_id=? AND source=? AND status='open'",
        (project_id, source)
    )

    for i in issues:
        fp = issue_fingerprint(source, i)
        existing = conn.execute(
            "SELECT * FROM issues WHERE project_id=? AND source=? AND fingerprint=? ORDER BY id DESC LIMIT 1",
            (project_id, source, fp)
        ).fetchone()
        if existing:
            # User decisions survive future crawls. Dismissed findings stay hidden until explicitly restored.
            # Snoozed findings stay hidden until their date expires; then a fresh audit can reopen them.
            next_status = "open"
            recheck_after = None
            resolved_by_action_id = None
            if existing["status"] == "dismissed":
                next_status = "dismissed"
            elif existing["status"] == "snoozed" and iso_is_future(existing["snoozed_until"]):
                next_status = "snoozed"
            elif existing["status"] == "resolved" and iso_is_future(existing["recheck_after"]):
                # A verified write gets a short stabilization window. Fresh Core /
                # crawler data can lag behind the public HTML and must not reopen
                # the same task immediately after Boban has just fixed it.
                next_status = "resolved"
                recheck_after = existing["recheck_after"]
                resolved_by_action_id = existing["resolved_by_action_id"]
            conn.execute(
                """
                UPDATE issues SET audit_id=?,channel='seo',category=?,severity=?,kind=?,code=?,title=?,detail=?,
                    target_url=?,entity_id=?,status=?,last_seen=?,fingerprint=?,context_json=?,
                    resolved_by_action_id=?,recheck_after=?
                WHERE id=?
                """,
                (
                    audit_id, i["category"], i["severity"], i.get("kind", "warning"), i["code"], i["title"],
                    i.get("detail", ""), i.get("target_url", ""), i.get("entity_id", ""), next_status, now(), fp,
                    json.dumps(i.get("context") or {}, ensure_ascii=False), resolved_by_action_id, recheck_after, existing["id"]
                )
            )
        else:
            conn.execute(
                """
                INSERT INTO issues(project_id,audit_id,channel,source,category,severity,kind,code,title,detail,target_url,entity_id,status,first_seen,last_seen,fingerprint,context_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    project_id, audit_id, "seo", source, i["category"], i["severity"], i.get("kind", "warning"),
                    i["code"], i["title"], i.get("detail", ""), i.get("target_url", ""),
                    i.get("entity_id", ""), "open", now(), now(), fp, json.dumps(i.get("context") or {}, ensure_ascii=False)
                )
            )

    conn.execute(
        "UPDATE issues SET status='resolved', last_seen=? WHERE project_id=? AND source=? AND status='stale'",
        (now(), project_id, source)
    )

    overall, category_scores = recompute_project_score(project_id, conn)
    conn.execute(
        "UPDATE audits SET score=?, summary_json=? WHERE id=?",
        (overall, json.dumps({**summary, "category_scores": category_scores}, ensure_ascii=False), audit_id)
    )
    add_activity(
        conn, project_id, "audit", f"SEO audit dokončen ({source})",
        f"Skóre {overall}/100; aktuální audit našel {len(issues)} bodů."
    )
    conn.commit()
    conn.close()
    return audit_id, overall


def migrate_issue_fingerprints():
    conn = db()
    rows = conn.execute(
        "SELECT id,project_id,source,code,target_url,entity_id,kind FROM issues ORDER BY id DESC"
    ).fetchall()
    seen = set()
    for row in rows:
        item = {"code": row["code"], "target_url": row["target_url"] or "", "entity_id": row["entity_id"] or ""}
        fp = issue_fingerprint(row["source"], item)
        key = (row["project_id"], row["source"], fp)
        if key in seen:
            conn.execute("DELETE FROM issues WHERE id=?", (row["id"],))
            continue
        seen.add(key)
        kind = row["kind"] or "warning"
        if row["source"] == "fresh_core" and row["code"] in {
            "seo_title_missing","meta_description_missing","canonical_missing","thin_content","duplicate_meta_description"
        }:
            kind = "opportunity"
        elif row["code"] in {"http_error","crawl_failed","rendered_title_missing","duplicate_rendered_title","rendered_noindex"}:
            kind = "error"
        conn.execute("UPDATE issues SET fingerprint=?, kind=? WHERE id=?", (fp, kind, row["id"]))
    
    if DB_BACKEND == "sqlite":
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_fingerprint ON issues(project_id,source,fingerprint)")

    conn.commit()
    project_ids = [r["id"] for r in conn.execute("SELECT id FROM projects").fetchall()]
    conn.close()
    for pid in project_ids:
        recompute_project_score(pid)


migrate_issue_fingerprints()


def connect_core_project(project_id, manifest_url):
    conn = db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not project:
        raise ValueError("Projekt neexistuje.")
    manifest_url = safe_http_url(manifest_url)
    manifest, snapshot = fetch_core_bundle(manifest_url, project["site_url"])
    seo_items, issues = core_seo_audit(snapshot)

    conn = db()
    conn.execute(
        """
        UPDATE projects
        SET status=?, core_manifest_url=?, core_site_url=?, core_version=?, core_last_sync=?,
            core_manifest_json=?, core_snapshot_json=?, seo_url_count=?, updated_at=?, last_snapshot=?
        WHERE id=?
        """,
        (
            "connected", manifest_url, manifest.get("site", {}).get("url"),
            manifest.get("fresh_core_version"), now(),
            json.dumps(manifest, ensure_ascii=False),
            json.dumps(snapshot, ensure_ascii=False),
            len(seo_items), now(), now(), project_id
        )
    )
    upsert_integration(
        conn, project_id, "fresh_core", "seo", "connected",
        {"manifest_url": manifest_url, "core_version": manifest.get("fresh_core_version")},
        now()
    )
    add_activity(
        conn, project_id, "connector", "Fresh Core připojen",
        f"Verze {manifest.get('fresh_core_version')}; {len(seo_items)} SEO URL."
    )
    conn.commit()
    conn.close()

    summary = {
        "type": "core",
        "core_version": manifest.get("fresh_core_version"),
        "seo_url_count": len(seo_items),
        "seo_bridge": bool(snapshot.get("seo") and "_error" not in (snapshot.get("seo") or {})),
    }
    persist_audit(project_id, "fresh_core", summary, issues, replace_open=True)
    return manifest, snapshot, seo_items


def sync_core_project(project_id):
    conn = db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not project:
        raise ValueError("Projekt neexistuje.")
    if not project["core_manifest_url"]:
        raise ValueError("Nejdřív vlož Fresh Core Manifest URL.")
    return connect_core_project(project_id, project["core_manifest_url"])


def connect_core(project_id, manifest_url):
    project_for_user(project_id)
    return connect_core_project(project_id, manifest_url)


def sync_core(project_id):
    project_for_user(project_id)
    return sync_core_project(project_id)


def auto_sync_core_project(project_id):
    conn = db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not project or not project["core_manifest_url"]:
        return {"changed": False, "reason": "no_manifest"}
    manifest = fetch_json(project["core_manifest_url"])
    old = {}
    try:
        old = json.loads(project["core_manifest_json"] or "{}")
    except Exception:
        old = {}
    current_fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    old_fingerprint = hashlib.sha256(json.dumps(old, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest() if old else ""
    if current_fingerprint == old_fingerprint:
        return {"changed": False, "reason": "unchanged"}
    connect_core_project(project_id, project["core_manifest_url"])
    return {"changed": True, "reason": "manifest_changed"}


def project_snapshot(project):
    raw = project["core_snapshot_json"] if "core_snapshot_json" in project.keys() else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def latest_audits(project_id):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM audits WHERE project_id=? ORDER BY id DESC LIMIT 10",
        (project_id,)
    ).fetchall()
    conn.close()
    return rows


def latest_issues(project_id, limit=200):
    conn = db()
    rows = conn.execute(
        """
        SELECT * FROM issues
        WHERE project_id=? AND status='open'
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, id DESC
        LIMIT ?
        """,
        (project_id, limit)
    ).fetchall()
    conn.close()
    return rows


def count_by_severity(project_id):
    conn = db()
    rows = conn.execute(
        "SELECT severity,COUNT(*) c FROM issues WHERE project_id=? AND status='open' GROUP BY severity",
        (project_id,)
    ).fetchall()
    conn.close()
    result = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in rows:
        result[r["severity"]] = int(r["c"])
    return result


def save_write_connector(project_id, endpoint, key):
    endpoint = safe_http_url(endpoint)
    if not endpoint.endswith("/write/ping") and "/wp-json/fresh-core/v1" not in endpoint:
        raise ValueError("Zadej REST URL Fresh Core, např. https://web.cz/wp-json/fresh-core/v1")
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/write/ping"):
        base = endpoint[:-len("/write/ping")].rstrip("/")
    else:
        base = endpoint
    ping_url = base + "/write/ping"
    r = requests.get(
        ping_url,
        headers={"X-Fresh-Core-Write-Key": key, "User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=HTTP_TIMEOUT
    )
    if r.status_code != 200:
        raise ValueError(f"Write bridge neověřen: HTTP {r.status_code}.")
    payload = r.json()
    if not payload.get("success"):
        raise ValueError("Write bridge nevrátil očekávanou odpověď.")

    conn = db()
    conn.execute(
        "UPDATE projects SET core_write_endpoint=?, core_write_key_enc=?, core_write_status='connected', updated_at=? WHERE id=?",
        (base, encrypt_secret(key), now(), project_id)
    )
    add_activity(conn, project_id, "connector", "Fresh Core write bridge ověřen",
                 "Web Booster může po schválení posílat povolené SEO změny.")
    conn.commit()
    conn.close()


def apply_seo_action(project, action):
    if project["core_write_status"] != "connected":
        raise ValueError("Fresh Core write bridge není připojen.")
    base = (project["core_write_endpoint"] or "").rstrip("/")
    key = decrypt_secret(project["core_write_key_enc"])
    if not key:
        raise ValueError("Nepodařilo se načíst šifrovaný write key.")

    proposed = json.loads(action["proposed_json"] or "{}")
    if action["action_type"] == "update_image_alt":
        endpoint = base + "/media/apply-alt"
        payload = {
            "attachment_id": int(action["target_id"]),
            "change_id": f"wb-{action['id']}",
            "alt": str(proposed.get("alt") or ""),
        }
    else:
        endpoint = base + "/seo/apply"
        payload = {
            "post_id": int(action["target_id"]),
            "change_id": f"wb-{action['id']}",
            "changes": proposed,
        }
    r = requests.post(
        endpoint,
        json=payload,
        headers={"X-Fresh-Core-Write-Key": key, "User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=(5, CORE_WRITE_TIMEOUT)
    )
    data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text[:1000]}
    if r.status_code >= 300 or not data.get("success"):
        raise ValueError(f"Fresh Core změnu odmítl: HTTP {r.status_code}: {data}")
    return data


def _norm_text(value):
    return " ".join(str(value or "").split()).strip().lower()


def verify_action_on_web(project, action, result=None):
    proposed = json.loads(action["proposed_json"] or "{}") if action else {}
    verification = {
        "checked_at": now(),
        "core_confirmed": False,
        "rendered_confirmed": False,
        "checks": {},
        "note": "",
    }
    action_type = action["action_type"] if action else "update_meta"
    try:
        before = json.loads(action["before_json"] or "{}") if action else {}
    except Exception:
        before = {}

    # Fresh Core returns data.before/data.after; this is the immediate write confirmation.
    try:
        data = (result or {}) if isinstance(result, dict) else {}
        if isinstance(data.get("data"), dict):
            data = data.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data")
        after = data.get("after") if isinstance(data, dict) else None
        if isinstance(after, dict):
            if action_type == "update_image_alt":
                verification["core_confirmed"] = _norm_text(after.get("alt")) == _norm_text(proposed.get("alt"))
            else:
                seo = after.get("seo") if isinstance(after.get("seo"), dict) else after
                checks = []
                for field, expected in proposed.items():
                    if field in {"title", "description", "canonical"}:
                        actual = seo.get(field)
                        checks.append(_norm_text(actual) == _norm_text(expected))
                    elif field in {"noindex", "nofollow"}:
                        checks.append(bool(seo.get(field)) == bool(expected))
                verification["core_confirmed"] = bool(checks) and all(checks)
    except Exception:
        pass

    url = action["target_url"] if action else ""
    if not url:
        verification["note"] = "Fresh Core odpověděl, ale chybí veřejná URL pro kontrolu výsledného HTML."
        return verification
    try:
        host = urlparse(project["site_url"]).hostname or ""
        if action_type == "update_image_alt":
            r = fetch_html(url, host)
            soup = BeautifulSoup(r.text, "html.parser")
            expected = str(proposed.get("alt") or "")
            image_url = str(before.get("image_url") or "")
            expected_key = _media_url_key(image_url)
            matched = []
            for img in soup.find_all("img"):
                candidate_urls = []
                for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                    value = str(img.get(attr) or "").strip()
                    if value:
                        candidate_urls.append(requests.compat.urljoin(url, value))
                srcset = str(img.get("srcset") or "").strip()
                if srcset:
                    for part in srcset.split(","):
                        value = part.strip().split(" ", 1)[0]
                        if value:
                            candidate_urls.append(requests.compat.urljoin(url, value))
                if expected_key and any(_media_url_key(x) == expected_key for x in candidate_urls):
                    matched.append(img)
            verification["checks"] = {"alt": bool(matched) and all(_norm_text(img.get("alt")) == _norm_text(expected) for img in matched)}
            verification["rendered_confirmed"] = verification["checks"]["alt"]
        else:
            page = crawl_page(url, host)
            checks = {}
            for field, expected in proposed.items():
                if field == "title":
                    actual = page.get("title") or ""
                    checks[field] = _norm_text(expected) in _norm_text(actual) if expected else True
                elif field == "description":
                    checks[field] = _norm_text(page.get("description")) == _norm_text(expected)
                elif field == "canonical":
                    checks[field] = str(page.get("canonical") or "").rstrip("/") == str(expected or "").rstrip("/")
                elif field == "noindex":
                    checks[field] = ("noindex" in str(page.get("robots") or "").lower()) == bool(expected)
                elif field == "nofollow":
                    checks[field] = ("nofollow" in str(page.get("robots") or "").lower()) == bool(expected)
            verification["checks"] = checks
            verification["rendered_confirmed"] = bool(checks) and all(checks.values())

        if verification["rendered_confirmed"]:
            verification["note"] = "Změna je potvrzena Fresh Core i výsledným veřejným HTML."
        elif verification["core_confirmed"]:
            verification["note"] = "Fresh Core změnu potvrdil, ale veřejné HTML ji zatím neukazuje. Může jít o cache nebo lazy-load; ověř znovu později."
        else:
            verification["note"] = "Změnu se zatím nepodařilo potvrdit ve výsledném HTML."
    except Exception as exc:
        verification["note"] = f"Fresh Core změnu přijal; veřejnou stránku se nepodařilo ověřit: {exc}"
    return verification


def save_action_verification(project_id, action_id, verification):
    verified = bool(verification.get("rendered_confirmed"))
    conn = db()
    current = conn.execute(
        "SELECT * FROM actions WHERE id=? AND project_id=?", (action_id, project_id)
    ).fetchone()
    current_status = current["status"] if current else "applied"
    if verified:
        new_status = "verified"
    elif current_status == "pending":
        new_status = "pending"
    else:
        new_status = "applied"
    verified_at = now()
    grace_until = (datetime.now() + timedelta(days=14)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE actions SET verification_json=?,verified_at=?,status=? WHERE id=? AND project_id=?",
        (json.dumps(verification, ensure_ascii=False), verified_at, new_status, action_id, project_id)
    )
    if verified and current and current_status != "verified":
        # Audit-backed project knowledge. Record only what verification proved;
        # never claim that a technical change caused additional sales.
        learning_title=("Ověřený SEO zásah #"+str(action_id))
        learning_summary=(str(current["reason"] or "SEO úprava")[:500])
        learning_body=("Úkol: #"+str(action_id)+"\nTyp: "+str(current["action_type"] or "")+
                       "\nOvěření: "+str(verification.get("note") or "")+
                       "\nPoznámka: Jde o technické ověření úpravy, nikoliv prokázaný růst návštěvnosti nebo objednávek.")
        # Avoid duplicates when a task is verified repeatedly.
        exists=conn.execute("SELECT id FROM marketing_knowledge WHERE project_id=? AND title=? LIMIT 1",
                            (project_id,learning_title)).fetchone()
        if not exists:
            conn.execute("INSERT INTO marketing_knowledge(project_id,category,title,summary,content,source_url,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (project_id,"Ověřené zásahy",learning_title,learning_summary,learning_body,
                          str(current["target_url"] or "")[:1000],None,now(),now()))
    if verified and current:
        # Resolve the originating finding and all metadata findings covered by
        # the same verified proposal. This prevents solved title/description
        # findings from remaining in the active audit until a later crawl.
        if current["issue_id"]:
            conn.execute(
                "UPDATE issues SET status='resolved',last_seen=?,resolved_by_action_id=?,recheck_after=? WHERE id=? AND project_id=? AND status='open'",
                (verified_at, action_id, grace_until, current["issue_id"], project_id)
            )
        try:
            proposed = json.loads(current["proposed_json"] or "{}")
        except Exception:
            proposed = {}
        codes = []
        if "title" in proposed:
            codes += ["seo_title_missing","rendered_title_missing","duplicate_seo_title","duplicate_rendered_title","seo_title_length"]
        if "description" in proposed:
            codes += ["meta_description_missing","rendered_description_missing","duplicate_meta_description","duplicate_rendered_description","meta_description_length"]
        if "canonical" in proposed:
            codes += ["canonical_missing","rendered_canonical_missing"]
        # ALT findings are attachment-specific and the originating issue_id is
        # authoritative. Do not close the crawler's page-level missing_alt
        # warning because the page may contain other images without ALT.
        if codes and current["target_url"]:
            marks = ",".join("?" for _ in codes)
            conn.execute(
                f"UPDATE issues SET status='resolved',last_seen=?,resolved_by_action_id=?,recheck_after=? WHERE project_id=? AND status='open' AND target_url=? AND code IN ({marks}) AND last_seen<=?",
                [verified_at, action_id, grace_until, project_id, current["target_url"], *codes, verified_at]
            )
        overall, _ = recompute_project_score(project_id, conn)
    conn.commit()
    conn.close()
    return verified


def _project_owner_id(project_id):
    conn = db()
    row = conn.execute("SELECT user_id FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    return int(row["user_id"]) if row else None


def create_notification(project_id, title, body="", url=None, level="info", kind="system", user_id=None):
    user_id = user_id or _project_owner_id(project_id)
    if not user_id:
        return None
    conn = db()
    cur = conn.execute(
        """INSERT INTO notifications(user_id,project_id,level,kind,title,body,url,is_read,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (user_id, project_id, level, kind, title, body, url, 0, now())
    )
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    try:
        levels=(smtp_config().get("notification_levels") or ["error"])
        if level in levels:
            queue_notification_email(int(user_id), project_id, title, body or title)
    except Exception:
        pass
    return nid


def add_boban_message(project_id, body, actions=None):
    user_id = _project_owner_id(project_id)
    if not user_id or not str(body or "").strip():
        return None
    meta = {"actions": actions or []}
    conn = db()
    cur = conn.execute(
        "INSERT INTO messages(project_id,user_id,role,body,meta_json,created_at) VALUES(?,?,?,?,?,?)",
        (project_id, user_id, "assistant", str(body).strip(), json.dumps(meta, ensure_ascii=False), now())
    )
    conn.commit(); mid = cur.lastrowid; conn.close()
    return mid


def unread_notification_count(user_id):
    conn = db()
    row = conn.execute(
        "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0 AND dismissed_at IS NULL AND (snoozed_until IS NULL OR snoozed_until<=?)",
        (user_id, now())
    ).fetchone()
    conn.close()
    return int(row["c"] if row else 0)


def worker_state(name="seo_queue"):
    """Actual heartbeat of a running worker; an idle process is not active."""
    conn = db()
    row = conn.execute("SELECT * FROM workers WHERE name=?", (name,)).fetchone()
    conn.close()
    if not row:
        return {"name": name, "status": "unknown", "healthy": False,
                "last_seen": None, "age_seconds": None, "detail": {}}
    age = None
    try:
        if row["last_seen"]:
            age = max(0, int((datetime.now() - datetime.fromisoformat(row["last_seen"])).total_seconds()))
    except (TypeError, ValueError):
        pass
    try:
        original_detail = json.loads(row["detail_json"] or "{}")
    except (TypeError, ValueError):
        original_detail = {}
    allowed = {"phase", "job_id", "job_type", "project_id", "processed", "started_at"}
    detail = {k: v for k, v in original_detail.items() if k in allowed} if isinstance(original_detail, dict) else {}
    return {"name": name, "status": row["status"],
            "healthy": bool(age is not None and age <= WORKER_STALE_SECONDS and row["status"] == "running"),
            "last_seen": row["last_seen"], "age_seconds": age, "detail": detail}


def touch_worker(name="default", status="running", detail=None):
    conn = db()
    if DB_BACKEND == "mysql":
        conn.execute(
            """INSERT INTO workers(name,status,last_seen,detail_json,updated_at) VALUES(?,?,?,?,?)
               ON DUPLICATE KEY UPDATE status=VALUES(status),last_seen=VALUES(last_seen),detail_json=VALUES(detail_json),updated_at=VALUES(updated_at)""",
            (name, status, now(), json.dumps(detail or {}, ensure_ascii=False), now())
        )
    else:
        conn.execute(
            """INSERT INTO workers(name,status,last_seen,detail_json,updated_at) VALUES(?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET status=excluded.status,last_seen=excluded.last_seen,detail_json=excluded.detail_json,updated_at=excluded.updated_at""",
            (name, status, now(), json.dumps(detail or {}, ensure_ascii=False), now())
        )
    conn.commit(); conn.close()


def kick_background_worker(command="work-queue"):
    """Request a whitelisted CLI subprocess; Popen is not evidence of completion.

    CLI flock serialises concurrent manual and cron workers on this host.
    """
    commands = {
        "work-queue": ["work-queue"],
        "daily-sync": ["daily-sync"],
        "daily-sync-force": ["daily-sync", "--force"],
        "tick": ["tick"],
        "catalog-sync": ["catalog-sync"],
    }
    args = commands.get(command)
    if not args:
        raise ValueError("Nepovolený příkaz workeru.")
    try:
        venv = os.getenv("VIRTUAL_ENV", "").strip()
        venv_python = Path(venv) / "bin" / "python" if venv else None
        python_bin = str(venv_python) if venv_python and venv_python.exists() else sys.executable
        with open(BASE_DIR / "worker.log", "a", encoding="utf-8") as log_handle:
            subprocess.Popen(
                [python_bin, str(BASE_DIR / "manage.py"), *args],
                cwd=str(BASE_DIR), stdout=log_handle, stderr=log_handle,
                start_new_session=True, close_fds=True,
            )
        return True
    except Exception as exc:
        try:
            with open(BASE_DIR / "worker.log", "a", encoding="utf-8") as f:
                f.write(f"{now()} worker kick failed: {type(exc).__name__}: {str(exc)[:180]}\\n")
        except Exception:
            pass
        return False


def queue_seo_apply_jobs(project_id, action_ids, kick=True, notify=True):
    action_ids = [int(x) for x in action_ids if str(x).isdigit()][:100]
    if not action_ids:
        raise ValueError("Není co zařadit do fronty.")
    owner_id = _project_owner_id(project_id)
    group_id = uuid.uuid4().hex[:20]
    conn = db()
    marks = ",".join("?" for _ in action_ids)
    valid = conn.execute(
        f"SELECT id FROM actions WHERE project_id=? AND id IN ({marks}) AND status IN ('draft','approved','failed','pending','queued') ORDER BY id",
        [project_id, *action_ids]
    ).fetchall()
    ids = [int(r["id"]) for r in valid]
    if not ids:
        conn.close(); raise ValueError("Žádný z vybraných úkolů není připravený k provedení.")
    inserted_ids = []
    for action_id in ids:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE action_id=? AND job_type='seo_apply_action' AND status IN ('queued','running','retry') LIMIT 1",
            (action_id,)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO jobs(project_id,user_id,action_id,group_id,job_type,status,attempts,max_attempts,payload_json,run_after,updated_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, owner_id, action_id, group_id, "seo_apply_action", "queued", 0, 3,
             json.dumps({"action_id": action_id}, ensure_ascii=False), now(), now(), now())
        )
        inserted_ids.append(action_id)
    if inserted_ids:
        marks = ",".join("?" for _ in inserted_ids)
        conn.execute(
            f"UPDATE actions SET status='queued',approved_at=COALESCE(approved_at,?),job_group_id=? WHERE project_id=? AND id IN ({marks})",
            [now(), group_id, project_id, *inserted_ids]
        )
    conn.commit(); conn.close()
    kicked = kick_background_worker("work-queue") if (kick and inserted_ids) else False
    if notify and inserted_ids:
        note = (f"Zařadil jsem {len(inserted_ids)} úkolů do fronty. "
                + ("Požádal jsem worker o spuštění; skutečné provedení ještě není potvrzené. " if kicked else
                   "Okamžité spuštění workeru se nepotvrdilo; úkoly čekají na plánovaný běh. ")
                + "Výsledky ověřím podle záznamů jednotlivých úloh.")
        create_notification(project_id, "Úkoly ve frontě", note,
            url=f"/projects/{project_id}/actions?view=todo", level="info", kind="job")
        add_boban_message(project_id, note, actions=[{"label":"Sledovat úkoly", "url":f"/projects/{project_id}/actions?view=todo", "primary":True}])
    return {"group_id": group_id, "count": len(inserted_ids), "worker_kicked": kicked,
            "already_queued": len(ids) - len(inserted_ids)}


def queue_seo_apply_job(project_id, action_ids):
    """Backward-compatible wrapper used by older routes/builds."""
    return queue_seo_apply_jobs(project_id, action_ids)["group_id"]


def queue_summary(project_id):
    """Latest batch progress; do not conflate pending jobs with completed tasks."""
    conn = db()
    latest = conn.execute(
        "SELECT group_id FROM jobs WHERE project_id=? AND job_type LIKE ? AND group_id IS NOT NULL ORDER BY id DESC LIMIT 1",
        (project_id, "seo_%")
    ).fetchone()
    data = {"queued": 0, "running": 0, "retry": 0, "failed": 0, "completed": 0, "canceled": 0,
            "total": 0, "count": 0, "percent": 100, "batch_total": 0, "batch_done": 0, "group_id": None}
    if latest:
        group = latest["group_id"]
        rows = conn.execute(
            "SELECT status,COUNT(*) c FROM jobs WHERE project_id=? AND group_id=? GROUP BY status",
            (project_id, group)
        ).fetchall()
        data["group_id"] = group
        for r in rows:
            status = str(r["status"] or "").lower()
            if status in data: data[status] = int(r["c"])
        data["batch_total"] = sum(int(r["c"]) for r in rows)
        data["batch_done"] = sum(int(r["c"]) for r in rows if str(r["status"] or "").lower() in {"completed","done","failed","canceled"})
        data["percent"] = round(100 * data["batch_done"] / data["batch_total"]) if data["batch_total"] else 100
    pending = conn.execute(
        "SELECT status,COUNT(*) c FROM jobs WHERE project_id=? AND job_type LIKE ? AND status IN ('queued','running','retry') GROUP BY status",
        (project_id, "seo_%")
    ).fetchall()
    for r in pending: data[str(r["status"]).lower()] = int(r["c"])
    data["total"] = data["queued"] + data["running"] + data["retry"]
    data["count"] = data["total"]
    conn.close()
    return data


def queue_ai_prepare_jobs(project_id, issue_rows, auto_apply=False, source="user"):
    issue_ids = [int(r["id"]) for r in issue_rows]
    if not issue_ids:
        raise ValueError("Není co připravit.")
    owner_id = _project_owner_id(project_id)
    group_id = uuid.uuid4().hex[:20]
    conn = db()
    chunks = 0
    for start in range(0, len(issue_ids), AI_BATCH_LIMIT):
        ids = issue_ids[start:start + AI_BATCH_LIMIT]
        conn.execute(
            """INSERT INTO jobs(project_id,user_id,group_id,job_type,status,attempts,max_attempts,payload_json,run_after,updated_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, owner_id, group_id, "seo_ai_prepare", "queued", 0, 3,
             json.dumps({"issue_ids": ids, "auto_apply": bool(auto_apply)}, ensure_ascii=False), now(), now(), now())
        )
        chunks += 1
    conn.commit(); conn.close()
    if source == "operator":
        notice_title = "Boban začal připravovat prioritní práci"
        notice_body = f"Z aktuálních dat jsem vybral {len(issue_ids)} konkrétních SEO zásahů. Připravím je v {chunks} skupinách a nechám je ke schválení."
        chat_body = f"Jdu na to. Z pracovního plánu jsem si vzal {len(issue_ids)} úkolů, které umím připravit sám. Nic zatím nepublikuji; až návrhy dokončím, čekají na tvoje schválení."
    else:
        notice_title = "Začínám připravovat SEO návrhy"
        notice_body = f"Vybral jsi {len(issue_ids)} stránek. Zpracuji je v {chunks} menších skupinách, abych nepřetížil AI ani web. Můžeš pokračovat v práci; ozvu se po dokončení."
        chat_body = f"Pustil jsem se do {len(issue_ids)} stránek. Rozdělím si je do {chunks} menších skupin, připravím návrhy a pak ti řeknu, co je připravené ke schválení{', případně rovnou k provedení' if auto_apply else ''}."
    create_notification(
        project_id, notice_title, notice_body,
        url=f"/projects/{project_id}/actions?view=todo", level="info", kind="ai_job", user_id=owner_id
    )
    add_boban_message(
        project_id, chat_body,
        actions=[{"label": "Sledovat průběh", "url": f"/projects/{project_id}/actions?view=todo", "primary": True}]
    )
    kicked = kick_background_worker("work-queue")
    return {"group_id": group_id, "count": len(issue_ids), "chunks": chunks, "worker_kicked": kicked}


def queue_growth_prepare_job(project_id, candidates, source="operator"):
    candidates = list(candidates or [])[:4]
    if not candidates:
        return {"count": 0}
    owner_id = _project_owner_id(project_id); group_id = uuid.uuid4().hex[:20]
    # Keep only compact, JSON-safe fields needed by the worker.
    safe = []
    for row in candidates:
        safe.append({k: row.get(k) for k in (
            "kind","query","primary_page","clicks","impressions","ctr","position","position_change","priority"
        )})
    conn=db(); ts=now()
    conn.execute(
        """INSERT INTO jobs(project_id,user_id,group_id,job_type,status,attempts,max_attempts,payload_json,run_after,updated_at,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (project_id, owner_id, group_id, "seo_growth_prepare", "queued", 0, 3,
         json.dumps({"candidates": safe, "source": source}, ensure_ascii=False), ts, ts, ts)
    )
    conn.commit(); conn.close()
    create_notification(
        project_id, "Analyzuji růstové příležitosti", f"Vzal jsem si {len(safe)} konkrétní příležitosti ze Search Console a prověřím, zda z nich umím připravit bezpečný zásah ke schválení.",
        url=f"/projects/{project_id}/actions?view=todo", level="info", kind=f"growth_group_{group_id}", user_id=owner_id
    )
    kicked=kick_background_worker("work-queue")
    return {"group_id": group_id, "count": len(safe), "worker_kicked": kicked}


# --- v0.7.3 Boban Operator --------------------------------------------------
OPERATOR_CAPABILITY_REGISTRY = {
    "metadata": {"label": "SEO metadata", "discover": True, "prepare": True, "execute": True, "verify": True, "measure": True},
    "canonical": {"label": "Canonical", "discover": True, "prepare": True, "execute": True, "verify": True, "measure": True},
    "image_alt": {"label": "ALT texty obrázků", "discover": True, "prepare": True, "execute": True, "verify": True, "measure": False},
    "indexing": {"label": "Indexace", "discover": True, "prepare": True, "execute": True, "verify": True, "measure": True},
    "content": {"label": "Obsah stránky", "discover": True, "prepare": True, "execute": False, "verify": True, "measure": True},
    "internal_links": {"label": "Interní prolinkování", "discover": True, "prepare": True, "execute": False, "verify": True, "measure": True},
    "performance": {"label": "Core Web Vitals / výkon", "discover": True, "prepare": True, "execute": False, "verify": True, "measure": True},
    "measurement": {"label": "Měření konverzí", "discover": True, "prepare": True, "execute": False, "verify": True, "measure": True},
    "backlinks": {"label": "Zpětné odkazy", "discover": False, "prepare": True, "execute": False, "verify": False, "measure": True},
}


def _csv_terms(value):
    return [x.strip() for x in re.split(r"[,;\n]+", str(value or "")) if x.strip()][:50]


def project_strategy(project):
    keys = set(project.keys()) if hasattr(project, "keys") else set()
    return {
        "business_goal": str(project["business_goal"] or "").strip() if "business_goal" in keys else "",
        "primary_conversion": str(project["primary_conversion"] or "").strip() if "primary_conversion" in keys else "",
        "priority_topics": _csv_terms(project["priority_topics"] if "priority_topics" in keys else ""),
        "brand_terms": _csv_terms(project["brand_terms"] if "brand_terms" in keys else ""),
        "mode": str(project["boban_mode"] or "specialist") if "boban_mode" in keys else "specialist",
        "cadence": str(project["boban_cadence"] or "twice_weekly") if "boban_cadence" in keys else "twice_weekly",
    }


def operator_actionable_issue_rows(project_id, limit=40):
    conn = db()
    rows = conn.execute(
        """SELECT * FROM issues WHERE project_id=? AND status='open'
           ORDER BY CASE kind WHEN 'error' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                    CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                    last_seen DESC LIMIT 500""",
        (project_id,)
    ).fetchall()
    actions = conn.execute(
        """SELECT issue_id,target_url,status,verified_at,completed_at,dismissed_at,snoozed_until,
                  action_type,target_type,target_id,proposed_json FROM actions
           WHERE project_id=? AND status NOT IN ('failed')""",
        (project_id,)
    ).fetchall()
    conn.close()
    blocked_issue_ids = set(); completed_by_issue = {}; blocked_urls = set(); recent_done_meta_urls = set()
    cooldown_cutoff = datetime.now() - timedelta(days=14)
    for a in actions:
        aid = int(a["issue_id"]) if a["issue_id"] else None
        status = str(a["status"] or "")
        url = str(a["target_url"] or "").rstrip("/")
        if status in {"draft","approved","queued","pending","applied"}:
            if aid: blocked_issue_ids.add(aid)
            if url: blocked_urls.add(url)
        elif status in {"dismissed","snoozed"}:
            if aid: blocked_issue_ids.add(aid)
        elif status in {"verified","completed"}:
            stamp = str(a["verified_at"] or a["completed_at"] or "")
            if aid:
                completed_by_issue[aid] = stamp
            try:
                recent = bool(stamp and datetime.fromisoformat(stamp) >= cooldown_cutoff)
            except Exception:
                recent = False
            if recent and url and str(a["action_type"] or "") == "update_meta":
                recent_done_meta_urls.add(url)
    out = []
    for r in rows:
        if r["code"] not in AI_ACTIONABLE_CODES:
            continue
        rid = int(r["id"])
        if rid in blocked_issue_ids:
            continue
        # A completed issue may return later. Only suppress it while the last
        # observation is not newer than the verified completion.
        verified = completed_by_issue.get(rid)
        if verified:
            try:
                # Do not let a lagging audit create the same task again right
                # after a verified publication. After 14 days a truly persistent
                # finding may legitimately return as a regression.
                if datetime.fromisoformat(verified) >= cooldown_cutoff:
                    continue
            except Exception:
                pass
            if str(r["last_seen"] or "") <= verified:
                continue
        url = str(r["target_url"] or "").rstrip("/")
        if url and url in blocked_urls:
            continue
        if url in recent_done_meta_urls and r["code"] in (AI_METADATA_CODES | DETERMINISTIC_ACTION_CODES):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _priority_from_issue(row):
    base = {"critical": 100, "high": 88, "medium": 72, "low": 55}.get(str(row.get("severity") if isinstance(row, dict) else row["severity"]), 55)
    kind = str(row.get("kind") if isinstance(row, dict) else row["kind"])
    if kind == "error": base += 6
    elif kind == "opportunity": base -= 5
    return min(100, max(1, base))


def _operator_url_key(url):
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().lstrip("www.")
        path = unquote(parsed.path or "/").rstrip("/") or "/"
        return host + path
    except Exception:
        return str(url or "").strip().lower().rstrip("/")


def _growth_priority(base, query, strategy):
    """Boost Search Console work that explicitly matches the customer's priority topics."""
    q = str(query or "").lower()
    priority = int(base)
    for term in strategy.get("priority_topics") or []:
        if str(term).lower() in q:
            priority += 8
            break
    return min(99, priority)


def operator_growth_candidates(project_id, limit=4):
    """Concrete Search Console opportunities with a landing page Boban can work on."""
    gsc = latest_source_snapshot(project_id, "search_console")
    if not gsc:
        return []
    conn = db(); project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    strategy = project_strategy(project) if project else {}
    ins = gsc.get("insights") or {}
    page_map = {}
    for qp in gsc.get("query_pages") or []:
        keys = qp.get("keys") or []
        if len(keys) < 2: continue
        q, page = str(keys[0]), str(keys[1])
        current = page_map.get(q)
        if current is None or float(qp.get("impressions") or 0) > float(current.get("impressions") or 0):
            page_map[q] = {"page": page, "impressions": qp.get("impressions") or 0}
    raw = []
    for kind, base, bucket in (
        ("decliner", 86, ins.get("decliners") or []),
        ("opportunity", 82, ins.get("opportunities") or []),
        ("low_ctr", 80, ins.get("low_ctr") or []),
    ):
        for row in bucket[:12]:
            query = str(row.get("query") or "").strip()
            fallback_page = (page_map.get(query) or {}).get("page") or ""
            page = str(row.get("primary_page") or fallback_page).strip()
            if not page or not query:
                continue
            item = dict(row)
            item["kind"] = kind
            item["primary_page"] = page
            item["priority"] = _growth_priority(base, query, strategy)
            raw.append(item)
    # One growth proposal per landing page per cycle. Prefer the strongest business signal.
    raw.sort(key=lambda x: (int(x.get("priority") or 0), float(x.get("impressions") or 0)), reverse=True)
    seen = set(); out = []
    for row in raw:
        key = _operator_url_key(row.get("primary_page"))
        if not key or key in seen:
            continue
        seen.add(key); out.append(row)
        if len(out) >= limit:
            break
    return out


def _recent_growth_action(project_id, target_id, days=28):
    conn = db()
    rows = conn.execute(
        """SELECT status,created_at,applied_at,verified_at,completed_at FROM actions
           WHERE project_id=? AND target_type='wordpress_post' AND target_id=? AND action_type='update_meta'
           ORDER BY id DESC LIMIT 8""",
        (project_id, str(target_id))
    ).fetchall()
    conn.close()
    cutoff = datetime.now() - timedelta(days=days)
    for row in rows:
        if str(row["status"] or "") in {"draft","approved","queued","pending","applied"}:
            return True
        stamp = row["verified_at"] or row["completed_at"] or row["applied_at"] or row["created_at"]
        try:
            if stamp and datetime.fromisoformat(str(stamp)) >= cutoff:
                return True
        except Exception:
            pass
    return False


def ai_prepare_growth_actions(project, candidates):
    """Turn real Search Console signals into editable metadata proposals when justified.

    This deliberately does not invent a change for every opportunity. If the page
    already has a good snippet or the real fix requires content/link work, the AI
    may return no metadata changes and the item remains in the work plan.
    """
    candidates = list(candidates or [])[:4]
    if not candidates:
        return [], []
    items = seo_items_from_snapshot(project_snapshot(project))
    by_url = {_operator_url_key(x.get("url")): x for x in items if x.get("url")}
    strategy = project_strategy(project)
    contexts = []; skipped = []
    for row in candidates:
        page = str(row.get("primary_page") or "").strip()
        item = by_url.get(_operator_url_key(page)) or {}
        post_id = str(item.get("id") or "")
        if not post_id.isdigit():
            skipped.append({"query": row.get("query"), "reason": "Cílovou URL neumím bezpečně přiřadit k WordPress položce."})
            continue
        if _recent_growth_action(project["id"], post_id):
            skipped.append({"query": row.get("query"), "reason": "Pro tuto stránku už mám čerstvý nebo rozpracovaný SEO zásah."})
            continue
        seo = item.get("seo") or {}
        contexts.append({
            "post_id": post_id,
            "url": page,
            "query": row.get("query") or "",
            "signal": row.get("kind") or "opportunity",
            "clicks": row.get("clicks") or 0,
            "impressions": row.get("impressions") or 0,
            "ctr": row.get("ctr") or 0,
            "position": row.get("position") or 0,
            "position_change": row.get("position_change"),
            "wp_title": item.get("wp_title") or item.get("title") or "",
            "current_title": seo.get("title") or "",
            "current_description": seo.get("description") or "",
            "page_role": item.get("page_role") or "",
            "word_count": item.get("word_count") or 0,
            "page_context": _ai_page_context(page, project["site_url"]),
        })
    if not contexts:
        return [], skipped
    prompt = (
        "Jsi Boban, výkonnostní SEO specialista. Dostáváš skutečné Search Console signály a obchodní cíl projektu. "
        "Rozhodni, zda u cílové stránky dává smysl změnit SEO title a/nebo meta description tak, aby lépe odpovídaly hledanému záměru a mohly zvýšit relevantní organickou návštěvnost. "
        "Nevyráběj změnu jen proto, že můžeš. Pokud je snippet už vhodný nebo problém vyžaduje hlavně obsah, interní odkazy či jiný zásah, vrať changes jako prázdný objekt a stručně uveď next_step. "
        "Vrať pouze JSON {\"items\":[{\"post_id\":\"123\",\"changes\":{\"title\":\"...\",\"description\":\"...\"},\"rationale\":\"...\",\"next_step\":\"...\"}]}. "
        "Měň pouze title/description. Nepoužívej keyword stuffing, nevymýšlej tvrzení a zachovej češtinu s diakritikou."
    )
    result = call_fresh_ai_engine(
        project, "seo_growth_optimize", prompt,
        {"strategy": strategy, "search_console_opportunities": contexts}, max_cost_usd=0.65,
    )
    proposals = {str(x.get("post_id") or ""): x for x in _find_proposal_items(result) if isinstance(x, dict)}
    created = []
    for ctx in contexts:
        post_id = str(ctx["post_id"]); proposal = proposals.get(post_id) or {}; raw = proposal.get("changes") or {}
        changes = {}
        title = str(raw.get("title") or "").strip()
        desc = str(raw.get("description") or "").strip()
        if title and title != str(ctx.get("current_title") or "").strip(): changes["title"] = title[:190]
        if desc and desc != str(ctx.get("current_description") or "").strip(): changes["description"] = desc[:500]
        if not changes:
            skipped.append({"query": ctx.get("query"), "page": ctx.get("url"), "reason": proposal.get("next_step") or "Metadata teď není nejlepší zásah."})
            continue
        before = {"title": ctx.get("current_title") or "", "description": ctx.get("current_description") or ""}
        signal = ctx.get("signal") or "opportunity"
        reason = (
            f"Search Console: {signal}; dotaz „{ctx.get('query')}“, pozice {float(ctx.get('position') or 0):.1f}, "
            f"{int(float(ctx.get('impressions') or 0))} impresí, CTR {float(ctx.get('ctr') or 0)*100:.1f} %. "
            + str(proposal.get("rationale") or "Boban připravil úpravu snippetu podle skutečného výkonu ve vyhledávání.")
        )
        created.append(create_or_merge_action(
            project["id"], post_id, ctx.get("url") or "", changes, reason, before=before,
            expected_metric="search_console",
            expected_outcome=f"Cílem je zlepšit relevanci a proklikovost pro dotaz „{ctx.get('query')}“; dopad vyhodnotím v Search Console po dostatečném období.",
            issue_id=None, action_type="update_meta", target_type="wordpress_post",
        ))
    return created, skipped


def build_operator_plan(project_id, persist=False):
    conn = db(); project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    if not project:
        return {"items": [], "summary": "Projekt nebyl nalezen."}
    strategy = project_strategy(project)
    gsc = latest_source_snapshot(project_id, "search_console")
    ga4 = latest_source_snapshot(project_id, "ga4")
    perf = latest_source_snapshot(project_id, "pagespeed_crux")
    gtm = latest_source_snapshot(project_id, "gtm")
    gsc_conf = integration_config(integration_row(project_id, "search_console"))
    ga4_conf = integration_config(integration_row(project_id, "ga4"))
    trust = data_trust_summary(project, gsc, ga4, gsc_conf, ga4_conf)
    items = []

    if not strategy["business_goal"]:
        items.append({"priority": 98, "kind": "strategy", "title": "Upřesnit obchodní cíl", "reason": "Abych nehonil SEO skóre samo pro sebe, potřebuji vědět, jaký obchodní výsledek má SEO podporovat.", "owner": "spolu", "can_prepare": False, "needs_user": True, "url": f"/projects/{project_id}#boban-context"})

    spam = trust.get("spam") or {}
    if spam.get("level") == "critical":
        items.append({"priority": 100, "kind": "incident", "title": "Prověřit podezření na SEO spam", "reason": f"Search Console obsahuje {spam.get('count',0)} podezřelých dotazů. Než budu růst považovat za úspěch, musíme ověřit web a index.", "owner": "spolu", "can_prepare": True, "needs_user": True, "url": f"/projects/{project_id}/search-performance"})

    pending_conn = db()
    pending = int(pending_conn.execute("SELECT COUNT(*) c FROM actions WHERE project_id=? AND status IN ('draft','approved','failed')", (project_id,)).fetchone()["c"] or 0)
    pending_conn.close()
    if pending:
        items.append({"priority": 96, "kind": "approval", "title": f"Schválit {pending} hotových návrhů", "reason": "Tyto změny už mám připravené. Nejrychlejší další krok je kontrola a schválení, abych je mohl publikovat a začít měřit dopad.", "owner": "uživatel", "can_prepare": False, "needs_user": True, "url": f"/projects/{project_id}/actions?view=todo"})

    actionable = operator_actionable_issue_rows(project_id, 60)
    grouped = {}
    for r in actionable:
        key = str(r["code"])
        grouped.setdefault(key, {"rows": [], "title": r["title"], "priority": _priority_from_issue(r)})
        grouped[key]["rows"].append(r)
        grouped[key]["priority"] = max(grouped[key]["priority"], _priority_from_issue(r))
    for code, group in sorted(grouped.items(), key=lambda kv: (kv[1]["priority"], len(kv[1]["rows"])), reverse=True)[:8]:
        count = len(group["rows"])
        items.append({"priority": group["priority"], "kind": "execution", "title": f"{group['title']} · {count}×", "reason": "Tento problém umím převést na konkrétní návrhy a u podporovaných polí po schválení zapsat přes Fresh Core.", "owner": "boban", "can_prepare": True, "needs_user": False, "code": code, "issue_ids": [int(r["id"]) for r in group["rows"][:AI_BATCH_LIMIT]], "url": f"/projects/{project_id}/seo/findings/{quote(str(code), safe='')}"})

    ins = (gsc.get("insights") or {}) if gsc else {}
    for row in (ins.get("decliners") or [])[:3]:
        page = str(row.get("primary_page") or "")
        can_prepare = bool(page)
        items.append({"priority": _growth_priority(86, row.get("query"), strategy), "kind": "growth", "title": f"Zastavit pokles: {row.get('query')}", "reason": f"Dotaz klesl přibližně o {abs(float(row.get('position_change') or 0)):.1f} pozice. " + (f"Cílová stránka: {page}. Připravím konkrétní zásah, pokud ho data a obsah stránky odůvodní." if page else "Nejdřív potřebuji spolehlivě určit cílovou stránku."), "owner": "boban", "can_prepare": can_prepare, "needs_user": False, "primary_page": page, "url": f"/projects/{project_id}/search-performance"})
    for row in (ins.get("opportunities") or [])[:4]:
        page = str(row.get("primary_page") or "")
        can_prepare = bool(page)
        items.append({"priority": _growth_priority(82, row.get("query"), strategy), "kind": "growth", "title": f"Posunout do TOP 10: {row.get('query')}", "reason": f"Pozice {float(row.get('position') or 0):.1f}, {int(row.get('impressions') or 0)} impresí. " + (f"Cílová stránka: {page}. Pokud je problém ve snippetu, připravím změnu rovnou ke schválení." if page else "Je to příležitost, ale zatím bez bezpečně určené cílové URL."), "owner": "boban", "can_prepare": can_prepare, "needs_user": False, "primary_page": page, "url": f"/projects/{project_id}/search-performance"})
    for row in (ins.get("low_ctr") or [])[:3]:
        page = str(row.get("primary_page") or "")
        can_prepare = bool(page)
        items.append({"priority": _growth_priority(80, row.get("query"), strategy), "kind": "growth", "title": f"Zvýšit CTR: {row.get('query')}", "reason": f"Web se zobrazuje kolem pozice {float(row.get('position') or 0):.1f}, ale CTR je jen {float(row.get('ctr') or 0)*100:.1f} %. " + (f"Cílová stránka: {page}. Prověřím title a description a změnu připravím jen tehdy, pokud dává smysl." if page else "Nejdřív potřebuji spolehlivě určit cílovou stránku."), "owner": "boban", "can_prepare": can_prepare, "needs_user": False, "primary_page": page, "url": f"/projects/{project_id}/search-performance"})

    crux = (perf.get("crux") or {}) if perf else {}
    if crux.get("available"):
        bad = [m.upper() for m, state in (crux.get("status") or {}).items() if state in {"poor", "needs_improvement"}]
        if bad:
            items.append({"priority": 84, "kind": "performance", "title": "Zlepšit Core Web Vitals: " + ", ".join(bad), "reason": "CrUX ukazuje problém na reálných uživatelských datech. Připravím technickou diagnostiku, ale část oprav může vyžadovat zásah do šablony, hostingu nebo JavaScriptu.", "owner": "spolu", "can_prepare": True, "needs_user": True, "url": f"/projects/{project_id}/connectors"})

    if gtm:
        for f in (gtm.get("findings") or [])[:2]:
            if f.get("level") in {"warning", "opportunity"}:
                items.append({"priority": 76, "kind": "measurement", "title": f.get("title") or "Prověřit měření", "reason": f.get("detail") or "Bez správného měření neumím optimalizovat obchodní výsledek.", "owner": "spolu", "can_prepare": True, "needs_user": True, "url": f"/projects/{project_id}/connectors"})

    # Stable de-duplication by title, highest priority wins.
    unique = {}
    for item in items:
        title = item.get("title") or ""
        if title not in unique or item.get("priority",0) > unique[title].get("priority",0):
            unique[title] = item
    items = sorted(unique.values(), key=lambda x: x.get("priority",0), reverse=True)[:16]
    boban_count = sum(1 for x in items if x.get("can_prepare") and not x.get("needs_user"))
    help_count = sum(1 for x in items if x.get("needs_user"))
    goal_text = strategy["business_goal"] or "zvýšit relevantní organickou návštěvnost a obchodní výsledek"
    summary = f"Cíl: {goal_text}. Teď vidím {len(items)} priorit; {boban_count} z nich umím rozpracovat sám a u {help_count} budu potřebovat tvoje rozhodnutí nebo externí zásah."
    plan = {"summary": summary, "items": items, "strategy": strategy, "generated_at": now(), "boban_count": boban_count, "help_count": help_count,
            "data_sources": {"fresh_core": bool(project["core_manifest_url"]), "search_console": bool(gsc), "ga4": bool(ga4), "pagespeed_crux": bool(perf), "gtm": bool(gtm)}}
    if persist:
        conn=db(); ts=now(); conn.execute("UPDATE operator_plans SET status='superseded',updated_at=? WHERE project_id=? AND status='active'", (ts, project_id))
        conn.execute("INSERT INTO operator_plans(project_id,status,strategy_json,plan_json,generated_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (project_id, "active", json.dumps(strategy, ensure_ascii=False), json.dumps(plan, ensure_ascii=False), ts, ts))
        # Keep history bounded.
        old = conn.execute("SELECT id FROM operator_plans WHERE project_id=? ORDER BY id DESC LIMIT 1000 OFFSET 30", (project_id,)).fetchall()
        if old:
            marks=','.join('?' for _ in old); conn.execute(f"DELETE FROM operator_plans WHERE id IN ({marks})", [r['id'] for r in old])
        conn.commit(); conn.close()
    return plan


def latest_operator_plan(project_id):
    conn=db(); row=conn.execute("SELECT * FROM operator_plans WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone(); conn.close()
    if row:
        try:
            plan=json.loads(row["plan_json"] or "{}")
            if plan: return plan
        except Exception: pass
    return build_operator_plan(project_id, persist=False)


def operator_cycle(project_id, force=False):
    conn=db(); project=conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    if not project or not project["core_manifest_url"]:
        return {"skipped": True, "reason": "Fresh Core není připojen."}
    strategy=project_strategy(project); mode=strategy.get("mode") or "specialist"
    plan=build_operator_plan(project_id, persist=True)
    prepared=0; queued=None; growth_queued=None
    if mode in {"specialist", "autopilot"}:
        rows=operator_actionable_issue_rows(project_id, min(AI_BATCH_LIMIT, 20))
        if rows:
            queued=queue_ai_prepare_jobs(project_id, rows, auto_apply=False, source="operator")
            prepared += len(rows)
        # The audit fixes hygiene. Search Console opportunities drive growth.
        # Queue a small second pass that may optimize the real landing page, but
        # only when the AI can justify a safe metadata change.
        growth = operator_growth_candidates(project_id, 3)
        if growth:
            growth_queued=queue_growth_prepare_job(project_id, growth, source="operator")
            prepared += int(growth_queued.get("count") or 0)
    ts=now(); conn=db(); conn.execute("UPDATE projects SET last_operator_run=?,updated_at=? WHERE id=?", (ts, ts, project_id)); conn.commit(); conn.close()
    if not prepared:
        add_boban_message(project_id, "Prošel jsem aktuální data a pracovní plán. Teď nemám nový bezpečný zásah, který bych mohl bez dalšího kontextu sám připravit. Prioritní body jsem seřadil na nástěnce.",
                          actions=[{"label":"Zobrazit pracovní plán","url":f"/projects/{project_id}#boban-context","primary":True}])
    return {"skipped": False, "prepared": prepared, "queued": queued or {}, "growth_queued": growth_queued or {}, "plan": plan}


def operator_cycle_due(project):
    strategy=project_strategy(project); cadence=strategy.get("cadence") or "twice_weekly"
    if cadence == "manual" or strategy.get("mode") == "assistant" or not project_automation_allowed(project["id"]):
        return False
    rule=automation_rule("operator_cycle")
    if not rule or not int(rule["enabled"] or 0): return False
    global_hours=max(1,int(rule["interval_hours"] or 84))
    project_hours = 168 if cadence == "weekly" else 84
    hours=min(global_hours,project_hours)
    last = project["last_operator_run"] if "last_operator_run" in project.keys() else None
    if not last: return True
    try: return datetime.now() - datetime.fromisoformat(str(last)) >= timedelta(hours=hours)
    except Exception: return True


def apply_seo_actions_batch(project, actions):
    """Compatibility helper. Executes independently so one slow WordPress write never loses the whole selection."""
    out = {}
    for action in list(actions)[:50]:
        try:
            out[action["id"]] = {"ok": True, "data": apply_seo_action(project, action)}
        except requests.exceptions.Timeout as exc:
            verification = verify_action_on_web(project, action, None)
            if verification.get("rendered_confirmed"):
                out[action["id"]] = {
                    "ok": True, "data": {"timeout_recovered": True},
                    "verification": verification,
                    "warning": "Fresh Core neodpověděl včas, ale změna je vidět na veřejném webu.",
                }
            else:
                out[action["id"]] = {
                    "ok": False, "pending": True,
                    "error": "Fresh Core neodpověděl včas. Změna může být zapsaná; Web Booster ji bude znovu ověřovat.",
                    "verification": verification,
                }
        except Exception as exc:
            out[action["id"]] = {"ok": False, "error": str(exc)}
    return out


def _safe_source_inventory():
    allowed_files = {
        "app.py", "passenger_wsgi.py", "requirements.txt", "README.md", ".env.example",
        "UPDATE-0.2.0.txt", "UPDATE-0.3.0.txt", "UPDATE-0.4.0.txt", "UPDATE-0.4.1.txt", "UPDATE-0.5.0.txt", "UPDATE-0.5.1.txt", "UPDATE-0.6.0.txt", "UPDATE-0.6.1.txt", "UPDATE-0.7.0.txt", "UPDATE-0.7.1.txt", "UPDATE-0.7.1.1.txt", "ARCHITECTURE.md", "INTEGRATIONS.md", "ROADMAP-0.7X-0.8.md",
        "manage.py", "migrate_sqlite_to_mysql.py", "DATABASE-MIGRATION.md",
    }
    allowed_dirs = {"templates", "static"}
    items = []
    for path in sorted(BASE_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(BASE_DIR).as_posix()
        top = rel.split("/", 1)[0]
        if rel not in allowed_files and top not in allowed_dirs:
            continue
        if path.suffix.lower() in {".pyc", ".sqlite", ".db", ".log"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        raw = content.encode("utf-8")
        items.append({
            "path": rel, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "content": content
        })
    return items


def _database_schema_manifest():
    conn = db()
    tables = []
    if DB_BACKEND == "mysql":
        rows = conn.execute("SHOW TABLES").fetchall()
        table_names = [next(iter(r.values())) for r in rows]
        for table_name in sorted(table_names):
            safe = re.sub(r"[^a-zA-Z0-9_]", "", table_name)
            columns = conn.execute(f"SHOW COLUMNS FROM `{safe}`").fetchall()
            count = conn.execute(f"SELECT COUNT(*) AS c FROM `{safe}`").fetchone()["c"]
            create_row = conn.execute(f"SHOW CREATE TABLE `{safe}`").fetchone()
            create_sql = create_row.get("Create Table") if isinstance(create_row, dict) else ""
            tables.append({
                "name": table_name,
                "row_count": int(count),
                "create_sql": create_sql,
                "columns": [{
                    "name": c["Field"], "type": c["Type"], "notnull": c["Null"] == "NO",
                    "default": c["Default"], "primary_key": c["Key"] == "PRI"
                } for c in columns]
            })
    else:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for row in rows:
            table_name = row["name"]
            safe_name = table_name.replace('"', '""')
            columns = conn.execute(f'PRAGMA table_info("{safe_name}")').fetchall()
            count = conn.execute(f'SELECT COUNT(*) AS c FROM "{safe_name}"').fetchone()["c"]
            tables.append({
                "name": table_name,
                "row_count": int(count),
                "create_sql": row["sql"],
                "columns": [{
                    "name": c["name"], "type": c["type"], "notnull": bool(c["notnull"]),
                    "default": c["dflt_value"], "primary_key": bool(c["pk"])
                } for c in columns]
            })
    conn.close()
    return tables


def _developer_manifest():
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        routes.append({"rule": rule.rule, "endpoint": rule.endpoint, "methods": methods})
    return {
        "connector": {
            "name": "Web Booster Developer Manifest",
            "version": 9,
            "read_only": True,
            "generated_at": now()
        },
        "application": {
            "name": os.getenv("APP_NAME", "Web Booster"),
            "version": APP_VERSION,
            "url": os.getenv("APP_URL", "")
        },
        "architecture": {
            "channels": ["seo", "ppc"],
            "implemented_channels": ["seo"],
            "pipeline": ["sources", "audit", "issues", "actions", "approval", "execution", "metrics", "impact"],
            "ppc_status": "SEO operator is active; PPC remains the next performance channel after the SEO playbook and connector layer"
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
            "database_backend": DB_BACKEND
        },
        "integrations": {
            "fresh_ai_engine_configured": bool(os.getenv("FRESH_AI_ENGINE_URL") and os.getenv("FRESH_AI_ENGINE_API_KEY")),
            "google_oauth_configured": google_oauth_ready(),
            "search_console_implemented": True,
            "search_console_write": True,
            "ga4_implemented": True,
            "ga4_write": True,
            "pagespeed_crux_implemented": True,
            "pagespeed_api_key_configured": pagespeed_ready(),
            "google_tag_manager_implemented": True,
            "google_tag_manager_mode": "read_only",
            "boban_operator": True,
            "business_goal_strategy": True,
            "planned": ["google_business_profile","bing_webmaster","seznam_webmaster","indexnow","backlink_data","merchant_center","google_ads","sklik"],
        },
        "privacy": {
            "environment_values_exposed": False,
            "password_hashes_exposed": False,
            "project_rows_exposed": False,
            "write_keys_exposed": False,
            "database_schema_only": True,
            "source_code_exposed": True,
        },
        "routes": routes,
        "database_schema": _database_schema_manifest(),
        "source_files": _safe_source_inventory(),
    }


@app.context_processor
def inject_globals():
    unread = 0
    sidebar_projects = []
    try:
        if current_user.is_authenticated:
            unread = unread_notification_count(current_user.id)
            sidebar_projects = accessible_projects(current_user.id, sidebar=True)
    except Exception:
        unread = 0
        sidebar_projects = []
    return {
        "app_name": os.getenv("APP_NAME", "Web Booster"),
        "year": datetime.now().year,
        "app_version": APP_VERSION,
        "notification_unread": unread,
        "sidebar_projects": sidebar_projects,
        "is_admin": bool(getattr(current_user, "is_admin", False)) if current_user.is_authenticated else False,
        "account_role": getattr(current_user, "role", "visitor") if current_user.is_authenticated else "visitor",
        "can_manage_project_access": can_manage_project_access,
        "project_access_role": project_access_role,
        "boban_image_url": os.getenv("BOBAN_IMAGE_URL", "https://www.freshcrackers.cz/wp-content/uploads/2026/08/boban.png"),
        "fresh_logo_url": os.getenv("FRESH_LOGO_URL", "https://www.freshcrackers.cz/wp-content/uploads/2023/10/Fresh-Crackers-Logo.png"),
    }


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Vyplň jméno, e-mail a heslo alespoň 8 znaků.", "error")
            return render_template("register.html")
        conn = db()
        try:
            admin_email=(os.getenv("WEBBOOSTER_ADMIN_EMAIL") or "soufek@freshcrackers.cz").strip().lower()
            role="admin" if email==admin_email else "visitor"
            paid="active" if role=="admin" else "none"
            conn.execute(
                "INSERT INTO users(name,email,password_hash,system_role,account_status,paid_access_status,created_at) VALUES(?,?,?,?,?,?,?)",
                (name, email, generate_password_hash(password), role, "active", paid, now())
            )
            conn.commit()
        except (sqlite3.IntegrityError, pymysql.err.IntegrityError):
            conn.close()
            flash("Účet s tímto e-mailem už existuje.", "error")
            return render_template("register.html")
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        login_user(User(row))
        try: _accept_project_invitations(int(row["id"]), email)
        except Exception: pass
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if row and row["account_status"] != "active":
            flash("Tento účet je deaktivovaný. Kontaktuj administrátora.", "error")
            return render_template("login.html")
        if row and check_password_hash(row["password_hash"], password):
            conn=db(); conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now(),row["id"])); conn.commit(); conn.close()
            row=dict(row); row["last_login_at"]=now()
            login_user(User(row), remember=True)
            try: _accept_project_invitations(int(row["id"]), email)
            except Exception: pass
            return redirect(url_for("dashboard"))
        flash("E-mail nebo heslo nesedí.", "error")
    return render_template("login.html")


@app.route("/account/request-editor", methods=["POST"])
@login_required
def request_editor_access():
    if current_user.role in {"admin","editor"}:
        flash("Editor přístup už máš aktivní.", "info"); return redirect(url_for("dashboard"))
    note=request.form.get("note","").strip()[:2000]
    conn=db(); existing=conn.execute("SELECT id FROM access_requests WHERE user_id=? AND status='pending' LIMIT 1", (current_user.id,)).fetchone()
    if existing:
        conn.close(); flash("Žádost už čeká na vyřízení.", "info"); return redirect(url_for("dashboard"))
    conn.execute("INSERT INTO access_requests(user_id,requested_role,status,note,created_at) VALUES(?,'editor','pending',?,?)", (current_user.id,note,now()))
    conn.execute("UPDATE users SET paid_access_status='requested' WHERE id=?", (current_user.id,)); conn.commit(); conn.close()
    flash("Žádost o Editor přístup jsem poslal administrátorovi.", "success"); return redirect(url_for("dashboard"))


@app.route("/fresh-key/login")
@login_required
def fresh_key_login():
    project_id = int(request.args.get("project_id") or 0)
    state = secrets.token_urlsafe(32)
    session["fresh_key_login_state"] = state
    session["fresh_key_login_project"] = project_id
    return_url = (os.getenv("APP_URL") or request.url_root.rstrip("/")).rstrip("/") + "/fresh-key/callback"
    try:
        return redirect(fresh_key.authorize_url(state, return_url))
    except Exception as exc:
        flash(f"Fresh účet se nepodařilo otevřít: {exc}", "error")
        return redirect(url_for("project_access", project_id=project_id) if project_id else url_for("dashboard"))


@app.route("/fresh-key/callback")
@login_required
def fresh_key_callback():
    state = str(request.args.get("state") or "")
    code = str(request.args.get("fresh_key_code") or "")
    expected = str(session.pop("fresh_key_login_state", "") or "")
    project_id = int(session.pop("fresh_key_login_project", 0) or 0)
    if not expected or not state or not hmac.compare_digest(expected, state) or not code:
        flash("Fresh účet se nepodařilo bezpečně ověřit.", "error")
        return redirect(url_for("project_access", project_id=project_id) if project_id else url_for("dashboard"))
    try:
        data = fresh_key.sso_exchange(code)
        ident = data.get("identity") or {}
        email = str(ident.get("email") or "").strip().lower()
        if email != str(current_user.email or "").strip().lower():
            raise RuntimeError("Fresh účet používá jiný e-mail než Boban.")
        token = str(data.get("binding_token") or "")
        external = str(data.get("external_user_id") or "")
        if token:
            fresh_key.sso_bind(token, int(current_user.id))
        elif external != str(current_user.id):
            raise RuntimeError("Fresh účet je v Bobanovi propojen s jiným uživatelem.")
        flash("Fresh účet je propojený.", "success")
    except Exception as exc:
        flash(f"Fresh účet se nepodařilo propojit: {exc}", "error")
    return redirect(url_for("project_access", project_id=project_id) if project_id else url_for("dashboard"))


def _access_role(role):
    value=str(role or "editor").strip().lower()
    if value in {"admin","superadmin","administrator"}: return "manager"
    if value in {"member","client","agency","user"}: return "editor"
    if value in {"visitor","viewer","reader","readonly","read_only"}: return "viewer"
    return value if value in {"owner","manager","editor","viewer"} else "editor"


def _relationship(value, legacy_role=""):
    rel=str(value or "").strip().lower()
    if not rel and str(legacy_role or "").lower() in {"client","agency"}: rel=str(legacy_role).lower()
    return rel if rel in {"member","client","agency"} else "member"


def _local_share_role(fresh_role):
    return _access_role(fresh_role)


def _upsert_local_project_member(project_id, email, fresh_role, relationship="member"):
    conn = db(); user = conn.execute("SELECT * FROM users WHERE LOWER(email)=?", (email.lower(),)).fetchone()
    if not user:
        conn.close(); return
    project = conn.execute("SELECT user_id FROM projects WHERE id=?", (project_id,)).fetchone()
    if project and int(user["id"]) == int(project["user_id"]):
        conn.close(); return
    role=_access_role(fresh_role); relationship=_relationship(relationship,fresh_role)
    params=(project_id,user["id"],role,relationship,"active",current_user.id,now(),now())
    if DB_BACKEND=="mysql":
        conn.execute("""INSERT INTO project_members(project_id,user_id,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE role=VALUES(role),relationship=VALUES(relationship),status='active',invited_by=VALUES(invited_by),updated_at=VALUES(updated_at)""", params)
    else:
        conn.execute("""INSERT INTO project_members(project_id,user_id,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role,relationship=excluded.relationship,status='active',invited_by=excluded.invited_by,updated_at=excluded.updated_at""", params)
    conn.commit(); conn.close()


def _accept_project_invitations(user_id, email):
    email=str(email or "").strip().lower()
    if not email: return 0
    conn=db(); pending=conn.execute("SELECT * FROM project_invitations WHERE LOWER(email)=? AND status='pending'", (email,)).fetchall()
    count=0
    for inv in pending:
        project=conn.execute("SELECT user_id FROM projects WHERE id=?", (inv["project_id"],)).fetchone()
        if project and int(project["user_id"]) != int(user_id):
            role=_access_role(inv["role"]); relationship=_relationship(inv["relationship"] if "relationship" in inv.keys() else "member", inv["role"])
            params=(inv["project_id"],user_id,role,relationship,"active",inv["invited_by"],now(),now())
            if DB_BACKEND=="mysql":
                conn.execute("""INSERT INTO project_members(project_id,user_id,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE role=VALUES(role),relationship=VALUES(relationship),status='active',invited_by=VALUES(invited_by),updated_at=VALUES(updated_at)""", params)
            else:
                conn.execute("""INSERT INTO project_members(project_id,user_id,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role,relationship=excluded.relationship,status='active',invited_by=excluded.invited_by,updated_at=excluded.updated_at""", params)
        conn.execute("UPDATE project_invitations SET status='accepted',updated_at=? WHERE id=?", (now(),inv["id"])); count+=1
    conn.commit(); conn.close(); return count



def _project_access_has_relationship(conn, table):
    try:
        return "relationship" in _table_columns(conn, table)
    except Exception:
        return False


def _project_people_local(project_id):
    """Read project people even when an older MySQL schema missed relationship.

    The access page must never 500 only because an additive role column was not
    migrated yet. Relationship then safely falls back to `member`.
    """
    conn=db()
    try:
        owner=conn.execute("SELECT u.id,u.name,u.email FROM projects p JOIN users u ON u.id=p.user_id WHERE p.id=?", (project_id,)).fetchone()
        member_rel = "pm.relationship" if _project_access_has_relationship(conn, "project_members") else "'member' AS relationship"
        invite_rel = "relationship" if _project_access_has_relationship(conn, "project_invitations") else "'member' AS relationship"
        members=conn.execute(f"SELECT u.id,u.name,u.email,pm.role,{member_rel},pm.status FROM project_members pm JOIN users u ON u.id=pm.user_id WHERE pm.project_id=? AND pm.status='active' ORDER BY u.name,u.email", (project_id,)).fetchall()
        invites=conn.execute(f"SELECT id,email,role,{invite_rel},status FROM project_invitations WHERE project_id=? AND status='pending' ORDER BY email", (project_id,)).fetchall()
    finally:
        conn.close()
    out=[]; owner_id=int(owner["id"]) if owner else 0
    if owner: out.append({"kind":"user","user_id":owner_id,"name":owner["name"] or owner["email"],"email":owner["email"],"role":"owner","relationship":"member","status":"active"})
    active={str(owner["email"] or "").lower()} if owner else set()
    for m in members:
        if int(m["id"])==owner_id: continue
        email=str(m["email"] or "").lower(); active.add(email)
        out.append({"kind":"user","user_id":int(m["id"]),"name":m["name"] or m["email"],"email":m["email"],"role":_access_role(m["role"]),"relationship":_relationship(m["relationship"],m["role"]),"status":"active"})
    for inv in invites:
        email=str(inv["email"] or "").lower()
        if email in active: continue
        out.append({"kind":"invite","invite_id":int(inv["id"]),"name":inv["email"],"email":inv["email"],"role":_access_role(inv["role"]),"relationship":_relationship(inv["relationship"],inv["role"]),"status":"pending"})
    return out


def _fresh_link_for_project(project_id):
    if not fresh_key.configured(): return None
    conn=db(); p=conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    if not p: return None
    try:
        summary=fresh_key.project_summary(int(current_user.id),dict(p),role=project_access_role(project_id) or "member")
        return summary if summary.get("linked") else None
    except Exception:
        return None


def _share_project_local(project_id, email, role, relationship="member"):
    if not can_manage_project_access(project_id): raise RuntimeError("Nemáš oprávnění sdílet tento projekt.")
    email=str(email or "").strip().lower(); legacy_role=str(role or "editor").strip().lower(); role=_access_role(legacy_role); relationship=_relationship(relationship,legacy_role)
    if not email or "@" not in email: raise RuntimeError("Doplň platný e-mail.")
    conn=db(); p=conn.execute("SELECT p.*,u.email owner_email FROM projects p JOIN users u ON u.id=p.user_id WHERE p.id=?", (project_id,)).fetchone()
    if not p: conn.close(); raise RuntimeError("Projekt nebyl nalezen.")
    if str(p["owner_email"] or "").lower()==email: conn.close(); raise RuntimeError("Vlastník projektu už přístup má.")
    user=conn.execute("SELECT id,name,email FROM users WHERE LOWER(email)=?", (email,)).fetchone()
    if user:
        params=(project_id,user["id"],_local_share_role(role),relationship,"active",current_user.id,now(),now())
        if DB_BACKEND=="mysql": conn.execute("""INSERT INTO project_members(project_id,user_id,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE role=VALUES(role),relationship=VALUES(relationship),status='active',invited_by=VALUES(invited_by),updated_at=VALUES(updated_at)""", params)
        else: conn.execute("""INSERT INTO project_members(project_id,user_id,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role,relationship=excluded.relationship,status='active',invited_by=excluded.invited_by,updated_at=excluded.updated_at""", params)
        conn.execute("UPDATE project_invitations SET status='accepted',updated_at=? WHERE project_id=? AND LOWER(email)=?", (now(),project_id,email)); status="active"
    else:
        params=(project_id,email,_local_share_role(role),relationship,"pending",current_user.id,now(),now())
        if DB_BACKEND=="mysql": conn.execute("""INSERT INTO project_invitations(project_id,email,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE role=VALUES(role),relationship=VALUES(relationship),status='pending',invited_by=VALUES(invited_by),updated_at=VALUES(updated_at)""", params)
        else: conn.execute("""INSERT INTO project_invitations(project_id,email,role,relationship,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,email) DO UPDATE SET role=excluded.role,relationship=excluded.relationship,status='pending',invited_by=excluded.invited_by,updated_at=excluded.updated_at""", params)
        status="pending"
    conn.commit(); conn.close()
    action=(os.getenv("APP_URL") or "https://webbooster.freshcrackers.cz").rstrip("/")+"/login"
    notice={}
    try: notice=fresh_key.notify_project_share(int(current_user.id),email,str(p["name"] or "Projekt"),role,action)
    except Exception:
        try:
            send_email_message(email, f"{'Spolupráce' if status=='active' else 'Pozvánka'} na projektu {p['name']}", f"Projekt {p['name']} s tebou byl nasdílen v Bobanovi. Přihlas se: {action}")
            notice={"email_sent":True,"recipient_status":"existing" if status=="active" else "invited"}
        except Exception: notice={"email_sent":False}
    link=_fresh_link_for_project(project_id)
    if link:
        try: fresh_key.add_member(int(current_user.id),link["fresh_key_id"],email,role,notify=False)
        except Exception: pass
    return {"status":status,**notice}


def _update_project_share_local(project_id,email,role,relationship="member"):
    if not can_manage_project_access(project_id): raise RuntimeError("Nemáš oprávnění upravit sdílení.")
    email=str(email or "").strip().lower(); legacy_role=str(role or "editor").strip().lower(); role=_access_role(legacy_role); relationship=_relationship(relationship,legacy_role)
    conn=db(); u=conn.execute("SELECT id FROM users WHERE LOWER(email)=?",(email,)).fetchone()
    if u: conn.execute("UPDATE project_members SET role=?,relationship=?,updated_at=? WHERE project_id=? AND user_id=?",(_local_share_role(role),relationship,now(),project_id,u["id"]))
    conn.execute("UPDATE project_invitations SET role=?,relationship=?,updated_at=? WHERE project_id=? AND LOWER(email)=?",(_local_share_role(role),relationship,now(),project_id,email)); conn.commit(); conn.close()
    link=_fresh_link_for_project(project_id)
    if link:
        target=next((m for m in link.get("members",[]) if str(m.get("email") or "").lower()==email),None)
        if target:
            try: fresh_key.update_member(int(current_user.id),link["fresh_key_id"],str(target.get("identity_id") or ""),role)
            except Exception: pass


def _remove_project_share_local(project_id,email):
    if not can_manage_project_access(project_id): raise RuntimeError("Nemáš oprávnění upravit sdílení.")
    email=str(email or "").strip().lower(); conn=db(); p=conn.execute("SELECT user_id FROM projects WHERE id=?",(project_id,)).fetchone(); u=conn.execute("SELECT id FROM users WHERE LOWER(email)=?",(email,)).fetchone()
    if u and p and int(u["id"])!=int(p["user_id"]): conn.execute("DELETE FROM project_members WHERE project_id=? AND user_id=?",(project_id,u["id"]))
    conn.execute("DELETE FROM project_invitations WHERE project_id=? AND LOWER(email)=?",(project_id,email)); conn.commit(); conn.close()
    link=_fresh_link_for_project(project_id)
    if link:
        target=next((m for m in link.get("members",[]) if str(m.get("email") or "").lower()==email),None)
        if target:
            try: fresh_key.remove_member(int(current_user.id),link["fresh_key_id"],str(target.get("identity_id") or ""))
            except Exception: pass


@app.route("/projects/<int:project_id>/access")
@login_required
def project_access(project_id):
    p=project_for_user(project_id)
    summary={"linked":False,"applications":[],"members":[],"can_manage":False}; fresh_error=""; fresh_requests=[]
    if fresh_key.configured():
        try:
            fresh_key.bootstrap_account(int(current_user.id), current_user.email, current_user.name or current_user.email)
            summary=fresh_key.project_summary(int(current_user.id), dict(p), role=project_access_role(project_id) or "editor")
            fresh_requests=[x for x in fresh_key.pending_link_requests(int(current_user.id)) if str(x.get("target_external_project_id") or "")==str(project_id)]
            _notify_fresh_key_link_requests(int(current_user.id),fresh_requests)
        except Exception as exc:
            fresh_error=str(exc)
    else:
        fresh_error="Fresh Key není nakonfigurován."
    try:
        people = _project_people_local(project_id)
    except Exception as exc:
        people = []
        fresh_error = (fresh_error + " · " if fresh_error else "") + f"Lokální sdílení čeká na DB opravu: {exc}"
    return render_template("project_access.html", project=p, fresh_key=summary, fresh_key_error=fresh_error, fresh_key_requests=fresh_requests, can_manage=can_manage_project_access(project_id), project_people=people, project_role=project_access_role(project_id), fresh_key_manage_url=(summary.get("manage_url") or fresh_key.manage_url()))


@app.route("/projects/<int:project_id>/access/publish", methods=["POST"])
@login_required
def project_access_publish(project_id):
    p=project_for_user(project_id)
    try:
        if not can_manage_project_access(project_id):
            raise RuntimeError("Projekt může do Fresh Key odeslat pouze Vlastník nebo Správce projektu.")
        fresh_key.bootstrap_account(int(current_user.id), current_user.email, current_user.name or current_user.email)
        link_id=fresh_key.publish_project(int(current_user.id),dict(p),role=project_access_role(project_id) or "editor")
        for person in _project_people_local(project_id):
            if person.get("role") == "owner": continue
            try: fresh_key.add_member(int(current_user.id),link_id,str(person.get("email") or ""),str(person.get("role") or "member"),notify=False)
            except Exception: pass
        flash("Projekt byl odeslán do Fresh Key. V AI Enginu se zobrazí jako propojení s Bobanem.","success")
    except Exception as exc:
        flash(f"Odeslání do Fresh Key selhalo: {exc}","error")
    return redirect(url_for("project_access",project_id=project_id))


@app.route("/projects/<int:project_id>/access/link-request/accept", methods=["POST"])
@login_required
def project_access_link_request_accept(project_id):
    p=project_for_user(project_id)
    try:
        if not can_manage_project_access(project_id):
            raise RuntimeError("Propojení může potvrdit pouze Vlastník nebo Správce projektu.")
        accepted=fresh_key.accept_link_request(int(current_user.id),str(request.form.get("request_id") or ""),dict(p),role=project_access_role(project_id) or "member")
        link_id=str(accepted.get("fresh_key_id") or "")
        if link_id:
            for person in _project_people_local(project_id):
                if person.get("role") == "owner":
                    continue
                try: fresh_key.add_member(int(current_user.id),link_id,str(person.get("email") or ""),str(person.get("role") or "member"),notify=False)
                except Exception: pass
        flash("Propojení bylo potvrzeno.","success")
    except Exception as exc:
        flash(f"Propojení se nepodařilo potvrdit: {exc}","error")
    return redirect(url_for("project_access",project_id=project_id))


@app.route("/fresh-key/link-request/decline", methods=["POST"])
@login_required
def fresh_key_link_request_decline():
    request_id=str(request.form.get("request_id") or "")
    back=str(request.form.get("back") or "dashboard")
    try:
        fresh_key.decline_link_request(int(current_user.id),request_id)
        flash("Návrh propojení byl odmítnut.","success")
    except Exception as exc:
        flash(f"Návrh se nepodařilo odmítnout: {exc}","error")
    if back.isdigit(): return redirect(url_for("project_access",project_id=int(back)))
    return redirect(url_for("dashboard"))


@app.route("/fresh-key/link-request/<request_id>/create", methods=["POST"])
@login_required
@editor_required
def fresh_key_link_request_create(request_id):
    try:
        pending=fresh_key.pending_link_requests(int(current_user.id))
        req=next((x for x in pending if str(x.get("id") or "")==request_id),None)
        if not req or req.get("target_external_project_id"):
            raise RuntimeError("Návrh na vytvoření projektu už není aktivní.")
        name=(request.form.get("name") or req.get("target_project_name") or req.get("link_name") or "Projekt").strip()
        site_url=(request.form.get("site_url") or req.get("requested_project_url") or "").strip().rstrip("/")
        if not site_url.startswith("https://"):
            raise RuntimeError("Boban pro nový projekt potřebuje veřejnou HTTPS URL webu.")
        conn=db(); cur=conn.execute("""INSERT INTO projects(user_id,name,site_url,status,health_score,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",(current_user.id,name,site_url,"waiting",0,now(),now())); pid=cur.lastrowid
        add_activity(conn,pid,"project","Projekt vytvořen z návrhu Fresh Key","Čekám na propojení přes Fresh Core.")
        conn.execute("INSERT INTO project_members(project_id,user_id,role,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(pid,current_user.id,"owner","active",current_user.id,now(),now())); conn.commit(); conn.close()
        p=project_for_user(pid)
        fresh_key.register_project(int(current_user.id),dict(p),role="owner")
        fresh_key.accept_link_request(int(current_user.id),request_id,dict(p),role="owner")
        flash("Nový projekt byl vytvořen v Bobanovi a propojen po tvém potvrzení.","success")
        return redirect(url_for("project_access",project_id=pid))
    except Exception as exc:
        flash(f"Projekt se nepodařilo vytvořit: {exc}","error")
        return redirect(url_for("dashboard"))


@app.route("/projects/<int:project_id>/access/share", methods=["POST"])
@login_required
def project_access_share(project_id):
    project_for_user(project_id)
    email=request.form.get("email","").strip().lower(); role=request.form.get("role","editor").strip().lower(); relationship=request.form.get("relationship","member").strip().lower()
    try:
        result=_share_project_local(project_id,email,role,relationship)
        flash("Uživatel byl přidán do projektu a dostal potvrzení spolupráce." if result.get("status")=="active" else "Pozvánka k projektu byla uložena a odeslána e-mailem.", "success")
    except Exception as exc:
        flash(f"Sdílení se nepodařilo: {exc}", "error")
    return redirect(url_for("project_access",project_id=project_id))


@app.route("/projects/<int:project_id>/access/member/update", methods=["POST"])
@login_required
def project_access_member_update(project_id):
    project_for_user(project_id)
    try:
        _update_project_share_local(project_id,str(request.form.get("email") or ""),str(request.form.get("role") or "editor"),str(request.form.get("relationship") or "member"))
        flash("Role uživatele byla upravena v Bobanovi.", "success")
    except Exception as exc:
        flash(f"Úprava se nepodařila: {exc}", "error")
    return redirect(url_for("project_access",project_id=project_id))


@app.route("/projects/<int:project_id>/access/member/remove", methods=["POST"])
@login_required
def project_access_remove(project_id):
    project_for_user(project_id)
    try:
        _remove_project_share_local(project_id,str(request.form.get("email") or ""))
        flash("Uživatel nebo pozvánka byly z projektu odebrány.", "success")
    except Exception as exc:
        flash(f"Odebrání se nepodařilo: {exc}", "error")
    return redirect(url_for("project_access",project_id=project_id))


def _admin_stats():
    conn=db()
    users=int(conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] or 0); projects=int(conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"] or 0)
    roles={r["system_role"]:int(r["c"]) for r in conn.execute("SELECT system_role,COUNT(*) c FROM users GROUP BY system_role").fetchall()}
    job_status={r["status"]:int(r["c"]) for r in conn.execute("SELECT status,COUNT(*) c FROM jobs GROUP BY status").fetchall()}
    action_status={r["status"]:int(r["c"]) for r in conn.execute("SELECT status,COUNT(*) c FROM actions GROUP BY status").fetchall()}
    since=(datetime.now()-timedelta(hours=24)).isoformat(timespec="seconds")
    engine=conn.execute("SELECT COUNT(*) runs,COALESCE(SUM(CASE WHEN status<>'completed' THEN 1 ELSE 0 END),0) errors,COALESCE(AVG(latency_ms),0) avg_latency,COALESCE(SUM(cost_usd),0) cost FROM engine_runs WHERE created_at>=?", (since,)).fetchone()
    failed_jobs=conn.execute("SELECT * FROM jobs WHERE status='failed' ORDER BY id DESC LIMIT 10").fetchall(); requests_=conn.execute("""SELECT ar.*,u.name,u.email FROM access_requests ar JOIN users u ON u.id=ar.user_id WHERE ar.status='pending' ORDER BY ar.id DESC""").fetchall()
    automation_state_count=int(conn.execute("SELECT COUNT(*) c FROM automation_state").fetchone()["c"] or 0)
    last_automation=conn.execute("SELECT MAX(updated_at) last_run FROM automation_state").fetchone()["last_run"]
    conn.close()
    return {"users":users,"projects":projects,"roles":roles,"jobs":job_status,"actions":action_status,"engine":engine,"failed_jobs":failed_jobs,"requests":requests_,"worker":worker_state(),"automation_state_count":automation_state_count,"last_automation":last_automation}


def admin_database_usage_snapshot():
    """On-demand, read-only diagnostics. Account sizes are JSON payload estimates,
    not disk allocation nor remote WooCommerce database sizes."""
    conn=db()
    try:
        if DB_BACKEND=='mysql':
            physical=conn.execute("""SELECT COALESCE(SUM(data_length+index_length),0) AS bytes,
                COUNT(*) AS tables FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'""").fetchone()
            physical_bytes=int(physical['bytes'] or 0)
            table_count=int(physical['tables'] or 0)
            backend_note='Odhad velikosti tabulek a indexů MariaDB; metriky InnoDB mohou být přibližné.'
        else:
            page=int(conn.execute('PRAGMA page_size').fetchone()[0]); pages=int(conn.execute('PRAGMA page_count').fetchone()[0])
            physical_bytes=page*pages
            table_count=int(conn.execute("SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()['n'])
            backend_note='Velikost databázového souboru SQLite podle počtu stránek.'
        owners=conn.execute("SELECT p.id,p.name,p.user_id,u.name AS owner_name FROM projects p JOIN users u ON u.id=p.user_id ORDER BY u.name,p.name").fetchall()
        totals={int(r['id']):{'project_id':int(r['id']),'project_name':r['name'],
                    'owner_id':int(r['user_id']),'owner_name':r['owner_name'],
                    'product_count':0,'variant_count':0,'payload_bytes':0} for r in owners}
        for table,kind in (('project_core_products','product_count'),('project_core_variants','variant_count')):
            byte_expr=f'OCTET_LENGTH(payload_json)' if DB_BACKEND=='mysql' else 'LENGTH(CAST(payload_json AS BLOB))'
            for r in conn.execute(f"SELECT project_id,COUNT(*) n, COALESCE(SUM({byte_expr}),0) bytes FROM {table} GROUP BY project_id").fetchall():
                item=totals.get(int(r['project_id']))
                if item:
                    item[kind]=int(r['n'] or 0)
                    item['payload_bytes']+=int(r['bytes'] or 0)
        account_map={}
        for item in totals.values():
            key=item['owner_id']
            if key not in account_map:
                account_map[key]={'owner_id':key,'owner_name':item['owner_name'],
                                  'project_count':0,'product_count':0,'variant_count':0,'payload_bytes':0}
            record=account_map[key]
            record['project_count']+=1
            record['product_count']+=item['product_count']
            record['variant_count']+=item['variant_count']
            record['payload_bytes']+=item['payload_bytes']
        return {'ok':True,'backend':DB_BACKEND,'database_bytes':physical_bytes,
                'table_count':table_count,'backend_note':backend_note,
                'projects':list(totals.values()),'accounts':list(account_map.values()),
                'disclaimer':'U projektů a účtů jde pouze o objem uložených JSON produktů a variant v Bobanovi, bez indexů, chatů a dalších tabulek. Celková velikost WooCommerce databáze a mediální knihovny se zde neměří.',
                'sampled_at':now()}
    finally:
        conn.close()


@app.route('/admin/database-usage',methods=['GET'])
@login_required
@admin_required
def admin_database_usage():
    try:
        result=admin_database_usage_snapshot()
        response=jsonify(result)
    except Exception:
        app.logger.exception('Database usage diagnostics failed')
        response=jsonify({'ok':False,'error':'Údaje se nepodařilo načíst; zkontroluj oprávnění čtení metadat databáze.'})
        response.status_code=503
    response.headers['Cache-Control']='private, no-store, max-age=0'
    return response


def _merchant_registration_form_csrf():
    if 'merchant_registration_csrf' not in session:
        session['merchant_registration_csrf'] = secrets.token_urlsafe(32)
    return session['merchant_registration_csrf']


@app.route("/admin")
@login_required
@admin_required
def admin_console():
    conn=db(); users=conn.execute("""SELECT u.*, (SELECT COUNT(*) FROM projects p WHERE p.user_id=u.id) owned_projects, (SELECT COUNT(*) FROM project_members pm WHERE pm.user_id=u.id AND pm.status='active' AND pm.role<>'owner') shared_projects FROM users u ORDER BY u.id""").fetchall(); rules=conn.execute("SELECT * FROM automation_rules ORDER BY rule_key").fetchall(); projects=conn.execute("""SELECT p.id,p.name,p.site_url,p.status,u.email owner_email,u.name owner_name FROM projects p JOIN users u ON u.id=p.user_id ORDER BY p.updated_at DESC""").fetchall(); conn.close()
    chat_settings=communication_settings()
    smtp=smtp_config(); smtp_safe=dict(smtp); smtp_safe.pop("password",None)
    manifest_token=(os.getenv("DEVELOPER_MANIFEST_TOKEN") or "").strip()
    manifest_url=url_for("developer_manifest", token=manifest_token, _external=True, _scheme="https") if manifest_token else None
    return render_template("admin.html", stats=_admin_stats(), users=users, rules=rules, projects=projects, smtp=smtp_safe, chat_settings=chat_settings, manifest_url=manifest_url, diagnostic_url=(url_for('safe_diagnostic_manifest',token=_safe_diagnostic_url_token(),_external=True,_scheme='https') if _safe_diagnostic_url_token() else None), smart_card_registry=SMART_CARD_REGISTRY, smart_card_enabled=smart_card_settings(), knowledge_entries=library_rows(limit=100), merchant_developer_registration=(get_system_setting("merchant_developer_registration", {}) or {}), merchant_registration_csrf=_merchant_registration_form_csrf(), google_oauth_ready=google_oauth_ready())


@app.route('/admin/merchant/register/start', methods=['POST'])
@login_required
@admin_required
def admin_merchant_register_start():
    expected = session.get('merchant_registration_csrf') or ''
    provided = request.form.get('csrf_token') or ''
    if not expected or not hmac.compare_digest(expected, provided):
        abort(403)
    if get_system_setting('merchant_developer_registration', {}).get('registration_name'):
        flash('WebBooster už má potvrzenou registraci. Novou registraci nespouštím.', 'info')
        return redirect(url_for('admin_console')+'#merchant-developer')
    if not google_oauth_ready():
        flash('Google OAuth není nakonfigurovaný.', 'error')
        return redirect(url_for('admin_console')+'#merchant-developer')
    try:
        account, email = merchant_registration.validate(request.form.get('merchant_id'), request.form.get('developer_email'))
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin_console')+'#merchant-developer')
    if request.form.get('confirm') != 'yes':
        flash('Potvrď, že je tento Merchant účet registračním účtem WebBoosteru a máš na něm přímé administrátorské oprávnění.', 'error')
        return redirect(url_for('admin_console')+'#merchant-developer')
    state = secrets.token_urlsafe(32)
    session['merchant_registration_oauth'] = {'state':state,'merchant_id':account,
        'developer_email':email,'admin_id':current_user.id,'created_at':time.time()}
    params={'client_id':os.getenv('GOOGLE_CLIENT_ID'), 'redirect_uri':os.getenv('GOOGLE_REDIRECT_URI'),
            'response_type':'code','scope':merchant_registration.SCOPE,'access_type':'offline',
            'prompt':'consent','state':state}
    return redirect(GOOGLE_AUTH_URL+'?'+urlencode(params))


def _admin_merchant_registration_callback(state):
    pending=session.pop('merchant_registration_oauth', None) or {}
    if not current_user.is_authenticated or not current_user.is_admin or str(pending.get('admin_id') or '') != str(current_user.id):
        abort(403)
    if not hmac.compare_digest(str(pending.get('state') or ''), str(state or '')) or time.time()-float(pending.get('created_at') or 0)>900:
        flash('Registrace vypršela nebo OAuth stav nesouhlasí. Spusť ji znovu.', 'error')
        return redirect(url_for('admin_console')+'#merchant-developer')
    if request.args.get('error'):
        flash('Google autorizace nebyla dokončena.', 'error')
        return redirect(url_for('admin_console')+'#merchant-developer')
    if get_system_setting('merchant_developer_registration', {}).get('registration_name'):
        flash('WebBooster už je registrovaný; duplicitní operaci jsem neprovedl.', 'info')
        return redirect(url_for('admin_console')+'#merchant-developer')
    try:
        token_response=requests.post(GOOGLE_TOKEN_URL, data={
            'code':request.args.get('code',''), 'client_id':os.getenv('GOOGLE_CLIENT_ID'),
            'client_secret':os.getenv('GOOGLE_CLIENT_SECRET'), 'redirect_uri':os.getenv('GOOGLE_REDIRECT_URI'),
            'grant_type':'authorization_code'}, timeout=max(HTTP_TIMEOUT,20))
        if token_response.status_code>=300:
            raise ValueError('Výměna Google OAuth kódu selhala (HTTP '+str(token_response.status_code)+').')
        token_data=token_response.json()
        token=token_data.get('access_token')
        if not token:
            raise ValueError('Google nevrátil přístupový token.')
        scopes=set(str(token_data.get('scope') or '').split())
        if scopes and merchant_registration.SCOPE not in scopes:
            raise ValueError('Google neudělil oprávnění Merchant API.')
        # This access token is deliberately not persisted. It only authorizes the single registration request.
        def post(url, body):
            return google_api_request('POST',url,token,body)
        registration=merchant_registration.register(post,pending['merchant_id'],pending['developer_email'])
        registration.update({'registered_at':now(),'registered_by':current_user.id})
        set_system_setting('merchant_developer_registration',registration,user_id=current_user.id)
        flash('WebBooster byl úspěšně zaregistrován pro Merchant API. Nyní můžeš připojit Merchant účet v konektorech projektu.', 'success')
    except (ValueError,requests.RequestException) as exc:
        app.logger.warning('Merchant developer registration failed: %s',type(exc).__name__)
        flash('Registraci Google nepotvrdil: '+str(exc)[:240], 'error')
    return redirect(url_for('admin_console')+'#merchant-developer')


@app.route("/admin/assistant/communication", methods=["POST"])
@login_required
@admin_required
def admin_assistant_communication():
    tone=request.form.get('tone','friendly')
    address=request.form.get('address','informal')
    if tone not in {'friendly','professional','energetic'} or address not in {'informal','formal'}: abort(400)
    instructions=(request.form.get('instructions') or '').strip()[:2500]
    if not instructions: abort(400)
    conn=db()
    for key,value in {'tone':tone,'address':address,'instructions':instructions}.items():
        if DB_BACKEND=='mysql':
            conn.execute('INSERT INTO assistant_settings(setting_key,setting_value) VALUES(?,?) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)',(key,value))
        else:
            conn.execute('INSERT OR REPLACE INTO assistant_settings(setting_key,setting_value) VALUES(?,?)',(key,value))
    conn.commit();conn.close()
    flash('Pravidla komunikace Bobana jsem uložil.','success')
    return redirect(url_for('admin_console')+'#assistant-communication')


@app.route("/admin/workspace/cards", methods=["POST"])
@login_required
@admin_required
def admin_smart_cards():
    chosen=[x for x in request.form.getlist("card") if x in SMART_CARD_REGISTRY]
    chosen=list(dict.fromkeys(chosen))
    if not chosen:
        flash("Ponech alespoň jednu kartu.","error")
        return redirect(url_for("admin_console")+"#smart-workspace-settings")
    order={x: min(99, max(0,int(request.form.get("order_"+x) or 50))) for x in chosen}
    chosen.sort(key=lambda x: (order[x],list(SMART_CARD_REGISTRY).index(x)))
    conn=db()
    value=json.dumps(chosen,ensure_ascii=False)
    if DB_BACKEND=="mysql":
        conn.execute("INSERT INTO assistant_settings(setting_key,setting_value) VALUES(?,?) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)",("smart_cards",value))
    else:
        conn.execute("INSERT OR REPLACE INTO assistant_settings(setting_key,setting_value) VALUES(?,?)",("smart_cards",value))
    conn.commit();conn.close()
    flash("Pracovní karty Bobana jsou uložené.","success")
    return redirect(url_for("admin_console")+"#smart-workspace-settings")


@app.route("/admin/users/<int:user_id>/update", methods=["POST"])
@login_required
@admin_required
def admin_user_update(user_id):
    role=request.form.get("role","visitor"); status=request.form.get("account_status","active"); paid=request.form.get("paid_access_status","none"); alerts=1 if request.form.get("email_alerts") else 0
    if role not in {"admin","editor","visitor"}: role="visitor"
    if status not in {"active","disabled"}: status="active"
    if paid not in {"none","requested","active","manual","expired"}: paid="none"
    admin_email=(os.getenv("WEBBOOSTER_ADMIN_EMAIL") or "soufek@freshcrackers.cz").strip().lower(); conn=db(); target=conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    if target and str(target["email"] or "").lower()==admin_email:
        role="admin"; status="active"; paid="active"
    conn.execute("UPDATE users SET system_role=?,account_status=?,paid_access_status=?,email_alerts=? WHERE id=?", (role,status,paid,alerts,user_id)); conn.commit(); conn.close(); flash("Účet byl aktualizován.","success"); return redirect(url_for("admin_console")+"#accounts")


@app.route("/admin/access-requests/<int:request_id>/<decision>", methods=["POST"])
@login_required
@admin_required
def admin_access_request_decide(request_id,decision):
    if decision not in {"approve","reject"}: abort(400)
    conn=db(); req=conn.execute("SELECT * FROM access_requests WHERE id=? AND status='pending'", (request_id,)).fetchone()
    if not req: conn.close(); flash("Žádost už byla vyřízena.","info"); return redirect(url_for("admin_console"))
    status="approved" if decision=="approve" else "rejected"; conn.execute("UPDATE access_requests SET status=?,decided_at=?,decided_by=? WHERE id=?", (status,now(),current_user.id,request_id))
    if decision=="approve": conn.execute("UPDATE users SET system_role='editor',paid_access_status='manual',account_status='active' WHERE id=?", (req["user_id"],))
    else: conn.execute("UPDATE users SET paid_access_status='none' WHERE id=?", (req["user_id"],))
    conn.commit(); conn.close(); flash("Žádost byla schválena." if decision=="approve" else "Žádost byla zamítnuta.","success"); return redirect(url_for("admin_console"))


@app.route("/admin/automation/<rule_key>", methods=["POST"])
@login_required
@admin_required
def admin_automation_update(rule_key):
    enabled=1 if request.form.get("enabled") else 0
    try: interval=max(1,min(8760,int(request.form.get("interval_hours") or 24)))
    except Exception: interval=24
    conn=db(); row=conn.execute("SELECT rule_key FROM automation_rules WHERE rule_key=?", (rule_key,)).fetchone()
    if not row: conn.close(); abort(404)
    conn.execute("UPDATE automation_rules SET enabled=?,interval_hours=?,updated_at=?,updated_by=? WHERE rule_key=?", (enabled,interval,now(),current_user.id,rule_key)); conn.commit(); conn.close(); flash("Pravidlo automatizace bylo uloženo.","success"); return redirect(url_for("admin_console")+"#automation")


@app.route("/admin/automation/run-now", methods=["POST"])
@login_required
@admin_required
def admin_automation_run_now():
    kicked = kick_background_worker("tick")
    flash("Spustil jsem systémový tick na pozadí." if kicked else "Tick se nepodařilo spustit. Zkontroluj worker.log a cron.", "success" if kicked else "error")
    return redirect(url_for("admin_console") + "#automation")


@app.route("/admin/email", methods=["POST"])
@login_required
@admin_required
def admin_email_update():
    password=request.form.get("password","")
    try: port=max(1,min(65535,int(request.form.get("port") or 587)))
    except Exception: port=587
    security=request.form.get("security","starttls")
    if security not in {"starttls","ssl","none"}: security="starttls"
    conf={"enabled":bool(request.form.get("enabled")),"notification_enabled":bool(request.form.get("notification_enabled")),"notification_levels":request.form.getlist("notification_levels") or ["error"],"host":request.form.get("host","").strip(),"port":port,"security":security,"username":request.form.get("username","").strip(),"from_email":request.form.get("from_email","").strip(),"from_name":request.form.get("from_name","").strip() or "Boban • Web Booster"}
    set_system_setting("smtp",conf,secret=password if password else None,user_id=current_user.id); flash("Nastavení e-mailu bylo uloženo.","success"); return redirect(url_for("admin_console")+"#email")


@app.route("/admin/email/test", methods=["POST"])
@login_required
@admin_required
def admin_email_test():
    to=request.form.get("to_email","").strip() or current_user.email
    try: send_email_message(to,"Web Booster – test e-mailu","Ahoj, toto je testovací zpráva z administrační konzole Web Boosteru. SMTP připojení funguje."); flash(f"Testovací e-mail byl odeslán na {to}.","success")
    except Exception as exc: flash(f"Test e-mailu selhal: {exc}","error")
    return redirect(url_for("admin_console")+"#email")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


def _notify_fresh_key_link_requests(user_id, requests):
    for req in requests or []:
        rid=str(req.get("id") or "")
        if not rid: continue
        kind=("fresh_key_link_"+rid.replace("-","")[:20])[:60]
        conn=db(); existing=conn.execute("SELECT id FROM notifications WHERE user_id=? AND kind=? LIMIT 1", (user_id,kind)).fetchone(); conn.close()
        if existing: continue
        target=str(req.get("target_external_project_id") or "")
        pid=int(target) if target.isdigit() else None
        url=url_for("project_access",project_id=pid) if pid else url_for("dashboard")
        who=(req.get("requester") or {}).get("display_name") or (req.get("requester") or {}).get("email") or "Uživatel Fresh AI"
        create_notification(pid,"Návrh propojení projektu",f"{who} navrhuje propojení s {req.get('link_name') or 'Fresh Key'}.",url,level="info",kind=kind,user_id=user_id)


@app.route("/dashboard")
@login_required
def dashboard():
    fresh_requests=[]
    if fresh_key.configured():
        try:
            # Fresh Key never auto-publishes local projects. Only an explicit
            # "Odeslat do Fresh Key" does that; here we only load proposals.
            projects = accessible_projects(current_user.id)
            fresh_key.bootstrap_account(int(current_user.id), current_user.email, getattr(current_user, "name", "") or current_user.email)
            fresh_requests=fresh_key.pending_link_requests(int(current_user.id))
            _notify_fresh_key_link_requests(int(current_user.id),fresh_requests)
        except Exception:
            projects = accessible_projects(current_user.id)
            fresh_requests=[]
    else:
        projects = accessible_projects(current_user.id)
    conn=db(); access_request=conn.execute("SELECT * FROM access_requests WHERE user_id=? ORDER BY id DESC LIMIT 1", (current_user.id,)).fetchone(); conn.close()
    return render_template("dashboard.html", projects=projects, access_request=access_request, fresh_key_requests=fresh_requests)


@app.route("/projects/new", methods=["GET", "POST"])
@login_required
@editor_required
def project_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        site_url = request.form.get("site_url", "").strip().rstrip("/")
        manifest_url = request.form.get("core_manifest_url", "").strip()
        if not name or not site_url.startswith("https://"):
            flash("Zadej název projektu a veřejnou HTTPS URL webu.", "error")
            return render_template("project_new.html")
        conn = db()
        cur = conn.execute(
            """INSERT INTO projects(user_id,name,site_url,status,health_score,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (current_user.id, name, site_url, "waiting", 0, now(), now())
        )
        pid = cur.lastrowid
        add_activity(conn, pid, "project", "Projekt vytvořen", "Čekám na propojení přes Fresh Core.")
        conn.execute("INSERT INTO project_members(project_id,user_id,role,status,invited_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (pid,current_user.id,"owner","active",current_user.id,now(),now()))
        conn.commit()
        conn.close()

        if manifest_url:
            try:
                connect_core(pid, manifest_url)
                flash("Fresh Core připojen a první CMS audit je hotový.", "success")
            except Exception as exc:
                flash(f"Projekt je vytvořen, ale Fresh Core se nepodařilo připojit: {exc}", "error")
        return redirect(url_for("project", project_id=pid))
    return render_template("project_new.html")


@app.route("/projects/<int:project_id>")
@login_required
def project(project_id):
    p = project_for_user(project_id)
    expire_snoozes(project_id)
    reconcile_project_state(project_id)
    chat_threads = chat_thread_list(project_id)
    current_thread = next((t for t in chat_threads if t["end_message_id"] is None), chat_threads[0])
    conn = db()
    messages = conn.execute(
        "SELECT * FROM messages WHERE project_id=? AND id>=? ORDER BY id DESC LIMIT 100",
        (project_id, current_thread["start_message_id"])
    ).fetchall()
    messages = list(reversed(messages))
    chat_messages = []
    for m in messages:
        item = dict(m)
        try:
            item["meta"] = json.loads(item.get("meta_json") or "{}")
        except Exception:
            item["meta"] = {}
        chat_messages.append(item)
    activities = conn.execute(
        "SELECT * FROM activities WHERE project_id=? ORDER BY id DESC LIMIT 20", (project_id,)
    ).fetchall()
    actions = conn.execute(
        "SELECT * FROM actions WHERE project_id=? AND status NOT IN ('dismissed','snoozed') ORDER BY id DESC LIMIT 8", (project_id,)
    ).fetchall()
    engine_run = conn.execute(
        "SELECT * FROM engine_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,)
    ).fetchone()
    conn.close()
    snapshot = project_snapshot(p)
    severities = count_by_severity(project_id)
    kinds = count_by_kind(project_id)
    gsc = latest_source_snapshot(project_id, "search_console")
    ga4 = latest_source_snapshot(project_id, "ga4")
    scorecard = seo_scorecard(project_id)
    return render_template(
        "project.html", project=p, messages=chat_messages, chat_threads=chat_threads, activities=activities,
        snapshot=snapshot, severities=severities, kinds=kinds, actions=actions,
        gsc=gsc, ga4=ga4, category_scores=scorecard.get("categories", {}), scorecard=scorecard,
        advisor=advisor_state(project_id), score_info=score_interpretation(scorecard.get("overall", 0)), queue=queue_summary(project_id), worker=worker_state(),
        engine_run=engine_run, value_summary=boban_value_summary(project_id),
        progress=project_progress_summary(project_id, gsc, ga4), strategy=project_strategy(p),
        **smart_workspace_context(project_id,p,smart_topic(next((m["body"] for m in reversed(chat_messages) if m["role"]=="user"), "")))
    )


def _explicit_strategy_from_chat(body):
    """Conservative local fallback when the user explicitly states a business goal.

    The AI Engine is allowed to return a richer strategy_update, but this keeps
    the basic "set my goal in chat" workflow working even if the Engine returns
    plain text. We intentionally do not infer goals from vague requests.
    """
    text = str(body or "").strip()
    if not text or len(text) > 1200:
        return None
    patterns = [
        r"(?is)^\s*(?:m[uů]j|n[aá][sš])?\s*(?:hlavn[ií]\s*)?(?:obchodn[ií]\s*)?c[ií]l(?:em)?\s*(?:je|:)\s*(.+?)\s*$",
        r"(?is)^\s*c[ií]lem\s+(?:webu|projektu)\s*(?:je|:)\s*(.+?)\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            goal = re.sub(r"\s+", " ", match.group(1)).strip(" .")
            if 8 <= len(goal) <= 900:
                return {"confirmed_by_user": True, "business_goal": goal}
    return None


def _chat_command_from_text(body):
    text = re.sub(r"\s+", " ", str(body or "").strip().lower())
    if len(text) > 260:
        return ""
    phrases = (
        "pokračuj podle plánu", "pokracuj podle planu", "pusť se do práce", "pust se do prace",
        "začni pracovat", "zacni pracovat", "udělej co můžeš", "udelej co muzes",
        "udělej všechno co můžeš", "udelej vsechno co muzes", "připrav práci", "priprav praci",
        "znovu analyzuj a připrav práci", "znovu analyzuj a priprav praci",
    )
    return "run_operator" if any(p in text for p in phrases) else ""


def apply_chat_strategy_update(project_id, update):
    if not isinstance(update, dict):
        return None
    if not bool(update.get("confirmed_by_user") or update.get("apply")):
        return None
    conn = db()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); return None
    values = {
        "business_goal": str(row["business_goal"] or ""),
        "primary_conversion": str(row["primary_conversion"] or ""),
        "priority_topics": str(row["priority_topics"] or ""),
        "brand_terms": str(row["brand_terms"] or ""),
    }
    limits = {"business_goal": 4000, "primary_conversion": 190, "priority_topics": 4000, "brand_terms": 2000}
    changed = []
    for key, limit in limits.items():
        if key not in update or update.get(key) in (None, "", []):
            continue
        raw = update.get(key)
        if isinstance(raw, (list, tuple)):
            raw = ", ".join(str(x).strip() for x in raw if str(x).strip())
        value = re.sub(r"\s+", " ", str(raw)).strip()[:limit]
        if value and value != values[key]:
            values[key] = value; changed.append(key)
    if not changed:
        conn.close(); return None
    ts = now()
    conn.execute(
        """UPDATE projects SET business_goal=?,primary_conversion=?,priority_topics=?,brand_terms=?,updated_at=? WHERE id=?""",
        (values["business_goal"], values["primary_conversion"], values["priority_topics"], values["brand_terms"], ts, project_id)
    )
    add_activity(conn, project_id, "strategy", "Boban upravil obchodní zadání z chatu", ", ".join(changed))
    conn.commit(); conn.close()
    build_operator_plan(project_id, persist=True)
    conn = db(); updated = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close()
    return project_strategy(updated) if updated else None


@app.route("/projects/<int:project_id>/goals")
@login_required
def project_goals(project_id):
    project = project_for_user(project_id)
    return render_template("business_goals.html", project=project)


def _stat_trend_chart(payload):
    """Convert GA4 daily channel rows to safe, non-duplicated daily session totals.

    Note: total channel counts reflect the provided channel breakdown; they
    must not be interpreted as sales or distinct people.
    """
    from collections import defaultdict
    reports=(payload.get('extended_reports') or {})
    rows = reports.get('daily_totals') if isinstance(reports.get('daily_totals'),list) and reports.get('daily_totals') else (reports.get('daily_channels') or [])
    totals = defaultdict(int)
    for item in rows:
        if not isinstance(item, dict):
            continue
        day = str(item.get('date') or '')
        if len(day) != 8 or not day.isdigit():
            continue
        try:
            sessions = max(0, int(item.get('sessions') or 0))
        except (ValueError, TypeError):
            continue
        totals[day] += sessions
    ordered = sorted(totals.items())
    if len(ordered) < 2:
        return {'points': '', 'labels': [], 'available': False}
    top = max(value for _, value in ordered) or 1
    width, height, margin = 880, 170, 14
    points = ' '.join(f'{margin + (width - 2*margin)*i/(len(ordered)-1):.2f},'
                      f'{height-margin-(height-2*margin)*value/top:.2f}'
                      for i, (_, value) in enumerate(ordered))
    return {'points': points, 'labels': [ordered[0][0], ordered[-1][0]],
            'available': True, 'max_value': top, 'n_days': len(ordered)}


@app.route("/projects/<int:project_id>/statistics")
@login_required
def project_statistics(project_id):
    project = project_for_user(project_id)
    conn = db()
    try:
        snapshots = conn.execute(
            "SELECT provider,period_start,period_end,captured_at,payload FROM source_snapshots WHERE project_id=? ORDER BY id DESC LIMIT 300",
            (project_id,)
        ).fetchall()
        integrations = conn.execute(
            "SELECT provider,status,config_json FROM integrations WHERE project_id=? ORDER BY provider", (project_id,)
        ).fetchall()
        # Read only latest automation log; no API calls on page load.
        jobs = conn.execute(
            "SELECT job_type,status,finished_at,result_json FROM jobs WHERE project_id=? ORDER BY id DESC LIMIT 150", (project_id,)
        ).fetchall()
        feed_counts={}
        for table,code in [('project_google_feeds','merchant_center'),('project_meta_feeds','meta_catalog'),
                           ('project_heureka_feeds','heureka'),('project_zbozi_feeds','zbozi_fenix')]:
            try:
                rec=conn.execute(f'SELECT exported_count,generated_at FROM {table} WHERE project_id=?',(project_id,)).fetchone()
                if rec:feed_counts[code]={'count':rec['exported_count'],'generated_at':rec['generated_at']}
            except Exception:
                pass
        analytical_runs = commerce_analytics.dashboard_rows(conn, project_id)
        ga_period = next((r for r in snapshots if r['provider']=='ga4'), None)
        outcome_summary = commerce_analytics.outcomes_summary(
            conn, project_id,
            start=ga_period['period_start'] if ga_period else None,
            end=ga_period['period_end'] if ga_period else None)
        # Only safe, business-oriented catalog details. No secrets exposed to HTML.
        platforms = {}
        for src in integrations:
            provider = str(src['provider'])
            if provider in ('ga4','search_console','merchant_center','zbozi_fenix','meta','meta_catalog','heureka'):
                try: cfg=json.loads(src['config_json'] or '{}')
                except (ValueError,TypeError):cfg={}
                platforms[provider] = {
                    'status':src['status'],
                    'checked_at': cfg.get('checked_at') or cfg.get('report_checked_at'),
                    'has_performance':bool(cfg.get('report')),
                    'report': ({k:cfg['report'].get(k) for k in ('clicks','impressions','ctr_percent','period_start','period_end','complete')}
                               if provider=='merchant_center' and isinstance(cfg.get('report'),dict) else None),
                    'report_error':str(cfg.get('report_last_error') or '')[:220],
                    'product_count': ((cfg.get('aggregate') or {}).get('totalProducts') if isinstance(cfg.get('aggregate'),dict) else None),
                }

    finally:
        conn.close()
    latest = {}
    for row in snapshots:
        if row['provider'] not in latest:
            try: payload = json.loads(row['payload'] or '{}')
            except (TypeError, ValueError): payload = {}
            latest[row['provider']] = dict(provider=row['provider'], period_start=row['period_start'],
                period_end=row['period_end'], captured_at=row['captured_at'], data=payload)
    job_last = {}
    for job in jobs:
        if job['job_type'] not in job_last:
            job_last[job['job_type']] = dict(job_type=job['job_type'], status=job['status'],
                finished_at=job['finished_at'])
    integrations_view = [dict(provider=r['provider'],status=r['status'],
        last_job=job_last.get(str(r['provider'])+'_sync')) for r in integrations]
    ga_data=latest.get('ga4',{}).get('data',{})
    gsc_data=latest.get('search_console',{}).get('data',{})
    business_type=business_dashboard.business_mode(project)
    quality=business_dashboard.analytics_quality(latest,analytical_runs)
    joined_pages=business_dashboard.page_summary(ga_data,gsc_data)
    queries_to_pages=business_dashboard.query_page_samples(gsc_data)
    funnel=business_dashboard.funnel_steps(business_type,ga_data,outcome_summary)
    sync_health={}
    for kind, jobtype in [('ga4','ga4_sync'),('search_console','search_console_sync')]:
        record=next((j for j in jobs if j['job_type']==jobtype),None)
        if record:
            summary={'status':record['status'],'finished_at':record['finished_at']}
            if record['status']=='failed':
                try: err=json.loads(record['result_json'] or '{}').get('error','Synchronizace selhala')
                except (ValueError,TypeError):err='Synchronizace selhala'
                # Never disclose OAuth response bodies or secrets in dashboard HTML.
                summary['error']='Google autorizace vyžaduje ověření' if 'token' in str(err).lower() else 'Synchronizace selhala; zkontrolujte log služby.'
            sync_health[kind]=summary
    previous=(ga_data.get('previous_total') or {})
    current=(ga_data.get('current_total') or {})
    current_sessions=current.get('sessions')
    previous_sessions=previous.get('sessions')
    session_delta=(round((float(current_sessions)-float(previous_sessions))/float(previous_sessions)*100,1)
                   if current_sessions is not None and previous_sessions not in (None,0,0.0) else None)
    return render_template('statistics.html', project=project, latest=latest,
        sources=integrations_view, jobs=job_last, catalog=core_catalog_summary(project_id),
        ga4=latest.get('ga4',{}).get('data',{}), gsc=latest.get('search_console',{}).get('data',{}),
        analytical_runs=analytical_runs, outcomes=outcome_summary, platforms=platforms, feed_counts=feed_counts,
        trend_chart=_stat_trend_chart(ga_data), business_type=business_type,
        data_quality=quality, joined_pages=joined_pages, query_pages=queries_to_pages,
        funnel_steps=funnel, sync_health=sync_health, session_delta=session_delta)


@app.route("/projects/<int:project_id>/chat/recent", methods=["GET"])
@login_required
def project_chat_recent(project_id):
    project_for_user(project_id)
    threads = chat_thread_list(project_id)
    active = next((t for t in threads if t['end_message_id'] is None), None)
    if not active:
        return jsonify({'messages':[]})
    conn=db()
    try:
        rows=conn.execute(
            "SELECT role,body,created_at FROM messages WHERE project_id=? AND id>=? ORDER BY id DESC LIMIT 40",
            (project_id, active['start_message_id'])
        ).fetchall()
        return jsonify({'messages':[{'role':r['role'],'body':r['body'],'created_at':r['created_at']} for r in reversed(rows)]})
    finally: conn.close()


@app.route("/projects/<int:project_id>/results")
@login_required
def business_results(project_id):
    p=project_for_user(project_id)
    gsc=latest_source_snapshot(project_id,"search_console")
    ga4=latest_source_snapshot(project_id,"ga4")
    return render_template("business_results.html",project=p,gsc=gsc,ga4=ga4,progress=project_progress_summary(project_id,gsc,ga4))


@app.route('/projects/<int:project_id>/advisor/evidence', methods=['GET'])
@login_required
def advisor_evidence(project_id):
    """User-visible trace of evidence and memory used by the chat."""
    project_for_user(project_id)
    conn=db()
    try:
        memory=advisor_intelligence.recent_memory(conn,project_id,limit=40)
        rows=conn.execute('SELECT id,tool_name,question,evidence_json,created_at FROM advisor_analysis_runs WHERE project_id=? ORDER BY id DESC LIMIT 25',(project_id,)).fetchall()
        history=[{'id':r['id'],'tool':r['tool_name'],'question':r['question'],
                  'sources':json.loads(r['evidence_json'] or '[]'),'created_at':r['created_at']} for r in rows]
        return jsonify({'project_id':project_id,'memory':memory,'recent_analyses':history,
                        'explanation':'Ověřené skutečnosti, uživatelská rozhodnutí a analytické stopy. Stale označuje údaj k opětovnému ověření.'})
    finally:conn.close()


def clean_advisor_answer(value):
    """Unwrap AI-engine JSON envelopes (including JSON-encoded strings).

    Keep arbitrary prose intact, never leak control fields into the chat bubble.
    """
    if isinstance(value, dict):
        for key in ("answer", "text", "message", "content"):
            if key in value and value[key] is not None:
                return clean_advisor_answer(value[key])
        return ""
    if not isinstance(value, str):
        return str(value or "")
    content = value.strip()
    for _ in range(3):
        candidate = content
        if candidate.startswith("```"):
            parts = candidate.split("\n", 1)
            if len(parts) > 1 and parts[1].rstrip().endswith("```"):
                candidate = parts[1].rstrip()[:-3].strip()
        if not candidate.startswith("{"):
            break
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError):
            break
        if not isinstance(parsed, dict) or not any(k in parsed for k in ("answer", "text", "message", "content")):
            break
        content = clean_advisor_answer(parsed)
    return content


@app.route("/projects/<int:project_id>/chat", methods=["POST"])
@login_required
def project_chat(project_id):
    p = project_for_user(project_id)
    payload_in = request.get_json(silent=True) if request.is_json else None
    body = str((payload_in or {}).get("body") if isinstance(payload_in, dict) else request.form.get("body", "")).strip()
    if not body:
        return redirect(url_for("project", project_id=project_id))

    threads = chat_thread_list(project_id)
    current_thread = next((t for t in threads if t["end_message_id"] is None), threads[0])
    conn = db()
    conn.execute(
        "INSERT INTO messages(project_id,user_id,role,body,created_at) VALUES(?,?,?,?,?)",
        (project_id, current_user.id, "user", body, now())
    )
    recent_messages = conn.execute(
        "SELECT role,body FROM messages WHERE project_id=? AND id>=? ORDER BY id DESC LIMIT 10",
        (project_id,current_thread["start_message_id"])
    ).fetchall()
    recent_actions = conn.execute(
        "SELECT id,status,target_url,reason,expected_outcome,applied_at,measured_at FROM actions WHERE project_id=? ORDER BY id DESC LIMIT 8",
        (project_id,)
    ).fetchall()
    conn.commit()
    conn.close()

    analysis_conn=db()
    try:
        analyst_context=advisor_intelligence.chat_context(analysis_conn,DB_BACKEND,project_id,body)
    finally:
        analysis_conn.close()
    state = advisor_state(project_id)
    state["queue"] = queue_summary(project_id)
    state["worker"] = worker_state()
    state["value_summary"] = boban_value_summary(project_id)
    answer = ""
    engine_error = ""
    strategy_update = None
    requested_command = ""
    requested_cards = []
    if os.getenv("FRESH_AI_ENGINE_URL") and os.getenv("FRESH_AI_ENGINE_API_KEY"):
        try:
            context = {
                "commercial_analysis": analyst_context,
                "site_url": p["site_url"],
                "seo_score": state.get("scorecard", {}).get("overall", p["health_score"]),
                "seo_scorecard": state.get("scorecard", {}),
                "score_explanation": state["score"],
                "seo_url_count": p["seo_url_count"],
                "open_issue_count": p["open_issue_count"],
                "findings": state["findings"],
                "pending_tasks": state["pending"],
                "completed_tasks": state["done"],
                "recent_actions": [dict(x) for x in recent_actions],
                "value_summary": state.get("value_summary", {}),
                "search_console": latest_source_snapshot(project_id, "search_console"),
                "ga4": latest_source_snapshot(project_id, "ga4"),
                "pagespeed_crux": latest_source_snapshot(project_id, "pagespeed_crux"),
                "gtm_audit": latest_source_snapshot(project_id, "gtm"),
                "business_strategy": project_strategy(p),
                "work_plan": latest_operator_plan(project_id),
                "advisor_evidence_url": url_for("advisor_evidence", project_id=project_id),
                "capabilities": OPERATOR_CAPABILITY_REGISTRY,
                "communication_rules": communication_settings(),
                "seo_knowledge_matches": knowledge_context_for_chat(project_id, body),
                "core_commerce": core_catalog_summary(project_id),
                "write_bridge_connected": p["core_write_status"] == "connected",
                "recent_chat": [dict(x) for x in reversed(recent_messages)],
                "workspace": {"topic": smart_topic(body), "visible_cards": smart_cards_for(smart_topic(body)),
                              "card_catalog": {key: item["title"] for key,item in SMART_CARD_REGISTRY.items()}},
                "available_ui": {
                    "business_goals": url_for("project_goals", project_id=project_id),
                    "business_results": url_for("business_results", project_id=project_id),
                    "seo_overview": url_for("seo", project_id=project_id),
                    "search_performance": url_for("search_performance", project_id=project_id),
                    "tasks": url_for("actions", project_id=project_id, view="todo"),
                    "archive": url_for("actions", project_id=project_id, view="done"),
                    "connectors": url_for("connectors", project_id=project_id),
                    "project": url_for("project", project_id=project_id),
                },
            }
            result = call_fresh_ai_engine(
                p,
                "seo_advisor",
                (
                    "Jsi Boban, výkonnostní SEO a growth specialista. Tvůj primární cíl není maximalizovat interní SEO skóre, ale plnit obchodní cíl projektu: zvyšovat relevantní organickou viditelnost, návštěvnost a měřitelné konverze. "
                    "Mluv v první osobě, přirozeně jako zkušený kolega. Přizpůsob tón pravidlům communication_rules, pokud nejsou v rozporu s bezpečností a pravdivostí. "
                    "Před odpovědí použij commercial_analysis.analysis ze skutečného analytického nástroje. Nevydávej odhad za naměřený fakt. Respektuj commercial_analysis.project_memory; informace s příznakem stale musíš ověřit. Když chybí objednávky, neuváděj nulu ani tvrzení, že se nic neprodalo. Pokud je katalog již connected, nenavrhuj jeho prvotní instalaci. "
                    "Nejdříve určete typ otázky. U vysvětlení pojmů odpověz přirozeně a jednoduše, nejlépe 2–4 krátkými odstavci s jedním konkrétním příkladem; netvoř automaticky plán ani dlouhý SEO audit. U obchodního zadání navrhni několik prioritních kroků, jen pokud si je uživatel přeje. "
                    "Důsledně respektuj capabilities: pokud něco umím připravit nebo provést přes Fresh Core/API, neříkej uživateli, aby to dělal ručně. Řekni, že to připravím a po schválení provedu. Pokud API zápis neumím, jasně řekni, s čím potřebuji pomoc. "
                    "Nikdy znovu nenavrhuj jako nový úkol něco, co recent_actions ukazují jako applied, verified nebo completed, pokud nemáš důkaz, že se problém vrátil. Připravené drafty nepřepisuj novými doporučeními; směřuj uživatele ke schválení. "
                    "Rozlišuj fakta z dat od očekávání. U změn vždy řekni očekávaný výsledek a jak ho později ověříme. Když chybí měření, nepřisuzuj si přínos. "
                    "Když se uživatel ptá na stav provedené práce, uveď co se opravdu stalo, jaký je důkaz a co následuje. U prostého dotazu na vysvětlení nic nevydávej za provedený úkol. "
                    "Použij relevantní seo_knowledge_matches z poradny a při odborném vysvětlení přidej jejich existující URL jako zdroj. Pokud znalost není v knihovně, nevymýšlej odkaz. "
                    "Pracovní panel automaticky ukazuje ověřené karty podle tématu. V odpovědi můžeš uvést odkazy na existující available_ui, ale nikdy si nevymýšlej nové URL či funkce. Neopisuj dlouhé statistiky, které jsou již v pracovním panelu. Pokud katalogová integrace není aktivní, jasně uveď, že ji teprve připravujeme. "
                    "Odpovídej vždy česky, lidsky a stručně, zpravidla do 150 slov u jednoduché otázky. Neopakuj celou analytiku, kterou uživatel vidí na stránce. Zůstaň u dotazu, vysvětli žargon, případně polož jednu přirozenou navazující otázku. U náročné analýzy může být odpověď delší. Nikdy nepublikuj bez schválení. "
                    "Když business_strategy.business_goal chybí, polož jednu krátkou otázku na obchodní výsledek, který mám podporovat. Pokud uživatel v aktuální zprávě cíl výslovně stanoví nebo změní, můžeš ho uložit z chatu. "
                    "Pokud rozhraní vyžaduje JSON, vrať validní objekt s polem answer jako obyčejným textem; nevracej JSON jako řetězec uvnitř answer. Vedlejší řídicí pole neuváděj v textu answer. "
                    "card_ids mohou obsahovat jen ID z workspace.card_catalog, nejvýše 5. Vyber karty užitečné pro konkrétní dotaz, ne vždy stejné. "
                    "strategy_update použij jen při explicitním zadání uživatele a pak vrať {\"confirmed_by_user\":true,\"business_goal\":\"...\",\"primary_conversion\":\"...\",\"priority_topics\":[...],\"brand_terms\":[...]}; nevyplněná pole vynech. "
                    "command nastav na run_operator pouze když uživatel výslovně žádá, abych se pustil do práce, pokračoval podle plánu nebo připravil úkoly; jinak none. "
                    f"\n\nUživatel: {body}"
                ),
                context,
                max_cost_usd=0.30,
            )
            if isinstance(result, str):
                answer = result.strip()
            elif isinstance(result, dict):
                answer = str(
                    result.get("answer") or result.get("text") or result.get("message") or result.get("content") or ""
                ).strip()
                if isinstance(result.get("strategy_update"), dict):
                    strategy_update = result.get("strategy_update")
                requested_command = str(result.get("command") or "").strip().lower()
                if isinstance(result.get("card_ids"),list):
                    requested_cards=result["card_ids"][:5]
        except Exception as exc:
            engine_error = str(exc)

    answer = clean_advisor_answer(answer)
    if not strategy_update:
        strategy_update = _explicit_strategy_from_chat(body)
    saved_strategy = apply_chat_strategy_update(project_id, strategy_update) if strategy_update else None
    if saved_strategy and saved_strategy.get("business_goal"):
        note = f"Obchodní cíl jsem si uložil: {saved_strategy['business_goal']}."
        if answer and note.lower() not in answer.lower():
            answer = note + "\n\n" + answer

    command = requested_command if requested_command in {"run_operator"} else _chat_command_from_text(body)
    operator_result = None
    if command == "run_operator":
        if getattr(current_user, "can_edit", False):
            try:
                operator_result = operator_cycle(project_id, force=True)
                prepared = int((operator_result or {}).get("prepared") or 0)
                if prepared:
                    answer = (answer + "\n\n" if answer else "") + f"Pustil jsem pracovní cyklus. Připravuji {prepared} konkrétních zásahů; jakmile budou hotové návrhy, najdeš je v Úkolech ke schválení."
                else:
                    answer = (answer + "\n\n" if answer else "") + "Pracovní plán jsem znovu prošel. Teď nemám nový bezpečný zásah, který bych mohl bez dalšího kontextu připravit."
            except Exception as exc:
                answer = (answer + "\n\n" if answer else "") + f"Pracovní cyklus se mi teď nepodařilo spustit: {str(exc)[:220]}"
        else:
            answer = (answer + "\n\n" if answer else "") + "Pracovní cyklus může spustit Editor nebo Admin. Tvůj přístup je teď pouze pro čtení."

    if not answer:
        # Deterministic evidence-based fallback; never present empty analytics as sales zero.
        answer = advisor_intelligence.fallback_answer(analyst_context["analysis"])
        if engine_error:
            answer += "\n\nTechnická poznámka: Fresh AI Engine není dostupný; zobrazil jsem ověřitelnou lokální analýzu."

    conn = db()
    state = advisor_state(project_id)  # strategy/operator may have changed during this message
    message_meta = {"actions": state.get("suggestions", [])[:4], "workspace_topic":smart_topic(body),
                    "workspace_cards":smart_selected_cards(smart_topic(body),requested_cards)}
    message_meta["analytical_tool"] = analyst_context["selected_tool"]
    message_meta["analytical_sources"] = analyst_context["analysis"]["evidence_sources"]
    if saved_strategy:
        message_meta["strategy_updated"] = True
        message_meta["strategy"] = saved_strategy
    assistant_created_at = now()
    conn.execute(
        "INSERT INTO messages(project_id,user_id,role,body,meta_json,created_at) VALUES(?,?,?,?,?,?)",
        (project_id, current_user.id, "assistant", answer, json.dumps(message_meta, ensure_ascii=False), assistant_created_at)
    )
    conn.commit()
    conn.close()
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "ok": True, "answer": answer, "created_at": assistant_created_at, "actions": message_meta.get("actions", []),
            "strategy_updated": bool(saved_strategy), "strategy": saved_strategy or {},
            "operator": operator_result or {},
            "workspace_cards": smart_workspace_html(project_id,smart_topic(body),requested_cards),
            "workspace_topic": smart_topic(body)
        })
    return redirect(url_for("project", project_id=project_id) + "#boban-chat")


@app.route("/projects/<int:project_id>/chat/new", methods=["POST"])
@login_required
def project_chat_new(project_id):
    project_for_user(project_id)
    chat_thread_list(project_id)
    cutoff = datetime.now().isoformat(timespec="microseconds")
    conn = db()
    last = conn.execute("SELECT id,start_message_id FROM chat_threads WHERE project_id=? AND end_message_id IS NULL ORDER BY id DESC LIMIT 1",(project_id,)).fetchone()
    last_msg = conn.execute("SELECT MAX(id) AS mx FROM messages WHERE project_id=?",(project_id,)).fetchone()
    max_id = int(last_msg["mx"] or 0)
    if last:
        conn.execute("UPDATE chat_threads SET end_message_id=? WHERE id=? AND project_id=?",(max_id,last["id"],project_id))
    conn.execute("INSERT INTO chat_threads(project_id,title,start_message_id,created_at) VALUES(?,?,?,?)",(project_id,"Nový chat",max_id+1,cutoff))
    conn.execute("UPDATE projects SET chat_cutoff=?,updated_at=? WHERE id=?", (cutoff, cutoff, project_id))
    conn.commit(); conn.close()
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": "Začínáme nový chat. Co chceš řešit?"})
    flash("Začal jsem nový chat. Starší konverzaci nepoužívám v aktuálním vlákně.", "success")
    return redirect(url_for("project", project_id=project_id) + "#boban-chat")


@app.route("/projects/<int:project_id>/chats/<int:thread_id>")
@login_required
def project_chat_archive(project_id, thread_id):
    project_for_user(project_id)
    chat_thread_list(project_id)
    conn=db()
    thread=conn.execute("SELECT * FROM chat_threads WHERE id=? AND project_id=?",(thread_id,project_id)).fetchone()
    if not thread:
        conn.close(); abort(404)
    end=int(thread["end_message_id"]) if thread["end_message_id"] is not None else 9223372036854775807
    rows=conn.execute("SELECT role,body,created_at FROM messages WHERE project_id=? AND id>=? AND id<=? ORDER BY id ASC LIMIT 300", (project_id,thread["start_message_id"],end)).fetchall()
    conn.close()
    return render_template("chat_archive.html",project=project_for_user(project_id),thread=thread,messages=rows)


@app.route("/projects/<int:project_id>/chats/<int:thread_id>/rename", methods=["POST"])
@login_required
def project_chat_rename(project_id, thread_id):
    project_for_user(project_id)
    if not current_user.can_edit: abort(403)
    title=str(request.form.get("title") or "").strip()[:180]
    if not title: abort(400)
    conn=db()
    conn.execute("UPDATE chat_threads SET title=? WHERE id=? AND project_id=?",(title,thread_id,project_id))
    conn.commit();conn.close()
    flash("Konverzaci jsem přejmenoval.","success")
    return redirect(url_for("project",project_id=project_id)+"#boban-chat")


@app.route("/projects/<int:project_id>/chats/<int:thread_id>/delete", methods=["POST"])
@login_required
def project_chat_delete(project_id, thread_id):
    project_for_user(project_id)
    if not current_user.can_edit: abort(403)
    chat_thread_list(project_id)
    conn=db()
    thread=conn.execute("SELECT * FROM chat_threads WHERE id=? AND project_id=?",(thread_id,project_id)).fetchone()
    if not thread: conn.close();abort(404)
    # Never delete the active thread or project strategy; only an archived conversation.
    if thread["end_message_id"] is None: conn.close();abort(409)
    conn.execute("DELETE FROM messages WHERE project_id=? AND id>=? AND id<=?",(project_id,thread["start_message_id"],thread["end_message_id"]))
    conn.execute("DELETE FROM chat_threads WHERE project_id=? AND id=?",(project_id,thread_id))
    conn.commit();conn.close()
    flash("Archivovanou konverzaci jsem smazal.","success")
    return redirect(url_for("project",project_id=project_id)+"#boban-chat")


@app.route("/projects/<int:project_id>/strategy", methods=["POST"])
@login_required
def project_strategy_save(project_id):
    project_for_user(project_id)
    goal=request.form.get("business_goal", "").strip()[:4000]
    conversion=request.form.get("primary_conversion", "").strip()[:190]
    topics=request.form.get("priority_topics", "").strip()[:4000]
    brands=request.form.get("brand_terms", "").strip()[:2000]
    previous = project_for_user(project_id)
    mode=request.form.get("boban_mode", previous["boban_mode"] or "specialist").strip()
    cadence=request.form.get("boban_cadence", previous["boban_cadence"] or "twice_weekly").strip()
    if mode not in {"assistant","specialist"}: mode="specialist"
    if cadence not in {"manual","weekly","twice_weekly"}: cadence="twice_weekly"
    conn=db(); conn.execute("""UPDATE projects SET business_goal=?,primary_conversion=?,priority_topics=?,brand_terms=?,boban_mode=?,boban_cadence=?,updated_at=? WHERE id=?""",
        (goal,conversion,topics,brands,mode,cadence,now(),project_id)); conn.commit(); conn.close()
    build_operator_plan(project_id, persist=True)
    flash("Obchodní zadání Bobana jsem uložil a přepočítal priority.", "success")
    return redirect(url_for("project", project_id=project_id) + "#boban-chat")


@app.route("/projects/<int:project_id>/operator/run", methods=["POST"])
@login_required
def operator_run(project_id):
    project_for_user(project_id)
    try:
        result=operator_cycle(project_id, force=True)
        prepared=int(result.get("prepared") or 0)
        if prepared:
            flash(f"Jdu na to. Z aktuálního plánu jsem si vzal {prepared} úkolů a připravuji je ke schválení.", "success")
        else:
            flash("Pracovní plán jsem znovu vyhodnotil. Nový bezpečně automatizovatelný úkol teď nemám; priority najdeš nahoře.", "info")
    except Exception as exc:
        flash(f"Pracovní cyklus se nepodařilo spustit: {exc}", "error")
    return redirect(url_for("project", project_id=project_id) + "#boban-chat")


@app.route("/projects/<int:project_id>/connectors")
@login_required
def connectors(project_id):
    p = project_for_user(project_id)
    conn = db()
    integrations = conn.execute(
        "SELECT * FROM integrations WHERE project_id=? ORDER BY provider", (project_id,)
    ).fetchall()
    conn.close()
    integration_map = {r["provider"]: r for r in integrations}
    gsc_config = integration_config(integration_map.get("search_console"))
    ga4_config = integration_config(integration_map.get("ga4"))
    gtm_config = integration_config(integration_map.get("gtm"))
    merchant_config = integration_config(integration_map.get("merchant_center"))
    heureka_config = heureka_settings(project_id)
    zbozi_api_config = integration_config(integration_map.get("zbozi_fenix"))
    meta_config = meta_settings(project_id)
    meta_config["api_token_cipher"] = None if not meta_config.get("api_token_cipher") else "configured"
    if 'merchant_csrf_token' not in session:
        session['merchant_csrf_token']=secrets.token_urlsafe(32)
    if gsc_config.get("selected_property"):
        gsc_config["domain_verified"] = search_console_domain_verified(p["site_url"], gsc_config.get("selected_property"))
    try:
        sitemaps = gsc_sitemaps(project_id) if integration_map.get("search_console") and gsc_config.get("selected_property") else []
    except Exception:
        sitemaps = []
    return render_template(
        "connectors.html",
        project=p, integrations=integrations, integration_map=integration_map,
        gsc_config=gsc_config, ga4_config=ga4_config, gtm_config=gtm_config, merchant_config=merchant_config, heureka_config=heureka_config, zbozi_api_config=zbozi_api_config, meta_config=meta_config, merchant_csrf=session['merchant_csrf_token'], gsc_sitemaps=sitemaps,
        performance=latest_source_snapshot(project_id, "pagespeed_crux"), gtm=latest_source_snapshot(project_id, "gtm"),
        connector_catalog=CONNECTOR_CATALOG, google_oauth_ready=google_oauth_ready(), pagespeed_ready=pagespeed_ready(), commerce_read=core_catalog_summary(project_id),
    )


@app.route("/projects/<int:project_id>/core/connect", methods=["POST"])
@login_required
def core_connect(project_id):
    project_for_user(project_id)
    manifest_url = request.form.get("core_manifest_url", "").strip()
    try:
        connect_core(project_id, manifest_url)
        flash("Fresh Core připojen. První CMS SEO audit je hotový.", "success")
    except Exception as exc:
        flash(f"Fresh Core se nepodařilo připojit: {exc}", "error")
    return redirect(url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/core/sync", methods=["POST"])
@login_required
def core_sync(project_id):
    project_for_user(project_id)
    try:
        sync_core(project_id)
        flash("Fresh Core data byla znovu načtena.", "success")
    except Exception as exc:
        flash(f"Synchronizace selhala: {exc}", "error")
    return redirect(url_for("project", project_id=project_id))


@app.route("/projects/<int:project_id>/core/write-connect", methods=["POST"])
@login_required
def core_write_connect(project_id):
    project_for_user(project_id)
    endpoint = request.form.get("core_write_endpoint", "").strip()
    key = request.form.get("core_write_key", "").strip()
    if len(key) < 24:
        flash("Write key je příliš krátký.", "error")
        return redirect(url_for("connectors", project_id=project_id))
    try:
        save_write_connector(project_id, endpoint, key)
        flash("Write bridge je ověřen. Změny stále vyžadují explicitní schválení.", "success")
    except Exception as exc:
        flash(f"Write bridge se nepodařilo ověřit: {exc}", "error")
    return redirect(url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/seo")
@login_required
def seo(project_id):
    p = project_for_user(project_id)
    expire_snoozes(project_id)
    reconcile_project_state(project_id)
    category = request.args.get("category", "").strip() or None
    kind = request.args.get("kind", "").strip() or None
    pillar = request.args.get("pillar", "").strip() or None
    if pillar not in {None, "technical", "content", "authority"}:
        pillar = None
    findings = grouped_findings(project_id, category, kind, pillar=pillar)
    audits = latest_audits(project_id)
    snapshot = project_snapshot(p)
    seo_items = seo_items_from_snapshot(snapshot)
    scorecard = seo_scorecard(project_id)
    return render_template(
        "seo.html", project=p, findings=findings, audits=audits,
        seo_items=seo_items[:100], severities=count_by_severity(project_id),
        kinds=count_by_kind(project_id), category_scores=scorecard.get("categories", {}), scorecard=scorecard,
        selected_category=category, selected_kind=kind, selected_pillar=pillar, ai_batch_limit=AI_BATCH_LIMIT,
        score_info=score_interpretation(scorecard.get("overall", 0)), suppressed_count=suppressed_issue_count(project_id),
        ai_actionable_codes=AI_ACTIONABLE_CODES, knowledge_map=ISSUE_KNOWLEDGE_MAP
    )


@app.route("/projects/<int:project_id>/seo/hidden")
@login_required
def seo_hidden(project_id):
    p = project_for_user(project_id)
    expire_snoozes(project_id)
    return render_template("hidden_issues.html", project=p, issues=hidden_issue_rows(project_id))


@app.route("/projects/<int:project_id>/seo/issues/state", methods=["POST"])
@login_required
def seo_issue_state(project_id):
    project_for_user(project_id)
    action = request.form.get("issue_action", "").strip()
    issue_ids = [int(x) for x in request.form.getlist("issue_ids") if str(x).isdigit()][:500]
    code = request.form.get("code", "").strip()
    source = request.form.get("source", "").strip()
    conn = db()
    if not issue_ids and code:
        if source:
            rows = conn.execute("SELECT id FROM issues WHERE project_id=? AND code=? AND source=? AND status='open'", (project_id, code, source)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM issues WHERE project_id=? AND code=? AND status='open'", (project_id, code)).fetchall()
        issue_ids = [int(r["id"]) for r in rows]
    if not issue_ids:
        conn.close()
        flash("Vyber alespoň jeden nález.", "info")
        return redirect(request.referrer or url_for("seo", project_id=project_id))
    marks = ",".join("?" for _ in issue_ids)
    if action == "snooze":
        until = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
        conn.execute(
            f"UPDATE issues SET status='snoozed',snoozed_until=?,decision_at=?,decision_by=? WHERE project_id=? AND id IN ({marks})",
            [until, now(), current_user.id, project_id, *issue_ids]
        )
        msg = f"Odložil jsem {len(issue_ids)} nálezů na 30 dní. Crawler je mezitím nebude vracet do hlavního přehledu."
    elif action == "dismiss":
        conn.execute(
            f"UPDATE issues SET status='dismissed',snoozed_until=NULL,decision_at=?,decision_by=? WHERE project_id=? AND id IN ({marks})",
            [now(), current_user.id, project_id, *issue_ids]
        )
        msg = f"Skryl jsem {len(issue_ids)} nálezů. Další crawl je bude evidovat, ale zůstanou mimo hlavní přehled, dokud je neobnovíš."
    elif action == "restore":
        conn.execute(
            f"UPDATE issues SET status='open',snoozed_until=NULL,decision_at=?,decision_by=? WHERE project_id=? AND id IN ({marks})",
            [now(), current_user.id, project_id, *issue_ids]
        )
        msg = f"Obnovil jsem {len(issue_ids)} nálezů do aktivního SEO přehledu."
    else:
        conn.close(); flash("Neznámá akce.", "error")
        return redirect(request.referrer or url_for("seo", project_id=project_id))
    recompute_project_score(project_id, conn)
    conn.commit(); conn.close()
    flash(msg, "success")
    return redirect(url_for("seo_hidden", project_id=project_id) if action == "restore" else url_for("seo", project_id=project_id))


@app.route("/projects/<int:project_id>/seo/crawl", methods=["POST"])
@login_required
def seo_crawl(project_id):
    p = project_for_user(project_id)
    snapshot = project_snapshot(p)
    seo_items = seo_items_from_snapshot(snapshot)
    if not seo_items:
        flash("Fresh Core zatím neposkytuje SEO index. Aktualizuj Fresh Core alespoň na 0.4.2 a znovu synchronizuj.", "error")
        return redirect(url_for("seo", project_id=project_id))
    try:
        results, issues = crawler_audit(p, seo_items)
        summary = {
            "type": "crawler",
            "crawl_limit": CRAWL_LIMIT,
            "pages_checked": len(results),
            "pages": results,
        }
        persist_audit(project_id, "crawler", summary, issues, replace_open=True)
        flash(f"Crawler zkontroloval {len(results)} URL a našel {len(issues)} bodů.", "success")
    except Exception as exc:
        flash(f"Crawler audit selhal: {exc}", "error")
    return redirect(url_for("seo", project_id=project_id))



@app.route("/projects/<int:project_id>/search-performance")
@login_required
def search_performance(project_id):
    p = project_for_user(project_id)
    gsc = latest_source_snapshot(project_id, "search_console")
    ga4 = latest_source_snapshot(project_id, "ga4")
    gsc_row = integration_row(project_id, "search_console")
    ga4_row = integration_row(project_id, "ga4")
    gsc_config = integration_config(gsc_row)
    ga4_config = integration_config(ga4_row)
    try:
        sitemaps = gsc_sitemaps(project_id) if gsc_row and gsc_config.get("selected_property") else []
    except Exception:
        sitemaps = []
    trust = data_trust_summary(p, gsc, ga4, gsc_config, ga4_config)
    return render_template(
        "search_performance.html",
        project=p, gsc=gsc, ga4=ga4, gsc_config=gsc_config, ga4_config=ga4_config,
        sitemaps=sitemaps, trust=trust, progress=project_progress_summary(project_id, gsc, ga4),
        gsc_period_label=period_label(gsc), ga4_period_label=period_label(ga4),
    )


@app.route("/projects/<int:project_id>/boban")
@login_required
def boban_scope(project_id):
    p = project_for_user(project_id)
    return render_template(
        "boban.html",
        project=p,
        kinds=count_by_kind(project_id),
        category_scores=category_scores(project_id),
        gsc=latest_source_snapshot(project_id, "search_console"),
        connector_catalog=CONNECTOR_CATALOG,
    )


@app.route("/projects/<int:project_id>/knowledge")
@login_required
def knowledge(project_id):
    p=project_for_user(project_id)
    q=(request.args.get('q') or '').strip()[:100]
    rows=library_rows(project_id,q=q)
    articles=[]
    for slug, article in SEO_KNOWLEDGE.items():
        if not q or q.lower() in (article['title']+' '+article['summary']).lower():
            articles.append({'slug':slug,**article})
    for a in rows:
        articles.append({'slug':'db-'+str(a['id']),'title':a['title'],'category':a['category'],
                         'summary':a['summary'],'scope':'projekt' if a['project_id'] else 'sdílená'})
    return render_template('knowledge.html',project=p,articles=articles,q=q)


@app.route("/projects/<int:project_id>/knowledge/<slug>")
@login_required
def knowledge_article(project_id,slug):
    p=project_for_user(project_id)
    if slug.startswith('db-') and slug[3:].isdigit():
        conn=db();row=conn.execute('SELECT * FROM marketing_knowledge WHERE id=? AND (project_id IS NULL OR project_id=?)',
                                   (int(slug[3:]),project_id)).fetchone();conn.close()
        if not row:abort(404)
        article={'title':row['title'],'category':row['category'],'summary':row['summary'],
                 'sections':[('Doporučení a zkušenosti',row['content'])],
                 'sources':[(row['source_url'],row['source_url'])] if row['source_url'] else []}
    else:
        article=SEO_KNOWLEDGE.get(slug)
    if not article:abort(404)
    return render_template('knowledge_article.html',project=p,article=article,slug=slug)


@app.route('/admin/knowledge/save',methods=['POST'])
@login_required
@admin_required
def admin_knowledge_save():
    raw_id=(request.form.get('id') or '').strip()
    entry_id=int(raw_id) if raw_id.isdigit() else None
    title=(request.form.get('title') or '').strip()[:220]
    category=(request.form.get('category') or 'SEO').strip()[:100]
    summary=(request.form.get('summary') or '').strip()[:1000]
    content=(request.form.get('content') or '').strip()[:12000]
    source=(request.form.get('source_url') or '').strip()[:1000]
    project_raw=(request.form.get('project_id') or '').strip()
    scope=int(project_raw) if project_raw.isdigit() else None
    if len(title)<4 or len(content)<12 or not summary:abort(400)
    if source:source=safe_http_url(source)
    if scope:
        conn=db(); exists=conn.execute('SELECT id FROM projects WHERE id=?',(scope,)).fetchone();conn.close()
        if not exists:abort(400)
    conn=db()
    if entry_id:
        existing=conn.execute('SELECT id FROM marketing_knowledge WHERE id=?',(entry_id,)).fetchone()
        if not existing:abort(404)
        conn.execute('UPDATE marketing_knowledge SET project_id=?,category=?,title=?,summary=?,content=?,source_url=?,updated_at=? WHERE id=?',
                     (scope,category,title,summary,content,source,now(),entry_id))
    else:
        conn.execute('INSERT INTO marketing_knowledge(project_id,category,title,summary,content,source_url,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                     (scope,category,title,summary,content,source,current_user.id,now(),now()))
    conn.commit();conn.close()
    flash('Záznam SEO knihovny uložen. Boban jej nyní může vyhledat.','success')
    return redirect(url_for('admin_console')+'#knowledge-library')


@app.route('/admin/knowledge/<int:entry_id>/delete',methods=['POST'])
@login_required
@admin_required
def admin_knowledge_delete(entry_id):
    conn=db();conn.execute('DELETE FROM marketing_knowledge WHERE id=?',(entry_id,));conn.commit();conn.close()
    flash('Záznam knihovny odstraněn.','success')
    return redirect(url_for('admin_console')+'#knowledge-library')



@contextlib.contextmanager
def commerce_sync_guard(project_id):
    # OS-level, cross-process lock. Only one import per project can run at once.
    lockdir=BASE_DIR / 'sync_locks'
    lockdir.mkdir(parents=True,exist_ok=True)
    with (lockdir / ('project_'+str(int(project_id))+'.lock')).open('a+b') as handle:
        try: fcntl.flock(handle.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Synchronizace už v tomto projektu probíhá.')
        try: yield
        finally: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def core_variations_read(project, key, page=1, per_page=25):
    base=safe_http_url((project['site_url'] or '').rstrip('/')+'/wp-json/fresh-core/v1/commerce/variations')
    result=requests.get(base,params={'page':page,'per_page':per_page},
        headers={'X-Fresh-Core-Key':key,'Accept':'application/json','User-Agent':USER_AGENT},
        timeout=(5,HTTP_TIMEOUT),allow_redirects=False)
    if result.status_code!=200:
        raise ValueError('Variace Fresh Core: HTTP '+str(result.status_code)+'. Aktualizuj Fresh Core na 0.7.7.')
    obj=result.json()
    if not isinstance(obj,dict) or not isinstance(obj.get('items'),list) or obj.get('available') is not True:
        raise ValueError('Variace Fresh Core: neplatná odpověď.')
    if int(obj.get('page',page))!=page or len(obj['items'])>per_page:
        raise ValueError('Variace Fresh Core: chybná velikost stránky.')
    return obj


def normalize_core_variant(item):
    from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl
    if not isinstance(item,dict) or int(item.get('variation_id') or 0)<=0 or int(item.get('parent_id') or 0)<=0:
        raise ValueError('Variace bez platného ID.')
    # WooCommerce selects a variation via attribute_* query values (original slugs).
    url=str(item.get('url') or '')
    attrs=item.get('variant_attributes_raw') or {}
    if attrs and url.startswith(('http://','https://')):
        parsed=urlsplit(url); query=dict(parse_qsl(parsed.query,keep_blank_values=True))
        query.update({str(k):str(v) for k,v in attrs.items() if str(k).startswith('attribute_')})
        query['variation_id']=str(item['variation_id'])
        url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(query),parsed.fragment))
    identifiers=item.get('identifiers') or {}
    vals=item.get('variant_attributes') or {}
    title=str(item.get('title') or '')
    if vals: title+=' – '+', '.join(str(x) for x in vals.values())[:120]
    return {'variation_id':int(item['variation_id']),'parent_id':int(item['parent_id']),
            'title':title,'url':url,'sku':str(item.get('sku') or ''),
            'description':str(item.get('description') or ''),'price':str(item.get('price') or ''),
            'currency':str(item.get('currency') or ''),'stock_status':str(item.get('stock_status') or ''),
            'purchasable':item.get('purchasable'),'image':str(item.get('image') or ''),
            'gtin':identifiers.get('gtin'),'brand':identifiers.get('brand'),
            'variant_attributes':vals, 'regular_price':item.get('regular_price'),
            'sale_price':item.get('sale_price'),'raw':item}


def core_variants_batch(project_id, project, key, reset=False):
    conn=db();state=conn.execute('SELECT next_page FROM project_core_variant_sync WHERE project_id=?',(project_id,)).fetchone();conn.close()
    first=1 if reset or not state else int(state['next_page'])
    if first<1:return {'complete':True,'processed':0}
    processed=0; next_page=first; started=time.monotonic();total=0
    for page in range(first,first+COMMERCE_BATCH_PAGES):
        if page>first and time.monotonic()-started>=COMMERCE_BATCH_SECONDS:break
        response=core_variations_read(project,key,page=page,per_page=COMMERCE_PAGE_SIZE)
        total=int(response.get('total') or 0)
        items=[normalize_core_variant(item) for item in response['items']]
        conn=db()
        try:
            if reset and page==1:conn.execute('DELETE FROM project_core_variants WHERE project_id=?',(project_id,))
            for item in items:
                params=(project_id,item['variation_id'],json.dumps(item,ensure_ascii=False),now())
                if DB_BACKEND=='mysql':
                    conn.execute('INSERT INTO project_core_variants(project_id,variation_id,payload_json,synced_at) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json),synced_at=VALUES(synced_at)',params)
                else:
                    conn.execute('INSERT OR REPLACE INTO project_core_variants(project_id,variation_id,payload_json,synced_at) VALUES(?,?,?,?)',params)
            next_page=page+1 if response.get('has_more') else 0
            count=conn.execute('SELECT COUNT(*) AS n FROM project_core_variants WHERE project_id=?',(project_id,)).fetchone()['n']
            args=(project_id,next_page,total,count,None,now() if next_page==0 else None)
            if DB_BACKEND=='mysql':
                conn.execute('INSERT INTO project_core_variant_sync(project_id,next_page,total,synced_count,last_error,finished_at) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE next_page=VALUES(next_page),total=VALUES(total),synced_count=VALUES(synced_count),last_error=VALUES(last_error),finished_at=VALUES(finished_at)',args)
            else:
                conn.execute('INSERT OR REPLACE INTO project_core_variant_sync(project_id,next_page,total,synced_count,last_error,finished_at) VALUES(?,?,?,?,?,?)',args)
            processed+=len(items);conn.commit()
        finally:conn.close()
        if next_page==0:break
    return {'complete':next_page==0,'processed':processed,'total':total,'next_page':next_page}



def catalog_cached_data(project_id):
    conn=db()
    parents=[json.loads(r['payload_json']) for r in conn.execute('SELECT payload_json FROM project_core_products WHERE project_id=?',(project_id,)).fetchall()]
    variants=[json.loads(r['payload_json']) for r in conn.execute('SELECT payload_json FROM project_core_variants WHERE project_id=?',(project_id,)).fetchall()]
    rules=feed_workflow.exclusions(conn,project_id)
    workflow=feed_workflow.state(conn,project_id)
    conn.close()
    return parents,variants,rules,workflow


def _catalog_category_cache_path(project_id):
    # Private lightweight taxonomy snapshot; not a second product catalogue.
    return BASE_DIR / 'catalog_metadata' / ('categories_'+str(int(project_id))+'.json')


def cached_catalog_categories(project_id):
    path=_catalog_category_cache_path(project_id)
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(payload,list) and payload and all(isinstance(c,dict) and int(c.get('id') or 0)>0 for c in payload):
            return payload
    except (FileNotFoundError,ValueError,TypeError,OSError):pass
    return None


def refresh_catalog_categories(project_id, site_url):
    """Fetch only Woo taxonomy (not products/variants). Fail closed on unavailable hierarchy.

    Store API is public, readonly and uses a tiny list of categories; there are no
    OAuth credentials or Woo database reads here. Do not follow redirects offsite.
    """
    root=safe_http_url(str(site_url or '').rstrip('/'))
    endpoint=root.rstrip('/')+'/wp-json/wc/store/v1/products/categories'
    rows=[];seen=set()
    for page in range(1,12):
        try:
            res=requests.get(endpoint, params={'page':page,'per_page':100,'hide_empty':'false'},
                             headers={'Accept':'application/json','User-Agent':USER_AGENT},
                             timeout=(4,12),allow_redirects=False)
            if res.status_code!=200:raise ValueError('HTTP '+str(res.status_code))
            data=res.json()
        except (requests.RequestException,ValueError,TypeError) as exc:
            raise ValueError('Nelze ověřit úplný strom kategorií WooCommerce (Store API): '+str(exc)[:100]+'. XML zůstává nezměněné.') from exc
        if not isinstance(data,list):
            raise ValueError('Store API nevrátilo seznam kategorií. XML zůstává nezměněné.')
        for value in data:
            if not isinstance(value,dict):continue
            try:ident=int(value.get('id') or 0);parent=int(value.get('parent') or 0)
            except (ValueError,TypeError):continue
            if ident<=0 or ident in seen:continue
            seen.add(ident)
            rows.append({'id':ident,'parent':parent,'name':str(value.get('name') or ('Kategorie '+str(ident)))[:120],
                         'count':max(0,int(value.get('count') or 0))})
        if len(data)<100:break
    else:raise ValueError('Strom kategorií překročil bezpečnostní limit 1100 kategorií.')
    if not rows:raise ValueError('Store API vrátilo prázdný strom kategorií; XML nebylo přepsáno.')
    # Keep taxonomy snapshot locally; publishing is based on current source, never stale cache.
    target=_catalog_category_cache_path(project_id)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        temp.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    return rows


def catalog_ready(project_id):
    info=ecommerce_data(project_id)
    return bool(info['catalog'].get('next_page')==0 and info['catalog'].get('finished_at') and info['variants_state'] and info['variants_state'].get('next_page')==0 and info['variants_state'].get('finished_at'))


def catalog_publish_google(project_id):
    """Only approved, fully-synced snapshots are published. Atomic rename preserves old feed."""
    if not catalog_ready(project_id):raise ValueError('Katalog ještě není kompletní.')
    project_row=None
    conn=db()
    try:
        project_row=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        state=feed_workflow.state(conn,project_id)
        if not state.get('approved'):raise ValueError('Výběr produktů není schválen.')
    finally:conn.close()
    if not project_row:raise ValueError('Projekt neexistuje.')
    parents,variants,excluded,state=catalog_cached_data(project_id)
    if len(parents)+len(variants)>CATALOG_MAX_EXPORT_ROWS:
        raise ValueError('Limit velikosti exportu; je nutný streamovaný export.')
    # Always verify the full hierarchy when category exclusions exist. This reads
    # only category terms, NOT thousands of products from WooCommerce.
    category_tree=(refresh_catalog_categories(project_id,project_row['site_url'])
                   if excluded['category'] else (cached_catalog_categories(project_id) or feed_workflow.category_tree(parents)))
    chosen_p,chosen_v,summary=feed_workflow.selected(parents,variants,excluded,categories=category_tree)
    xml,report=merchant_export.build_google_feed(project_row['name'],chosen_p,chosen_v,project_row['site_url'])
    report['selection']=summary
    report['category_tree_source']='woocommerce-store-api' if excluded['category'] else 'cached'
    report['category_count']=len(category_tree)
    # Detect unexpected category leakage independently from the selected() result.
    excluded_ids=feed_workflow.excluded_category_ids(category_tree,excluded['category'])
    leaked=[p.get('id') for p in chosen_p if feed_workflow.product_category_ids(p)&excluded_ids]
    if leaked:raise ValueError('Export zablokován: vyloučená kategorie prošla filtrem.')
    if not report['exported']:raise ValueError('Žádné validní produkty k publikaci.')
    conn=db()
    try:
        rec=conn.execute('SELECT feed_token FROM project_google_feeds WHERE project_id=?',(project_id,)).fetchone()
        token=rec['feed_token'] if rec else secrets.token_urlsafe(32)
        CATALOG_FEED_DIR.mkdir(parents=True,exist_ok=True)
        dest=CATALOG_FEED_DIR / ('google_'+str(project_id)+'_'+token+'.xml')
        temp=dest.with_name(dest.name+'.'+secrets.token_hex(8)+'.tmp')
        try:
            temp.write_bytes(xml)
            temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)
        record=(project_id,token,now(),report['exported'],report['omitted'],json.dumps(report,ensure_ascii=False))
        if DB_BACKEND=='mysql':
            conn.execute('INSERT INTO project_google_feeds(project_id,feed_token,generated_at,exported_count,omitted_count,report_json) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE feed_token=VALUES(feed_token),generated_at=VALUES(generated_at),exported_count=VALUES(exported_count),omitted_count=VALUES(omitted_count),report_json=VALUES(report_json)',record)
        else:
            conn.execute('INSERT OR REPLACE INTO project_google_feeds(project_id,feed_token,generated_at,exported_count,omitted_count,report_json) VALUES(?,?,?,?,?,?)',record)
        feed_workflow.update(conn,DB_BACKEND,project_id,now(),published_revision=state['revision'],last_error=None)
        conn.commit()
    finally:conn.close()
    return report


def heureka_settings(project_id):
    conn=db()
    try:
        rec=conn.execute('SELECT * FROM project_heureka_feeds WHERE project_id=?',(project_id,)).fetchone()
        return dict(rec) if rec else {}
    finally:conn.close()


def catalog_publish_heureka(project_id):
    """Publish both Heureka feeds from the currently approved local snapshot."""
    if not catalog_ready(project_id):raise ValueError('Nejdříve dokonči načítání katalogu.')
    conn=db()
    try:
        project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        state=feed_workflow.state(conn,project_id)
        if not project:raise ValueError('Projekt neexistuje.')
        if not state.get('approved'):raise ValueError('Nejdříve schval společný sortiment.')
        record=conn.execute('SELECT * FROM project_heureka_feeds WHERE project_id=?',(project_id,)).fetchone()
        confirmed=bool(record and record['fast_dispatch_confirmed'])
        delivery_days=record['default_delivery_days'] if record else None
        token=record['feed_token'] if record else secrets.token_urlsafe(32)
        registered=int(record['shop_registered']) if record else 0
    finally:conn.close()
    parents,variants,excluded,_=catalog_cached_data(project_id)
    if len(parents)+len(variants)>CATALOG_MAX_EXPORT_ROWS:
        raise ValueError('Katalog překročil exportní limit.')
    categories=(refresh_catalog_categories(project_id,project['site_url'])
                if excluded['category'] else (cached_catalog_categories(project_id) or feed_workflow.category_tree(parents)))
    chosen_p,chosen_v,selection=feed_workflow.selected(parents,variants,excluded,categories=categories)
    ids=feed_workflow.excluded_category_ids(categories,excluded['category'])
    if any(feed_workflow.product_category_ids(x)&ids for x in chosen_p):
        raise ValueError('Export zablokován: prošla vyloučená kategorie.')
    xml,stock_xml,report=heureka_export.build_heureka_feeds(chosen_p,chosen_v,confirmed_fast_dispatch=confirmed,taxonomy=categories,default_delivery_days=delivery_days)
    report['selection']=selection
    report['stock_policy_confirmed']=confirmed
    if not report['exported']:raise ValueError('Heureka XML nemá žádné platné prodejní položky.')
    CATALOG_FEED_DIR.mkdir(parents=True,exist_ok=True)
    paths=[CATALOG_FEED_DIR / ('heureka_'+str(project_id)+'_'+token+'.xml'),
           CATALOG_FEED_DIR / ('heureka_stock_'+str(project_id)+'_'+token+'.xml')]
    payloads=[xml,stock_xml]
    # Prepare and fsync both complete files before moving either into public view.
    temps=[]
    try:
        for dest,data in zip(paths,payloads):
            temp=dest.with_name(dest.name+'.'+secrets.token_hex(6)+'.tmp')
            with temp.open('wb') as handle:
                handle.write(data);handle.flush();os.fsync(handle.fileno())
            temps.append(temp)
        for temp,dest in zip(temps,paths):temp.replace(dest)
    finally:
        for temp in temps:temp.unlink(missing_ok=True)
    conn=db()
    try:
        data=(project_id,token,now(),report['exported'],report['availability_count'],json.dumps(report,ensure_ascii=False),int(confirmed),registered)
        if DB_BACKEND=='mysql':
            conn.execute("""INSERT INTO project_heureka_feeds(project_id,feed_token,generated_at,exported_count,availability_count,report_json,fast_dispatch_confirmed,shop_registered)
                VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE generated_at=VALUES(generated_at),exported_count=VALUES(exported_count),
                availability_count=VALUES(availability_count),report_json=VALUES(report_json),fast_dispatch_confirmed=VALUES(fast_dispatch_confirmed),shop_registered=VALUES(shop_registered),last_error=NULL""",data)
        else:
            conn.execute("""INSERT INTO project_heureka_feeds(project_id,feed_token,generated_at,exported_count,availability_count,report_json,fast_dispatch_confirmed,shop_registered)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET generated_at=excluded.generated_at,exported_count=excluded.exported_count,
                availability_count=excluded.availability_count,report_json=excluded.report_json,
                fast_dispatch_confirmed=excluded.fast_dispatch_confirmed,shop_registered=excluded.shop_registered,last_error=NULL""",data)
        conn.commit()
    finally:conn.close()
    return report


def meta_settings(project_id):
    conn=db()
    try:
        rec=conn.execute('SELECT * FROM project_meta_feeds WHERE project_id=?',(project_id,)).fetchone()
        return dict(rec) if rec else {}
    finally:conn.close()


def catalog_publish_meta(project_id):
    if not catalog_ready(project_id):raise ValueError('Nejdříve dokonči načtení katalogu.')
    conn=db()
    try:
        project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        state=feed_workflow.state(conn,project_id)
        if not project:raise ValueError('Projekt neexistuje.')
        if not state.get('approved'):raise ValueError('Nejdříve schval společný sortiment.')
        rec=conn.execute('SELECT feed_token FROM project_meta_feeds WHERE project_id=?',(project_id,)).fetchone()
        token=rec['feed_token'] if rec else secrets.token_urlsafe(32)
    finally:conn.close()
    parents,variants,excluded,_=catalog_cached_data(project_id)
    if len(parents)+len(variants)>CATALOG_MAX_EXPORT_ROWS:raise ValueError('Katalog překročil exportní limit.')
    categories=(refresh_catalog_categories(project_id,project['site_url']) if excluded['category'] else (cached_catalog_categories(project_id) or feed_workflow.category_tree(parents)))
    chosen_p,chosen_v,selection=feed_workflow.selected(parents,variants,excluded,categories=categories)
    forbidden=feed_workflow.excluded_category_ids(categories,excluded['category'])
    if any(feed_workflow.product_category_ids(x)&forbidden for x in chosen_p):raise ValueError('Export obsahuje vyloučenou kategorii.')
    xml,report=meta_export.build_meta_feed(project['name'],chosen_p,chosen_v,project['site_url'])
    report['selection']=selection
    if not report['exported']:raise ValueError('Meta XML nemá žádné platné nabídky.')
    CATALOG_FEED_DIR.mkdir(parents=True,exist_ok=True)
    dest=CATALOG_FEED_DIR/('meta_'+str(project_id)+'_'+token+'.xml')
    temp=dest.with_name(dest.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with temp.open('wb') as out:out.write(xml);out.flush();os.fsync(out.fileno())
        temp.replace(dest)
    finally:temp.unlink(missing_ok=True)
    conn=db()
    try:
        data=(project_id,token,now(),report['exported'],json.dumps(report,ensure_ascii=False))
        if DB_BACKEND=='mysql':
            conn.execute("""INSERT INTO project_meta_feeds(project_id,feed_token,generated_at,exported_count,report_json)
              VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE generated_at=VALUES(generated_at),exported_count=VALUES(exported_count),report_json=VALUES(report_json),last_error=NULL""",data)
        else:
            conn.execute("""INSERT INTO project_meta_feeds(project_id,feed_token,generated_at,exported_count,report_json)
              VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET generated_at=excluded.generated_at,exported_count=excluded.exported_count,report_json=excluded.report_json,last_error=NULL""",data)
        conn.commit()
    finally:conn.close()
    return report


@app.route('/catalog/meta/<token>.xml',methods=['GET'])
def catalog_meta_public(token):
    if len(token)<32 or len(token)>100:abort(404)
    conn=db()
    try:rec=conn.execute('SELECT project_id FROM project_meta_feeds WHERE feed_token=?',(token,)).fetchone()
    finally:conn.close()
    if not rec:abort(404)
    path=CATALOG_FEED_DIR/('meta_'+str(rec['project_id'])+'_'+token+'.xml')
    if not path.is_file():abort(404)
    from flask import send_file
    response=send_file(path,mimetype='application/xml',conditional=True,max_age=300)
    response.headers['Cache-Control']='public, max-age=300'
    return response


@app.route('/projects/<int:project_id>/ecommerce/meta/build',methods=['POST'])
@login_required
def ecommerce_meta_build(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    try:
        with commerce_sync_guard(project_id):report=catalog_publish_meta(project_id)
        flash('Meta katalog připraven: '+str(report['exported'])+' nabídek. Připoj URL v Meta Commerce Manageru.','success')
    except Exception as exc:flash('Meta export: '+str(exc)[:220],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#meta-platform')


def _meta_token(project_id):
    row=meta_settings(project_id)
    return decrypt_secret(row.get('api_token_cipher'))

def _meta_store(project_id, **updates):
    allowed={'api_token_cipher','catalog_id','api_feed_id','api_status','api_last_result','api_checked_at','catalog_confirmed'}
    if not updates or any(key not in allowed for key in updates):raise ValueError('Neplatná Meta aktualizace.')
    conn=db()
    try:
        existing=conn.execute('SELECT feed_token FROM project_meta_feeds WHERE project_id=?',(project_id,)).fetchone()
        if not existing:
            conn.execute('INSERT INTO project_meta_feeds(project_id,feed_token) VALUES(?,?)',(project_id,secrets.token_urlsafe(32)))
        fields=list(updates)
        conn.execute('UPDATE project_meta_feeds SET '+','.join(k+'=?' for k in fields)+' WHERE project_id=?',tuple(updates[k] for k in fields)+(project_id,))
        conn.commit()
    finally:conn.close()

@app.route('/projects/<int:project_id>/connectors/meta/start')
@login_required
def meta_oauth_start(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    if not meta_graph.configured():
        flash('Meta OAuth není nakonfigurován. Doplň META_APP_ID a META_APP_SECRET do .env.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#meta-connector')
    state=secrets.token_urlsafe(32)
    session['meta_oauth_state']={'state':state,'project_id':project_id,'user_id':str(current_user.id),'at':time.time()}
    return redirect(meta_graph.oauth_url(state,url_for('meta_oauth_callback',_external=True)))

@app.route('/connectors/meta/callback')
@login_required
def meta_oauth_callback():
    data=session.pop('meta_oauth_state',None) or {}
    state=str(request.args.get('state') or '')
    project_id=data.get('project_id')
    if not project_id or not state or not hmac.compare_digest(state,str(data.get('state') or '')) or str(data.get('user_id'))!=str(current_user.id) or time.time()-float(data.get('at') or 0)>600:
        abort(403)
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    if request.args.get('error'):
        flash('Meta autorizace zamítnuta: '+str(request.args.get('error_reason') or 'přístup nepovolen')[:90],'error')
    else:
        try:
            code=str(request.args.get('code') or '')
            if not code:raise ValueError('Chybí autorizační kód Meta.')
            token=meta_graph.exchange_code(code,url_for('meta_oauth_callback',_external=True))
            meta_graph.call('GET','me',token,params={'fields':'id,name'})
            _meta_store(project_id,api_token_cipher=encrypt_secret(token),api_status='connected',api_checked_at=now(),api_last_result=json.dumps({'message':'Autorizace dokončena; zvol katalog.'},ensure_ascii=False))
            flash('Meta účet propojen. Ověř katalog a jeho datový zdroj v Konektorech.','success')
        except (ValueError,meta_graph.MetaAPIError) as exc:
            flash('Meta připojení: '+str(exc)[:180],'error')
    return redirect(url_for('connectors',project_id=project_id)+'#meta-connector')

@app.route('/projects/<int:project_id>/connectors/meta',methods=['POST'])
@login_required
def meta_connector_save(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    catalog_id=str(request.form.get('meta_catalog_id') or '').strip()
    if not catalog_id.isdigit() or len(catalog_id)>30:
        flash('Zadej číselné ID Meta katalogu.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#meta-connector')
    token=_meta_token(project_id)
    if not token:
        flash('Nejdřív autorizuj Meta účet.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#meta-connector')
    try:
        catalog=meta_graph.catalog(token,catalog_id)
        feeds=meta_graph.feeds(token,catalog_id)
        meta_row=meta_settings(project_id)
        expected='/catalog/meta/'+str(meta_row.get('feed_token') or '')+'.xml'
        match=meta_graph.match_feed(feeds,expected)
        _meta_store(project_id,catalog_id=catalog_id,api_feed_id=match.get('id') if match else None,api_status='connected',
                    api_checked_at=now(),api_last_result=json.dumps({'catalog':catalog.get('name'),'feed_count':len(feeds),'matched_feed':bool(match)},ensure_ascii=False))
        flash('Katalog '+str(catalog.get('name') or catalog_id)+' ověřen. '+('Existující Bobanův zdroj nalezen.' if match else 'Bobanův zdroj zatím nebyl rozpoznán; vyber ho v E-commerce.'),'success')
    except (ValueError,meta_graph.MetaAPIError) as exc:flash('Meta: '+str(exc)[:180],'error')
    return redirect(url_for('connectors',project_id=project_id)+'#meta-connector')

@app.route('/projects/<int:project_id>/ecommerce/meta/api',methods=['POST'])
@login_required
def ecommerce_meta_api(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    action=str(request.form.get('meta_action') or '')
    row=meta_settings(project_id);token=_meta_token(project_id)
    try:
        if not token or not row.get('catalog_id'):raise ValueError('V Konektorech připoj Meta a ověř ID katalogu.')
        catalog_id=str(row['catalog_id'])
        if action=='status':
            catalog=meta_graph.catalog(token,catalog_id)
            feeds=meta_graph.feeds(token,catalog_id)
            selected=next((f for f in feeds if str(f.get('id'))==str(row.get('api_feed_id'))),None)
            uploads=meta_graph.uploads(token,selected['id']) if selected else []
            recent=uploads[:3]
            # Meta's catalog-level product_count is not a report of upload results.
            # Fetch diagnostic samples only for the newest upload, without exposing tokens.
            issues=[]
            if recent and recent[0].get('id'):
                try:issues=meta_graph.upload_errors(token,recent[0]['id'])
                except meta_graph.MetaAPIError:pass  # Some accounts restrict errors edge.
            result={'catalog':catalog.get('name'),'product_count':catalog.get('product_count'),
                    'feeds':[{'id':f.get('id'),'name':f.get('name')} for f in feeds],
                    'selected_feed':selected.get('id') if selected else None,
                    'uploads':recent,'latest_upload_errors':issues,
                    'explanation':'product_count je stav katalogu; num_detected_items a num_persisted_items popisují poslední zpracování zdroje.'}
            _meta_store(project_id,api_checked_at=now(),api_last_result=json.dumps(result,ensure_ascii=False,default=str))
            flash('Meta: stav katalogu načten.','success')
        elif action=='bind':
            fid=str(request.form.get('meta_feed_id') or '')
            if not fid.isdigit():raise ValueError('Vyber existující Meta datový zdroj.')
            feeds=meta_graph.feeds(token,catalog_id)
            if fid not in [str(f.get('id')) for f in feeds]:raise ValueError('Datový zdroj nepatří k vybranému katalogu.')
            _meta_store(project_id,api_feed_id=fid,api_status='connected',api_checked_at=now())
            flash('Existující Meta zdroj byl bezpečně vybrán.','success')
        elif action=='upload':
            fid=str(row.get('api_feed_id') or '')
            if not fid.isdigit():raise ValueError('Nejdříve vyber existující Meta datový zdroj. Žádný nový automaticky nevytváříme.')
            if not row.get('generated_at'):raise ValueError('Nejdřív publikuj opravené Meta XML.')
            feeds=meta_graph.feeds(token,catalog_id)
            if fid not in [str(f.get('id')) for f in feeds]:raise ValueError('Zdroj již není dostupný v tomto katalogu.')
            url=url_for('catalog_meta_public',token=row['feed_token'],_external=True)
            if not url.startswith('https://'):raise ValueError('Veřejný Meta feed musí používat HTTPS.')
            result=meta_graph.trigger_upload(token,fid,url)
            _meta_store(project_id,api_checked_at=now(),api_last_result=json.dumps({'upload_requested':now(),'result':result},ensure_ascii=False))
            flash('Meta přijala požadavek na zpracování XML. Stav importu ověř pomocí Načíst stav.','success')
        else:raise ValueError('Neznámá operace Meta.')
    except (ValueError,meta_graph.MetaAPIError) as exc:
        flash('Meta API: '+str(exc)[:200],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#meta-platform')


def zbozi_settings(project_id):
    conn=db()
    try:
        rec=conn.execute('SELECT * FROM project_zbozi_feeds WHERE project_id=?',(project_id,)).fetchone()
        return dict(rec) if rec else {}
    finally:conn.close()


def catalog_publish_zbozi(project_id):
    if not catalog_ready(project_id):raise ValueError('Nejdříve dokonči načítání katalogu.')
    conn=db()
    try:
        project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        state=feed_workflow.state(conn,project_id)
        if not project:raise ValueError('Projekt neexistuje.')
        if not state.get('approved'):raise ValueError('Nejdříve schval společný sortiment.')
        record=conn.execute('SELECT * FROM project_zbozi_feeds WHERE project_id=?',(project_id,)).fetchone()
        token=record['feed_token'] if record else secrets.token_urlsafe(32)
        default_days=record['default_delivery_days'] if record else None
    finally:conn.close()
    parents,variants,excluded,_=catalog_cached_data(project_id)
    if len(parents)+len(variants)>CATALOG_MAX_EXPORT_ROWS:raise ValueError('Katalog překročil exportní limit.')
    categories=(refresh_catalog_categories(project_id,project['site_url']) if excluded['category'] else (cached_catalog_categories(project_id) or feed_workflow.category_tree(parents)))
    chosen_p,chosen_v,selection=feed_workflow.selected(parents,variants,excluded,categories=categories)
    forbidden=feed_workflow.excluded_category_ids(categories,excluded['category'])
    if any(feed_workflow.product_category_ids(x)&forbidden for x in chosen_p):raise ValueError('Export obsahuje vyloučenou kategorii.')
    # Official Seznam taxonomy, cached separately; never refetch Woo product catalogue.
    category_resolver, taxonomy_state = zbozi_categories.resolver_from_official_cache(
        CATALOG_FEED_DIR / 'zbozi_official_categories.json')
    try:
        shipping_rules=json.loads(record['shipping_rules_json'] or '[]') if record and record['shipping_rules_json'] else []
        if not isinstance(shipping_rules,list):shipping_rules=[]
    except (ValueError,TypeError):shipping_rules=[]
    xml,report=zbozi_export.build_zbozi_feed(
        chosen_p,chosen_v,taxonomy=categories,default_delivery_days=default_days,
        category_resolver=category_resolver,shipping_rules=shipping_rules)
    report['official_taxonomy_state']=taxonomy_state
    report['selection']=selection
    if not report['exported']:raise ValueError('Zboží.cz XML nemá žádné platné položky.')
    CATALOG_FEED_DIR.mkdir(parents=True,exist_ok=True)
    dest=CATALOG_FEED_DIR/('zbozi_'+str(project_id)+'_'+token+'.xml')
    tmp=dest.with_name(dest.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with tmp.open('wb') as out:out.write(xml);out.flush();os.fsync(out.fileno())
        tmp.replace(dest)
    finally:tmp.unlink(missing_ok=True)
    conn=db()
    try:
        data=(project_id,token,now(),report['exported'],json.dumps(report,ensure_ascii=False))
        if DB_BACKEND=='mysql':
            conn.execute('''INSERT INTO project_zbozi_feeds(project_id,feed_token,generated_at,exported_count,report_json)
                VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE generated_at=VALUES(generated_at),exported_count=VALUES(exported_count),report_json=VALUES(report_json),last_error=NULL''',data)
        else:
            conn.execute('''INSERT INTO project_zbozi_feeds(project_id,feed_token,generated_at,exported_count,report_json)
                VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET generated_at=excluded.generated_at,exported_count=excluded.exported_count,report_json=excluded.report_json,last_error=NULL''',data)
        conn.commit()
    finally:conn.close()
    return report


@app.route('/catalog/zbozi/<token>.xml',methods=['GET'])
def catalog_zbozi_public(token):
    if len(token)<32 or len(token)>100:abort(404)
    conn=db()
    try:rec=conn.execute('SELECT project_id FROM project_zbozi_feeds WHERE feed_token=?',(token,)).fetchone()
    finally:conn.close()
    if not rec:abort(404)
    path=CATALOG_FEED_DIR/('zbozi_'+str(rec['project_id'])+'_'+token+'.xml')
    if not path.is_file():abort(404)
    from flask import send_file
    return send_file(path,mimetype='application/xml',conditional=True,max_age=300)


@app.route('/projects/<int:project_id>/ecommerce/zbozi/shipping',methods=['POST'])
@login_required
def ecommerce_zbozi_shipping(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    valid_carriers = {
        'ALZABOX','CESKA_POSTA_BALIKOVNA','CESKA_POSTA_NA_POSTU',
        'DPD_PICKUP','GLS_PARCELSHOP','PPL_PARCELSHOP','TOPTRANS_DEPO',
        'ONE_POINT','ZASILKOVNA','VLASTNI_VYDEJNI_MISTA',
        'CESKA_POSTA','BALIKOVNA_NA_ADRESU','123_KURYR','DACHSER','DB_SCHENKER',
        'DPD','DHL','DSV','EMONS','FOFR','GEBRUDER_WEISS','GEIS','GLS',
        'HDS','SHIPIFY','IN_TIME_KURYR','ONE_COURIER','NAS_KURYR',
        'MESSENGER','LAGERMAX','PPL','TNT','TOPTRANS','UPS','FEDEX',
        'RABEN_LOGISTICS','RHENUS','ZASILKOVNA_NA_ADRESU','VLASTNI_PREPRAVA',
    }
    carrier=str(request.form.get('zbozi_delivery_id') or '').strip()
    if not carrier:
        rules=[]
    else:
        if carrier not in valid_carriers or request.form.get('zbozi_shipping_confirm')!='yes':
            flash('Vyber podporovaného dopravce a potvrď, že služba platí pro celý katalog.','error')
            return redirect(url_for('ecommerce',project_id=project_id)+'#zbozi-platform')
        from decimal import Decimal, InvalidOperation
        def validate_shipping_price(value,required):
            if (value is None or not str(value).strip()) and not required:return None
            try:
                val=Decimal(str(value).strip().replace(',','.'))
                if not val.is_finite() or val<0 or val>100000 or val.as_tuple().exponent<-2:
                    raise ValueError('Cena dopravy musí být nezáporná částka s nejvýše dvěma desetinnými místy.')
                return format(val,'.2f')
            except (InvalidOperation,ValueError):
                raise ValueError('Neplatná cena dopravy nebo dobírky.')
        try:
            price=validate_shipping_price(request.form.get('zbozi_delivery_price'),True)
            cod=validate_shipping_price(request.form.get('zbozi_delivery_cod'),False)
        except ValueError as exc:
            flash(str(exc),'error')
            return redirect(url_for('ecommerce',project_id=project_id)+'#zbozi-platform')
        rules=[{'id':carrier,'price':price,'cod_price':cod}]
    conn=db()
    try:
        existing=conn.execute('SELECT feed_token FROM project_zbozi_feeds WHERE project_id=?',(project_id,)).fetchone()
        if existing:
            conn.execute('UPDATE project_zbozi_feeds SET shipping_rules_json=? WHERE project_id=?',
                         (json.dumps(rules),project_id))
        else:
            conn.execute('INSERT INTO project_zbozi_feeds(project_id,feed_token,shipping_rules_json) VALUES(?,?,?)',
                         (project_id,secrets.token_urlsafe(32),json.dumps(rules)))
        conn.commit()
    finally:conn.close()
    flash('Doprava uložena. Pro promítnutí do XML znovu připrav feed Zboží.cz.','success')
    return redirect(url_for('ecommerce',project_id=project_id)+'#zbozi-platform')


@app.route('/projects/<int:project_id>/ecommerce/zbozi/build',methods=['POST'])
@login_required
def ecommerce_zbozi_build(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    try:
        with commerce_sync_guard(project_id):report=catalog_publish_zbozi(project_id)
        flash('Zboží.cz XML připraveno: '+str(report['exported'])+' nabídek.','success')
    except Exception as exc:flash('Zboží.cz export: '+str(exc)[:200],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#zbozi-platform')


@app.route('/projects/<int:project_id>/connectors/zbozi',methods=['POST'])
@login_required
def zbozi_connector_save(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    key=str(request.form.get('fenix_refresh_token') or '').strip()
    if not key:
        flash('Vlož API klíč Fénix ze Skliku.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#zbozi-connector')
    # First authenticate the Sklik/Fénix account. Existing shopping feeds are NOT
    # required to save a valid API key (shop registration may happen later).
    try:
        probe=zbozi_fenix.probe_feeds(key)
    except (ValueError,requests.RequestException) as exc:
        flash('Klíč se nepodařilo ověřit: '+str(exc)[:200],'error')
        return redirect(url_for('connectors',project_id=project_id)+'#zbozi-connector')
    summary={'connected_at':now(), 'api_verified':True,
             'feed_status':probe.get('feed_status'),
             'feed_http_status':probe.get('feed_http_status'),
             'feed_count':probe.get('feed_count'),
             'last_checked_at':now()}
    # Persist encrypted credentials BEFORE showing the connection as complete.
    # update_integration_secret may create the integration row when necessary.
    try:
        update_integration_secret(project_id,'zbozi_fenix',{'refresh_token':key},'r')
        conn=db()
        try:
            upsert_integration(conn,project_id,'zbozi_fenix','ecommerce','connected',summary,now())
            conn.commit()
        finally:conn.close()
    except Exception:
        app.logger.exception('Fénix: nelze uložit připojení projektu %s',project_id)
        flash('API klíč prošel ověřením, ale jeho bezpečné uložení se nezdařilo. Zkontroluj serverový log.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#zbozi-connector')
    if probe.get('feed_status')=='ok':
        flash('Fénix API připojeno. Načteno %s feedů.' % (probe.get('feed_count') if probe.get('feed_count') is not None else '—'),'success')
    else:
        flash('Fénix API klíč ověřen a uložen. Feed/provozovna zatím nejsou dostupné (HTTP %s); ověř jejich nastavení v Seznam Nákupy.' % (probe.get('feed_http_status') or '—'),'info')
    return redirect(url_for('connectors',project_id=project_id)+'#zbozi-connector')


@app.route('/projects/<int:project_id>/ecommerce/zbozi/check',methods=['POST'])
@login_required
def ecommerce_zbozi_check(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    merchant_check_csrf()
    try:
        creds=integration_secret(project_id,'zbozi_fenix')
        response=zbozi_fenix.probe_feeds(creds.get('refresh_token'))
        cfg=integration_config(integration_row(project_id,'zbozi_fenix'))
        cfg.update({'last_checked_at':now(), 'api_verified':True,
                    'feed_status':response['feed_status'],
                    'feed_http_status':response['feed_http_status'],
                    'feed_count':response['feed_count']})
        conn=db()
        try:
            upsert_integration(conn,project_id,'zbozi_fenix','ecommerce','connected',cfg,now())
            conn.commit()
        finally:conn.close()
        if response['feed_status']=='ok':
            flash('Seznam API ověřeno; počet feedů: %s.' % (response['feed_count'] if response['feed_count'] is not None else '—'),'success')
        else:
            flash('API klíč platí, ale feedy zatím nejdou načíst (HTTP %s). Zkontroluj přístup k provozovně.' % (response['feed_http_status'] or '—'),'info')
    except (ValueError,requests.RequestException) as exc:flash('Zboží.cz API: '+str(exc)[:200],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#zbozi-platform')


@app.route('/catalog/heureka/<token>.xml',methods=['GET'])
def catalog_heureka_public(token):
    if len(token)<32 or len(token)>100:abort(404)
    conn=db()
    try:rec=conn.execute('SELECT project_id FROM project_heureka_feeds WHERE feed_token=?',(token,)).fetchone()
    finally:conn.close()
    if not rec:abort(404)
    path=CATALOG_FEED_DIR / ('heureka_'+str(rec['project_id'])+'_'+token+'.xml')
    if not path.is_file():abort(404)
    from flask import send_file
    return send_file(path,mimetype='application/xml',conditional=True,max_age=300)


@app.route('/catalog/heureka/<token>/availability.xml',methods=['GET'])
def catalog_heureka_availability_public(token):
    if len(token)<32 or len(token)>100:abort(404)
    conn=db()
    try:rec=conn.execute('SELECT project_id,fast_dispatch_confirmed,availability_count FROM project_heureka_feeds WHERE feed_token=?',(token,)).fetchone()
    finally:conn.close()
    # Never advertise an empty/uncertified availability feed as ready for Heureka.
    if not rec or not rec['fast_dispatch_confirmed'] or not rec['availability_count']:abort(404)
    path=CATALOG_FEED_DIR / ('heureka_stock_'+str(rec['project_id'])+'_'+token+'.xml')
    if not path.is_file():abort(404)
    from flask import send_file, Response
    if 'gzip' in (request.headers.get('Accept-Encoding') or '').lower():
        import gzip
        compressed=gzip.compress(path.read_bytes(),compresslevel=6)
        response=Response(compressed,mimetype='application/xml')
        response.headers['Content-Encoding']='gzip'
        response.headers['Cache-Control']='public, max-age=120'
        response.headers['Vary']='Accept-Encoding'
        return response
    response=send_file(path,mimetype='application/xml',conditional=True,max_age=120)
    response.headers['Vary']='Accept-Encoding'
    return response


@app.route('/projects/<int:project_id>/ecommerce/heureka/build',methods=['POST'])
@login_required
def ecommerce_heureka_build(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    if not hmac.compare_digest(str(session.get('merchant_csrf_token') or ''),str(request.form.get('merchant_csrf_token') or '')):abort(403)
    try:
        with commerce_sync_guard(project_id):report=catalog_publish_heureka(project_id)
        flash('Heureka XML připraveno: '+str(report['exported'])+' položek. Dostupnost: '+str(report['availability_count'])+'.','success')
    except Exception as exc:flash('Heureka export: '+str(exc)[:200],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#heureka-platform')


@app.route('/projects/<int:project_id>/connectors/heureka',methods=['POST'])
@login_required
def heureka_connector_save(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    if not hmac.compare_digest(str(session.get('merchant_csrf_token') or ''),str(request.form.get('merchant_csrf_token') or '')):abort(403)
    confirmed=int(request.form.get('fast_dispatch_confirmed')=='1')
    registered=int(request.form.get('shop_registered')=='1')
    delivery_text=str(request.form.get('default_delivery_days') or '').strip()
    if delivery_text and (not delivery_text.isdecimal() or not 0 <= int(delivery_text) <= 30):
        flash('Heureka: expedice musí být celé číslo 0 až 30 dní.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#heureka-connector')
    delivery_days=int(delivery_text) if delivery_text else None
    conn=db()
    try:
        existing=conn.execute('SELECT feed_token FROM project_heureka_feeds WHERE project_id=?',(project_id,)).fetchone()
        token=existing['feed_token'] if existing else secrets.token_urlsafe(32)
        if DB_BACKEND=='mysql':
            conn.execute("""INSERT INTO project_heureka_feeds(project_id,feed_token,fast_dispatch_confirmed,shop_registered,default_delivery_days)
                VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE fast_dispatch_confirmed=VALUES(fast_dispatch_confirmed),shop_registered=VALUES(shop_registered),default_delivery_days=VALUES(default_delivery_days)""",(project_id,token,confirmed,registered,delivery_days))
        else:
            conn.execute("""INSERT INTO project_heureka_feeds(project_id,feed_token,fast_dispatch_confirmed,shop_registered,default_delivery_days)
                VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET fast_dispatch_confirmed=excluded.fast_dispatch_confirmed,shop_registered=excluded.shop_registered,default_delivery_days=excluded.default_delivery_days""",(project_id,token,confirmed,registered,delivery_days))
        conn.commit()
    finally:conn.close()
    # Rebuild immediately when settings change and published feed already exists.
    old=heureka_settings(project_id)
    if old.get('generated_at'):
        try:
            with commerce_sync_guard(project_id):catalog_publish_heureka(project_id)
        except Exception as exc:flash('Nastavení uloženo, ale aktualizace dostupnosti se nezdařila: '+str(exc)[:140],'error')
    flash('Nastavení Heureky uloženo. Registraci obchodu ověřujeme ručně v účtu Heureky, nejde o API autorizaci.','success')
    return redirect(url_for('connectors',project_id=project_id)+'#heureka-connector')


def catalog_workflow_tick(project_id):
    """Cron-friendly bounded unit of work. No thread/background request spawning."""
    conn=db()
    try:
        workflow=feed_workflow.state(conn,project_id)
        if workflow['mode'] not in ('running','active'):return None
        project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        read_key=conn.execute('SELECT read_key_enc FROM project_core_read WHERE project_id=?',(project_id,)).fetchone()
    finally:conn.close()
    if not project or not read_key:
        conn=db()
        try:feed_workflow.update(conn,DB_BACKEND,project_id,now(),mode='paused',last_error='Projekt nebo čtecí klíč Fresh Core není dostupný.')
        finally:conn.close()
        return 'chybí projekt nebo přístup'
    try:
        with commerce_sync_guard(project_id):
            info=ecommerce_data(project_id)
            # Active projects refresh after their configured interval.
            if workflow['mode']=='active' and catalog_ready(project_id):
                feed=info.get('feed')
                if feed and feed.get('generated_at'):
                    try:
                        last=datetime.fromisoformat(str(feed['generated_at']).replace('Z','+00:00')).replace(tzinfo=None)
                        if (datetime.utcnow()-last).total_seconds()<int(workflow['interval_minutes'])*60:return None
                    except (TypeError,ValueError):pass
                reset_products=True
            else:reset_products=False
            key=decrypt_secret(read_key['read_key_enc'])
            products_complete=bool(info['catalog'].get('next_page')==0 and info['catalog'].get('finished_at'))
            variants_complete=bool(info['variants_state'] and info['variants_state'].get('next_page')==0 and info['variants_state'].get('finished_at'))
            if reset_products or not products_complete:
                result=core_catalog_batch(project_id,project,key,reset=reset_products,pages=COMMERCE_BATCH_PAGES)
                # An active refresh must update both products and variants before publishing.
                if reset_products:
                    conn=db()
                    try:conn.execute('DELETE FROM project_core_variant_sync WHERE project_id=?',(project_id,));conn.commit()
                    finally:conn.close()
                return 'produkty '+str(result['processed'])
            if not variants_complete:
                result=core_variants_batch(project_id,project,key,reset=(not info['variants_state']))
                return 'varianty '+str(result['processed'])
            if workflow['approved']:
                report=catalog_publish_google(project_id)
                if heureka_settings(project_id).get('generated_at'):
                    try:
                        catalog_publish_heureka(project_id)
                    except Exception as heureka_exc:
                        # A secondary output must never stop working Google catalogue sync.
                        conn_err=db()
                        try:
                            conn_err.execute('UPDATE project_heureka_feeds SET last_error=? WHERE project_id=?',
                                             (str(heureka_exc)[:240],project_id))
                            conn_err.commit()
                        finally:conn_err.close()
                if zbozi_settings(project_id).get('generated_at'):
                    try:catalog_publish_zbozi(project_id)
                    except Exception as zbozi_exc:
                        conn_err=db()
                        try:
                            conn_err.execute('UPDATE project_zbozi_feeds SET last_error=? WHERE project_id=?',(str(zbozi_exc)[:240],project_id))
                            conn_err.commit()
                        finally:conn_err.close()
                if meta_settings(project_id).get('generated_at'):
                    try:catalog_publish_meta(project_id)
                    except Exception as meta_exc:
                        conn_err=db()
                        try:
                            conn_err.execute('UPDATE project_meta_feeds SET last_error=? WHERE project_id=?',(str(meta_exc)[:240],project_id))
                            conn_err.commit()
                        finally:conn_err.close()
                feed_workflow.update(db_conn:=db(),DB_BACKEND,project_id,now(),mode='active',last_error=None)
                db_conn.close()
                return 'publikováno '+str(report['exported'])
            conn=db()
            try:feed_workflow.update(conn,DB_BACKEND,project_id,now(),mode='review',last_error=None)
            finally:conn.close()
            return 'čeká na schválení'
    except ValueError as exc:
        # Another process has lock: let the next tick retry, don't mark as failed.
        if 'už v tomto projektu probíhá' in str(exc):return 'obsazeno'
        error=str(exc)[:400]
    except Exception as exc:
        error=str(exc)[:400]
    conn=db()
    try:feed_workflow.update(conn,DB_BACKEND,project_id,now(),mode='paused',last_error=error)
    finally:conn.close()
    return 'chyba: '+error


def catalog_workflow_all(limit=5):
    touch_worker('catalog', 'running', {'phase':'catalog-sync'})
    conn=db()
    rows=conn.execute("SELECT project_id FROM catalog_workflows WHERE mode IN ('running','active') ORDER BY updated_at LIMIT ?",(limit,)).fetchall()
    conn.close()
    results=[]
    for r in rows:results.append((r['project_id'],catalog_workflow_tick(r['project_id'])))
    touch_worker('catalog', 'idle', {'results':results})
    return results

def _catalog_tree_rows(categories):
    """Order category records by ancestry, guarding missing parents and cycles."""
    by_id={int(c['id']):dict(c) for c in categories}
    children={}
    for cat in by_id.values():
        parent=int(cat.get('parent') or 0)
        if parent not in by_id or parent == cat['id']:parent=0
        children.setdefault(parent,[]).append(cat)
    for siblings in children.values():siblings.sort(key=lambda x:x['name'].casefold())
    output=[];visited=set()
    def visit(cat,depth):
        if cat['id'] in visited:return
        visited.add(cat['id'])
        output.append(dict(cat,depth=min(depth,12)))
        for child in children.get(cat['id'],[]):visit(child,depth+1)
    for root in children.get(0,[]):visit(root,0)
    for cat in by_id.values():visit(cat,0)
    return output


def ecommerce_data(project_id):
    conn=db()
    products=conn.execute('SELECT COUNT(*) AS n FROM project_core_products WHERE project_id=?',(project_id,)).fetchone()['n']
    variants=conn.execute('SELECT COUNT(*) AS n FROM project_core_variants WHERE project_id=?',(project_id,)).fetchone()['n']
    varstate=conn.execute('SELECT * FROM project_core_variant_sync WHERE project_id=?',(project_id,)).fetchone()
    feed=conn.execute('SELECT * FROM project_google_feeds WHERE project_id=?',(project_id,)).fetchone()
    conn.close()
    return {'products':products,'variants':variants,'variants_state':dict(varstate) if varstate else None,
            'feed':dict(feed) if feed else None,'catalog':core_catalog_summary(project_id)}


def catalog_live_status(project_id):
    """Lightweight, read-only snapshot. Never starts or resets a queue."""
    conn=db()
    try:
        state=feed_workflow.state(conn,project_id)
        p=conn.execute('SELECT COUNT(*) AS n FROM project_core_products WHERE project_id=?',(project_id,)).fetchone()
        v=conn.execute('SELECT COUNT(*) AS n FROM project_core_variants WHERE project_id=?',(project_id,)).fetchone()
        ps=conn.execute('SELECT next_page,total,synced_count,sync_started_at,last_error,finished_at FROM project_core_sync WHERE project_id=?',(project_id,)).fetchone()
        vs=conn.execute('SELECT next_page,total,synced_count,last_error,finished_at FROM project_core_variant_sync WHERE project_id=?',(project_id,)).fetchone()
        worker=conn.execute('SELECT status,last_seen,detail_json FROM workers WHERE name=?',('catalog',)).fetchone()
    finally:
        conn.close()
    def as_dict(record):
        return dict(record) if record else {}
    products=as_dict(ps);variants=as_dict(vs);w=as_dict(worker)
    done_p=int(p['n'] if p else 0);done_v=int(v['n'] if v else 0)
    total_p=max(0,int(products.get('total') or 0)); total_v=max(0,int(variants.get('total') or 0))
    total=total_p+total_v; processed=done_p+done_v
    percentage=min(100,round(100*processed/total,1)) if total else 0
    completed=bool(products.get('finished_at') and products.get('next_page')==0 and variants.get('finished_at') and variants.get('next_page')==0)
    last_seen=w.get('last_seen')
    age=None
    if last_seen:
        try:age=max(0,int((datetime.now()-datetime.fromisoformat(str(last_seen))).total_seconds()))
        except (ValueError,TypeError):pass
    last_result=None
    if w.get('detail_json'):
        try:
            details=json.loads(w['detail_json'])
            for entry in reversed(details.get('results') or []):
                if int(entry[0])==int(project_id):last_result=str(entry[1] or '')[:140];break
        except (ValueError,TypeError,IndexError,KeyError):pass
    mode=str(state.get('mode') or 'idle')
    error=state.get('last_error') or products.get('last_error') or variants.get('last_error')
    if error: label='Vyžaduje pozornost'
    elif mode=='paused':label='Pozastaveno'
    elif completed and mode=='review':label='Načteno – čeká na schválení'
    elif completed and mode=='active':label='Aktuální katalog – automatická správa'
    elif mode in ('running','active') and age is None:label='Čeká na první běh plánovače'
    elif mode in ('running','active') and age>180:label='Plánovač se dlouho neozval'
    elif mode in ('running','active') and w.get('status')=='running':label='Probíhá zpracování dávky'
    elif mode in ('running','active'):label='Čeká na další dávku'
    else:label='Čeká na spuštění'
    return {'mode':mode,'label':label,'products':{'loaded':done_p,'total':total_p,'finished':bool(products.get('finished_at')),'next_page':products.get('next_page')},
        'variants':{'loaded':done_v,'total':total_v,'finished':bool(variants.get('finished_at')),'next_page':variants.get('next_page')},
        'total_loaded':processed,'total_expected':total,'percent':percentage,'complete':completed,
        'last_worker_at':last_seen,'worker_age_seconds':age,'last_result':last_result,
        'last_product_batch_at':products.get('sync_started_at'),'last_variant_batch_at':variants.get('sync_started_at'),
        'error':str(error)[:240] if error else None,'sampled_at':now()}


@app.route('/projects/<int:project_id>/ecommerce/status', methods=['GET'])
@login_required
def ecommerce_status(project_id):
    project_for_user(project_id)
    response=jsonify({'ok':True,**catalog_live_status(project_id)})
    response.headers['Cache-Control']='no-store, private, max-age=0'
    response.headers['Pragma']='no-cache'
    return response


@app.route('/projects/<int:project_id>/ecommerce')
@login_required
def ecommerce(project_id):
    project=project_for_user(project_id)
    info=ecommerce_data(project_id)
    parents,variants,excluded,workflow=catalog_cached_data(project_id)
    categories=cached_catalog_categories(project_id) or feed_workflow.category_tree(parents)
    cats=_catalog_tree_rows(categories)
    inherited_excluded=feed_workflow.excluded_category_ids(categories,excluded['category'])
    page=max(1,min(100000,int(request.args.get('page') or 1))) if str(request.args.get('page') or '1').isdigit() else 1
    q=(request.args.get('q') or '').strip().lower()[:90]
    # Apply category exclusions *before* rendering the product selector.
    # Individual product exceptions are kept visible so they can be re-enabled.
    category_only={'category':excluded['category'],'product':set()}
    permitted_parents,permitted_variants,_=feed_workflow.selected(parents,variants,category_only,categories=categories)
    listing=[dict(p, selector_id=p['id'], selector_kind='produkt') for p in permitted_parents]
    listing.extend(dict(v, selector_id=v['variation_id'], selector_kind='varianta') for v in permitted_variants)
    filtered=[p for p in listing if not q or q in (str(p.get('title') or '')+' '+str(p.get('sku') or '')+' '+str(p.get('selector_id') or '')).lower()]
    rows=filtered[(page-1)*35:page*35]
    picked_parents,picked_variants,excluded_count=feed_workflow.selected(parents,variants,excluded,categories=categories)
    preview={'parents':len(picked_parents),'variants':len(picked_variants),**excluded_count}
    merchant_row=integration_row(project_id,'merchant_center')
    merchant_snapshot=integration_config(merchant_row)
    if 'merchant_csrf_token' not in session:
        session['merchant_csrf_token']=secrets.token_urlsafe(32)
    heureka_config=heureka_settings(project_id)
    zbozi_config=zbozi_settings(project_id)
    if zbozi_config.get('report_json'):
        try:zbozi_config['report']=json.loads(zbozi_config['report_json'])
        except (ValueError,TypeError):zbozi_config['report']={}
    try:
        zbozi_config['shipping_rules']=json.loads(zbozi_config.get('shipping_rules_json') or '[]')
    except (TypeError,ValueError):zbozi_config['shipping_rules']=[]
    zbozi_api_config=integration_config(integration_row(project_id,"zbozi_fenix"))
    meta_config=meta_settings(project_id)
    meta_config["api_token_cipher"] = None if not meta_config.get("api_token_cipher") else "configured"
    try:
        meta_config['api_result']=json.loads(meta_config.get('api_last_result') or '{}')
    except (TypeError,ValueError):
        meta_config['api_result']={}
    if meta_config.get('report_json'):
        try:meta_config['report']=json.loads(meta_config['report_json'])
        except (ValueError,TypeError):meta_config['report']={}
    if heureka_config.get('report_json'):
        try:heureka_config['report']=json.loads(heureka_config['report_json'])
        except (ValueError,TypeError):heureka_config['report']={}
    return render_template('ecommerce.html',merchant_connected=bool(merchant_row and merchant_row['status'] != 'disconnected'),merchant_csrf=session['merchant_csrf_token'],merchant_snapshot=merchant_snapshot,heureka_config=heureka_config,zbozi_config=zbozi_config,zbozi_api_config=zbozi_api_config,meta_config=meta_config,project=project,ecommerce=info,export_report=json.loads(info['feed']['report_json']) if info['feed'] and info['feed'].get('report_json') else {},workflow=workflow,category_rows=cats,excluded_categories=excluded['category'],inherited_excluded_categories=inherited_excluded,excluded_products=excluded['product'],product_rows=rows,product_page=page,product_pages=max(1,(len(filtered)+34)//35),product_query=q,selection_preview=preview,product_visible_total=len(filtered),category_visible_total=len(listing))


@app.route('/projects/<int:project_id>/ecommerce/sync-variants',methods=['POST'])
@login_required
def ecommerce_sync_variants(project_id):
    project=project_for_user(project_id)
    conn=db();keyrow=conn.execute('SELECT read_key_enc FROM project_core_read WHERE project_id=?',(project_id,)).fetchone();conn.close()
    if not keyrow:
        flash('Nejprve ověř REST čtení Fresh Core v konektorech.','error')
        return redirect(url_for('connectors',project_id=project_id))
    try:
        with commerce_sync_guard(project_id):
            result=core_variants_batch(project_id,project,decrypt_secret(keyrow['read_key_enc']),reset=request.form.get('reset')=='1')
        flash('Varianty: načteno '+str(result['processed'])+', dostupných '+str(result.get('total',0))+'.'+(' Hotovo.' if result['complete'] else ' Pokračuj další dávkou.'),'success')
    except Exception as exc:
        flash('Synchronizace variant: '+str(exc)[:180],'error')
    return redirect(url_for('ecommerce',project_id=project_id))


@app.route('/projects/<int:project_id>/ecommerce/sync-products',methods=['POST'])
@login_required
def ecommerce_sync_products(project_id):
    p=project_for_user(project_id)
    conn=db();keyrow=conn.execute('SELECT read_key_enc FROM project_core_read WHERE project_id=?',(project_id,)).fetchone();conn.close()
    if not keyrow:
        flash('Nejprve ověř REST čtení Fresh Core v konektorech.','error')
        return redirect(url_for('connectors',project_id=project_id))
    try:
        with commerce_sync_guard(project_id):
            result=core_catalog_batch(project_id,p,decrypt_secret(keyrow['read_key_enc']),reset=request.form.get('reset')=='1',pages=COMMERCE_BATCH_PAGES)
        flash('Produkty: načteno '+str(result['processed'])+'.'+(' Hotovo.' if result['complete'] else ' Pokračuj další dávkou.'),'success')
    except Exception as exc:
        flash('Synchronizace produktů: '+str(exc)[:180],'error')
    return redirect(url_for('ecommerce',project_id=project_id))


@app.route('/projects/<int:project_id>/ecommerce/google/build',methods=['POST'])
@login_required
def ecommerce_google_build(project_id):
    project_for_user(project_id)
    try:
        report=catalog_publish_google(project_id)
        flash('Google XML zveřejněno: '+str(report['exported'])+' položek.','success')
    except Exception as exc:flash('Export: '+str(exc)[:200],'error')
    return redirect(url_for('ecommerce',project_id=project_id))

@app.route('/projects/<int:project_id>/ecommerce/workflow',methods=['POST'])
@login_required
def ecommerce_workflow_update(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    action=request.form.get('action')
    conn=db()
    try:
        state=feed_workflow.state(conn,project_id)
        if action=='start':
            feed_workflow.update(conn,DB_BACKEND,project_id,now(),mode='running',last_error=None)
            kicked=kick_background_worker('catalog-sync')
            flash('Synchronizace obnovena od uložené stránky. '+('První dávka byla předána ke zpracování.' if kicked else 'Okamžité spuštění se nezdařilo; ověř serverový cron.'),'success' if kicked else 'error')
        elif action=='run_once':
            if state.get('mode') not in ('running','active'):
                raise ValueError('Nejdřív spusť nebo obnov frontu.')
            # Run a separate bounded worker process to avoid blocking the request.
            kicked=kick_background_worker('catalog-sync')
            flash('Jedna dávka předána ke zpracování.' if kicked else 'Spuštění dávky selhalo; ověř plánovač a worker.log.','success' if kicked else 'error')
        elif action=='restart':
            if request.form.get('confirm')!='RESTART':
                raise ValueError('Pro novou frontu je potřeba potvrzení.')
            # Clear only the working cache/cursors. Published Google XML and exclusions survive.
            for table in ('project_core_sync','project_core_variant_sync','project_core_products','project_core_variants'):
                conn.execute('DELETE FROM '+table+' WHERE project_id=?',(project_id,))
            feed_workflow.update(conn,DB_BACKEND,project_id,now(),mode='running',approved=0,approved_at=None,last_error=None,revision=int(state['revision'])+1)
            kicked=kick_background_worker('catalog-sync')
            flash('Nová fronta založena od začátku. Výběr kategorií a poslední veřejný XML export zůstávají zachované. '+('Spouštím první dávku.' if kicked else 'Nyní je nutné spustit serverový plánovač.'),'success' if kicked else 'error')
        elif action=='pause':
            feed_workflow.update(conn,DB_BACKEND,project_id,now(),mode='paused')
            flash('Synchronizace pozastavena.','success')
        elif action=='approve':
            if not catalog_ready(project_id):raise ValueError('Nejdříve dokonči načítání katalogu.')
            feed_workflow.update(conn,DB_BACKEND,project_id,now(),approved=1,approved_at=now(),mode='running',revision=state['revision']+1)
            flash('Výběr schválen, Boban připraví a publikuje Google XML.','success')
        elif action=='interval':
            minutes=int(request.form.get('minutes') or 60)
            if minutes not in (15,30,60,180,360,720,1440):raise ValueError('Neplatný interval')
            feed_workflow.update(conn,DB_BACKEND,project_id,now(),interval_minutes=minutes)
            flash('Interval kontrol byl uložen.','success')
        else:abort(400)
    except ValueError as exc:flash(str(exc),'error')
    finally:conn.close()
    return redirect(url_for('ecommerce',project_id=project_id))

@app.route('/projects/<int:project_id>/ecommerce/exclusion',methods=['POST'])
@login_required
def ecommerce_exclusion_update(project_id):
    project_for_user(project_id)
    if not current_user.can_edit:abort(403)
    kind=request.form.get('kind')
    try:ident=int(request.form.get('id') or 0)
    except (TypeError,ValueError):abort(400)
    conn=db()
    try:
        existing=feed_workflow.exclusions(conn,project_id)
        if kind not in ('category','product') or ident<=0:abort(400)
        feed_workflow.set_exclusion(conn,DB_BACKEND,project_id,kind,ident,ident not in existing[kind])
        state=feed_workflow.state(conn,project_id)
        feed_workflow.update(conn,DB_BACKEND,project_id,now(),approved=0,approved_at=None,mode='review',revision=state['revision']+1)
        flash('Výběr upraven. Nový export vyžaduje schválení; dřívější feed zůstává dostupný.','success')
    finally:conn.close()
    return redirect(url_for('ecommerce',project_id=project_id,q=request.form.get('q') or '',page=request.form.get('page') or 1)+'#catalog-selection')

@app.route('/catalog/google/<token>.xml',methods=['GET'])
def catalog_google_public(token):
    if len(token)<32 or len(token)>100:abort(404)
    conn=db();rec=conn.execute('SELECT project_id FROM project_google_feeds WHERE feed_token=?',(token,)).fetchone();conn.close()
    if not rec:abort(404)
    filepath=CATALOG_FEED_DIR / ('google_'+str(rec['project_id'])+'_'+token+'.xml')
    if not filepath.is_file():abort(404)
    from flask import send_file
    return send_file(filepath,mimetype='application/xml',conditional=True,max_age=300)


@app.route('/projects/<int:project_id>/core/catalog/read-key', methods=['POST'])
@login_required
def project_core_catalog_key(project_id):
    p=project_for_user(project_id)
    key=(request.form.get('read_key') or '').strip()
    if len(key)<32 or len(key)>256:abort(400)
    try:
        data=core_catalog_read(p,key,page=1,per_page=1)
    except Exception as exc:
        flash('Katalog nelze ověřit: '+str(exc)[:150],'error')
        return redirect(url_for('connectors',project_id=project_id)+'#core-commerce')
    conn=db();secret=encrypt_secret(key)
    if DB_BACKEND=='mysql':
        conn.execute('INSERT INTO project_core_read(project_id,read_key_enc,checked_at) VALUES(?,?,?) ON DUPLICATE KEY UPDATE read_key_enc=VALUES(read_key_enc),checked_at=VALUES(checked_at)',
                     (project_id,secret,now()))
    else:
        conn.execute('INSERT OR REPLACE INTO project_core_read(project_id,read_key_enc,checked_at) VALUES(?,?,?)',(project_id,secret,now()))
    conn.execute('DELETE FROM project_core_sync WHERE project_id=?',(project_id,))
    conn.execute('DELETE FROM project_core_products WHERE project_id=?',(project_id,))
    conn.execute('DELETE FROM project_core_variants WHERE project_id=?',(project_id,))
    conn.execute('DELETE FROM project_core_variant_sync WHERE project_id=?',(project_id,))
    add_activity(conn,project_id,'connector','Fresh Core REST čtení ověřeno','Existující Fresh Core – pouze čtení, bez nového WooCommerce konektoru.')
    conn.commit();conn.close()
    flash('Fresh Core katalog ověřen – dostupných produktů: '+str(data.get('total',0)),'success')
    return redirect(url_for('connectors',project_id=project_id)+'#core-commerce')


@app.route('/projects/<int:project_id>/core/catalog/check',methods=['POST'])
@login_required
def project_core_catalog_check(project_id):
    p=project_for_user(project_id)
    conn=db();rec=conn.execute('SELECT read_key_enc FROM project_core_read WHERE project_id=?',(project_id,)).fetchone();conn.close()
    if not rec:
        flash('Nejdříve jednorázově autorizuj čtení REST v kartě Fresh Core.','error')
        return redirect(url_for('connectors',project_id=project_id)+'#fresh-core')
    reset=request.form.get('reset')=='1'
    try:
        result=core_catalog_batch(project_id,p,decrypt_secret(rec['read_key_enc']),reset=reset,pages=COMMERCE_BATCH_PAGES)
        conn=db();summary=core_catalog_summary(project_id)
        upsert_integration(conn,project_id,'core_commerce','catalog','connected',
                           {'total':summary.get('total',0),'cached_products':summary['cached_products'],
                            'complete':result['complete'],'note':'Read-only data cache, not a catalog export'},now())
        conn.commit();conn.close()
        flash('Fresh Core: načteno '+str(result['processed'])+' produktů v dávce; uloženo '+str(summary['cached_products'])+' / '+str(result['total'])+'.'+(' Hotovo.' if result['complete'] else ' Pokračuj další dávkou.'),'success')
    except Exception as exc:
        conn=db()
        if DB_BACKEND=='mysql':
            conn.execute('INSERT INTO project_core_sync(project_id,next_page,last_error) VALUES(?,?,?) ON DUPLICATE KEY UPDATE last_error=VALUES(last_error)',(project_id,1,str(exc)[:500]))
        else:
            old=conn.execute('SELECT project_id FROM project_core_sync WHERE project_id=?',(project_id,)).fetchone()
            if old:conn.execute('UPDATE project_core_sync SET last_error=? WHERE project_id=?',(str(exc)[:500],project_id))
            else:conn.execute('INSERT INTO project_core_sync(project_id,next_page,last_error) VALUES(?,?,?)',(project_id,1,str(exc)[:500]))
        conn.commit();conn.close()
        flash('Čtení produktů selhalo: '+str(exc)[:180],'error')
    return redirect(url_for('connectors',project_id=project_id)+'#fresh-core')


@app.route("/projects/<int:project_id>/seo/findings/<code>")
@login_required
def seo_finding(project_id, code):
    p = project_for_user(project_id)
    source = request.args.get("source", "").strip() or None
    rows = finding_rows(project_id, code, source)
    if not rows:
        abort(404)
    view_rows = []
    for row in rows:
        item = dict(row)
        item["context"] = _issue_context(row)
        view_rows.append(item)
    return render_template(
        "finding.html",
        project=p,
        finding=view_rows[0],
        issues=view_rows,
        actionable=code in AI_ACTIONABLE_CODES,
        ai_batch_limit=AI_BATCH_LIMIT,
        knowledge_slug=ISSUE_KNOWLEDGE_MAP.get(code),
    )


@app.route("/projects/<int:project_id>/seo/ai-fix", methods=["POST"])
@login_required
def seo_ai_fix(project_id):
    p = project_for_user(project_id)
    code = request.form.get("code", "").strip()
    source = request.form.get("source", "").strip() or None
    issue_ids = [x for x in request.form.getlist("issue_ids") if str(x).isdigit()]
    # v0.7.0: AI never publishes directly. Boban prepares a proposal, the user
    # may edit it, and only then the explicit publish action uses Fresh Core.
    auto_apply = False

    conn = db()
    if issue_ids:
        marks = ",".join("?" for _ in issue_ids[:200])
        rows = conn.execute(
            f"SELECT * FROM issues WHERE project_id=? AND status='open' AND id IN ({marks}) ORDER BY id",
            [project_id, *issue_ids[:200]]
        ).fetchall()
    elif code:
        if source:
            rows = conn.execute(
                "SELECT * FROM issues WHERE project_id=? AND status='open' AND code=? AND source=? ORDER BY id LIMIT 200",
                (project_id, code, source)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM issues WHERE project_id=? AND status='open' AND code=? ORDER BY id LIMIT 200",
                (project_id, code)
            ).fetchall()
    else:
        rows = []
    conn.close()

    if not rows:
        flash("Vyber alespoň jednu stránku, kterou chceš řešit.", "info")
        return redirect(request.referrer or url_for("seo", project_id=project_id))

    queued = queue_ai_prepare_jobs(project_id, rows, auto_apply=False)
    flash(
        f"Začínám. {queued['count']} stránek projdu po menších skupinách a připravím návrhy. Než se cokoliv publikuje, můžeš každý návrh upravit a teprve potom ho schválit.",
        "success"
    )
    return redirect(url_for("actions", project_id=project_id, view="todo"))


@app.route("/projects/<int:project_id>/actions/bulk-apply", methods=["POST"])
@login_required
def actions_bulk_apply(project_id):
    p = project_for_user(project_id)
    ids = [int(x) for x in request.form.getlist("action_ids") if str(x).isdigit()][:50]
    if not ids:
        flash("Vyber alespoň jeden úkol.", "info")
        return redirect(url_for("actions", project_id=project_id))

    conn = db()
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM actions WHERE project_id=? AND id IN ({marks}) AND status IN ('draft','approved','failed') ORDER BY id",
        [project_id, *ids]
    ).fetchall()
    conn.close()
    valid_ids = []
    blocked = []
    for row in rows:
        ready, reason = action_provider_ready(p, row)
        if ready: valid_ids.append(row["id"])
        else: blocked.append(f"#{row['id']}: {reason}")
    if not valid_ids:
        flash("Nebyl nalezen žádný úkol připravený k provedení.", "info")
        return redirect(url_for("actions", project_id=project_id))

    queued = queue_seo_apply_jobs(project_id, valid_ids)
    message = f"Mám to. {queued['count']} úkolů zpracuji postupně na pozadí. Nemusíš čekat na této stránce; výsledek ti pošlu do oznámení."
    if blocked:
        message += " Přeskočil jsem úkoly bez potřebného write oprávnění: " + "; ".join(blocked[:4])
    flash(message, "success" if not blocked else "info")
    return redirect(url_for("actions", project_id=project_id, view="todo"))


@app.route("/projects/<int:project_id>/actions")
@login_required
def actions(project_id):
    p = project_for_user(project_id)
    expire_snoozes(project_id)
    reconcile_project_state(project_id)
    view = request.args.get("view", "todo").strip().lower()
    if view not in {"todo", "done", "hidden", "all"}:
        view = "todo"
    if view == "todo":
        status_where = "status IN ('draft','approved','failed','queued','pending')"
    elif view == "done":
        status_where = "status IN ('applied','verified','completed')"
    elif view == "hidden":
        status_where = "status IN ('snoozed','dismissed')"
    else:
        status_where = "1=1"

    conn = db()
    rows = conn.execute(
        f"""SELECT actions.*,
                   (SELECT j.result_json FROM jobs j WHERE j.action_id=actions.id AND j.job_type='seo_apply_action' ORDER BY j.id DESC LIMIT 1) AS latest_job_result,
                   (SELECT j.status FROM jobs j WHERE j.action_id=actions.id AND j.job_type='seo_apply_action' ORDER BY j.id DESC LIMIT 1) AS latest_job_status
            FROM actions WHERE project_id=? AND {status_where} ORDER BY id DESC LIMIT 500""", (project_id,)
    ).fetchall()
    counts = conn.execute(
        """SELECT
            SUM(CASE WHEN status IN ('draft','approved','failed','queued','pending') THEN 1 ELSE 0 END) todo_count,
            SUM(CASE WHEN status IN ('applied','verified','completed') THEN 1 ELSE 0 END) done_count,
            SUM(CASE WHEN status IN ('snoozed','dismissed') THEN 1 ELSE 0 END) hidden_count,
            COUNT(*) total_count
           FROM actions WHERE project_id=?""",
        (project_id,)
    ).fetchone()
    conn.close()
    cards = []
    for row in rows:
        item = dict(row)
        for field in ("proposed_json", "ai_proposal_json", "before_json", "result_json", "baseline_metrics_json", "impact_json", "verification_json"):
            try:
                item[field.replace("_json", "")] = json.loads(row[field] or "{}") if field in row.keys() else {}
            except Exception:
                item[field.replace("_json", "")] = {}
        if not item.get("last_error") and item.get("latest_job_result"):
            try:
                job_result = json.loads(item["latest_job_result"])
                item["visible_error"] = str(job_result.get("error") or "")[:1200] if item.get("latest_job_status") in ("retry", "failed") else ""
            except (ValueError, TypeError, AttributeError):
                item["visible_error"] = ""
        else:
            item["visible_error"] = str(item.get("last_error") or "")[:1200]
        cards.append(item)
    return render_template(
        "actions.html", project=p, actions=cards,
        gsc=latest_source_snapshot(project_id, "search_console"),
        view=view, counts=counts or {"todo_count": 0, "done_count": 0, "hidden_count": 0, "total_count": 0},
        queue=queue_summary(project_id), worker=worker_state('seo_queue')
    )


@app.route("/projects/<int:project_id>/actions/state", methods=["POST"])
@login_required
def actions_state(project_id):
    project_for_user(project_id)
    action = request.form.get("task_action", "").strip()
    ids = [int(x) for x in request.form.getlist("action_ids") if str(x).isdigit()][:500]
    if not ids:
        flash("Vyber alespoň jeden úkol.", "info")
        return redirect(request.referrer or url_for("actions", project_id=project_id, view="todo"))
    conn = db()
    marks = ",".join("?" for _ in ids)
    if action == "snooze":
        until = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
        conn.execute(
            f"UPDATE actions SET status='snoozed',snoozed_until=?,dismissed_at=NULL WHERE project_id=? AND id IN ({marks}) AND status IN ('draft','failed','approved')",
            [until, project_id, *ids]
        )
        conn.execute(
            f"UPDATE jobs SET status='canceled',finished_at=?,updated_at=? WHERE project_id=? AND action_id IN ({marks}) AND status IN ('queued','retry')",
            [now(), now(), project_id, *ids]
        )
        msg = "Odložil jsem vybrané úkoly na 30 dní."
    elif action == "dismiss":
        conn.execute(
            f"UPDATE actions SET status='dismissed',dismissed_at=?,snoozed_until=NULL WHERE project_id=? AND id IN ({marks}) AND status IN ('draft','failed','approved')",
            [now(), project_id, *ids]
        )
        conn.execute(
            f"UPDATE jobs SET status='canceled',finished_at=?,updated_at=? WHERE project_id=? AND action_id IN ({marks}) AND status IN ('queued','retry')",
            [now(), now(), project_id, *ids]
        )
        msg = "Zahodil jsem vybrané úkoly. V archivu skrytých je můžeš kdykoliv obnovit."
    elif action == "restore":
        conn.execute(
            f"UPDATE actions SET status='draft',dismissed_at=NULL,snoozed_until=NULL WHERE project_id=? AND id IN ({marks}) AND status IN ('snoozed','dismissed')",
            [project_id, *ids]
        )
        msg = "Obnovil jsem vybrané úkoly."
    else:
        conn.close(); flash("Neznámá akce.", "error")
        return redirect(request.referrer or url_for("actions", project_id=project_id, view="todo"))
    conn.commit(); conn.close()
    flash(msg, "success")
    return redirect(url_for("actions", project_id=project_id, view="hidden" if action in {"snooze","dismiss"} else "todo"))


@app.route("/projects/<int:project_id>/actions/new", methods=["POST"])
@login_required
def action_new(project_id):
    p = project_for_user(project_id)
    post_id = request.form.get("post_id", "").strip()
    target_url = request.form.get("target_url", "").strip()
    changes = {}
    for field in ("title", "description", "canonical"):
        value = request.form.get(field, "").strip()
        if value:
            changes[field] = value
    if "noindex" in request.form:
        changes["noindex"] = True
    if "nofollow" in request.form:
        changes["nofollow"] = True

    if not post_id.isdigit() or not changes:
        flash("Vyber WordPress ID a alespoň jednu změnu.", "error")
        return redirect(url_for("seo", project_id=project_id))

    conn = db()
    cur = conn.execute(
        """
        INSERT INTO actions(project_id,channel,action_type,target_type,target_id,target_url,reason,proposed_json,status,expected_outcome,user_edited_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            project_id, "seo", "update_meta", "wordpress_post", post_id, target_url,
            "Ruční návrh SEO změny ve Web Boosteru",
            json.dumps(changes, ensure_ascii=False), "draft", expected_outcome_for_changes(changes), now(), now()
        )
    )
    save_action_revision(conn, project_id, cur.lastrowid, "user", changes)
    add_activity(conn, project_id, "action", "SEO změna připravena",
                 f"WordPress post ID {post_id}; čeká na schválení.")
    conn.commit()
    conn.close()
    flash("Změna je uložená jako návrh. Nic se na webu ještě nezměnilo.", "success")
    return redirect(url_for("actions", project_id=project_id))


@app.route("/projects/<int:project_id>/actions/<int:action_id>/edit", methods=["POST"])
@login_required
def action_edit(project_id, action_id):
    project_for_user(project_id)
    conn = db()
    action = conn.execute("SELECT * FROM actions WHERE id=? AND project_id=?", (action_id, project_id)).fetchone()
    if not action:
        conn.close(); abort(404)
    if action["status"] not in {"draft", "failed", "approved"}:
        conn.close()
        flash("Návrh lze upravit jen před publikací.", "info")
        return redirect(url_for("actions", project_id=project_id, view="todo"))

    try:
        current = json.loads(action["proposed_json"] or "{}")
    except Exception:
        current = {}
    changes = {}
    provider = str(action["provider"] or "fresh_core") if "provider" in action.keys() else "fresh_core"
    operation = str(action["operation"] or action["action_type"] or "") if "operation" in action.keys() else str(action["action_type"] or "")
    if provider == "search_console" and operation in {"submit_sitemap","delete_sitemap"}:
        value = request.form.get("sitemap_url", "").strip()
        if value: changes["sitemap_url"] = value
    elif provider == "ga4" and operation == "create_key_event":
        value = request.form.get("event_name", "").strip()
        if value: changes["event_name"] = value
        changes["counting_method"] = request.form.get("counting_method", current.get("counting_method") or "ONCE_PER_EVENT")
    elif action["action_type"] == "update_image_alt":
        value = request.form.get("alt", "").strip()
        if value: changes["alt"] = value
    else:
        for field in ("title", "description", "canonical"):
            value = request.form.get(field, "").strip()
            if value: changes[field] = value
        for field in ("noindex", "nofollow"):
            if field in current: changes[field] = bool(current[field])
    if not changes:
        conn.close()
        flash("Finální verze nemůže být prázdná.", "error")
        return redirect(url_for("actions", project_id=project_id, view="todo"))

    conn.execute(
        "UPDATE actions SET proposed_json=?,expected_outcome=?,user_edited_at=?,status='draft',last_error=NULL WHERE id=? AND project_id=?",
        (json.dumps(changes, ensure_ascii=False), (action["expected_outcome"] or expected_outcome_for_changes(changes, action["action_type"])), now(), action_id, project_id)
    )
    save_action_revision(conn, project_id, action_id, "user", changes)
    add_activity(conn, project_id, "action", "Návrh úkolu upraven uživatelem", f"Úkol #{action_id}; finální verze čeká na publikaci.")
    conn.commit(); conn.close()
    flash("Uložil jsem tvoji finální verzi. Na webu se zatím nic nezměnilo.", "success")
    return redirect(url_for("actions", project_id=project_id, view="todo"))


@app.route("/projects/<int:project_id>/actions/<int:action_id>/apply", methods=["POST"])
@login_required
def action_apply(project_id, action_id):
    p = project_for_user(project_id)
    conn = db()
    action = conn.execute("SELECT * FROM actions WHERE id=? AND project_id=?", (action_id, project_id)).fetchone()
    conn.close()
    if not action:
        abort(404)
    if action["status"] not in {"draft", "approved", "failed", "pending", "queued"}:
        flash("Tento úkol už je hotový nebo právě běží.", "info")
        return redirect(url_for("actions", project_id=project_id, view="todo"))
    ready, reason = action_provider_ready(p, action)
    if not ready:
        flash(reason, "error")
        return redirect(url_for("connectors", project_id=project_id))
    queued = queue_seo_apply_jobs(project_id, [action_id])
    provider = str(action["provider"] or "fresh_core") if "provider" in action.keys() else "fresh_core"
    flash(f"Úkol byl zařazen do fronty pro {provider}. Zápis na web zatím není potvrzený; sleduj stav workeru a výsledek úlohy.", "info")
    return redirect(url_for("actions", project_id=project_id, view="todo"))


@app.route("/projects/<int:project_id>/actions/<int:action_id>/verify", methods=["POST"])
@login_required
def action_verify(project_id, action_id):
    p = project_for_user(project_id)
    conn = db()
    action = conn.execute("SELECT * FROM actions WHERE id=? AND project_id=?", (action_id, project_id)).fetchone()
    conn.close()
    if not action:
        abort(404)
    try:
        result = json.loads(action["result_json"] or "{}")
    except Exception:
        result = {}
    verification = verify_action(p, action, result)
    verified = save_action_verification(project_id, action_id, verification)
    flash(
        "Ověřeno: cílová služba potvrzuje provedenou změnu." if verified else "Změnu jsem provedl, ale cílová služba ji zatím nepotvrdila.",
        "success" if verified else "info"
    )
    return redirect(url_for("actions", project_id=project_id, view="done"))



@app.route("/api/notifications")
@login_required
def api_notifications():
    project_id = request.args.get("project_id", type=int)
    conn = db()
    visible = "dismissed_at IS NULL AND (snoozed_until IS NULL OR snoozed_until<=?)"
    if project_id:
        rows = conn.execute(
            f"SELECT * FROM notifications WHERE user_id=? AND project_id=? AND {visible} ORDER BY id DESC LIMIT 30",
            (current_user.id, project_id, now())
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM notifications WHERE user_id=? AND {visible} ORDER BY id DESC LIMIT 30",
            (current_user.id, now())
        ).fetchall()
    unread = conn.execute(
        f"SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0 AND {visible}",
        (current_user.id, now())
    ).fetchone()["c"]
    conn.close()
    items = [dict(r) for r in rows]
    q = queue_summary(project_id) if project_id else None
    return jsonify({"ok": True, "unread": int(unread), "items": items, "worker": worker_state(), "queue": q})


@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_notifications_read():
    payload = request.get_json(silent=True) or {}
    nid = payload.get("id")
    conn = db()
    if nid and str(nid).isdigit():
        conn.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (int(nid), current_user.id))
    else:
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND dismissed_at IS NULL", (current_user.id,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/notifications/state", methods=["POST"])
@login_required
def api_notifications_state():
    payload = request.get_json(silent=True) or {}
    nid = payload.get("id")
    action = str(payload.get("action") or "").strip()
    if not nid or not str(nid).isdigit():
        return jsonify({"ok": False, "error": "missing id"}), 400
    conn = db()
    if action == "dismiss":
        conn.execute("UPDATE notifications SET dismissed_at=?,is_read=1 WHERE id=? AND user_id=?", (now(), int(nid), current_user.id))
    elif action == "snooze":
        until = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
        conn.execute("UPDATE notifications SET snoozed_until=?,is_read=1 WHERE id=? AND user_id=?", (until, int(nid), current_user.id))
    else:
        conn.close(); return jsonify({"ok": False, "error": "unknown action"}), 400
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/projects/<int:project_id>/actions/process-now", methods=["POST"])
@login_required
def actions_process_now(project_id):
    project_for_user(project_id)
    kicked = kick_background_worker("work-queue")
    if kicked:
        flash("Spustil jsem zpracování fronty. Stránku můžeš klidně opustit; o výsledku tě upozorním.", "success")
    else:
        flash("Nepodařilo se spustit worker přímo z aplikace. Fronta zůstává bezpečně uložená a čeká na serverový cron.", "error")
    return redirect(url_for("actions", project_id=project_id, view="todo"))


# Merchant connector: separate OAuth scope, same Google client and existing integration table.
def merchant_check_csrf():
    expected=session.get('merchant_csrf_token') or ''
    provided=request.form.get('merchant_csrf_token') or ''
    if not expected or not hmac.compare_digest(str(expected),str(provided)):
        abort(403)

def merchant_api(project_id):
    row=integration_row(project_id,"merchant_center")
    if not row or row['status'] == 'disconnected':raise ValueError('Nejdříve připoj Google Merchant účet.')
    creds=integration_secret(project_id,"merchant_center")
    if MERCHANT_SCOPE not in str(creds.get('scope') or '').split():
        raise ValueError('Chybí oprávnění Merchant Center; obnov Google připojení.')
    def call(method,url,payload=None):
        if not url.startswith('https://merchantapi.googleapis.com/'):
            raise ValueError('Merchant API musí používat oficiální doménu Google.')
        token=google_refresh_access(project_id,"merchant_center")
        return google_api_request(method,url,token,payload)
    return call


def merchant_config_save(project_id,config,status='connected'):
    conn=db()
    upsert_integration(conn,project_id,'merchant_center','ecommerce',status,config,now())
    conn.commit();conn.close()


def merchant_feed_address(project_id):
    conn=db(); feed=conn.execute('SELECT feed_token,generated_at,exported_count FROM project_google_feeds WHERE project_id=?',(project_id,)).fetchone();conn.close()
    if not feed or not feed['generated_at'] or not int(feed['exported_count'] or 0):
        raise ValueError('Nejprve dokonči import, schval sortiment a publikuj Google XML v E-commerce.')
    conn=db()
    try: state=feed_workflow.state(conn,project_id)
    finally:conn.close()
    if not state.get('approved') or state.get('revision') != state.get('published_revision'):
        raise ValueError('Výběr sortimentu se změnil. Před připojením znovu schval a publikuj aktuální XML.')
    return url_for('catalog_google_public',token=feed['feed_token'],_external=True)


@app.route('/projects/<int:project_id>/merchant/account',methods=['POST'])
@login_required
def merchant_choose_account(project_id):
    project_for_user(project_id)
    merchant_check_csrf()
    row=integration_row(project_id,'merchant_center')
    cfg=integration_config(row)
    selection=merchant_connector.account_name(request.form.get('account'))
    if selection not in [x.get('name') for x in cfg.get('available_accounts',[])]:abort(400)
    cfg.update(selected_account=selection,data_source=cfg.get('data_source','') if selection==cfg.get('selected_account') else '',last_error='',report=None,upload=None,aggregate=None)
    merchant_config_save(project_id,cfg)
    flash('Merchant účet vybrán; produkty zatím nebyly odeslány.','success')
    return redirect(url_for('connectors',project_id=project_id)+'#merchant-center')


@app.route('/projects/<int:project_id>/merchant/publish',methods=['POST'])
@login_required
def merchant_publish_feed(project_id):
    p=project_for_user(project_id)
    merchant_check_csrf()
    cfg=integration_config(integration_row(project_id,'merchant_center'))
    # All preconditions MUST run inside the handler: a newly connected project
    # may have a Merchant account but no approved/published XML yet.
    try:
        account=merchant_connector.account_name(cfg.get('selected_account'))
        feed_url=merchant_feed_address(project_id)
        # Never silently duplicate a source; reuse an existing file-fetch source with matching URL.
        api=merchant_api(project_id)
        sources=merchant_connector.list_sources(api,account)
        found=merchant_connector.find_existing_source(sources,feed_url)
        if not found:
            found=merchant_connector.create_source(api,account,feed_url,p['name']+' – WebBooster feed')
        source_name=merchant_connector.source_name(found['name'],account)
        # The source may already exist; don't schedule a second first-fetch implicitly.
        same_source=cfg.get('data_source')==source_name
        cfg.update(data_source=source_name,
                   data_source_url=feed_url,last_error='',connected_at=now())
        if not same_source:
            cfg.pop('fetch_requested_at',None)
            cfg.pop('upload_error',None)
            cfg.pop('upload',None)
        merchant_config_save(project_id,cfg)
        flash('Datový zdroj je připojený. Pro první import klikni na „Spustit načtení XML“; další načítání proběhne dle plánu.','success')
    except (ValueError,requests.RequestException,KeyError) as exc:
        flash('Merchant – připojení XML: '+str(exc)[:240],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#merchant-platform')


def merchant_published_feed_fingerprint(project_id):
    """Digest of *published* feed bytes, without refreshing WooCommerce/catalog data."""
    conn=db()
    try:
        rec=conn.execute('SELECT feed_token,generated_at FROM project_google_feeds WHERE project_id=?',(project_id,)).fetchone()
    finally:conn.close()
    if not rec:raise ValueError('Nejprve publikuj Google XML v E-commerce.')
    path=CATALOG_FEED_DIR / ('google_'+str(project_id)+'_'+rec['feed_token']+'.xml')
    if not path.is_file():raise ValueError('Publikovaný XML soubor nebyl nalezen.')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest(),str(rec['generated_at'] or '')


@app.route('/projects/<int:project_id>/merchant/fetch',methods=['POST'])
@login_required
def merchant_fetch_now(project_id):
    project_for_user(project_id)
    merchant_check_csrf()
    cfg=integration_config(integration_row(project_id,'merchant_center'))
    try:
        account=merchant_connector.account_name(cfg.get('selected_account'))
        source=merchant_connector.source_name(cfg.get('data_source'),account)
        # Do not fetch a stale or unapproved catalog; source must match the current approved feed.
        approved_url=merchant_feed_address(project_id)
        if cfg.get('data_source_url') != approved_url:
            raise ValueError('Adresa XML se změnila. Nejprve znovu připoj schválený feed.')
        digest,published_at=merchant_published_feed_fingerprint(project_id)
        last=cfg.get('fetch_requested_at')
        if last:
            try:
                elapsed=(datetime.now()-datetime.fromisoformat(last)).total_seconds()
            except (TypeError, ValueError):
                elapsed=0
            previous_digest=cfg.get('fetch_feed_sha256')
            # Compatibility for imports triggered before fingerprint tracking existed.
            content_changed=(previous_digest != digest if previous_digest else
                             bool(published_at and published_at > str(last)))
            # Never interrupt an import that Google explicitly reports as in progress.
            state=(cfg.get('upload') or {}).get('processingState')
            if state=='IN_PROGRESS':
                raise ValueError('Google ještě zpracovává předchozí načtení. Nejprve obnov stav Google.')
            if elapsed < 20*3600 and not content_changed:
                raise ValueError('Google už dostal tento XML obsah. Pro další ruční načtení nejprve publikuj opravený XML feed v E-commerce; nezměněné XML má ochrannou lhůtu 20 hodin.')
            if content_changed and state not in ('SUCCEEDED','FAILED','PROCESSING_STATE_UNSPECIFIED',None):
                raise ValueError('Předchozí stav importu není dokončený. Ověř stav Google.')
            # After any request, do not hammer Google immediately even with new content.
            if content_changed and elapsed < 60:
                raise ValueError('Poslední načtení bylo vyžádáno před méně než minutou.')
        merchant_connector.fetch_source(merchant_api(project_id),source,account)
        cfg['fetch_requested_at']=now()
        cfg['fetch_feed_sha256']=digest
        cfg['fetch_feed_published_at']=published_at
        cfg['upload']=None
        cfg['upload_error']='Google převzal požadavek na načtení. Zpracování běží asynchronně; stav ověř později.'
        cfg['last_error']=''
        merchant_config_save(project_id,cfg)
        flash('Google přijal požadavek na načtení XML. Import může trvat delší dobu; stav ověř tlačítkem „Načíst stav Google“.','success')
    except (ValueError,requests.RequestException) as exc:
        flash('Spuštění načtení Merchant XML: '+str(exc)[:240],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#merchant-platform')


@app.route('/projects/<int:project_id>/merchant/check',methods=['POST'])
@login_required
def merchant_check(project_id):
    project_for_user(project_id)
    merchant_check_csrf()
    cfg=integration_config(integration_row(project_id,'merchant_center'))
    try:
        api=merchant_api(project_id)
        account=merchant_connector.account_name(cfg.get('selected_account'))
        source=cfg.get('data_source')
        if source:
            try:
                cfg['upload']=merchant_connector.file_status(api,source,account)
                cfg.pop('upload_error',None)
            except ValueError as exc:
                message=str(exc)
                if 'HTTP 404' in message and 'File upload not found' in message:
                    cfg['upload']=None
                    cfg['upload_error']=('Google zatím nezpracoval první XML. Požadavek na načtení byl odeslán; zkontroluj stav později.'
                        if cfg.get('fetch_requested_at') else
                        'Google zatím nemá žádný záznam o načtení. Klikni na „Spustit načtení XML“.')
                else:
                    cfg['upload_error']=message[:240]
        cfg['aggregate']=merchant_connector.aggregate_status(api,account)
        cfg['checked_at']=now();cfg['last_error']=''
        merchant_config_save(project_id,cfg)
        flash('Merchant diagnostika aktualizována.','success')
    except (ValueError,requests.RequestException) as exc:
        flash('Merchant diagnostika: '+str(exc)[:240],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#merchant-platform')


@app.route('/projects/<int:project_id>/merchant/performance',methods=['POST'])
@login_required
def merchant_performance(project_id):
    project_for_user(project_id)
    merchant_check_csrf()
    cfg=integration_config(integration_row(project_id,'merchant_center'))
    try:
        api=merchant_api(project_id)
        account=merchant_connector.account_name(cfg.get('selected_account'))
        cfg['report']=merchant_connector.performance(api,account)
        cfg['report_checked_at']=now()
        merchant_config_save(project_id,cfg)
        flash('Přehled neplacených produktových záznamů aktualizován.','success')
    except (ValueError,requests.RequestException) as exc:
        flash('Merchant report: '+str(exc)[:240],'error')
    return redirect(url_for('ecommerce',project_id=project_id)+'#merchant-platform')


@app.route("/connectors/google/start/<int:project_id>")
@login_required
def google_start(project_id):
    project_for_user(project_id)
    if not google_oauth_ready():
        flash("Nejdřív doplň GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET a GOOGLE_REDIRECT_URI do .env.", "info")
        return redirect(url_for("connectors", project_id=project_id))
    service = request.args.get("service", "google_stack").strip()
    if service not in GOOGLE_SERVICE_SCOPES: service = "google_stack"
    state = secrets.token_urlsafe(32)
    session["google_oauth"] = {"state":state,"project_id":project_id,"service":service,"created_at":time.time()}
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"), "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI"),
        "response_type":"code", "scope":" ".join(google_scopes_for(service)), "access_type":"offline",
        "prompt":"consent", "include_granted_scopes":"true", "state":state,
    }
    return redirect(GOOGLE_AUTH_URL + "?" + urlencode(params))


@app.route("/connectors/google/callback")
@login_required
def google_callback():
    if session.get('merchant_registration_oauth'):
        return _admin_merchant_registration_callback(request.args.get('state',''))
    pending=session.pop("google_oauth",None) or {}; state=request.args.get("state","")
    if not pending or not hmac.compare_digest(str(pending.get("state") or ""),state):
        flash("Google OAuth stav nesouhlasí. Zkus připojení znovu.","error"); return redirect(url_for("dashboard"))
    if time.time()-float(pending.get("created_at") or 0)>900:
        flash("Google OAuth požadavek vypršel. Zkus připojení znovu.","error"); return redirect(url_for("dashboard"))
    project_id=int(pending.get("project_id") or 0); project_for_user(project_id); service=str(pending.get("service") or "google_stack")
    if request.args.get("error"):
        flash(f"Google připojení nebylo dokončeno: {request.args.get('error')}","error"); return redirect(url_for("connectors",project_id=project_id))
    try:
        creds=google_exchange_code(project_id,request.args.get("code",""),service); results=[]
        if service in {"search_console","google_stack"}:
            try: connect_search_console_with_creds(project_id,creds); results.append("Search Console")
            except Exception as exc: results.append(f"Search Console: {exc}")
        if service in {"ga4","google_stack"}:
            try: connect_ga4_with_creds(project_id,creds); results.append("GA4")
            except Exception as exc: results.append(f"GA4: {exc}")
        if service in {"gtm","google_stack"}:
            try: connect_gtm_with_creds(project_id,creds); results.append("GTM read-only")
            except Exception as exc: results.append(f"GTM: {exc}")
        if service == "merchant_center":
            update_integration_secret(project_id,"merchant_center",creds,creds.get('scope',''))
            try:
                accounts=merchant_connector.list_accounts(lambda m,u,p=None: google_api_request(m,u,creds['access_token'],p))
            except (ValueError, requests.RequestException) as merchant_error:
                previous=integration_config(integration_row(project_id,"merchant_center"))
                previous.update({'last_error':str(merchant_error)[:350]})
                conn=db()
                upsert_integration(conn,project_id,'merchant_center','ecommerce','needs_registration',previous,now())
                conn.commit();conn.close()
                flash('Google OAuth bylo uloženo. Merchant API zatím odmítá načtení účtů; dokonči systémovou registraci v superadmin konzoli.', 'warning')
                return redirect(url_for('connectors',project_id=project_id)+'#merchant-center')
            previous=integration_config(integration_row(project_id,"merchant_center"))
            previous_account=previous.get('selected_account')
            selected=previous_account if previous_account in [a.get('name') for a in accounts] else ''
            config={**previous,"available_accounts":accounts,"selected_account":selected,
                    "data_source":previous.get('data_source','') if selected else '',"last_error":""}
            conn=db()
            upsert_integration(conn,project_id,"merchant_center","ecommerce","needs_selection" if accounts else "no_account",config,now())
            conn.commit();conn.close()
            update_integration_secret(project_id,"merchant_center",creds,creds.get('scope',''))
            results.append(f"Merchant Center: nalezeno {len(accounts)} účtů, vyber účet")
        flash("Google připojení dokončeno: " + "; ".join(results),"success")
    except Exception as exc:
        flash(f"Google služby se nepodařilo připojit: {exc}","error")
    return redirect(url_for("connectors",project_id=project_id))


@app.route("/projects/<int:project_id>/performance/sync", methods=["POST"])
@login_required
def performance_sync(project_id):
    project_for_user(project_id)
    try:
        data = sync_pagespeed_crux(project_id)
        mobile = data.get("mobile") or {}; crux = data.get("crux") or {}
        msg = f"Výkon načten: mobile Lighthouse {mobile.get('performance_score') if mobile.get('performance_score') is not None else '—'}/100."
        if crux.get("available"):
            msg += f" CrUX p75: LCP {int(crux.get('lcp_ms') or 0)} ms, INP {int(crux.get('inp_ms') or 0)} ms, CLS {float(crux.get('cls') or 0):.3f}."
        flash(msg, "success")
    except Exception as exc:
        flash(f"PageSpeed/CrUX synchronizace selhala: {exc}", "error")
    return redirect(request.referrer or url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/gtm/container", methods=["POST"])
@login_required
def gtm_container(project_id):
    project_for_user(project_id); path = request.form.get("container", "").strip()
    row = integration_row(project_id, "gtm"); config = integration_config(row)
    allowed = {str(x.get("path") or "") for x in config.get("available_containers") or []}
    if path not in allowed:
        flash("Vybraný GTM kontejner není v připojeném účtu.", "error")
        return redirect(url_for("connectors", project_id=project_id))
    config["selected_container"] = path
    conn=db(); upsert_integration(conn, project_id, "gtm", "analytics", "connected", config, now()); conn.commit(); conn.close()
    flash("GTM kontejner uložen. Boban ho bude zatím pouze číst a auditovat.", "success")
    return redirect(url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/gtm/sync", methods=["POST"])
@login_required
def gtm_sync(project_id):
    project_for_user(project_id)
    try:
        data=sync_gtm(project_id); counts=data.get("counts") or {}
        flash(f"GTM audit hotový: {counts.get('tags',0)} tagů, {counts.get('triggers',0)} triggerů, {counts.get('variables',0)} proměnných.", "success")
    except Exception as exc:
        flash(f"GTM audit selhal: {exc}", "error")
    return redirect(request.referrer or url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/search-console/property", methods=["POST"])
@login_required
def search_console_property(project_id):
    project = project_for_user(project_id)
    prop = request.form.get("property", "").strip()
    row = integration_row(project_id, "search_console")
    config = integration_config(row)
    allowed = {str(x.get("siteUrl") or "") for x in config.get("available_properties") or []}
    if prop not in allowed:
        flash("Vybraná Search Console property není v připojeném účtu.", "error")
        return redirect(url_for("connectors", project_id=project_id))
    config["selected_property"] = prop
    config["selected_permission"] = search_console_property_permission(config.get("available_properties") or [], prop)
    config["domain_verified"] = search_console_domain_verified(project["site_url"], prop)
    config["write_enabled"] = search_console_can_write(
        config.get("available_properties") or [], prop,
        integration_secret(project_id, "search_console").get("scope")
    )
    conn = db()
    upsert_integration(conn, project_id, "search_console", "seo", "connected", config, now())
    conn.commit(); conn.close()
    if config["domain_verified"]:
        flash(f"Search Console property ověřena pro tento web: {prop}", "success")
    else:
        flash(f"Property je připojená, ale doména neodpovídá projektu: {prop}", "error")
    return redirect(url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/search-console/sync", methods=["POST"])
@login_required
def search_console_sync(project_id):
    project_for_user(project_id)
    try:
        data=sync_search_console(project_id); cur=data.get("current") or {}; flash(f"Search Console načtena: {int(cur.get('clicks') or 0)} kliknutí, {int(cur.get('impressions') or 0)} impresí a {len(data.get('top_queries') or [])} dotazů.","success")
    except Exception as exc: flash(f"Synchronizace Search Console selhala: {exc}","error")
    return redirect(request.referrer or url_for("search_performance",project_id=project_id))


@app.route("/projects/<int:project_id>/search-console/sitemap/prepare", methods=["POST"])
@login_required
def search_console_sitemap_prepare(project_id):
    project_for_user(project_id); sitemap=request.form.get("sitemap_url","").strip(); operation=request.form.get("operation","submit_sitemap").strip()
    if operation not in {"submit_sitemap","delete_sitemap"}: operation="submit_sitemap"
    if not sitemap.startswith(("https://","http://")): flash("Zadej platnou URL sitemap.","error"); return redirect(request.referrer or url_for("search_performance",project_id=project_id))
    action_id=create_connector_action(project_id,"search_console",operation,{"sitemap_url":sitemap},"Boban připravil změnu sitemap v Google Search Console.","Po schválení změnu odešlu přes Search Console API a následně ověřím, že Google eviduje požadovaný stav sitemap.",target_url=sitemap)
    flash(f"Připravil jsem úkol #{action_id}. Nic jsem zatím do Search Console nezapsal.","success"); return redirect(url_for("actions",project_id=project_id,view="todo"))


@app.route("/projects/<int:project_id>/search-console/inspect", methods=["POST"])
@login_required
def search_console_inspect(project_id):
    p=project_for_user(project_id); url=request.form.get("inspection_url","").strip() or p["site_url"]
    try:
        data=inspect_search_console_url(project_id,url); result=(data.get("inspectionResult") or {}).get("indexStatusResult") or {}; verdict=result.get("verdict") or "UNKNOWN"; coverage=result.get("coverageState") or ""; last=result.get("lastCrawlTime") or ""; flash(f"Google index: {verdict}. {coverage}" + (f" Poslední crawl: {last}." if last else ""),"success" if verdict=="PASS" else "info")
    except Exception as exc: flash(f"URL Inspection selhala: {exc}","error")
    return redirect(request.referrer or url_for("search_performance",project_id=project_id))


@app.route("/projects/<int:project_id>/ga4/property", methods=["POST"])
@login_required
def ga4_property(project_id):
    project = project_for_user(project_id)
    prop = request.form.get("property", "").strip()
    row = integration_row(project_id, "ga4")
    config = integration_config(row)
    allowed = {str(x.get("property") or "") for x in config.get("available_properties") or []}
    if prop not in allowed:
        flash("Vybraná GA4 property není v připojeném účtu.", "error")
        return redirect(url_for("connectors", project_id=project_id))

    selected_row = next(
        (x for x in config.get("available_properties") or [] if str(x.get("property") or "") == prop), {}
    )
    try:
        token = google_refresh_access(project_id, "ga4")
        checked = ga4_selected_config(token, selected_row or {"property": prop}, project["site_url"])
    except Exception as exc:
        checked = dict(selected_row or {})
        checked.update({"domainVerified": False, "verifiedUri": "", "measurementIds": [], "streamHosts": []})
        flash(f"Property jsem uložil, ale web stream se nepodařilo ověřit: {exc}", "info")

    config["selected_property"] = prop
    config["selected_can_edit"] = bool(selected_row.get("canEdit"))
    config["selected_domain_verified"] = bool(checked.get("domainVerified"))
    config["selected_verified_uri"] = checked.get("verifiedUri") or ""
    config["selected_measurement_ids"] = checked.get("measurementIds") or []
    config["selected_stream_hosts"] = checked.get("streamHosts") or []
    config["write_enabled"] = (
        GA4_EDIT_SCOPE in str(integration_secret(project_id, "ga4").get("scope") or "").split()
        and bool(selected_row.get("canEdit"))
        and bool(config["selected_domain_verified"])
    )
    # Persist the enriched version in the dropdown too.
    enriched = []
    for x in config.get("available_properties") or []:
        if str(x.get("property") or "") == prop:
            y = dict(x)
            y.update({
                "domainVerified": config["selected_domain_verified"],
                "verifiedUri": config["selected_verified_uri"],
                "measurementIds": config["selected_measurement_ids"],
                "streamHosts": config["selected_stream_hosts"],
                "streamChecked": True,
            })
            enriched.append(y)
        else:
            enriched.append(x)
    config["available_properties"] = enriched

    conn = db()
    upsert_integration(conn, project_id, "ga4", "analytics", "connected", config, now())
    conn.commit(); conn.close()
    if config["selected_domain_verified"]:
        flash(f"GA4 property ověřena podle web streamu: {config['selected_verified_uri']}", "success")
    else:
        hosts = ", ".join(config["selected_stream_hosts"][:4]) if config["selected_stream_hosts"] else "žádný web stream"
        flash(f"Pozor: vybraná GA4 property neobsahuje web stream pro {normalize_host(project['site_url'])}. Vidím: {hosts}.", "error")
    return redirect(url_for("connectors", project_id=project_id))


@app.route("/projects/<int:project_id>/ga4/sync", methods=["POST"])
@login_required
def ga4_sync(project_id):
    project_for_user(project_id)
    try:
        data=sync_ga4(project_id); cur=data.get("current") or {}; flash(f"GA4 načtena: Organic Search {int(cur.get('sessions') or 0)} návštěv, {float(cur.get('keyEvents') or 0):.0f} klíčových událostí.","success")
    except Exception as exc: flash(f"Synchronizace GA4 selhala: {exc}","error")
    return redirect(request.referrer or url_for("search_performance",project_id=project_id))


@app.route("/projects/<int:project_id>/ga4/key-event/prepare", methods=["POST"])
@login_required
def ga4_key_event_prepare(project_id):
    project_for_user(project_id); event_name=request.form.get("event_name","").strip(); counting=request.form.get("counting_method","ONCE_PER_EVENT").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}",event_name): flash("Event name musí začínat písmenem a používat jen písmena, číslice a podtržítko.","error"); return redirect(request.referrer or url_for("search_performance",project_id=project_id))
    if counting not in {"ONCE_PER_EVENT","ONCE_PER_SESSION"}: counting="ONCE_PER_EVENT"
    action_id=create_connector_action(project_id,"ga4","create_key_event",{"event_name":event_name,"counting_method":counting},"Boban připravil vytvoření klíčové události v Google Analytics 4.","Po schválení vytvořím GA4 Key Event přes Admin API a ověřím, že je v property skutečně evidovaný.")
    flash(f"Připravil jsem GA4 úkol #{action_id}. Změna čeká na tvoje schválení.","success"); return redirect(url_for("actions",project_id=project_id,view="todo"))


@app.route("/api/fresh-core/<int:project_id>/snapshot", methods=["POST"])
def legacy_fresh_core_snapshot(project_id):
    # Compatibility endpoint from 0.1.x. New integrations should use Connector Manifest URL.
    secret = request.headers.get("X-Fresh-Core-Secret", "")
    expected = os.getenv("FRESH_CORE_SHARED_SECRET", "")
    if not expected or not hmac.compare_digest(secret, expected):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    conn = db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        conn.close()
        return jsonify({"ok": False, "error": "project_not_found"}), 404

    conn.execute(
        "INSERT INTO snapshots(project_id,payload,created_at) VALUES(?,?,?)",
        (project_id, json.dumps(payload, ensure_ascii=False), now())
    )
    add_activity(conn, project_id, "legacy", "Legacy Fresh Core snapshot přijat",
                 "Pro nové projekty používej statický Manifest URL.")
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deprecated": True})


def _safe_diagnostic_url_token():
    """Stable unguessable read-only link. Override secret to revoke shared URLs."""
    secret=(os.getenv('DIAGNOSTIC_MANIFEST_SECRET') or os.getenv('SECRET_KEY') or '').strip()
    if len(secret)<32 or secret=='dev-change-me':return None
    return hmac.new(secret.encode('utf-8'),b'webbooster-safe-diagnostic-v1',hashlib.sha256).hexdigest()


def _safe_diagnostic_manifest():
    """Allowlisted operational facts only: never project URLs, source, credentials, or user data."""
    result={'schema':'fresh-webbooster-diagnostics/1','application_version':APP_VERSION,
            'generated_at':now(),'database_backend':DB_BACKEND,
            'safety':{'source_code_included':False,'secrets_included':False,
                      'emails_included':False,'product_payloads_included':False},
            'catalog_settings':{'page_size':COMMERCE_PAGE_SIZE,'batch_pages':COMMERCE_BATCH_PAGES,
                                'budget_seconds':COMMERCE_BATCH_SECONDS,'http_timeout_seconds':HTTP_TIMEOUT},
            'checks':{},'catalogs':[]}
    conn=db()
    try:
        conn.execute('SELECT 1 AS ok').fetchone();result['checks']['database']='ok'
        # Cron heartbeat is observable; a configured rule does not prove a scheduler runs.
        try:
            worker=worker_state()
            result['scheduler']={'worker_status':str(worker.get('status') or 'unknown')[:40],
                                 'last_seen':str(worker.get('last_seen') or '')[:40],
                                 'catalog_tick_requires':'manage.py catalog-sync (cron každou minutu)', 'catalog_worker':worker_state('catalog'),
                                 'seo_queue_worker':worker_state('seo_queue'),
                                 'seo_queue_requires':'manage.py work-queue (cron každou minutu; flock)'}
        except Exception as exc:result['scheduler']={'status':'unavailable','error_type':type(exc).__name__}
        try:
            rows=conn.execute("SELECT status, COUNT(*) AS n FROM jobs WHERE job_type IN ('seo_ai_prepare','seo_growth_prepare','seo_apply_action','seo_verify_action') GROUP BY status").fetchall()
            result['scheduler']['seo_queue_counts']={str(r['status']):int(r['n']) for r in rows}
        except Exception:
            result['scheduler']['seo_queue_counts_unavailable']=True
        projects=conn.execute('SELECT id FROM projects ORDER BY id LIMIT 100').fetchall()
        for project in projects:
            pid=int(project['id'])
            item={'project_id':pid}
            try:
                workflow=feed_workflow.state(conn,pid)
                item['workflow']={k:workflow.get(k) for k in ('mode','approved','revision','published_revision','interval_minutes','updated_at')}
                item['workflow']['error_present']=bool(workflow.get('last_error'))
                # Only known failure categories; arbitrary exception messages may contain URLs/secrets.
                if workflow.get('last_error'):
                    msg=str(workflow['last_error']).lower()
                    item['workflow']['error_kind']=('authorization' if any(x in msg for x in ('401','403','klíč','oprávněn')) else
                        'timeout' if any(x in msg for x in ('timeout','časový limit','timed out')) else
                        'remote_response' if any(x in msg for x in ('http ','json','formát')) else 'other')
                for table,key in [('project_core_sync','products'),('project_core_variant_sync','variants')]:
                    row=conn.execute('SELECT * FROM '+table+' WHERE project_id=?',(pid,)).fetchone()
                    item[key]=({k:row[k] for k in ('next_page','total','synced_count','finished_at') if k in row.keys()} if row else None)
                    if row:item[key]['error_present']=bool(row['last_error'])
                for table,key in [('project_core_products','cached_products'),('project_core_variants','cached_variants')]:
                    item[key]=int(conn.execute('SELECT COUNT(*) AS n FROM '+table+' WHERE project_id=?',(pid,)).fetchone()['n'])
                rec=conn.execute('SELECT generated_at,exported_count,omitted_count FROM project_google_feeds WHERE project_id=?',(pid,)).fetchone()
                item['google_feed']=dict(rec) if rec else None
                excount=conn.execute('SELECT kind, COUNT(*) AS n FROM catalog_exclusions WHERE project_id=? GROUP BY kind',(pid,)).fetchall()
                item['exclusions']={str(r['kind']):int(r['n']) for r in excount}
                item['core_read_configured']=bool(conn.execute('SELECT 1 FROM project_core_read WHERE project_id=?',(pid,)).fetchone())
            except Exception as exc:item['diagnostic_error_type']=type(exc).__name__
            result['catalogs'].append(item)
    except Exception as exc:result['checks']['database']='failed';result['checks']['error_type']=type(exc).__name__
    finally:conn.close()
    return result


@app.route('/diagnostics/<token>/manifest.json')
def safe_diagnostic_manifest(token):
    expected=_safe_diagnostic_url_token()
    if not expected or not hmac.compare_digest(token,expected):abort(404)
    response=jsonify(_safe_diagnostic_manifest())
    response.headers['Cache-Control']='no-store, private, max-age=0'
    response.headers['X-Robots-Tag']='noindex, nofollow, noarchive'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'none'; frame-ancestors 'none'"
    return response


@app.route("/developer/<token>/manifest.json")
def developer_manifest(token):
    # Full source inventory is never shareable by bearer token alone.
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):abort(404)
    expected = os.getenv("DEVELOPER_MANIFEST_TOKEN", "").strip()
    if len(expected) < 24 or not hmac.compare_digest(token, expected):
        abort(404)
    response = jsonify(_developer_manifest())
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Disposition"] = 'inline; filename="webbooster-manifest.json"'
    return response


@app.route("/health")
def health():
    db_ok = False
    db_error = None
    try:
        conn = db()
        conn.execute("SELECT 1 AS ok").fetchone()
        conn.close()
        db_ok = True
    except Exception as exc:
        db_error = str(exc)[:300]
    try:
        wstate = worker_state()
    except Exception as exc:
        wstate = {"status": "error", "healthy": False, "error": str(exc)[:300]}
    return jsonify({
        "ok": bool(db_ok),
        "service": "webbooster",
        "version": APP_VERSION,
        "fresh_core_mode": "manifest-pull",
        "channels": {"seo": "active", "ppc": "planned"},
        "search_console": "oauth+performance+write actions",
        "ga4": "oauth+site and organic analytics+key event write actions",
        "pagespeed_crux": "lighthouse+field CWV",
        "gtm": "read-only measurement audit",
        "boban_operator": "business-goal prioritization + proactive proposal preparation",
        "ai_bulk_fixes": True,
        "database_backend": DB_BACKEND,
        "database_ok": db_ok,
        "database_error": db_error,
        "worker": wstate,
        "background_sync": "durable DB queue + detached worker + manage.py tick safety net"
    }), (200 if db_ok else 503)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
