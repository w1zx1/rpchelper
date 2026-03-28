#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 0 ]; then
  echo "Error: this script does not accept command-line arguments. Run it as: ./run.sh" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if command -v python3 >/dev/null 2>&1; then
  python_cmd="python3"
elif command -v python >/dev/null 2>&1; then
  python_cmd="python"
else
  echo "Error: python is not installed." >&2
  exit 1
fi

"$python_cmd" -m rpchelper.main
