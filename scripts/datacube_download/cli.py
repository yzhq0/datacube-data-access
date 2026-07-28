from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .job import JobError, reject_secret_keys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explore or produce verified DataCube datasets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pull = subparsers.add_parser(
        "pull",
        help="Run a bounded exploratory request.",
    )
    pull.add_argument("api_name", help="Confirmed DataCube API name.")
    pull.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable API parameter; values are parsed as JSON when possible.",
    )
    pull.add_argument(
        "--fields",
        default="",
        help="Comma-separated fields. Default: all fields returned by the API.",
    )
    pull.add_argument(
        "--out",
        type=Path,
        help="Optional exploratory .csv, .json, or .parquet output.",
    )
    pull.add_argument(
        "--preview-rows",
        type=int,
        default=5,
        help="Preview row count. Default: 5; use 0 to suppress.",
    )
    pull.add_argument(
        "--all-pages",
        action="store_true",
        help="Enable bounded automatic paging; requires --max-pages.",
    )
    pull.add_argument(
        "--max-pages",
        type=int,
        help="Positive page bound required with --all-pages.",
    )

    check = subparsers.add_parser(
        "check",
        help="Validate and hash a verified job without network or writes.",
    )
    check.add_argument("job", type=Path, help="Path to a JSON v1 job.")

    run = subparsers.add_parser(
        "run",
        help="Execute and atomically publish a verified job.",
    )
    run.add_argument("job", type=Path, help="Path to a JSON v1 job.")
    return parser


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_params(raw_params: list[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for raw in raw_params:
        if "=" not in raw:
            raise JobError(f"expected key=value, got: {raw}")
        key, raw_value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise JobError(f"parameter key cannot be empty: {raw}")
        params[key] = parse_value(raw_value)
    reject_secret_keys(params, context="pull parameters")
    return params


def parse_fields(raw: str) -> tuple[str, ...]:
    fields = tuple(item.strip() for item in raw.split(",") if item.strip())
    if len(set(fields)) != len(fields):
        raise JobError("--fields contains duplicates")
    return fields


def validate_pull_args(args: argparse.Namespace) -> None:
    if args.preview_rows < 0:
        raise JobError("--preview-rows must be non-negative")
    if args.all_pages:
        if args.max_pages is None or args.max_pages <= 0:
            raise JobError("--all-pages requires a positive --max-pages")
    elif args.max_pages is not None:
        raise JobError("--max-pages requires --all-pages")
    if args.out is not None and args.out.suffix.lower() not in {
        ".csv",
        ".json",
        ".parquet",
    }:
        raise JobError("--out must end with .csv, .json, or .parquet")
