#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 0 ]; then
  echo "Error: this script does not accept command-line arguments. Run it as: ./run.sh" >&2
  exit 2
fi

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python3 -m rpchelper.main
