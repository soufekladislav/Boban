#!/usr/bin/env bash
# Explicit opt-in only. May execute queued, previously approved remote actions.
set -euo pipefail
ROOT="/home2/lauhannq/webbooster.freshcrackers.cz"
PY="$HOME/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python"
LINE="* * * * * cd $ROOT && /usr/bin/flock -n $ROOT/.seo-worker.lock $PY manage.py work-queue >> /home2/lauhannq/webbooster-seo-worker.log 2>&1 # BOBAN_SEO_WORKER"
[[ -f "$ROOT/manage.py" && -x "$PY" ]] || { echo 'Chybi manage.py nebo Python virtualenv; cron nemenim' >&2; exit 2; }
CURRENT="$(crontab -l 2>/dev/null || true)"
if grep -q 'BOBAN_SEO_WORKER' <<< "$CURRENT"; then
  echo 'SEO cron jiz existuje; nic nemenim.'
  crontab -l | grep BOBAN_
  exit 0
fi
printf '%s\n%s\n' "$CURRENT" "$LINE" | crontab -
echo 'Pridan BOBAN_SEO_WORKER. Puvodni crony zachovany.'
crontab -l | grep BOBAN_
