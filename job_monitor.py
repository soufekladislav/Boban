"""Readable, read-only task ledger for Boban users and administrators.

Uses existing jobs/actions/issues; never exposes raw payloads, model prompts,
credentials or target write secrets. No schema changes or API writes.
"""
import json
import re
from datetime import datetime, timedelta

ACTIVE = {"queued", "running", "retry"}
STATUSES = {"queued", "running", "retry", "failed", "completed", "canceled", "cancelled"}
SEVERITY = {
    "queued": "Čeká", "running": "Právě probíhá",
    "retry": "Budu opakovat", "failed": "Chyba",
    "completed": "Technicky dokončeno", "canceled": "Zrušeno",
    "cancelled": "Zrušeno",
}
JOB_TYPES = {
    "seo_apply_action": "Publikování schválené změny",
    "seo_verify_action": "Ověření publikované změny",
    "seo_ai_prepare": "Příprava SEO návrhů",
    "seo_growth_prepare": "Analýza růstové příležitosti",
    "catalog_sync": "Synchronizace katalogu",
}


def clean_text(value, length=160):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:length - 1] + "…" if len(text) > length else text


def _parse(payload):
    if not payload:
        return {}
    try:
        result = json.loads(payload)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def title_for(row, issue_titles=None):
    """Name the actual work, not 'job #123'; never invent a site or issue title."""
    typ = str(row.get("job_type") or "")
    issue = clean_text(row.get("issue_title"), 125)
    if issue:
        return issue
    parsed = _parse(row.get("payload_json"))
    issue_ids = parsed.get("issue_ids") or []
    if isinstance(issue_ids, list) and issue_titles and row.get("project_id") is not None:
        titles = [clean_text(issue_titles.get((int(row["project_id"]), int(v))), 95)
                  for v in issue_ids[:4] if str(v).isdigit()]
        titles = [v for v in titles if v]
        if titles:
            suffix = " (+" + str(len(issue_ids) - 1) + " dalších)" if len(issue_ids) > 1 else ""
            return "Připravuji: " + titles[0] + suffix
    candidates = parsed.get("candidates") or []
    if typ == "seo_growth_prepare" and isinstance(candidates, list) and candidates:
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        query = clean_text(first.get("query") or first.get("primary_page"), 100)
        if query:
            return "Růstová příležitost: " + query
    proposed = _parse(row.get("proposed_json"))
    label = clean_text(proposed.get("title") or proposed.get("alt") or proposed.get("event_name"), 110)
    if label:
        return label
    reason = clean_text(row.get("action_reason"), 125)
    if reason:
        return reason
    action_type = str(row.get("action_type") or "")
    friendly = {
        "update_seo_metadata": "Úprava SEO metadat",
        "update_image_alt": "Úprava ALT obrázku",
        "create_key_event": "Nastavení konverzní události GA4",
        "submit_sitemap": "Odeslání sitemap",
    }.get(action_type)
    return friendly or JOB_TYPES.get(typ, "Úloha " + clean_text(typ or "bez typu", 65))


def load_jobs(conn, project_id=None, status=None, limit=60):
    """Bounded ledger, accessible per project or to admins across projects."""
    limit = max(1, min(int(limit), 150))
    terms = []
    params = []
    if project_id is not None:
        terms.append("j.project_id=?")
        params.append(int(project_id))
    if status in STATUSES:
        terms.append("j.status=?")
        params.append(status)
    where = "WHERE " + " AND ".join(terms) if terms else ""
    sql = f"""SELECT j.id,j.project_id,j.action_id,j.job_type,j.status,j.attempts,
       j.max_attempts,j.created_at,j.started_at,j.finished_at,j.updated_at,j.run_after,
       j.locked_at,j.payload_json,p.name AS project_name,
       a.action_type,a.reason AS action_reason,a.target_url,a.proposed_json,
       i.title AS issue_title
       FROM jobs j
       LEFT JOIN projects p ON p.id=j.project_id
       LEFT JOIN actions a ON a.id=j.action_id AND a.project_id=j.project_id
       LEFT JOIN issues i ON i.id=a.issue_id AND i.project_id=j.project_id
       {where}
       ORDER BY CASE WHEN j.status='running' THEN 0
                     WHEN j.status='retry' THEN 1
                     WHEN j.status='queued' THEN 2
                     WHEN j.status='failed' THEN 3
                     ELSE 4 END, j.id DESC
       LIMIT ?"""
    fetched = [dict(r) for r in conn.execute(sql, (*params, limit)).fetchall()]
    issue_ids = set()
    for row in fetched:
        if row["job_type"] != "seo_ai_prepare" or row.get("action_id"):
            continue
        raw = _parse(row.get("payload_json")).get("issue_ids")
        if isinstance(raw, list):
            issue_ids.update(int(v) for v in raw[:4] if str(v).isdigit())
    issue_titles = {}
    if issue_ids:
        marks = ",".join("?" for _ in issue_ids)
        issues = conn.execute(
            f"SELECT id,project_id,title FROM issues WHERE id IN ({marks})",
            tuple(sorted(issue_ids))
        ).fetchall()
        issue_titles = {(int(i["project_id"]), int(i["id"])): i["title"] for i in issues}
    result = []
    for row in fetched:
        title = title_for(row, issue_titles)
        item = {key: row.get(key) for key in
                ("id", "project_id", "project_name", "action_id", "job_type", "status",
                 "attempts", "max_attempts", "created_at", "started_at", "updated_at",
                 "finished_at", "run_after", "locked_at")}
        item["title"] = title
        item["stage"] = SEVERITY.get(item["status"], clean_text(item["status"], 40))
        item["action_url"] = (f"/projects/{item['project_id']}/actions?view=all&expand={item['action_id']}#action-{item['action_id']}"
                              if item["action_id"] is not None and item["project_id"] is not None else None)
        item["purpose"] = clean_text(row.get("action_reason"), 210) or {
            "seo_ai_prepare": "Připravuji návrhy ke schválení.",
            "seo_growth_prepare": "Vyhodnocuji data a připravuji návrh.",
            "seo_verify_action": "Ověřuji výsledek schválené změny.",
            "seo_apply_action": "Provádím už schválenou změnu."
        }.get(item["job_type"], "Provádím naplánovanou práci.")
        result.append(item)
    return result


def stats(conn, project_id=None):
    """Separate accepted, started, actually finished work and heartbeat."""
    condition = "WHERE project_id=?" if project_id is not None else ""
    values = (int(project_id),) if project_id is not None else ()
    counts = {r["status"]: int(r["n"]) for r in conn.execute(
        f"SELECT status,COUNT(*) n FROM jobs {condition} GROUP BY status", values).fetchall()}
    summary = conn.execute(
        f"""SELECT MAX(CASE WHEN status='completed' THEN finished_at END) AS last_completed,
                   MAX(started_at) AS last_started,
                   MIN(CASE WHEN status IN ('queued','retry') THEN created_at END) AS oldest_waiting,
                   MAX(CASE WHEN status='failed' THEN finished_at END) AS last_failed
            FROM jobs {condition}""", values).fetchone()
    recent_where = " WHERE status='completed' AND finished_at>=?"
    recent_args = [(datetime.now()-timedelta(minutes=15)).isoformat(timespec="seconds")]
    if project_id is not None:
        recent_where += " AND project_id=?"
        recent_args.append(int(project_id))
    recent = int(conn.execute(
        "SELECT COUNT(*) AS n FROM jobs" + recent_where,
        tuple(recent_args)
    ).fetchone()["n"] or 0)
    running_where="WHERE status='running'"
    running_args=[]
    if project_id is not None:
        running_where += " AND project_id=?"
        running_args.append(int(project_id))
    running_ids=[int(r["id"]) for r in conn.execute(
        "SELECT id FROM jobs " + running_where + " ORDER BY id DESC LIMIT 30",
        tuple(running_args)
    ).fetchall()]
    return {"counts": counts, "running_job_ids":running_ids,
            "active": sum(counts.get(s, 0) for s in ACTIVE),
            "completed_15m": recent,
            "last_completed": summary["last_completed"],
            "last_started": summary["last_started"],
            "oldest_waiting": summary["oldest_waiting"],
            "last_failed": summary["last_failed"]}


def movement_state(summary, worker, now=None, stale_after=180):
    """Truthful state: heartbeat alone cannot establish a completed action."""
    active = int(summary.get("active") or 0)
    last_seen = worker.get("last_seen") if worker else None
    age = worker.get("age_seconds") if worker else None
    confirmed = bool(age is not None and age <= stale_after)
    if not active:
        return {"status": "empty", "message": "Momentálně nejsou žádné úlohy k provedení.",
                "cron_confirmed": confirmed}
    if not confirmed:
        return {"status": "unconfirmed", "message": "Nemám čerstvé potvrzení běhu plánovače. Fronta může čekat na cron.",
                "cron_confirmed": False}
    if summary.get("counts", {}).get("running", 0):
        detail=(worker or {}).get("detail") or {}
        current_id=detail.get("job_id")
        confirmed_job=bool(worker and worker.get("status") == "running"
                           and str(current_id).isdigit()
                           and int(current_id) in summary.get("running_job_ids", []))
        if confirmed_job:
            return {"status": "running", "message": "Zpracovávám úlohu; dokončení potvrdím samostatně.",
                    "cron_confirmed": True}
        return {"status": "unconfirmed_running",
                "message": "Úloha je označená jako běžící, ale nemám čerstvé potvrzení jejího vykonávání.",
                "cron_confirmed": True}
    return {"status": "pending", "message": "Plánovač reagoval, ale čekající úlohy ještě nemají potvrzené dokončení.",
            "cron_confirmed": True}
