#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from tushare_plus import DataCubeAPI


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_key_value(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"Expected key=value, got: {raw}")
    key, value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError(f"Parameter key cannot be empty: {raw}")
    return key, parse_value(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download DataCube data with tushare_plus.DataCubeAPI.get_data()."
    )
    parser.add_argument("api_name", help="DataCube API name, for example: daily")
    parser.add_argument(
        "--fields",
        default="",
        help="Comma-separated field list. Default: all fields returned by the API.",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable API parameter. Values are parsed as JSON when possible.",
    )
    parser.add_argument(
        "--params-json",
        help="JSON object containing API parameters, for example: '{\"ts_code\": \"000001.SZ\"}'",
    )
    parser.add_argument(
        "--split-by",
        help=(
            "Repeat the request by overriding a single API parameter, "
            "for example: --split-by trade_date."
        ),
    )
    parser.add_argument(
        "--split-values",
        help=(
            "Comma-separated split values or a JSON array string, "
            "for example: 20260309,20260310 or '[\"000001.SZ\", \"000002.SZ\"]'."
        ),
    )
    parser.add_argument(
        "--split-values-file",
        type=Path,
        help=(
            "Load split values from a .txt, .csv, .tsv, or .json file. "
            "CSV/JSON records default to the --split-by column unless --split-column is set."
        ),
    )
    parser.add_argument(
        "--split-column",
        help="Column/key name to read from CSV/JSON records when using --split-values-file.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep processing remaining split values when one batch request fails.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional pause between split requests. Default: 0.",
    )
    parser.add_argument(
        "--token",
        help="Override DATACUBE_TOKEN for this command only.",
    )
    parser.add_argument(
        "--no-auto-paging",
        action="store_true",
        help="Disable automatic pagination.",
    )
    parser.add_argument(
        "--concurrent",
        action="store_true",
        help="Enable concurrent paging requests.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Maximum pages to request. Mainly useful with concurrent mode.",
    )
    parser.add_argument(
        "--limit-per-request",
        type=int,
        help=(
            "Override the runtime-detected page size. Use only after the interface limit "
            "has been verified or for bounded smoke tests."
        ),
    )
    parser.add_argument(
        "--no-detect-limit",
        action="store_true",
        help=(
            "Skip request-limit detection and use the client fallback page size when "
            "--limit-per-request is not set. Advanced repeat-run option; keep detection "
            "enabled for first-time interface use."
        ),
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=60.0,
        help="Per-request HTTP timeout in seconds. Default: 60.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry count for retryable API or transport failures. Default: 3.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="Initial retry delay in seconds. Default: 1.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Exponential retry backoff multiplier. Default: 2.",
    )
    parser.add_argument(
        "--retry-jitter",
        type=float,
        default=0.1,
        help="Retry jitter ratio applied to the current delay. Default: 0.1.",
    )
    parser.add_argument(
        "--max-retry-delay",
        type=float,
        default=60.0,
        help="Maximum retry sleep in seconds. Default: 60.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output file path. Suffix decides the format unless --format is set.",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "json", "parquet"),
        help="Output format override. Default: infer from --out suffix, else csv.",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=5,
        help="Rows to print as a preview. Use 0 to suppress the preview.",
    )
    return parser


def merge_params(raw_params: list[str], params_json: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if params_json:
        try:
            data = json.loads(params_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid --params-json value: {exc}") from exc
        if not isinstance(data, dict):
            raise SystemExit("--params-json must decode to a JSON object")
        params.update(data)

    for raw in raw_params:
        key, value = parse_key_value(raw)
        params[key] = value

    return params


def resolve_format(path: Path | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    if path is None:
        return "csv"

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    if suffix == ".parquet":
        return "parquet"
    raise SystemExit(
        f"Cannot infer output format from suffix '{suffix or '<none>'}'. "
        "Use --format csv|json|parquet."
    )


def write_output(df: Any, path: Path, output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "csv":
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return
    if output_format == "json":
        path.write_text(
            df.to_json(orient="records", force_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    if output_format == "parquet":
        df.to_parquet(path, index=False)
        return
    raise SystemExit(f"Unsupported output format: {output_format}")


def parse_split_values_arg(raw: str) -> list[Any]:
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid --split-values JSON array: {exc}") from exc
        if not isinstance(data, list):
            raise SystemExit("--split-values JSON input must decode to an array")
        return data
    return [parse_value(item.strip()) for item in raw.split(",") if item.strip()]


def load_split_values_from_table_file(path: Path, column: str | None) -> list[Any]:
    suffix = path.suffix.lower()
    delimiter = "\t" if suffix == ".tsv" else ","
    sample = path.read_text(encoding="utf-8").splitlines()
    if not sample:
        return []

    has_header = False
    try:
        has_header = csv.Sniffer().has_header("\n".join(sample[:5]))
    except csv.Error:
        has_header = False

    values: list[Any] = []
    if has_header:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if reader.fieldnames is None:
                return []
            target_column = column or reader.fieldnames[0]
            if target_column not in reader.fieldnames:
                raise SystemExit(
                    f"Column '{target_column}' not found in {path}. "
                    f"Available columns: {', '.join(reader.fieldnames)}"
                )
            for row in reader:
                cell = (row.get(target_column) or "").strip()
                if cell:
                    values.append(parse_value(cell))
        return values

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            if not row:
                continue
            cell = row[0].strip()
            if cell:
                values.append(parse_value(cell))
    return values


def load_split_values_from_json_file(path: Path, column: str | None) -> list[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc

    if isinstance(data, list):
        if all(not isinstance(item, dict) for item in data):
            return data
        if column is None:
            raise SystemExit(
                f"{path} contains JSON objects. Use --split-column to choose a field."
            )
        values: list[Any] = []
        for item in data:
            if not isinstance(item, dict):
                raise SystemExit(
                    f"{path} mixes scalar and object entries; only one shape is supported."
                )
            if column not in item:
                raise SystemExit(f"Column '{column}' not found in one of the JSON records in {path}.")
            values.append(item[column])
        return values

    if isinstance(data, dict):
        if "values" in data and isinstance(data["values"], list):
            return data["values"]
        if column and isinstance(data.get(column), list):
            return data[column]

    raise SystemExit(
        f"Unsupported JSON structure in {path}. "
        "Expected an array, {'values': [...]}, or an object containing the requested column as an array."
    )


def load_split_values_from_file(path: Path, column: str | None) -> list[Any]:
    if not path.exists():
        raise SystemExit(f"Split values file does not exist: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_split_values_from_json_file(path, column)
    if suffix in {".csv", ".tsv"}:
        return load_split_values_from_table_file(path, column)

    values: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            values.append(parse_value(line))
    return values


def resolve_split_values(args: argparse.Namespace) -> list[Any]:
    values: list[Any] = []

    if not args.split_by:
        if args.split_values or args.split_values_file or args.split_column:
            raise SystemExit("--split-values/--split-values-file require --split-by")
        return values

    if args.split_values:
        values.extend(parse_split_values_arg(args.split_values))

    if args.split_values_file:
        column = args.split_column or args.split_by
        values.extend(load_split_values_from_file(args.split_values_file, column))

    if not values:
        raise SystemExit(
            "--split-by requires at least one value from --split-values or --split-values-file"
        )

    return values


def run_single_request(
    client: DataCubeAPI,
    api_name: str,
    fields: str,
    auto_paging: bool,
    concurrent: bool,
    max_pages: int | None,
    limit_per_request: int | None,
    detect_limit: bool,
    params: dict[str, Any],
) -> Any:
    return client.get_data(
        api_name,
        fields=fields,
        auto_paging=auto_paging,
        concurrent=concurrent,
        max_pages=max_pages,
        limit_per_request=limit_per_request,
        detect_limit=detect_limit,
        **params,
    )


def run_split_requests(
    client: DataCubeAPI,
    args: argparse.Namespace,
    params: dict[str, Any],
    split_values: list[Any],
) -> Any:
    frames: list[Any] = []
    failures = 0

    for index, value in enumerate(split_values, start=1):
        batch_params = dict(params)
        batch_params[args.split_by] = value
        label = f"{args.split_by}={value}"

        try:
            df = run_single_request(
                client=client,
                api_name=args.api_name,
                fields=args.fields,
                auto_paging=not args.no_auto_paging,
                concurrent=args.concurrent,
                max_pages=args.max_pages,
                limit_per_request=args.limit_per_request,
                detect_limit=not args.no_detect_limit,
                params=batch_params,
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(
                f"[{index}/{len(split_values)}] failed: {label} -> {exc}",
                file=sys.stderr,
            )
            if not args.continue_on_error:
                raise
        else:
            print(
                f"[{index}/{len(split_values)}] {label} -> {len(df)} rows",
                file=sys.stderr,
            )
            frames.append(df)

        if args.sleep_seconds > 0 and index < len(split_values):
            time.sleep(args.sleep_seconds)

    if not frames:
        if failures > 0:
            raise SystemExit("All split requests failed or returned no dataframe.")
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    print(
        f"Split requests: {len(frames)}/{len(split_values)} succeeded",
        file=sys.stderr,
    )
    return merged


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    params = merge_params(args.param, args.params_json)
    split_values = resolve_split_values(args)
    if args.no_detect_limit and args.limit_per_request is None:
        print(
            "Warning: --no-detect-limit without --limit-per-request uses the client fallback "
            "page size. Keep detection enabled for first-time interface use.",
            file=sys.stderr,
        )

    try:
        client_kwargs = {
            "request_timeout": args.request_timeout,
            "max_retries": args.max_retries,
            "retry_delay": args.retry_delay,
            "retry_backoff": args.retry_backoff,
            "retry_jitter": args.retry_jitter,
            "max_retry_delay": args.max_retry_delay,
        }
        if args.token:
            client_kwargs["token"] = args.token
        client = DataCubeAPI(**client_kwargs)
        if split_values:
            df = run_split_requests(client=client, args=args, params=params, split_values=split_values)
        else:
            df = run_single_request(
                client=client,
                api_name=args.api_name,
                fields=args.fields,
                auto_paging=not args.no_auto_paging,
                concurrent=args.concurrent,
                max_pages=args.max_pages,
                limit_per_request=args.limit_per_request,
                detect_limit=not args.no_detect_limit,
                params=params,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"DataCube request failed: {exc}", file=sys.stderr)
        return 1

    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    if len(df.columns) > 0:
        print("Column names:", ", ".join(str(name) for name in df.columns))

    if args.preview_rows > 0:
        if df.empty:
            print("Preview: <empty dataframe>")
        else:
            print("\nPreview:")
            print(df.head(args.preview_rows).to_string(index=False))

    if args.out:
        output_format = resolve_format(args.out, args.format)
        try:
            write_output(df, args.out, output_format)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to write output: {exc}", file=sys.stderr)
            return 1
        print(f"\nSaved: {args.out.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
