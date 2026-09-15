#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$root_dir/.env" ]]; then
  echo "Missing .env at $root_dir/.env" >&2
  exit 1
fi

if [[ ! -x "$root_dir/.venv/bin/python" ]]; then
  echo "Python virtual environment is missing. Create it with: python3 -m venv .venv" >&2
  exit 1
fi

exec "$root_dir/.venv/bin/python" "$root_dir/scripts/kafka/list_topics.py"
