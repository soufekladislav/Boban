#!/usr/bin/env bash
# Print safe cPanel cron entries. Never modify the server's crontab implicitly.
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$BASE_DIR/scripts/run_boban_cron.sh"
cat <<EOF
Vlož do cPanel > Cron Jobs:
* * * * * /bin/bash "$RUNNER" queue >> "$BASE_DIR/queue_cron.log" 2>&1
*/5 * * * * /bin/bash "$RUNNER" daily >> "$BASE_DIR/daily_cron.log" 2>&1

Synchronizace si sama ověřuje čas Europe/Prague a začne po 05:00.
Úspěšně načtený zdroj se ve stejný den automaticky znovu nestahuje.
Nechávej vypnuté původní duplicitní cron příkazy 'manage.py tick',
'manage.py seo-apply' a 'manage.py analytics-sync'.
VIRTUALENV Python nastav přes WEBBOOSTER_PYTHON v prostředí cronu.
EOF
