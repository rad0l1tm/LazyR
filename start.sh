#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -n "${VIRTUAL_ENV:-}" ]]; then exec python app.py "$@"; fi
if [[ -x .venv/bin/python ]]; then exec .venv/bin/python app.py "$@"; fi
printf '%s\n' 'Сначала выполните bash setup.sh' >&2
exit 1
