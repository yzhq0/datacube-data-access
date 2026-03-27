#!/usr/bin/env bash
set -euo pipefail

ROOT_URL="${DATACUBE_DOC_ROOT:-https://datacube.foundersc.com/document/2}"
DOC_ID=""
PATTERN=""
CONTEXT=2
LINES=""
RENDERER="${DATACUBE_DOC_RENDERER:-auto}"

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

Environment:
  DATACUBE_DOC_RENDERER  Force the page-dump backend: auto, w3m, lynx, or python.
                         Default: auto. Auto prefers python on Windows and w3m
                         then lynx on Unix, with python as the final fallback.
EOF
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

is_windows_platform() {
  if [[ "${OS:-}" == "Windows_NT" ]]; then
    return 0
  fi

  case "$(uname -s 2>/dev/null || printf 'unknown')" in
    CYGWIN*|MINGW*|MSYS*)
      return 0
      ;;
  esac

  return 1
}

pick_renderer() {
  case "$RENDERER" in
    auto)
      if is_windows_platform; then
        if have_cmd python; then
          printf 'python\n'
          return 0
        fi
        if have_cmd w3m; then
          printf 'w3m\n'
          return 0
        fi
        if have_cmd lynx; then
          printf 'lynx\n'
          return 0
        fi
      else
        if have_cmd w3m; then
          printf 'w3m\n'
          return 0
        fi
        if have_cmd lynx; then
          printf 'lynx\n'
          return 0
        fi
        if have_cmd python; then
          printf 'python\n'
          return 0
        fi
      fi
      printf 'No supported doc renderer found. Install python, w3m, or lynx.\n' >&2
      exit 1
      ;;
    w3m|lynx|python)
      need_cmd "$RENDERER"
      printf '%s\n' "$RENDERER"
      ;;
    *)
      printf 'Unsupported DATACUBE_DOC_RENDERER: %s\nExpected one of: auto, w3m, lynx, python\n' "$RENDERER" >&2
      exit 1
      ;;
  esac
}

render_with_python() {
  local page_url="$1"
  python - "$page_url" <<'PY'
from __future__ import annotations

import html
import re
import sys
import urllib.request

page_url = sys.argv[1]
request = urllib.request.Request(
    page_url,
    headers={"User-Agent": "Codex Datacube Skill/1.0"},
)

with urllib.request.urlopen(request) as response:
    charset = response.headers.get_content_charset() or "utf-8"
    page = response.read().decode(charset, "ignore")

page = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", page)
page = re.sub(r"(?i)<br\s*/?>", "\n", page)
page = re.sub(r"(?i)<hr[^>]*>", "\n----------------------------------------\n", page)
page = re.sub(r"(?i)<li[^>]*>", "\n- ", page)
page = re.sub(r"(?i)</(p|div|section|article|header|footer|aside|main|ul|ol|li|table|thead|tbody|tfoot|tr|h1|h2|h3|h4|h5|h6|pre)>", "\n", page)
page = re.sub(r"(?i)</(td|th)>", "\t", page)
page = re.sub(r"(?is)<[^>]+>", "", page)
page = html.unescape(page).replace("\xa0", " ")

lines: list[str] = []
blank_count = 0

for raw_line in page.splitlines():
    if "\t" in raw_line:
        cells = [
            re.sub(r"\s+", " ", cell).strip()
            for cell in raw_line.split("\t")
        ]
        line = "\t".join(cell for cell in cells if cell)
    else:
        line = re.sub(r"\s+", " ", raw_line).strip()

    if not line:
        blank_count += 1
        if blank_count <= 2:
            lines.append("")
        continue

    blank_count = 0
    lines.append(line)

sys.stdout.write("\n".join(lines).strip() + "\n")
PY
}

dump_page_text() {
  local page_url="$1"
  local renderer

  renderer="$(pick_renderer)"

  case "$renderer" in
    w3m)
      w3m -dump "$page_url"
      ;;
    lynx)
      lynx -dump -nolist "$page_url"
      ;;
    python)
      render_with_python "$page_url"
      ;;
  esac
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
  PAGE_URL="${ROOT_URL}?doc_id=${DOC_ID}"

  if [[ -n "$PATTERN" ]]; then
    need_cmd rg
    dump_page_text "$PAGE_URL" | rg -n -C "$CONTEXT" --color=never "$PATTERN" || true
    exit 0
  fi

  if [[ -n "$LINES" ]]; then
    dump_page_text "$PAGE_URL" | sed -n "$LINES"
    exit 0
  fi

  dump_page_text "$PAGE_URL"
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
