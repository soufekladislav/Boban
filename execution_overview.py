"""User-facing execution view for Boban: what, why and evidence-based ETA.

Pure helpers. No network calls, no remote writes and no invented durations.
"""
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

PRAGUE = ZoneInfo("Europe/Prague")
ACTIVE = {"queued", "running", "retry"}
TYPES = ("seo_apply_action", "seo_verify_action", "seo_ai_prepare", "seo_growth_prepare")
LABELS = {
    "seo_apply_action": "Provádím schválenou změnu",
    "seo_verify_action": "Ověřuji výsledek změny",
    "seo_ai_prepare": "Připravuji návrhy k posouzení",
    "seo_growth_prepare": "Prověřuji růstové příležitosti",
}
WHY = {
    "seo_apply_action": "Změnu jsi schválil. Zapisuji ji do cílové služby.",
    "seo_verify_action": "Kontroluji, zda cílová služba změnu opravdu potvrdila.",
    "seo_ai_prepare": "Procházím zjištěné problémy a připravuji konkrétní řešení ke schválení.",
    "seo_growth_prepare": "Podle dat hledám opodstatněné kroky k lepším výsledkům webu.",
}


def parse_stamp(value):
    if not value:
        return None
    try:
        value = str(value).replace("Z", "+00:00")
        stamp = datetime.fromisoformat(value)
        return stamp.replace(tzinfo=PRAGUE) if stamp.tzinfo is None else stamp.astimezone(PRAGUE)
    except (TypeError, ValueError, OverflowError):
        return None


def historical_seconds(rows, min_samples=3):
    """Use observed, completed execution durations; not claimed success or AI guesses."""
    by_type = {}
    for row in rows:
        job_type = str(row.get("job_type") or "")
        start, end = parse_stamp(row.get("started_at")), parse_stamp(row.get("finished_at"))
        if job_type not in TYPES or not start or not end:
            continue
        seconds = (end - start).total_seconds()
        if 1 <= seconds <= 7200:
            by_type.setdefault(job_type, []).append(seconds)
    results = {}
    for job_type, values in by_type.items():
        if len(values) < min_samples:
            continue
        ordered = sorted(values)
        results[job_type] = {
            "samples": len(values),
            "median": int(median(ordered)),
            "p80": int(ordered[min(len(ordered) - 1, int(0.8 * len(ordered)))]),
        }
    return results


def can_prepare_more(active_prepare, awaiting_approval, limit=8):
    """Prevent autonomous planning from flooding the user's approval inbox."""
    return int(active_prepare) == 0 and int(awaiting_approval) < int(limit)


def _text(value, maximum=220):
    value = " ".join(str(value or "").split())
    return (value[:maximum - 1] + "…") if len(value) > maximum else value


def _work_item(job):
    job_type = str(job.get("job_type") or "")
    status = str(job.get("status") or "")
    target = str(job.get("target_url") or "")
    hostname = urlsplit(target).hostname if target else None
    reason = _text(job.get("action_reason")) or WHY.get(job_type, "Provedu naplánovaný krok a ověřím výsledek.")
    title = LABELS.get(job_type, "Provádím pracovní krok")
    if hostname and job_type in ("seo_apply_action", "seo_verify_action"):
        title += " na " + hostname
    return {
        "id": int(job["id"]),
        "action_id": int(job["action_id"]) if job.get("action_id") else None,
        "title": title, "why": reason, "status": status,
        "stage": {"queued": "Čeká na převzetí", "running": "Právě pracuji",
                  "retry": "Čeká na další pokus"}.get(status, "Neznámý stav"),
        "retry_at": job.get("run_after") if status == "retry" else None,
    }


def overview(jobs, historic_rows, worker, awaiting_approval, global_ahead=0, now=None):
    """Display timings only with at least three real samples per active job type.

    If a process is stale, paused or the history is too sparse, ETA is unknown.
    'Queue accepted' must not masquerade as 'running'.
    """
    now = now or datetime.now(PRAGUE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PRAGUE)
    active = [j for j in jobs if str(j.get("status")) in ACTIVE and str(j.get("job_type")) in TYPES]
    active.sort(key=lambda j: (0 if j["status"] == "running" else 1,
                               0 if j["job_type"] == "seo_apply_action" else 1,
                               int(j["id"])))
    counts = {s: sum(1 for j in active if j["status"] == s) for s in ACTIVE}
    running = next((j for j in active if j["status"] == "running"), None)
    live = bool(worker and worker.get("healthy") and worker.get("status") == "running")
    measured = historical_seconds(historic_rows)
    view = [_work_item(j) for j in active[:8]]
    waiting = int(awaiting_approval or 0)
    total = len(active)
    scheduler_known = bool(worker and worker.get("scheduler_confirmed"))
    title = ("Právě pracuji na úkolech projektu" if running and live else
             "Úkol právě běží, ale spojení s vykonavatelem nepotvrzeno" if running else
             "Nemohu potvrdit automatické převzetí úkolů" if total and not scheduler_known else
             "Úkoly čekají na provedení" if total else
             f"Čekám na schválení {waiting} návrhů" if waiting else
             "Nemám nevyřízenou práci")
    reason = (
        "Probíhá zápis, příprava návrhu nebo ověření. Postup se průběžně aktualizuje."
        if running and live else
        "Poslední potvrzení činnosti chybí. Žádný termín zatím neslibuji."
        if running else
        "Úkoly jsou připravené, ale nevidím čerstvé potvrzení automatického spouštění. Je nutná kontrola plánovače."
        if total and not scheduler_known else
        "Zařazené úkoly automaticky postupně převezmu, nemusíš je ručně spouštět."
        if total else
        "Další provedení vyžaduje tvoje rozhodnutí. Po schválení si úkol převezmu."
        if waiting else
        "Zatím nic nečeká. Nové návrhy připravím podle nastaveného plánu."
    )
    eta = None
    eta_confidence = "unavailable"
    if total and not running and not live:
        # A queue waiting for a missing cron has no trustworthy finish time.
        eta_confidence = "waiting_for_worker"
    if total and (live or not running):
        # Only published a prediction when a recent, confirmed scheduler run
        # and reliable duration samples are available.
        estimated = []
        for job in active:
            item = measured.get(str(job.get("job_type")))
            if item is None:
                estimated = []
                break
            remaining = item["p80"]
            if job["status"] == "running":
                elapsed = 0
                start = parse_stamp(job.get("started_at"))
                if start:
                    elapsed = max(0, int((now - start).total_seconds()))
                remaining = max(10, remaining - elapsed)
            if job["status"] == "retry":
                due = parse_stamp(job.get("run_after"))
                if due and due > now:
                    remaining += int((due - now).total_seconds())
            estimated.append(remaining)
        # Never calculate queue ETA from stale heartbeat or unverified cron.
        if estimated and (not running or live) and worker and worker.get("scheduler_confirmed"):
            # Global jobs ahead make these predictions optimistic; report a range.
            typical = int(median([v["median"] for v in measured.values()]))
            ahead = max(0, int(global_ahead))
            queue_items = len(estimated) + ahead
            base = sum(estimated) + ahead * typical
            # The cron-driven worker handles at most three jobs per invocation,
            # once per minute. Fast jobs do NOT imply unlimited throughput.
            cadence_floor = max(0, (queue_items - 1) // 3) * 60
            low = max(base, cadence_floor)
            high = max(int(base * 1.6), cadence_floor + 60)
            eta = {"min_minutes": max(1, (low + 59) // 60),
                   "max_minutes": max(2, (high + 59) // 60),
                   "samples": min(measured[str(j["job_type"])]["samples"] for j in active)}
            eta_confidence = "estimated_from_history"
    return {
        "title": title, "why": reason, "total": total, "running": counts["running"],
        "queued": counts["queued"], "retry": counts["retry"], "approvals": waiting,
        "items": view, "eta": eta, "eta_confidence": eta_confidence,
        "progress_label": (f"Právě provádím úlohu #{running['id']}" if running and live else
                           f"Čekám na převzetí {total} úloh" if total else
                           "Čekám na schválení" if waiting else "Bez otevřených úloh"),
        "next_retry": next((j.get("run_after") for j in active if j["status"] == "retry"), None),
    }
