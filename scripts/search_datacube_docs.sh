#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python >/dev/null 2>&1; then
  printf 'Missing required command: python\n' >&2
  exit 1
fi

exec python "$SCRIPT_DIR/search_datacube_docs.py" "$@"
