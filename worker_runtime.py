"""Safe single-host worker locking, per-job heartbeats and Prague daily scheduling.

The lock is advisory and works only when *every* worker entrypoint uses it.
It is intentionally separate from the DB action approval/verification layer.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from zoneinfo import ZoneInfo
import fcntl
import os

PRAGUE = ZoneInfo("Europe/Prague")
HEARTBEAT_SECONDS = 10
RETRY_DAILY_MINUTES = 45


@contextmanager
def exclusive_lock(path):
    """Return False, not a fake 'completed', when another worker owns the lock."""
    handle = open(Path(path), "a+", encoding="utf-8")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class JobHeartbeat:
    """Refresh the DB lease in an independent connection while a slow API call runs."""

    def __init__(self, callback, interval=HEARTBEAT_SECONDS):
        self.callback = callback
        self.interval = max(1, float(interval))
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="boban-job-heartbeat", daemon=True)

    def _run(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.callback()
            except Exception:
                # An API operation may still finish; stale recovery remains the safety net.
                pass

    def __enter__(self):
        self.callback()
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop_event.set()
        self.thread.join(timeout=2)
        return False


def prague_now():
    return datetime.now(PRAGUE)


def utc_now():
    return datetime.now(timezone.utc)


def daily_due(state, local_now=None, force=False):
    """One successful run per Prague calendar day; failed runs retry after 45 min.

    Cron can run every 5 minutes without duplicate data pulls. Forced manual
    runs may repeat completed syncs, but never overtake an in-progress one.
    """
    local_now = local_now or prague_now()
    status = str((state or {}).get("status") or "")
    # An explicit manual request is durable and may run before 05:00.
    if status == "requested":
        return True
    if not force and local_now.hour < 5:
        return False
    if not state:
        return True
    if status == "completed" and not force:
        return False
    stamp = state.get("started_at")
    if not stamp:
        return True
    try:
        started = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = utc_now() - started.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return True
    if elapsed < timedelta(0):
        return False
    if status == "running":
        return elapsed >= timedelta(minutes=50)
    if status == "failed" and not force:
        return elapsed >= timedelta(minutes=RETRY_DAILY_MINUTES)
    return True


def public_worker_summary(worker, queue):
    """Distinguish an accepted queue, a living worker, and actual finished jobs."""
    queue = queue or {}
    worker = worker or {}
    total = int(queue.get("total") or 0)
    running = int(queue.get("running") or 0)
    retry = int(queue.get("retry") or 0)
    if not total:
        return "Dokončeno nebo nejsou čekající úlohy."
    if running and worker.get("healthy") and worker.get("status") == "running":
        return "Pracuji na úloze. Průběh aktualizuji během zpracování."
    if running:
        return "Úloha je označená jako běžící, ale worker neposílá aktuální heartbeat."
    if retry:
        return "Část úloh čeká na bezpečné opakování po chybě."
    return "Úlohy jsou ve frontě, čekají na spuštění workeru."
