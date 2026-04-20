#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from datetime import datetime
from pathlib import Path


DEFAULT_NOTE_DIR = Path.home() / ".codex" / "state" / "datacube-data-access" / "runtime-notes"


def parse_param(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"Expected key=value, got: {raw}")
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise argparse.ArgumentTypeError(f"Expected non-empty key=value, got: {raw}")
    return key, value


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned or "runtime-note"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a Datacube runtime note into private local state.",
    )
    parser.add_argument("--task", required=True, help="Short task title.")
    parser.add_argument("--topic", required=True, help="Topic label such as etf or wind.")
    parser.add_argument("--summary", required=True, help="Observed behavior or finding.")
    parser.add_argument(
        "--evidence",
        action="append",
        required=True,
        help="Concrete evidence. Repeat for multiple evidence items.",
    )
    parser.add_argument(
        "--impact",
        required=True,
        help="Why this finding changes a decision, workflow, or risk judgment.",
    )
    parser.add_argument("--api-name", help="Observed API name.")
    parser.add_argument("--doc-id", help="Related DataCube doc_id.")
    parser.add_argument("--page-url", help="Related page URL.")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        type=parse_param,
        help="Repeatable key parameter for the note.",
    )
    parser.add_argument(
        "--status",
        choices=("tentative", "durable"),
        default="tentative",
        help="Durability of the observation. Default: tentative.",
    )
    parser.add_argument(
        "--note-dir",
        type=Path,
        default=None,
        help="Override the private runtime-note directory. Default: ~/.codex/state/datacube-data-access/runtime-notes",
    )
    return parser


def render_note(args: argparse.Namespace, timestamp: datetime) -> str:
    params = "\n".join(f"- `{key}` = `{value}`" for key, value in args.param) or "- none recorded"
    evidence = "\n".join(f"- {item}" for item in args.evidence)
    source_bits: list[str] = []
    if args.doc_id:
        source_bits.append(f"- `doc_id`: `{args.doc_id}`")
    if args.page_url:
        source_bits.append(f"- page: `{args.page_url}`")
    source = "\n".join(source_bits) or "- none recorded"

    return "\n".join(
        [
            f"# Runtime Note: {args.task}",
            "",
            f"- Date: `{timestamp.strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- Topic: `{args.topic}`",
            f"- Status: `{args.status}`",
            f"- API Name: `{args.api_name or 'unknown'}`",
            "",
            "## Source",
            source,
            "",
            "## Key Params",
            params,
            "",
            "## Observed Behavior",
            args.summary,
            "",
            "## Evidence",
            evidence,
            "",
            "## Decision Impact",
            args.impact,
            "",
        ]
    )


def resolve_note_dir(override: Path | None) -> Path:
    if override is not None:
        return override
    if raw := os.environ.get("DATACUBE_RUNTIME_NOTE_DIR"):
        return Path(raw)
    return DEFAULT_NOTE_DIR


def next_note_path(note_dir: Path, timestamp: datetime, topic: str) -> Path:
    base_name = f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{slugify(topic)}"
    note_path = note_dir / f"{base_name}.md"
    if not note_path.exists():
        return note_path

    suffix = 2
    while True:
        candidate = note_dir / f"{base_name}-{suffix}.md"
        if not candidate.exists():
            return candidate
        suffix += 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    now = datetime.now()
    note_dir = resolve_note_dir(args.note_dir)
    note_dir.mkdir(parents=True, exist_ok=True)

    note_path = next_note_path(note_dir, now, args.topic)
    note_path.write_text(render_note(args, now), encoding="utf-8")
    print(note_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
