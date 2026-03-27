#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag


DEFAULT_ROOT_URL = "https://datacube.foundersc.com/document/2"


@dataclass
class TableSection:
    title: str
    headers: list[str]
    rows: list[dict[str, str]]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_doc_id(target: str) -> str | None:
    if target.isdigit():
        return target
    parsed = urlparse(target)
    if not parsed.scheme or not parsed.netloc:
        return None
    values = parse_qs(parsed.query).get("doc_id")
    return values[0] if values else None


def resolve_target(target: str, root_url: str) -> tuple[str | None, str]:
    doc_id = extract_doc_id(target)
    if target.isdigit():
        return doc_id, f"{root_url}?doc_id={doc_id}"
    return doc_id, target


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(request) as response:
        return response.read().decode("utf-8", "ignore")


def parse_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in text.splitlines():
        line = normalize_text(line)
        if not line:
            continue
        if "：" in line:
            key, value = line.split("：", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        meta[normalize_text(key)] = normalize_text(value)
    return meta


def find_content_root(soup: BeautifulSoup) -> Tag:
    content = soup.select_one("div.content")
    if content is None:
        raise SystemExit("Could not locate DataCube document content container.")
    return content


def find_meta_paragraph(content: Tag) -> Tag | None:
    for paragraph in content.find_all("p", recursive=False):
        text = paragraph.get_text("\n", strip=True)
        if "接口" in text and ("描述" in text or "限量" in text):
            return paragraph
    for paragraph in content.find_all("p"):
        text = paragraph.get_text("\n", strip=True)
        if "接口" in text and ("描述" in text or "限量" in text):
            return paragraph
    return None


def parse_table(table: Tag, title: str) -> TableSection:
    header_row = table.find("thead")
    if header_row is not None:
        headers = [
            normalize_text(cell.get_text(" ", strip=True))
            for cell in header_row.find_all(["th", "td"])
        ]
        body_rows = table.find_all("tbody")
        tr_list = body_rows[0].find_all("tr", recursive=False) if body_rows else table.find_all("tr")[1:]
    else:
        tr_all = table.find_all("tr")
        if not tr_all:
            return TableSection(title=title, headers=[], rows=[])
        headers = [
            normalize_text(cell.get_text(" ", strip=True))
            for cell in tr_all[0].find_all(["th", "td"])
        ]
        tr_list = tr_all[1:]

    rows: list[dict[str, str]] = []
    for tr in tr_list:
        cells = [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if not any(cells):
            continue
        row: dict[str, str] = {}
        for index, cell in enumerate(cells):
            key = headers[index] if index < len(headers) and headers[index] else f"column_{index + 1}"
            row[key] = cell
        rows.append(row)
    return TableSection(title=title, headers=headers, rows=rows)


def extract_sections(content: Tag) -> dict[str, TableSection]:
    sections: dict[str, TableSection] = {}
    targets = ("输入参数", "输出参数", "表信息")

    for paragraph in content.find_all("p"):
        title = normalize_text(paragraph.get_text(" ", strip=True))
        if title not in targets or title in sections:
            continue

        sibling = paragraph.find_next_sibling()
        while sibling is not None and getattr(sibling, "name", None) not in {"table", "p", "h2", "h3"}:
            sibling = sibling.find_next_sibling()

        if sibling is not None and sibling.name == "table":
            sections[title] = parse_table(sibling, title)

    return sections


def extract_examples(content: Tag) -> list[str]:
    scored_examples: list[tuple[int, int, str]] = []
    for block in content.find_all("pre"):
        code = block.get_text("\n", strip=True).strip()
        if code:
            score = 0
            if "pro.query(" in code:
                score += 3
            if re.search(r"\bpro\.[a-zA-Z0-9_]+\(", code) and "pro_api" not in code:
                score += 2
            if "pro_api(" in code:
                score += 1
            scored_examples.append((score, len(scored_examples), code))
    scored_examples.sort(key=lambda item: (-item[0], item[1]))
    return [code for _, _, code in scored_examples]


def build_contract_payload(target: str, root_url: str) -> dict[str, Any]:
    doc_id, url = resolve_target(target, root_url)
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    content = find_content_root(soup)

    title_tag = content.find("h2")
    title = normalize_text(title_tag.get_text(" ", strip=True)) if title_tag else ""

    meta_paragraph = find_meta_paragraph(content)
    meta = parse_meta(meta_paragraph.get_text("\n", strip=True)) if meta_paragraph else {}
    sections = extract_sections(content)
    examples = extract_examples(content)

    input_rows = sections.get("输入参数", TableSection("输入参数", [], [])).rows
    output_rows = sections.get("输出参数", TableSection("输出参数", [], [])).rows
    required_params = [row for row in input_rows if row.get("必选", "").upper() in {"Y", "YES", "TRUE", "1"}]
    optional_params = [row for row in input_rows if row not in required_params]

    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "url": url,
        "title": title,
        "api_name": meta.get("接口", ""),
        "meta": meta,
        "required_params": required_params,
        "optional_params": optional_params,
        "input_params": input_rows,
        "output_params": output_rows,
        "output_fields": [row.get("名称", "") for row in output_rows if row.get("名称")],
        "examples": examples,
    }

    if "表信息" in sections:
        payload["table_info"] = sections["表信息"].rows

    return payload


def render_param_rows(rows: list[dict[str, str]], include_required: bool) -> list[str]:
    lines: list[str] = []
    for row in rows:
        name = row.get("名称", "<unknown>")
        row_type = row.get("类型", "")
        required = row.get("必选", "")
        desc = row.get("描述", "")
        bits = [name]
        if row_type:
            bits.append(f"type={row_type}")
        if include_required and required:
            bits.append(f"required={required}")
        if desc:
            bits.append(desc)
        lines.append(" - " + " | ".join(bits))
    return lines


def render_output_rows(rows: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        name = row.get("名称", "<unknown>")
        row_type = row.get("类型", "")
        default = row.get("默认显示", "")
        desc = row.get("描述", "")
        bits = [name]
        if row_type:
            bits.append(f"type={row_type}")
        if default:
            bits.append(f"default={default}")
        if desc:
            bits.append(desc)
        lines.append(" - " + " | ".join(bits))
    return lines


def render_text(payload: dict[str, Any], example_limit: int) -> str:
    lines: list[str] = []
    lines.append(f"Title: {payload['title']}")
    if payload.get("doc_id"):
        lines.append(f"Doc ID: {payload['doc_id']}")
    lines.append(f"URL: {payload['url']}")
    if payload.get("api_name"):
        lines.append(f"API: {payload['api_name']}")

    meta = payload.get("meta", {})
    for key in ("描述", "限量", "更新", "数据更新频率", "数据更新时间", "积分"):
        value = meta.get(key)
        if value:
            lines.append(f"{key}: {value}")

    lines.append("")
    lines.append(f"Required Params ({len(payload['required_params'])})")
    lines.extend(render_param_rows(payload["required_params"], include_required=False))

    lines.append("")
    lines.append(f"Optional Params ({len(payload['optional_params'])})")
    lines.extend(render_param_rows(payload["optional_params"], include_required=False))

    lines.append("")
    lines.append(f"Output Fields ({len(payload['output_params'])})")
    lines.extend(render_output_rows(payload["output_params"]))

    if payload.get("table_info"):
        lines.append("")
        lines.append("Table Info")
        for row in payload["table_info"]:
            name = row.get("表名", "")
            chinese_name = row.get("表中文名", "")
            desc = row.get("说明", "")
            bits = [bit for bit in (chinese_name, name, desc) if bit]
            lines.append(" - " + " | ".join(bits))

    if payload.get("examples"):
        lines.append("")
        lines.append(f"Examples ({min(example_limit, len(payload['examples']))})")
        for example in payload["examples"][:example_limit]:
            lines.append("```")
            lines.append(example)
            lines.append("```")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract DataCube document contract details such as api_name, "
            "input params, output fields, and sample code."
        )
    )
    parser.add_argument(
        "target",
        help="Document doc_id or a full DataCube document URL.",
    )
    parser.add_argument(
        "--root-url",
        default=DEFAULT_ROOT_URL,
        help=f"Base document URL used when target is a doc_id. Default: {DEFAULT_ROOT_URL}",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Default: text.",
    )
    parser.add_argument(
        "--example-limit",
        type=int,
        default=3,
        help="Maximum number of example code blocks to print. Default: 3.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        payload = build_contract_payload(args.target, args.root_url)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to extract contract: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(render_text(payload, example_limit=args.example_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
