#!/bin/bash
# Denní spuštění analytické synchronizace a operátora pro Bobana
PROJECT_DIR="/home2/cesta/k/vašemu/webu/webbooster.freshcrackers.cz"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python" # Upravte cestu k venv, pokud ji používáte

cd "$PROJECT_DIR"

# Ochrana proti souběhu pomocí flock
flock -n .analytics-sync.lock "$VENV_PYTHON" manage.py analytics-sync
flock -n .operator.lock "$VENV_PYTHON" manage.py operator-run-all
