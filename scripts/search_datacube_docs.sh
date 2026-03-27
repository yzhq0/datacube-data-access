#!/usr/bin/env bash
set -euo pipefail

ROOT_URL="${DATACUBE_DOC_ROOT:-https://datacube.foundersc.com/document/2}"
DOC_ID=""
PATTERN=""
CONTEXT=2
LINES=""

usage() {
  cat <<'EOF'
Search DataCube docs or dump a specific page in plain text.

Usage:
  search_datacube_docs.sh "<keyword>"
  search_datacube_docs.sh --doc-id 10303
  search_datacube_docs.sh --doc-id 10303 --pattern '输入参数|输出参数'
  search_datacube_docs.sh --doc-id 10303 --lines 600:760

Options:
  --doc-id ID       Dump a specific doc page instead of searching the index.
  --pattern REGEX   Filter the dumped page with rg -n -C <context>.
  --context N       Context lines for --pattern. Default: 2.
  --lines A:B       Print a specific inclusive line window from the dumped page.
  -h, --help        Show this help text.
EOF
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

convert_lines() {
  local spec="$1"
  if [[ "$spec" =~ ^[0-9]+:[0-9]+$ ]]; then
    printf '%sp\n' "${spec/:/,}"
    return 0
  fi
  printf 'Invalid --lines value: %s\nExpected A:B, for example 600:760\n' "$spec" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --doc-id)
      DOC_ID="${2:-}"
      shift 2
      ;;
    --pattern)
      PATTERN="${2:-}"
      shift 2
      ;;
    --context)
      CONTEXT="${2:-}"
      shift 2
      ;;
    --lines)
      LINES="$(convert_lines "${2:-}")"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [[ -n "$DOC_ID" ]]; then
  need_cmd w3m
  PAGE_URL="${ROOT_URL}?doc_id=${DOC_ID}"

  if [[ -n "$PATTERN" ]]; then
    need_cmd rg
    w3m -dump "$PAGE_URL" | rg -n -C "$CONTEXT" --color=never "$PATTERN" || true
    exit 0
  fi

  if [[ -n "$LINES" ]]; then
    w3m -dump "$PAGE_URL" | sed -n "$LINES"
    exit 0
  fi

  w3m -dump "$PAGE_URL"
  exit 0
fi

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 1
fi

QUERY="$*"
need_cmd python
python - "$ROOT_URL" "$QUERY" <<'PY'
from __future__ import annotations

import html
import re
import sys
import urllib.request
from urllib.parse import urljoin

root_url = sys.argv[1]
query = sys.argv[2]

with urllib.request.urlopen(root_url) as response:
    page = response.read().decode("utf-8", "ignore")

seen: set[tuple[str, str]] = set()
found = False

try:
    pattern = re.compile(query, re.IGNORECASE)
except re.error:
    pattern = re.compile(re.escape(query), re.IGNORECASE)

for href, title in re.findall(r'<a href="([^"]+)">([^<]+)</a>', page):
    title = html.unescape(title).strip()
    if not title:
        continue
    url = urljoin(root_url, href)
    item = (title, url)
    if item in seen:
        continue
    seen.add(item)
    if pattern.search(title):
        found = True
        print(f"{title}\t{url}")

if not found:
    sys.exit(1)
PY
