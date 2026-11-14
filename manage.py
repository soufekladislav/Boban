#!/usr/bin/env python3
"""Web Booster worker / maintenance CLI.

Recommended cPanel cron safety net (every minute):
    <VENV_PYTHON> /home2/.../webbooster.freshcrackers.cz/manage.py tick

The web app also performs a best-effort detached worker kick whenever work is queued.
The database queue is authoritative, so a killed process can resume safely later.
"""
import json
import sys
from datetime import datetime, timedelta

import requests
import app as wb
import sync_reporting
import worker_runtime
import sync_schedule
import connector_health

WORKER_NAME = "default"


def list_projects():
    conn = wb.db()
    rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
    conn.close()
    return rows


def _row_get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def log_job(project_id, job_type, status, payload=None, result=None, started_at=None):
    conn = wb.db()
    conn.execute(
        """INSERT INTO jobs(project_id,job_type,status,payload_json,result_json,started_at,finished_at,updated_at,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            project_id, job_type, status,
            json.dumps(payload or {}, ensure_ascii=False),
            json.dumps(result or {}, ensure_ascii=False),
            started_at, wb.now(), wb.now(), wb.now(),
        )
    )
    conn.commit(); conn.close()


def recover_stale_jobs():
    cutoff = (datetime.now() - timedelta(seconds=wb.WORKER_STALE_SECONDS)).isoformat(timespec="seconds")
    conn = wb.db()
    rows = conn.execute(
        "SELECT id,action_id,attempts,max_attempts FROM jobs WHERE status='running' AND COALESCE(locked_at,started_at,created_at) < ?",
        (cutoff,)
    ).fetchall()
    recovered = 0
    for row in rows:
        attempts = int(_row_get(row, "attempts", 0) or 0) + 1
        max_attempts = int(_row_get(row, "max_attempts", 3) or 3)
        status = "failed" if attempts >= max_attempts else "retry"
        conn.execute(
            "UPDATE jobs SET status=?,attempts=?,locked_at=NULL,run_after=?,updated_at=?,result_json=? WHERE id=?",
            (
                status, attempts,
                wb.now() if status == "retry" else None,
                wb.now(),
                json.dumps({"recovered": True, "reason": "stale_worker"}, ensure_ascii=False),
                row["id"],
            )
        )
        action_id = _row_get(row, "action_id")
        if action_id and status == "failed":
            conn.execute("UPDATE actions SET status='failed' WHERE id=? AND status IN ('queued','pending')", (action_id,))
        recovered += 1
    conn.commit(); conn.close()
    return recovered


def migrate_legacy_queue():
    """Split v0.4.1 batch jobs and orphan queued actions into one durable job per action."""
    conn = wb.db()
    legacy = conn.execute(
        "SELECT * FROM jobs WHERE job_type='seo_apply' AND status IN ('queued','running','retry') ORDER BY id"
    ).fetchall()
    created = 0
    for job in legacy:
        try:
            payload = json.loads(job["payload_json"] or "{}")
        except Exception:
            payload = {}
        ids = [int(x) for x in payload.get("action_ids", []) if str(x).isdigit()]
        group_id = _row_get(job, "group_id") or f"legacy-{job['id']}"
        owner = _row_get(job, "user_id") or wb._project_owner_id(job["project_id"])
        for action_id in ids:
            exists = conn.execute(
                "SELECT id FROM jobs WHERE job_type='seo_apply_action' AND action_id=? AND status IN ('queued','running','retry') LIMIT 1",
                (action_id,)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO jobs(project_id,user_id,action_id,group_id,job_type,status,attempts,max_attempts,payload_json,run_after,updated_at,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job["project_id"], owner, action_id, group_id, "seo_apply_action", "queued", 0, 3,
                 json.dumps({"action_id": action_id, "migrated_from": job["id"]}, ensure_ascii=False), wb.now(), wb.now(), wb.now())
            )
            conn.execute("UPDATE actions SET status='queued',job_group_id=? WHERE id=?", (group_id, action_id))
            created += 1
        conn.execute(
            "UPDATE jobs SET status='completed',result_json=?,finished_at=?,updated_at=? WHERE id=?",
            (json.dumps({"migrated": True, "created_jobs": created}, ensure_ascii=False), wb.now(), wb.now(), job["id"])
        )

    # Recover action rows that say queued but have no runnable job.
    orphans = conn.execute(
        """SELECT a.id,a.project_id,p.user_id,a.job_group_id
           FROM actions a JOIN projects p ON p.id=a.project_id
           WHERE a.status='queued' AND NOT EXISTS (
               SELECT 1 FROM jobs j WHERE j.action_id=a.id AND j.job_type='seo_apply_action' AND j.status IN ('queued','running','retry')
           )"""
    ).fetchall()
    for action in orphans:
        group_id = _row_get(action, "job_group_id") or f"recover-{action['id']}"
        conn.execute(
            """INSERT INTO jobs(project_id,user_id,action_id,group_id,job_type,status,attempts,max_attempts,payload_json,run_after,updated_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (action["project_id"], action["user_id"], action["id"], group_id, "seo_apply_action", "queued", 0, 3,
             json.dumps({"action_id": action["id"], "recovered_orphan": True}, ensure_ascii=False), wb.now(), wb.now(), wb.now())
        )
        created += 1
    conn.commit(); conn.close()
    return created


def _retry_delay(attempt):
    return [60, 300, 900, 1800][min(max(0, attempt - 1), 3)]


def _schedule_retry(job, error, action_status="queued"):
    attempt = int(_row_get(job, "attempts", 0) or 0) + 1
    max_attempts = int(_row_get(job, "max_attempts", 3) or 3)
    conn = wb.db()
    if attempt >= max_attempts:
        conn.execute(
            "UPDATE jobs SET status='failed',attempts=?,result_json=?,finished_at=?,locked_at=NULL,updated_at=? WHERE id=?",
            (attempt, json.dumps({"error": str(error)}, ensure_ascii=False), wb.now(), wb.now(), job["id"])
        )
        if _row_get(job, "action_id"):
            conn.execute(
                "UPDATE actions SET status='failed',last_error=? WHERE id=?",
                (str(error)[:2000], job["action_id"])
            )
        conn.commit(); conn.close()
        wb.create_notification(
            job["project_id"], "Potřebuji tvoji pozornost",
            f"Úkol #{_row_get(job, 'action_id', '?')} se nepodařilo dokončit ani po {attempt} pokusech. Otevři úkol a podíváme se na důvod.",
            url=f"/projects/{job['project_id']}/actions?view=todo", level="error", kind="job_error", user_id=_row_get(job, "user_id")
        )
        return "failed"
    run_after = (datetime.now() + timedelta(seconds=_retry_delay(attempt))).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE jobs SET status='retry',attempts=?,run_after=?,result_json=?,locked_at=NULL,updated_at=? WHERE id=?",
        (attempt, run_after, json.dumps({"error": str(error), "retry": True}, ensure_ascii=False), wb.now(), job["id"])
    )
    if _row_get(job, "action_id"):
        conn.execute("UPDATE actions SET status=? WHERE id=?", (action_status, job["action_id"]))
    conn.commit(); conn.close()
    return "retry"


def _schedule_verify(project, action, group_id, user_id, reason="timeout"):
    conn = wb.db()
    exists = conn.execute(
        "SELECT id FROM jobs WHERE job_type='seo_verify_action' AND action_id=? AND status IN ('queued','running','retry') LIMIT 1",
        (action["id"],)
    ).fetchone()
    if not exists:
        conn.execute(
            """INSERT INTO jobs(project_id,user_id,action_id,group_id,job_type,status,attempts,max_attempts,payload_json,run_after,updated_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project["id"], user_id, action["id"], group_id, "seo_verify_action", "queued", 0, 6,
             json.dumps({"action_id": action["id"], "reason": reason}, ensure_ascii=False),
             (datetime.now()+timedelta(seconds=45)).isoformat(timespec="seconds"), wb.now(), wb.now())
        )
    conn.execute("UPDATE actions SET status='pending' WHERE id=?", (action["id"],))
    conn.commit(); conn.close()


def _finish_job(job_id, result):
    conn = wb.db()
    conn.execute(
        "UPDATE jobs SET status='completed',result_json=?,finished_at=?,locked_at=NULL,updated_at=? WHERE id=?",
        (json.dumps(result or {}, ensure_ascii=False), wb.now(), wb.now(), job_id)
    )
    conn.commit(); conn.close()


def _group_notify_if_done(project_id, group_id, user_id=None):
    if not group_id:
        return
    conn = wb.db()
    left = conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE project_id=? AND group_id=? AND status IN ('queued','running','retry')",
        (project_id, group_id)
    ).fetchone()["c"]
    if left:
        conn.close(); return
    kind = f"job_group_{group_id}"
    already = conn.execute("SELECT id FROM notifications WHERE project_id=? AND kind=? LIMIT 1", (project_id, kind)).fetchone()
    if already:
        conn.close(); return
    rows = conn.execute(
        "SELECT status,COUNT(*) c FROM actions WHERE project_id=? AND job_group_id=? GROUP BY status",
        (project_id, group_id)
    ).fetchall()
    summary = {r["status"]: int(r["c"]) for r in rows}
    conn.close()
    good = sum(summary.get(k, 0) for k in ("applied","verified","completed","pending"))
    failed = summary.get("failed", 0)
    if failed:
        title = "Úkoly jsem zpracoval, část potřebuje kontrolu"
        body = f"Hotovo nebo ověřuji: {good}. Nepodařilo se: {failed}. Otevři přehled a projdeme zbytek."
        level = "warning"
    else:
        title = "Mám hotovo"
        body = f"Zpracoval jsem {good} úkolů. U změn, které cílová služba ještě nepotvrdila, dál automaticky ověřuji výsledek."
        level = "success"
    wb.create_notification(project_id, title, body, url=f"/projects/{project_id}/actions?view=done", level=level, kind=kind, user_id=user_id)
    wb.add_boban_message(
        project_id, body,
        actions=[{"label": "Otevřít výsledky", "url": f"/projects/{project_id}/actions?view=done", "primary": True}]
    )


def _claim_jobs(limit_jobs=10):
    nowv = wb.now()
    conn = wb.db()
    rows = conn.execute(
        """SELECT * FROM jobs
           WHERE job_type IN ('seo_ai_prepare','seo_growth_prepare','seo_apply_action','seo_verify_action')
             AND status IN ('queued','retry')
             AND (run_after IS NULL OR run_after<=?)
           ORDER BY id LIMIT ?""",
        (nowv, limit_jobs)
    ).fetchall()
    claimed = []
    for row in rows:
        cur = conn.execute(
            """UPDATE jobs SET status='running',started_at=COALESCE(started_at,?),locked_at=?,updated_at=?
               WHERE id=? AND status IN ('queued','retry')""",
            (nowv, nowv, nowv, row["id"])
        )
        if getattr(cur, "rowcount", 0) == 1:
            claimed.append(row)
    conn.commit(); conn.close()
    return claimed


def _heartbeat_job(job):
    """Extend only the currently claimed job lease using a NEW DB connection."""
    ts = wb.now()
    conn = wb.db()
    try:
        cur = conn.execute(
            "UPDATE jobs SET locked_at=?,updated_at=? WHERE id=? AND status='running'",
            (ts, ts, job["id"])
        )
        conn.commit()
        active = getattr(cur, "rowcount", 0) == 1
    finally:
        conn.close()
    if active:
        wb.touch_worker("seo_queue", "running", {
            "phase": "working", "job_id": int(job["id"]),
            "job_type": str(job["job_type"]), "project_id": int(job["project_id"]),
            "started_at": str(_row_get(job, "started_at") or ts),
        })


def process_seo_apply_jobs(limit_jobs=10):
    wb.touch_worker("seo_queue", "running", {"phase": "actions"})
    processed = 0
    # Claim ONE job at a time. A slow first job must never falsely mark the
    # remaining jobs as running (or let stale recovery repeat their writes).
    for _ in range(max(1, int(limit_jobs))):
        batch = _claim_jobs(1)
        if not batch:
            break
        job = batch[0]
        project_id = job["project_id"]
        action_id = _row_get(job, "action_id")
        group_id = _row_get(job, "group_id")
        with worker_runtime.JobHeartbeat(lambda: _heartbeat_job(job)):
            try:
                conn = wb.db()
                project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
                action = conn.execute("SELECT * FROM actions WHERE id=? AND project_id=?", (action_id, project_id)).fetchone() if action_id else None
                conn.close()
                if not project:
                    _finish_job(job["id"], {"skipped": True, "reason": "missing_project"})
                    continue

                # AI preparation jobs intentionally have no action_id yet: their
                # purpose is to create actions. Handle them before requiring an
                # action row.
                if job["job_type"] == "seo_ai_prepare":
                    try:
                        payload = json.loads(job["payload_json"] or "{}")
                    except Exception:
                        payload = {}
                    issue_ids = [int(x) for x in payload.get("issue_ids", []) if str(x).isdigit()]
                    auto_apply = bool(payload.get("auto_apply"))
                    if issue_ids:
                        conn = wb.db()
                        marks = ",".join("?" for _ in issue_ids)
                        rows = conn.execute(
                            f"SELECT * FROM issues WHERE project_id=? AND status='open' AND id IN ({marks}) ORDER BY id",
                            [project_id, *issue_ids]
                        ).fetchall()
                        conn.close()
                    else:
                        rows = []
                    if not rows:
                        _finish_job(job["id"], {"skipped": True, "reason": "issues_missing"})
                    else:
                        created, _ = wb.ai_prepare_issue_actions(project, rows, auto_apply=False)
                        if auto_apply and created:
                            wb.queue_seo_apply_jobs(project_id, created, kick=False, notify=False)
                        _finish_job(job["id"], {"created_actions": created, "auto_apply": auto_apply})
                        # Only the last AI chunk sends the summary notification.
                        conn = wb.db()
                        left = conn.execute(
                            "SELECT COUNT(*) c FROM jobs WHERE project_id=? AND group_id=? AND job_type='seo_ai_prepare' AND status IN ('queued','running','retry')",
                            (project_id, group_id)
                        ).fetchone()["c"]
                        conn.close()
                        if not left:
                            if auto_apply:
                                msg = "SEO návrhy jsem dokončil a bezpečné změny jsem rovnou zařadil k provedení. Teď je postupně zapisuji přes Fresh Core a ověřuji na webu."
                                wb.create_notification(
                                    project_id, "Návrhy mám připravené", msg,
                                    url=f"/projects/{project_id}/actions?view=todo", level="success", kind=f"ai_group_{group_id}", user_id=_row_get(job, "user_id")
                                )
                                wb.add_boban_message(project_id, msg, actions=[{"label":"Sledovat provedení","url":f"/projects/{project_id}/actions?view=todo","primary":True}])
                            else:
                                msg = "Dokončil jsem návrhy. Otevři Úkoly, kde je můžeš projít, označit a schválit."
                                wb.create_notification(
                                    project_id, "SEO návrhy jsou připravené", msg,
                                    url=f"/projects/{project_id}/actions?view=todo", level="success", kind=f"ai_group_{group_id}", user_id=_row_get(job, "user_id")
                                )
                                wb.add_boban_message(project_id, msg, actions=[{"label":"Projít návrhy","url":f"/projects/{project_id}/actions?view=todo","primary":True}])
                    processed += 1
                    continue

                if job["job_type"] == "seo_growth_prepare":
                    try:
                        payload = json.loads(job["payload_json"] or "{}")
                    except Exception:
                        payload = {}
                    candidates = payload.get("candidates") or []
                    created, skipped = wb.ai_prepare_growth_actions(project, candidates)
                    _finish_job(job["id"], {"created_actions": created, "skipped": skipped})
                    if created:
                        msg = f"Z dat Search Console jsem prověřil {len(candidates)} růstové příležitosti a připravil {len(created)} konkrétní návrhy ke schválení. Tam, kde metadata nebyla správný zásah, jsem změnu nevyráběl naslepo."
                        wb.create_notification(
                            project_id, "Růstové návrhy jsou připravené", msg,
                            url=f"/projects/{project_id}/actions?view=todo", level="success", kind=f"growth_done_{group_id}", user_id=_row_get(job, "user_id")
                        )
                        wb.add_boban_message(project_id, msg, actions=[{"label":"Projít návrhy","url":f"/projects/{project_id}/actions?view=todo","primary":True}])
                    else:
                        msg = "Růstové příležitosti ze Search Console jsem prověřil, ale nevytvořil jsem změnu jen pro změnu. U těchto stránek teď metadata nejsou bezpečně nejlepší zásah; nechávám je v pracovním plánu pro obsah/prolinkování."
                        wb.add_boban_message(project_id, msg, actions=[{"label":"Zobrazit pracovní plán","url":f"/projects/{project_id}#boban-context","primary":True}])
                    processed += 1
                    continue

                if not action:
                    _finish_job(job["id"], {"skipped": True, "reason": "missing_action"})
                    processed += 1
                    continue

                if job["job_type"] == "seo_verify_action":
                    result_data = {}
                    try:
                        result_data = json.loads(action["result_json"] or "{}")
                    except Exception:
                        pass
                    verification = wb.verify_action(project, action, result_data)
                    if wb.save_action_verification(project_id, action_id, verification):
                        _finish_job(job["id"], {"verified": True})
                    else:
                        state = _schedule_retry(job, "Cílová služba změnu zatím nepotvrdila.", action_status="pending")
                        if state == "failed":
                            conn = wb.db()
                            conn.execute("UPDATE actions SET status='pending' WHERE id=?", (action_id,))
                            conn.commit(); conn.close()
                    processed += 1
                    _group_notify_if_done(project_id, group_id, _row_get(job, "user_id"))
                    continue

                # If the remote write was already accepted, only verify; NEVER re-apply
                # after a crash during verification.
                if action["status"] in ("verified", "completed"):
                    _finish_job(job["id"], {"skipped_write": True, "already_verified": True})
                    processed += 1
                    continue
                if action["status"] in ("applied", "pending"):
                    _schedule_verify(project, action, group_id, _row_get(job, "user_id"), reason="already_applied")
                    _finish_job(job["id"], {"skipped_write": True, "verification_queued": True})
                    processed += 1
                    continue

                # On retry, first inspect the remote state. This is essential
                # for non-idempotent GA4 creation after a crash/unknown response.
                if int(_row_get(job, "attempts", 0) or 0) > 0:
                    try:
                        earlier = wb.verify_action(project, action, None)
                    except Exception:
                        earlier = {}
                    if earlier.get("rendered_confirmed"):
                        wb.save_action_verification(project_id, action_id, earlier)
                        _finish_job(job["id"], {"recovered_from_remote": True, "verified": True})
                        processed += 1
                        continue

                # Apply one action. Idempotent change_id wb-<action id> protects retries on Fresh Core 0.4.3+.
                try:
                    provider = _row_get(action, "provider", "fresh_core") or "fresh_core"
                    baseline = wb.page_metrics_from_gsc(wb.latest_source_snapshot(project_id, "search_console"), action["target_url"]) if provider == "fresh_core" else {}
                    result = wb.apply_action(project, action)
                    conn = wb.db()
                    conn.execute(
                        """UPDATE actions SET status='applied',applied_at=?,result_json=?,baseline_metrics_json=?,last_error=NULL WHERE id=?""",
                        (wb.now(), json.dumps(result, ensure_ascii=False), json.dumps(baseline or {}, ensure_ascii=False), action_id)
                    )
                    conn.commit(); conn.close()
                    conn = wb.db(); fresh = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone(); conn.close()
                    try:
                        verification = wb.verify_action(project, fresh, result)
                        wb.save_action_verification(project_id, action_id, verification)
                        _finish_job(job["id"], {"applied": True, "verified": bool(verification.get("rendered_confirmed"))})
                    except Exception as verify_exc:
                        # The WRITE succeeded: a failed read-back must never
                        # cause the WRITE job to be repeated.
                        _schedule_verify(project, fresh, group_id, _row_get(job, "user_id"), reason="readback_failed")
                        _finish_job(job["id"], {"applied": True, "verification_pending": True,
                                                "verification_error_type": type(verify_exc).__name__})
                except requests.exceptions.Timeout as exc:
                    try:
                        verification = wb.verify_action(project, action, None)
                    except Exception as verify_exc:
                        verification = {"rendered_confirmed": False, "provider_confirmed": False,
                                        "checked_at": wb.now(), "checks": {},
                                        "note": "Po timeoutu není zatím možné ověřit odpověď cílové služby."}
                    if verification.get("rendered_confirmed"):
                        conn = wb.db()
                        conn.execute(
                            "UPDATE actions SET status='verified',applied_at=COALESCE(applied_at,?),verification_json=?,verified_at=?,last_error=NULL WHERE id=?",
                            (wb.now(), json.dumps(verification, ensure_ascii=False), wb.now(), action_id)
                        )
                        conn.commit(); conn.close()
                        _finish_job(job["id"], {"timeout_recovered": True, "verified": True})
                    else:
                        conn = wb.db()
                        conn.execute(
                            "UPDATE actions SET status='pending',last_error=?,verification_json=?,verified_at=? WHERE id=?",
                            (str(exc)[:2000], json.dumps(verification, ensure_ascii=False), wb.now(), action_id)
                        )
                        conn.commit(); conn.close()
                        _finish_job(job["id"], {"timeout": True, "pending_verification": True})
                        _schedule_verify(project, action, group_id, _row_get(job, "user_id"), reason="write_timeout")
                except Exception as exc:
                    _schedule_retry(job, exc, action_status="queued")

                processed += 1
                _group_notify_if_done(project_id, group_id, _row_get(job, "user_id"))
            except Exception as exc:
                _schedule_retry(job, exc, action_status="queued")
                processed += 1
            wb.touch_worker("seo_queue", "running", {"phase": "actions", "processed": processed})

    wb.touch_worker("seo_queue", "idle", {"processed": processed})
    return processed


def verify_applied_actions():
    verified = 0
    conn = wb.db()
    rows = conn.execute(
        "SELECT * FROM actions WHERE status IN ('applied','pending') ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    for action in rows:
        conn = wb.db(); project = conn.execute("SELECT * FROM projects WHERE id=?", (action["project_id"],)).fetchone(); conn.close()
        if not project:
            continue
        try:
            result = json.loads(action["result_json"] or "{}")
        except Exception:
            result = {}
        try:
            verification = wb.verify_action(project, action, result)
            if wb.save_action_verification(project["id"], action["id"], verification):
                verified += 1
        except Exception as exc:
            print(f"verify action {action['id']}: ERROR {exc}")
    return verified


def core_sync_all():
    changed = 0
    for project in list_projects():
        manifest_url = _row_get(project, "core_manifest_url")
        if not manifest_url or not wb.project_automation_allowed(project["id"]) or not wb.automation_rule_due(project["id"], "core_sync", 1):
            continue
        started = wb.now()
        try:
            result = wb.auto_sync_core_project(project["id"])
            wb.mark_automation_run(project["id"], "core_sync", "completed")
            if result.get("changed"):
                changed += 1
                log_job(project["id"], "core_sync", "completed", result=result, started_at=started)
            print(f"core project {project['id']}: {result}")
        except Exception as exc:
            wb.mark_automation_run(project["id"], "core_sync", "failed", exc)
            log_job(project["id"], "core_sync", "failed", result={"error": str(exc)}, started_at=started)
            print(f"core project {project['id']}: ERROR {exc}")
    return changed


def gsc_sync_due():
    synced = 0
    for project in list_projects():
        integ = wb.integration_row(project["id"], "search_console")
        if not integ or integ["status"] != "connected":
            continue
        if not wb.project_automation_allowed(project["id"]) or not wb.automation_rule_due(project["id"], "search_console_sync", 12):
            continue
        started = wb.now()
        try:
            data = wb.sync_search_console(project["id"])
            wb.mark_automation_run(project["id"], "search_console_sync", "completed")
            log_job(project["id"], "search_console_sync", "completed", result={"period": data.get("period")}, started_at=started)
            synced += 1
            print(f"gsc project {project['id']}: synced")
        except Exception as exc:
            wb.mark_automation_run(project["id"], "search_console_sync", "failed", exc)
            log_job(project["id"], "search_console_sync", "failed", result={"error": str(exc)}, started_at=started)
            print(f"gsc project {project['id']}: ERROR {exc}")
    return synced


def ga4_sync_due():
    synced = 0
    for project in list_projects():
        integ = wb.integration_row(project["id"], "ga4")
        if not integ or integ["status"] != "connected":
            continue
        if not wb.project_automation_allowed(project["id"]) or not wb.automation_rule_due(project["id"], "ga4_sync", 12):
            continue
        started = wb.now()
        try:
            data = wb.sync_ga4(project["id"])
            wb.mark_automation_run(project["id"], "ga4_sync", "completed")
            log_job(project["id"], "ga4_sync", "completed", result={"period": data.get("period")}, started_at=started)
            synced += 1
            print(f"ga4 project {project['id']}: synced")
        except Exception as exc:
            wb.mark_automation_run(project["id"], "ga4_sync", "failed", exc)
            log_job(project["id"], "ga4_sync", "failed", result={"error": str(exc)}, started_at=started)
            print(f"ga4 project {project['id']}: ERROR {exc}")
    return synced


def performance_sync_due():
    if not wb.pagespeed_ready():
        return 0
    synced = 0
    for project in list_projects():
        integ = wb.integration_row(project["id"], "pagespeed_crux")
        if not wb.project_automation_allowed(project["id"]) or not wb.automation_rule_due(project["id"], "pagespeed_crux_sync", 24): continue
        started = wb.now()
        try:
            data = wb.sync_pagespeed_crux(project["id"])
            wb.mark_automation_run(project["id"], "pagespeed_crux_sync", "completed")
            log_job(project["id"], "pagespeed_crux_sync", "completed", result={"captured_at": data.get("captured_at")}, started_at=started)
            synced += 1
        except Exception as exc:
            wb.mark_automation_run(project["id"], "pagespeed_crux_sync", "failed", exc)
            log_job(project["id"], "pagespeed_crux_sync", "failed", result={"error": str(exc)}, started_at=started)
            print(f"performance project {project['id']}: ERROR {exc}")
    return synced


def gtm_sync_due():
    synced = 0
    for project in list_projects():
        integ = wb.integration_row(project["id"], "gtm")
        if not integ or integ["status"] != "connected":
            continue
        conf = wb.integration_config(integ)
        if not conf.get("selected_container"):
            continue
        if not wb.project_automation_allowed(project["id"]) or not wb.automation_rule_due(project["id"], "gtm_sync", 24): continue
        started = wb.now()
        try:
            data = wb.sync_gtm(project["id"])
            wb.mark_automation_run(project["id"], "gtm_sync", "completed")
            log_job(project["id"], "gtm_sync", "completed", result={"counts": data.get("counts")}, started_at=started)
            synced += 1
        except Exception as exc:
            wb.mark_automation_run(project["id"], "gtm_sync", "failed", exc)
            log_job(project["id"], "gtm_sync", "failed", result={"error": str(exc)}, started_at=started)
            print(f"gtm project {project['id']}: ERROR {exc}")
    return synced


def seo_crawl_due():
    ran=0
    for project in list_projects():
        if not _row_get(project,"core_manifest_url") or not wb.project_automation_allowed(project["id"]) or not wb.automation_rule_due(project["id"],"seo_crawl",168):
            continue
        started=wb.now()
        try:
            snapshot=wb.project_snapshot(project); seo_items=wb.seo_items_from_snapshot(snapshot)
            if not seo_items:
                wb.mark_automation_run(project["id"],"seo_crawl","skipped","Fresh Core neposkytuje SEO index")
                continue
            results,issues=wb.crawler_audit(project,seo_items)
            wb.persist_audit(project["id"],"crawler",{"type":"crawler","crawl_limit":wb.CRAWL_LIMIT,"pages_checked":len(results),"pages":results},issues,replace_open=True)
            wb.mark_automation_run(project["id"],"seo_crawl","completed")
            log_job(project["id"],"seo_crawl","completed",result={"pages":len(results),"issues":len(issues)},started_at=started); ran+=1
        except Exception as exc:
            wb.mark_automation_run(project["id"],"seo_crawl","failed",exc); log_job(project["id"],"seo_crawl","failed",result={"error":str(exc)},started_at=started)
            print(f"seo crawl project {project['id']}: ERROR {exc}")
    return ran


def process_email_outbox(limit=10):
    conn=wb.db(); rows=conn.execute("SELECT * FROM email_outbox WHERE status IN ('queued','retry') ORDER BY id LIMIT ?",(limit,)).fetchall(); conn.close(); sent=0
    for row in rows:
        try:
            wb.send_email_message(row["to_email"],row["subject"],row["body"]); conn=wb.db(); conn.execute("UPDATE email_outbox SET status='sent',sent_at=?,last_error=NULL WHERE id=?",(wb.now(),row["id"])); conn.commit(); conn.close(); sent+=1
        except Exception as exc:
            attempts=int(_row_get(row,"attempts",0) or 0)+1; status="failed" if attempts>=3 else "retry"; conn=wb.db(); conn.execute("UPDATE email_outbox SET status=?,attempts=?,last_error=? WHERE id=?",(status,attempts,str(exc)[:2000],row["id"])); conn.commit(); conn.close()
    return sent


def operator_cycles_due():
    ran = 0
    for project in list_projects():
        if not wb.operator_cycle_due(project):
            continue
        started = wb.now()
        try:
            result = wb.operator_cycle(project["id"])
            wb.mark_automation_run(project["id"], "operator_cycle", "completed")
            log_job(project["id"], "operator_cycle", "completed", result={"prepared": result.get("prepared", 0)}, started_at=started)
            ran += 1
        except Exception as exc:
            wb.mark_automation_run(project["id"], "operator_cycle", "failed", exc)
            log_job(project["id"], "operator_cycle", "failed", result={"error": str(exc)}, started_at=started)
            print(f"operator project {project['id']}: ERROR {exc}")
    return ran


def _probe_connector(project, provider):
    """Small read-only API check, separate from data sync and stored OAuth state."""
    pid = int(project["id"])
    if provider == "core":
        url = str(_row_get(project, "core_manifest_url") or "")
        if not url:
            return "not_connected"
        data = wb.fetch_json(url, expected_host=wb.normalize_host(project["site_url"]))
        if not isinstance(data, dict):
            raise ValueError("Manifest nevrátil JSON objekt.")
        return "ok"
    integ = wb.integration_row(pid, provider)
    if not integ or integ["status"] != "connected":
        return "not_connected"
    config = wb.integration_config(integ)
    if provider == "search_console":
        selected = str(config.get("selected_property") or "")
        if not selected:
            return "needs_setup"
        token = wb.google_refresh_access(pid, provider)
        sites = wb.google_api_get("https://www.googleapis.com/webmasters/v3/sites", token)
        available = {str(r.get("siteUrl") or "") for r in sites.get("siteEntry") or []}
        return "ok" if selected in available else "needs_setup"
    if provider == "ga4":
        selected = str(config.get("selected_property") or "")
        if not selected.startswith("properties/"):
            return "needs_setup"
        token = wb.google_refresh_access(pid, provider)
        item = wb.google_api_get(f"https://analyticsadmin.googleapis.com/v1beta/{selected}", token)
        return "ok" if str(item.get("name") or "") == selected else "needs_setup"
    if provider == "gtm":
        selected = str(config.get("selected_container") or "")
        if not selected.startswith("accounts/"):
            return "needs_setup"
        token = wb.google_refresh_access(pid, provider)
        item = wb.google_api_get(f"https://tagmanager.googleapis.com/tagmanager/v2/{selected}", token)
        return "ok" if str(item.get("path") or "") == selected else "needs_setup"
    raise ValueError("Nepodporovaný provider.")


def connector_heartbeat():
    """Periodically verify live connectivity, without resyncing metrics or writing websites."""
    statuses = {"ok": 0, "failed": 0, "not_connected": 0, "needs_setup": 0}
    for project in list_projects():
        pid = int(project["id"])
        if not wb.project_automation_allowed(pid):
            continue
        for provider in ("core", "search_console", "ga4", "gtm"):
            wb.touch_worker("connector_health", "running", {"phase": provider, "project_id": pid})
            error_type = None
            try:
                status = _probe_connector(project, provider)
            except Exception as exc:
                status = "failed"
                error_type = type(exc).__name__
            conn = wb.db()
            try:
                connector_health.record(conn, wb.DB_BACKEND, pid, provider, status, error_type)
                conn.commit()
            finally:
                conn.close()
            statuses[status] += 1
    wb.touch_worker("connector_health", "idle", {"processed": sum(statuses.values())})
    print("CONNECTOR HEARTBEAT: " + json.dumps(statuses, ensure_ascii=False))
    return statuses


def locked_connector_heartbeat():
    with worker_runtime.exclusive_lock(wb.BASE_DIR / ".connector-heartbeat.lock") as acquired:
        if not acquired:
            print("CONNECTOR HEARTBEAT: jiná kontrola už běží")
            return {"skipped": "already_running"}
        return connector_heartbeat()


def run_daily_sync(force=False, project_id=None, provider=None):
    """Collect business data once per Europe/Prague day, at/after 05:00.

    Every source has its own durable state, so one failed API will not block
    successful sources. Explicit manual runs bypass the daily success gate.
    """
    local_now = worker_runtime.prague_now()
    # Before 05:00 process only durable manual requests; normal data collection waits.
    day = local_now.date().isoformat()
    result = {"date": day, "completed": 0, "failed": 0, "skipped": 0}
    for project in list_projects():
        pid = int(project["id"])
        if project_id is not None and pid != int(project_id):
            continue
        if not wb.project_automation_allowed(pid):
            result["skipped"] += 1
            continue
        specs = [
            ("core", "core_sync", bool(_row_get(project, "core_manifest_url")), lambda: wb.auto_sync_core_project(pid)),
            ("search_console", "search_console_sync", bool((i := wb.integration_row(pid, "search_console")) and i["status"] == "connected"), lambda: wb.sync_search_console(pid)),
            ("ga4", "ga4_sync", bool((i := wb.integration_row(pid, "ga4")) and i["status"] == "connected"), lambda: wb.sync_ga4(pid)),
            ("gtm", "gtm_sync", bool((i := wb.integration_row(pid, "gtm")) and i["status"] == "connected" and wb.integration_config(i).get("selected_container")), lambda: wb.sync_gtm(pid)),
            ("pagespeed_crux", "pagespeed_crux_sync", bool(wb.pagespeed_ready()), lambda: wb.sync_pagespeed_crux(pid)),
        ]
        for name, rule, connected, perform in specs:
            if provider and provider != name:
                continue
            if not connected:
                result["skipped"] += 1
                continue
            conn = wb.db()
            try:
                state = sync_schedule.get_state(conn, pid, name, day)
                requested = bool(state and state.get("status") == "requested")
                if not (force or requested or wb.automation_rule_enabled(rule)):
                    result["skipped"] += 1
                    continue
                if not worker_runtime.daily_due(state, local_now, force=force):
                    result["skipped"] += 1
                    continue
                sync_schedule.record_state(conn, wb.DB_BACKEND, pid, name, day, "running")
                conn.commit()
            finally:
                conn.close()
            started = wb.now()
            wb.touch_worker("daily_sync", "running", {
                "phase": name, "project_id": pid, "started_at": started
            })
            try:
                data = perform()
                conn = wb.db()
                try:
                    sync_schedule.record_state(conn, wb.DB_BACKEND, pid, name, day, "completed")
                    conn.commit()
                finally:
                    conn.close()
                wb.mark_automation_run(pid, rule, "completed")
                safe_result = {"date": day, "source": name}
                if isinstance(data, dict) and isinstance(data.get("period"), dict):
                    safe_result["period"] = data["period"]
                log_job(pid, "daily_sync_" + name, "completed", result=safe_result, started_at=started)
                result["completed"] += 1
                print(f"DAILY SYNC: projekt={pid} zdroj={name} dokončeno")
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)[:240]
                conn = wb.db()
                try:
                    sync_schedule.record_state(conn, wb.DB_BACKEND, pid, name, day, "failed", error=error)
                    conn.commit()
                finally:
                    conn.close()
                wb.mark_automation_run(pid, rule, "failed", error)
                log_job(pid, "daily_sync_" + name, "failed", result={"date": day, "source": name, "error": error}, started_at=started)
                result["failed"] += 1
                print(f"DAILY SYNC: projekt={pid} zdroj={name} chyba={type(exc).__name__}")
    wb.touch_worker("daily_sync", "idle", {"processed": result["completed"] + result["failed"]})
    print("DAILY SYNC: " + json.dumps(result, ensure_ascii=False))
    return result


def locked_daily_sync(force=False, project_id=None, provider=None):
    with worker_runtime.exclusive_lock(wb.BASE_DIR / ".daily-sync.lock") as acquired:
        if not acquired:
            print("DAILY SYNC: jiný proces už provádí synchronizaci; nic nového nespouštím")
            return {"skipped": "already_running"}
        return run_daily_sync(force=force, project_id=project_id, provider=provider)


def locked_work_queue():
    with worker_runtime.exclusive_lock(wb.BASE_DIR / ".seo-worker.lock") as acquired:
        if not acquired:
            print("SEO QUEUE: jiný worker už běží; ponechávám úkoly v bezpečné frontě")
            return False
        work_queue()
        return True


def tick():
    """Compatibility scheduler: never download analytics twice daily or race the SEO worker."""
    wb.touch_worker("scheduler", "running", {"phase": "tick"})
    locked_work_queue()
    daily = locked_daily_sync()
    crawl = seo_crawl_due()
    operator = operator_cycles_due()
    catalogs = wb.catalog_workflow_all(limit=5)
    emails = process_email_outbox()
    wb.touch_worker("scheduler", "idle", {"phase": "tick"})
    print(f"tick complete: daily={daily}, crawl={crawl}, operator={operator}, catalogs={catalogs}, emails={emails}")


def work_queue_errors(project_id=3, limit=20):
    """Read-only error diagnosis for SEO work; does not execute or retry jobs."""
    conn = wb.db()
    try:
        rows = conn.execute(
            """SELECT j.id,j.project_id,j.action_id,j.status,j.attempts,j.max_attempts,
                      j.run_after,j.result_json,a.status AS action_status,a.last_error,
                      a.action_type,a.target_url
               FROM jobs j LEFT JOIN actions a ON a.id=j.action_id AND a.project_id=j.project_id
               WHERE j.project_id=? AND j.job_type='seo_apply_action'
                 AND j.status IN ('failed','retry')
               ORDER BY j.id DESC LIMIT ?""", (int(project_id),max(1,min(int(limit),100)))
        ).fetchall()
        output=[]
        for r in rows:
            d=dict(r)
            try:
                payload=json.loads(d.pop('result_json') or '{}')
            except (TypeError,ValueError):
                payload={}
            # No raw payloads/tokens. These errors may contain upstream details; redact common secrets.
            raw=str(d.pop('last_error') or payload.get('error') or '')
            import re
            raw=re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/-]+',r'\1[REDACTED]',raw)
            raw=re.sub(r'(?i)((?:api[_-]?key|token|secret|password)[=:]\s*)[^\s,;]+',r'\1[REDACTED]',raw)
            d['error']=raw[:1000] or '(důvod chyby nebyl uložen)'
            output.append(d)
        return output
    finally:
        conn.close()


def work_queue_status():
    """Read-only snapshot of real persistent SEO jobs; never expose payload or secrets."""
    conn = wb.db()
    try:
        kinds = ('seo_ai_prepare','seo_growth_prepare','seo_apply_action','seo_verify_action')
        marks = ','.join('?' for _ in kinds)
        rows = conn.execute(
            f"SELECT project_id,job_type,status,COUNT(*) AS n FROM jobs WHERE job_type IN ({marks}) GROUP BY project_id,job_type,status ORDER BY project_id,job_type,status",
            kinds,
        ).fetchall()
        result = {}
        for r in rows:
            project = str(r['project_id'])
            result.setdefault(project, {}).setdefault(r['job_type'], {})[r['status']] = int(r['n'])
        return result
    finally:
        conn.close()



def work_queue_pending_details(limit=30):
    """Safe scheduling diagnostics. Due status is distinct from job completion.

    Never display job payloads or credentials. Database times use app's existing
    local time convention, matching the scheduler's run_after comparison.
    """
    conn=wb.db()
    try:
        nowv=wb.now()
        rows=conn.execute(
            """SELECT id,project_id,job_type,status,attempts,max_attempts,run_after,updated_at
                 FROM jobs
                 WHERE job_type IN ('seo_ai_prepare','seo_growth_prepare','seo_apply_action','seo_verify_action')
                   AND status IN ('queued','retry','running')
                 ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                          COALESCE(run_after,created_at),id LIMIT ?""",
            (limit,)
        ).fetchall()
        return [
            {'id':int(r['id']),'project_id':int(r['project_id']),
             'job_type':r['job_type'],'status':r['status'],
             'attempts':int(r['attempts'] or 0),'max_attempts':int(r['max_attempts'] or 0),
             'run_after':r['run_after'],'due':bool(r['status'] in ('queued','retry') and
                 (not r['run_after'] or str(r['run_after'])<=nowv)),
             'updated_at':r['updated_at']} for r in rows]
    finally:
        conn.close()

def work_queue():
    """Bounded SEO worker only. Must be cron-locked with flock; NO full tick here.

    Work that writes remotely is still controlled by existing per-action approval.
    Do not start other syncs, operator plans, emails or crawls from this entrypoint.
    """
    wb.touch_worker('seo_queue', 'running', {'phase': 'recovery'})
    try:
        recovered = recover_stale_jobs()
        migrated = migrate_legacy_queue()
        wb.touch_worker('seo_queue', 'running', {'phase': 'jobs'})
        before = work_queue_status()
        processed = process_seo_apply_jobs(limit_jobs=3)
        # Scheduled verification jobs are handled by the same queue processor.
        # Legacy applied actions without jobs can be reconciled through 'verify' manually.
        status = work_queue_status()
        print(f"SEO QUEUE: recovered={recovered} migrated={migrated} attempted={processed} (attempted is NOT completed)")
        print('SEO QUEUE BEFORE: ' + json.dumps(before, ensure_ascii=False, sort_keys=True))
        print('SEO QUEUE AFTER: ' + json.dumps(status, ensure_ascii=False, sort_keys=True))
        print('SEO QUEUE PENDING: ' + json.dumps(work_queue_pending_details(), ensure_ascii=False))
        wb.touch_worker('seo_queue', 'idle', {'recovered': recovered, 'migrated': migrated, 'processed': processed})
    except Exception as exc:
        wb.touch_worker('seo_queue', 'error', {'error_type': type(exc).__name__})
        raise


def doctor():
    """Read-only production diagnostics. Prints no secrets."""
    print(f"Web Booster {wb.APP_VERSION}")
    print(f"database_backend={wb.DB_BACKEND}")
    conn = wb.db()
    try:
        conn.execute("SELECT 1 AS ok").fetchone()
        print("database=OK")
        for table in ("users", "projects", "project_members", "access_requests", "automation_rules", "jobs", "actions", "notifications", "email_outbox", "workers", "engine_runs"):
            try:
                count = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                print(f"table {table}: {count}")
            except Exception as exc:
                print(f"table {table}: ERROR {exc}")
        rows = conn.execute("SELECT status,COUNT(*) c FROM jobs GROUP BY status ORDER BY status").fetchall()
        print("jobs=" + json.dumps({r["status"]: int(r["c"]) for r in rows}, ensure_ascii=False))
        rows = conn.execute("SELECT status,COUNT(*) c FROM actions GROUP BY status ORDER BY status").fetchall()
        print("actions=" + json.dumps({r["status"]: int(r["c"]) for r in rows}, ensure_ascii=False))
    finally:
        conn.close()
    print("worker=" + json.dumps(wb.worker_state(), ensure_ascii=False))
    print("fresh_ai_engine_configured=" + str(bool(wb.os.getenv("FRESH_AI_ENGINE_URL") and wb.os.getenv("FRESH_AI_ENGINE_API_KEY"))))
    print("doctor=OK")



def merchant_organic_sync_due():
    """Read-only Merchant free listings report; at most once per day per project."""
    completed=0
    for project in list_projects():
        pid=project['id']
        integ=wb.integration_row(pid,'merchant_center')
        if not integ or integ['status']!='connected':continue
        cfg=wb.integration_config(integ)
        if not cfg.get('selected_account') or not wb.project_automation_allowed(pid):continue
        last=cfg.get('report_attempted_at') or cfg.get('report_checked_at')
        if last:
            try:
                if datetime.now()-datetime.fromisoformat(last) < timedelta(hours=24 if cfg.get('report_checked_at')==last else 6):continue
            except (TypeError,ValueError):pass
        started=wb.now()
        try:
            api=wb.merchant_api(pid)
            account=wb.merchant_connector.account_name(cfg['selected_account'])
            report=wb.merchant_connector.performance(api,account)
            cfg['report']=report
            cfg['report_checked_at']=wb.now()
            cfg['report_attempted_at']=cfg['report_checked_at']
            cfg.pop('report_last_error',None)
            wb.merchant_config_save(pid,cfg)
            conn=wb.db()
            try:
                wb.commerce_analytics.record_merchant_organic(conn,pid,report,wb.DB_BACKEND,wb.now())
                conn.commit()
            finally:conn.close()
            log_job(pid,'merchant_organic_sync','completed',result={'clicks':report['clicks'],'impressions':report['impressions']},started_at=started)
            completed+=1
        except Exception as exc:
            cfg['report_last_error']=str(exc)[:220]
            cfg['report_attempted_at']=wb.now()
            try: wb.merchant_config_save(pid,cfg)
            except Exception: pass
            log_job(pid,'merchant_organic_sync','failed',result={'error':str(exc)[:220]},started_at=started)
            print(f'merchant report project {pid}: ERROR {exc}')
    return completed


def analytics_backfill():
    """Materialize latest snapshots without external network calls."""
    total=0
    for project in list_projects():
        pid=project['id']; conn=wb.db()
        try:
            snapshots=conn.execute("SELECT provider,payload,captured_at FROM source_snapshots WHERE project_id=? AND provider IN ('ga4','search_console') ORDER BY id DESC LIMIT 120",(pid,)).fetchall()
            # Replay oldest first so the newest snapshot wins overlapping daily keys.
            for snapshot in reversed(snapshots):
                try: payload=json.loads(snapshot['payload'] or '{}')
                except (ValueError,TypeError):continue
                total+=wb.commerce_analytics.record_snapshot(conn,pid,snapshot['provider'],payload,wb.DB_BACKEND,snapshot['captured_at'])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:conn.close()
    return total

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "tick":
        tick()
    elif cmd in ("work-queue", "seo-apply"):
        locked_work_queue()
    elif cmd == "connector-heartbeat":
        locked_connector_heartbeat()
    elif cmd == "daily-sync":
        flags = sys.argv[2:]
        force = "--force" in flags
        def option(name):
            if name not in flags:
                return None
            idx = flags.index(name) + 1
            if idx >= len(flags):
                raise SystemExit("Chybí hodnota pro " + name)
            return flags[idx]
        project_value = option("--project")
        project_id = int(project_value) if project_value is not None else None
        provider = option("--provider")
        if provider is not None and provider not in ("core", "search_console", "ga4", "gtm", "pagespeed_crux"):
            raise SystemExit("Nepodporovaný zdroj synchronizace.")
        locked_daily_sync(force=force, project_id=project_id, provider=provider)
    elif cmd == "work-queue-errors":
        project_id = int(sys.argv[2]) if len(sys.argv)>2 else 3
        print(json.dumps(work_queue_errors(project_id), ensure_ascii=False, indent=2))
    elif cmd == "work-queue-status":
        print(json.dumps(work_queue_status(), ensure_ascii=False, indent=2, sort_keys=True))
        print('seo_queue_worker=' + json.dumps(wb.worker_state('seo_queue'), ensure_ascii=False))
        print('seo_queue_pending=' + json.dumps(work_queue_pending_details(), ensure_ascii=False))
    elif cmd == "core-sync":
        core_sync_all()
    elif cmd == "verify":
        verify_applied_actions()
    elif cmd == "analytics-sync":
        # Read-only analytical API collection; unlike tick this never applies SEO edits.
        locked_daily_sync(force=True)
        print("Ruční analytics-sync proběhl přes stejnou serializovanou a evidovanou cestu jako denní sync.")
    elif cmd == "analytics-backfill":
        print("Materialized observations:", analytics_backfill())
    elif cmd == "gsc-sync":
        gsc_sync_due()
    elif cmd == "ga4-sync":
        ga4_sync_due()
    elif cmd == "performance-sync":
        performance_sync_due()
    elif cmd == "gtm-sync":
        gtm_sync_due()
    elif cmd == "operator":
        operator_cycles_due()
    elif cmd == "catalog-sync":
        print(wb.catalog_workflow_all(limit=10))
    elif cmd == "doctor":
        doctor()
    else:
        raise SystemExit("Usage: python manage.py [tick|connector-heartbeat|daily-sync [--force] [--project ID] [--provider NAME]|work-queue|work-queue-status|work-queue-errors|analytics-sync|analytics-backfill|core-sync|seo-apply|verify|gsc-sync|ga4-sync|performance-sync|gtm-sync|operator|catalog-sync|doctor]")


if __name__ == "__main__":
    main()
