#!/usr/bin/env python
from __future__ import annotations

import argparse
import html
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from urllib.parse import urljoin


ROOT_URL = os.environ.get("DATACUBE_DOC_ROOT", "https://datacube.foundersc.com/document/2")
DEFAULT_RENDERER = os.environ.get("DATACUBE_DOC_RENDERER", "auto").lower()
USER_AGENT = "Codex Datacube Skill/1.0"


def is_windows_platform() -> bool:
    if os.environ.get("OS") == "Windows_NT":
        return True

    system = platform.system().lower()
    return system.startswith("win") or sys.platform.startswith(("cygwin", "msys"))


def have_cmd(command: str) -> bool:
    return shutil.which(command) is not None


def pick_renderer() -> str:
    if DEFAULT_RENDERER == "auto":
        ordered = ["python", "w3m", "lynx"] if is_windows_platform() else ["w3m", "lynx", "python"]
        for renderer in ordered:
            if renderer == "python" or have_cmd(renderer):
                return renderer
        raise SystemExit("No supported doc renderer found. Install python, w3m, or lynx.")

    if DEFAULT_RENDERER not in {"python", "w3m", "lynx"}:
        raise SystemExit(
            f"Unsupported DATACUBE_DOC_RENDERER: {DEFAULT_RENDERER}\n"
            "Expected one of: auto, w3m, lynx, python"
        )

    if DEFAULT_RENDERER != "python" and not have_cmd(DEFAULT_RENDERER):
        raise SystemExit(f"Configured DATACUBE_DOC_RENDERER={DEFAULT_RENDERER}, but the command is not available.")

    return DEFAULT_RENDERER


def fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "ignore")


def render_with_python(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", page)
    page = re.sub(r"(?i)<br\s*/?>", "\n", page)
    page = re.sub(r"(?i)<hr[^>]*>", "\n----------------------------------------\n", page)
    page = re.sub(r"(?i)<li[^>]*>", "\n- ", page)
    page = re.sub(
        r"(?i)</(p|div|section|article|header|footer|aside|main|ul|ol|li|table|thead|tbody|tfoot|tr|h1|h2|h3|h4|h5|h6|pre)>",
        "\n",
        page,
    )
    page = re.sub(r"(?i)</(td|th)>", "\t", page)
    page = re.sub(r"(?is)<[^>]+>", "", page)
    page = html.unescape(page).replace("\xa0", " ")

    lines: list[str] = []
    blank_count = 0

    for raw_line in page.splitlines():
        if "\t" in raw_line:
            cells = [re.sub(r"\s+", " ", cell).strip() for cell in raw_line.split("\t")]
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

    return "\n".join(lines).strip() + "\n"


def render_page(url: str) -> str:
    renderer = pick_renderer()
    if renderer == "python":
        return render_with_python(fetch_url(url))

    command = [renderer, "-dump", url]
    if renderer == "lynx":
        command.insert(2, "-nolist")

    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout if result.stdout.endswith("\n") else result.stdout + "\n"


def search_index(query: str) -> int:
    page = fetch_url(ROOT_URL)
    seen: set[tuple[str, str]] = set()
    found = False

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    for href, title in re.findall(r'<a href="([^"]+)">([^<]+)</a>', page):
        clean_title = html.unescape(title).strip()
        if not clean_title:
            continue
        url = urljoin(ROOT_URL, href)
        item = (clean_title, url)
        if item in seen:
            continue
        seen.add(item)
        if pattern.search(clean_title):
            found = True
            print(f"{clean_title}\t{url}")

    return 0 if found else 1


def parse_lines(spec: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d+:\d+", spec):
        raise SystemExit(f"Invalid --lines value: {spec}\nExpected A:B, for example 600:760")
    start_text, end_text = spec.split(":", 1)
    start = int(start_text)
    end = int(end_text)
    if start > end:
        raise SystemExit(f"Invalid --lines value: {spec}\nExpected A:B with A <= B")
    return start, end


def emit_line_window(text: str, spec: str) -> None:
    start, end = parse_lines(spec)
    lines = text.splitlines()
    window = lines[start - 1 : end]
    if window:
        sys.stdout.write("\n".join(window) + "\n")


def emit_pattern_matches(text: str, pattern_text: str, context: int) -> None:
    try:
        pattern = re.compile(pattern_text)
    except re.error as exc:
        raise SystemExit(f"Invalid --pattern regex: {exc}") from exc

    lines = text.splitlines()
    matched = [line_no for line_no, line in enumerate(lines, start=1) if pattern.search(line)]
    if not matched:
        return

    included: set[int] = set()
    for line_no in matched:
        start = max(1, line_no - context)
        end = min(len(lines), line_no + context)
        included.update(range(start, end + 1))

    last_line_no = 0
    match_set = set(matched)

    for line_no in sorted(included):
        if last_line_no and line_no != last_line_no + 1:
            print("--")
        separator = ":" if line_no in match_set else "-"
        print(f"{line_no}{separator}{lines[line_no - 1]}")
        last_line_no = line_no


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search DataCube docs or dump a specific page in plain text.",
        epilog=(
            "DATACUBE_DOC_RENDERER can be set to auto, w3m, lynx, or python. "
            "Auto prefers python on Windows and w3m then lynx on Unix."
        ),
    )
    parser.add_argument("query", nargs="*", help="Keyword query when searching the root index.")
    parser.add_argument("--doc-id", help="Dump a specific doc page instead of searching the index.")
    parser.add_argument("--pattern", help="Filter the dumped page with a regex.")
    parser.add_argument("--context", type=int, default=2, help="Context lines for --pattern. Default: 2.")
    parser.add_argument("--lines", help="Print a specific inclusive line window from the dumped page, such as 600:760.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.doc_id:
        page_url = f"{ROOT_URL}?doc_id={args.doc_id}"
        text = render_page(page_url)
        if args.pattern:
            emit_pattern_matches(text, args.pattern, args.context)
            return 0
        if args.lines:
            emit_line_window(text, args.lines)
            return 0
        sys.stdout.write(text)
        return 0

    if not args.query:
        parser.error("query is required unless --doc-id is provided")

    return search_index(" ".join(args.query))


if __name__ == "__main__":
    raise SystemExit(main())
