#!/usr/bin/env bash
# Safe cPanel runner. Scheduling is configured in cPanel Cron Jobs.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${WEBBOOSTER_PYTHON:-}"
if [[ -z "$PYTHON" && "$PROJECT_DIR" == "/home2/lauhannq/webbooster.freshcrackers.cz" ]]; then
    PYTHON="/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python"
fi
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
    echo "BOBAN CRON: VIRTUALENV Python není k dispozici. Nastav WEBBOOSTER_PYTHON." >&2
    exit 2
fi
cd "$PROJECT_DIR"
case "${1:-}" in
  queue) exec "$PYTHON" -u manage.py work-queue ;;
  daily) exec "$PYTHON" -u manage.py daily-sync ;;
  heartbeat) exec "$PYTHON" -u manage.py connector-heartbeat ;;
  cycle) exec "$PYTHON" -u manage.py boban-cycle ;;
  *) echo "Použití: $0 queue|daily|heartbeat|cycle" >&2; exit 2 ;;
esac
