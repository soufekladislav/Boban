#!/usr/bin/env bash
# Print safe cPanel cron entries. Never modify the server's crontab implicitly.
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$BASE_DIR/scripts/run_boban_cron.sh"
cat <<EOF
Vlož do cPanel > Cron Jobs:
* * * * * /bin/bash "$RUNNER" queue >> "$BASE_DIR/queue_cron.log" 2>&1
*/5 * * * * /bin/bash "$RUNNER" daily >> "$BASE_DIR/daily_cron.log" 2>&1
*/15 * * * * /bin/bash "$RUNNER" heartbeat >> "$BASE_DIR/heartbeat_cron.log" 2>&1
*/15 * * * * /bin/bash "$RUNNER" cycle >> "$BASE_DIR/boban_cycle_cron.log" 2>&1

Synchronizace si sama ověřuje čas Europe/Prague a začne po 05:00.
Úspěšně načtený zdroj se ve stejný den automaticky znovu nestahuje.\nHeartbeat ověřuje konektory zvlášť každých 15 minut, bez stahování statistik.\nBobanův plánovač každých 15 minut prověří, zda nastal čas k dalšímu naplánovanému úkolu; nové SEO změny pouze připravuje ke schválení.\nV cPanelu ověř, že příkazy skutečně běží: samotné přidání souborů cron nenainstaluje.
Nechávej vypnuté původní duplicitní cron příkazy 'manage.py tick',
'manage.py seo-apply' a 'manage.py analytics-sync'.
VIRTUALENV Python nastav přes WEBBOOSTER_PYTHON v prostředí cronu.
EOF
