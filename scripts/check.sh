#!/usr/bin/env bash
# Runs the same checks as CI. Usage: bash scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv/Scripts/python ]; then BIN=.venv/Scripts; else BIN=.venv/bin; fi

echo "== lint"
"$BIN/ruff" check .
"$BIN/ruff" format --check .
echo "== migrations";  "$BIN/python" manage.py makemigrations --check --dry-run
echo "== deploy check"
DJANGO_SETTINGS_MODULE=config.settings.prod ALLOWED_HOSTS=example.com \
  SECRET_KEY="local-deploy-check-$(date +%s)-padding-padding-padding-padding" \
  "$BIN/python" manage.py check --deploy --fail-level ERROR
echo "== tests";       "$BIN/pytest" --cov=apps --cov-report=term:skip-covered "$@"
