#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  python3 -m venv .venv
  exec .venv/bin/python setup.py "$@"
fi
exec python setup.py "$@"
