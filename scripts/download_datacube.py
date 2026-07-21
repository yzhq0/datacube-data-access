#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from hashlib import sha256
import inspect
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

import pandas as pd
from tushare_plus import DataCubeAPI

try:
    from tushare_plus import PartitionPlan
except ImportError:  # Compatibility with tushare_plus releases before plan execution.
    PartitionPlan = None  # type: ignore[assignment]

from dataset_validation import (
    audit_dataset,
    build_dataset_manifest,
    filter_to_expected_keys,
    load_table,
    sha256_file,
    write_json_atomic,
)


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
        "--request-plan",
        type=Path,
        help=(
            "JSON, JSONL, CSV, or TSV file whose records contain complete parameter "
            "overrides for each request partition. Cannot be combined with --split-by; "
            "requires tushare_plus>=0.1.9."
        ),
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help=(
            "Deprecated compatibility option: finish remaining partitions, but any "
            "failure still withholds --out and exits non-zero."
        ),
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
        help="Enable concurrent paging requests within one partition.",
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
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        help=(
            "Verified partition checkpoint directory. Required implicitly for "
            "--request-plan/--split-by and otherwise derived from --out."
        ),
    )
    parser.add_argument(
        "--partition-format",
        choices=("csv", "parquet"),
        default="csv",
        help="Checkpoint partition format. Default: csv.",
    )
    parser.add_argument(
        "--partition-workers",
        type=int,
        default=1,
        help="Concurrent request partitions. Default: 1.",
    )
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        help="Resume only fingerprint/hash-verified checkpoints (default).",
    )
    resume_group.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Re-fetch every planned partition.",
    )
    parser.set_defaults(resume=True)
    parser.add_argument(
        "--execution-manifest",
        type=Path,
        help="tushare_plus execution manifest path.",
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        help="Dataset-contract manifest path; defaults beside --out.",
    )
    parser.add_argument(
        "--key-fields",
        help="Comma-separated exact dataset key fields, for example trade_date,code.",
    )
    parser.add_argument(
        "--expected-keys",
        type=Path,
        help="Independent expected-key table (csv/tsv/json/jsonl/parquet).",
    )
    parser.add_argument(
        "--filter-to-expected-keys",
        action="store_true",
        help=(
            "After entity-interval pulls, retain only exact expected keys before the "
            "hard dataset audit. Requires --expected-keys and --key-fields."
        ),
    )
    parser.add_argument(
        "--group-fields",
        help="Comma-separated group fields for cardinality validation.",
    )
    parser.add_argument(
        "--expected-group-cardinality",
        type=int,
        help=(
            "Fixed unique-key count per group. Omit when expected keys should define "
            "each group's cardinality."
        ),
    )
    parser.add_argument(
        "--validation-sample-limit",
        type=int,
        default=20,
        help="Maximum missing/extra/cardinality sample records in the manifest.",
    )
    parser.add_argument(
        "--dataset-metadata-json",
        help="Optional JSON object recorded in the dataset manifest; secrets are redacted.",
    )
    parser.add_argument(
        "--doc-id",
        type=int,
        help="Confirmed DataCube dictionary doc_id recorded in the dataset manifest.",
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


def parse_field_names(raw: str | None, *, option: str) -> tuple[str, ...]:
    if not raw:
        return ()
    fields = tuple(item.strip() for item in raw.split(",") if item.strip())
    if len(set(fields)) != len(fields):
        raise SystemExit(f"{option} contains duplicate fields")
    return fields


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return bool(
        normalized in {"token", "authorization", "credential", "credentials"}
        or normalized.endswith("_token")
        or "password" in normalized
        or "secret" in normalized
        or "api_key" in normalized
        or "access_key" in normalized
        or "private_key" in normalized
    )


def reject_secret_params(value: Any, *, context: str = "request params") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_secret_key(key):
                raise SystemExit(
                    f"{context} contains secret-bearing key '{key}'; "
                    "pass authentication through DATACUBE_TOKEN or --token instead"
                )
            reject_secret_params(item, context=context)
    elif isinstance(value, list):
        for item in value:
            reject_secret_params(item, context=context)


def _normalize_plan_record(record: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SystemExit(f"request-plan record {index} must be a JSON object")
    if "params" in record:
        params = record["params"]
        if not isinstance(params, dict):
            raise SystemExit(
                f"request-plan record {index} field 'params' must be an object"
            )
    else:
        params = record
    normalized = {str(key): value for key, value in params.items()}
    reject_secret_params(normalized, context=f"request-plan record {index}")
    return normalized


def _records_from_json_document(data: Any, *, path: Path) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("requests", "partitions", "param_chunks"):
            if key in data:
                records = data[key]
                if not isinstance(records, list):
                    raise SystemExit(f"{path}: '{key}' must be a JSON array")
                return records
        # One complete parameter mapping is a valid one-partition plan.
        return [data]
    raise SystemExit(f"{path}: request plan must be a JSON object or array")


def load_request_plan(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SystemExit(f"Request-plan file does not exist: {path}")
    suffix = path.suffix.lower()
    records: list[Any]
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON request plan {path}: {exc}") from exc
        records = _records_from_json_document(data, path=path)
    elif suffix in {".jsonl", ".ndjson"}:
        records = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Invalid JSON on line {line_number} of {path}: {exc}"
                ) from exc
    elif suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise SystemExit(f"Request-plan table has no header: {path}")
            records = [
                {
                    # CSV has no type system. Preserve exact text (including
                    # leading-zero codes); use JSON/JSONL for typed values.
                    str(key): value.strip()
                    for key, value in row.items()
                    if key is not None and value is not None and value != ""
                }
                for row in reader
            ]
    else:
        raise SystemExit("--request-plan must be .json, .jsonl, .ndjson, .csv, or .tsv")

    if not records:
        raise SystemExit(f"Request plan is empty: {path}")
    chunks = [
        _normalize_plan_record(record, index=index)
        for index, record in enumerate(records, start=1)
    ]
    fingerprints: set[str] = set()
    for index, chunk in enumerate(chunks, start=1):
        try:
            canonical = json.dumps(
                chunk,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"request-plan record {index} is not canonical JSON: {exc}"
            ) from exc
        fingerprint = sha256(canonical.encode("utf-8")).hexdigest()
        if fingerprint in fingerprints:
            raise SystemExit(f"request-plan contains duplicate record {index}")
        fingerprints.add(fingerprint)
    return chunks


def verify_contract_input_sha256(
    path: Path,
    *,
    expected_sha256: str,
    label: str,
) -> None:
    """Fail if an independent contract input no longer matches its snapshot."""

    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        observed_sha256 = sha256_file(path)
    except OSError as exc:
        raise ValueError(f"{label} contract input is unavailable: {path}") from exc
    if observed_sha256 != expected_sha256:
        raise ValueError(f"{label} contract input changed during execution: {path}")


def load_frozen_contract_input(
    path: Path,
    *,
    label: str,
    loader: Callable[[Path], Any],
) -> tuple[Any, str]:
    """Parse a contract input only when its pre/post-parse hashes agree."""

    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        frozen_sha256 = sha256_file(path)
    except OSError as exc:
        raise SystemExit(f"{label} contract input is unavailable: {path}") from exc
    value = loader(path)
    try:
        verify_contract_input_sha256(
            path,
            expected_sha256=frozen_sha256,
            label=label,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return value, frozen_sha256


def verify_frozen_contract_inputs(
    inputs: Iterable[tuple[str, Path, str]],
) -> None:
    for label, path, expected_sha256 in inputs:
        verify_contract_input_sha256(
            path,
            expected_sha256=expected_sha256,
            label=label,
        )


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


def stage_output(df: Any, path: Path, output_format: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    format_suffix = {
        "csv": ".csv",
        "json": ".json",
        "parquet": ".parquet",
    }[output_format]
    temporary = path.parent / f".{path.name}.{uuid4().hex}.staged{format_suffix}"
    write_output(df, temporary, output_format)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    return temporary


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(str(path.parent), flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _publication_lock_paths(output_path: Path, manifest_path: Path) -> list[Path]:
    candidates = {
        output_path.parent
        / f".{output_path.name}.publish-{sha256(str(output_path.resolve()).encode()).hexdigest()[:12]}.lock",
        manifest_path.parent
        / f".{manifest_path.name}.publish-{sha256(str(manifest_path.resolve()).encode()).hexdigest()[:12]}.lock",
    }
    return sorted(candidates, key=lambda path: str(path.resolve()))


@contextmanager
def publication_lock(output_path: Path, manifest_path: Path):
    lock_paths = _publication_lock_paths(output_path, manifest_path)
    acquired: list[tuple[int, Path]] = []
    try:
        for lock_path in lock_paths:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                raise RuntimeError(
                    f"dataset publication lock already exists: {lock_path}"
                ) from exc
            acquired.append((descriptor, lock_path))
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        for descriptor, lock_path in reversed(acquired):
            try:
                os.close(descriptor)
            finally:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass


def commit_staged_dataset(
    *,
    staged_output: Path,
    output_path: Path,
    manifest_path: Path,
    final_manifest: Mapping[str, Any],
) -> None:
    """Two-phase publication with rollback of a pre-existing output.

    The visible manifest is first committed as ``prepared`` and non-publishable.
    Only after the staged output replaces ``--out`` is it atomically updated to
    ``complete``.  A runtime failure rolls the output back; a process crash can
    at worst leave a new output paired with a non-publishable prepared manifest.
    """

    with publication_lock(output_path, manifest_path):
        transaction_id = uuid4().hex
        output_backup = output_path.parent / f".{output_path.name}.{transaction_id}.bak"
        manifest_backup = manifest_path.parent / f".{manifest_path.name}.{transaction_id}.bak"
        output_existed = output_path.is_file()
        manifest_existed = manifest_path.is_file()
        output_committed = False
        output_backup_ready = False
        manifest_backup_ready = False
        try:
            if output_existed:
                shutil.copy2(output_path, output_backup)
                output_backup_ready = True
            if manifest_existed:
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest_path, manifest_backup)
                manifest_backup_ready = True

            prepared_manifest = dict(final_manifest)
            prepared_manifest["publication_state"] = "prepared"
            prepared_manifest["output_published"] = False
            prepared_manifest["publishable"] = False
            completed_manifest = dict(final_manifest)
            completed_manifest["publication_state"] = "complete"
            write_json_atomic(manifest_path, prepared_manifest)
            os.replace(staged_output, output_path)
            _fsync_parent(output_path)
            output_committed = True
            write_json_atomic(manifest_path, completed_manifest)
        except BaseException:
            if output_committed:
                if output_existed and output_backup_ready:
                    os.replace(output_backup, output_path)
                    _fsync_parent(output_path)
                elif output_path.exists():
                    output_path.unlink()
                    _fsync_parent(output_path)
            if manifest_existed and manifest_backup_ready:
                os.replace(manifest_backup, manifest_path)
            raise
        finally:
            for temporary in (staged_output, output_backup, manifest_backup):
                try:
                    if temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass


def write_withheld_manifest_locked(
    *,
    output_path: Path,
    manifest_path: Path,
    payload: Mapping[str, Any],
) -> None:
    with publication_lock(output_path, manifest_path):
        write_json_atomic(manifest_path, payload)


def _safe_text(value: Any, secrets: Iterable[str | None]) -> str:
    message = str(value)
    for secret in secrets:
        if secret:
            message = message.replace(str(secret), "<redacted>")
    return message


def _safe_error_text(exc: BaseException, secrets: Iterable[str | None]) -> str:
    return _safe_text(exc, secrets)


def _redact_known_values(value: Any, secrets: Iterable[str | None]) -> Any:
    known = [str(secret) for secret in secrets if secret]
    if isinstance(value, Mapping):
        return {
            str(key): _redact_known_values(item, known)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_known_values(item, known) for item in value]
    if isinstance(value, tuple):
        return [_redact_known_values(item, known) for item in value]
    if isinstance(value, str):
        for secret in known:
            value = value.replace(secret, "<redacted>")
    return value


def _dataset_metadata(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --dataset-metadata-json: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("--dataset-metadata-json must decode to an object")
    return value


def resolve_checkpoint_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.checkpoint_dir is not None:
        checkpoint_dir = args.checkpoint_dir
    elif args.out is not None:
        checkpoint_dir = args.out.parent / f".{args.out.name}.partitions"
    else:
        safe_api = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in str(args.api_name)
        )
        checkpoint_dir = Path("output") / f"{safe_api}-partitions"
    execution_manifest = (
        args.execution_manifest
        if args.execution_manifest is not None
        else checkpoint_dir / "execution-manifest.json"
    )
    return checkpoint_dir, execution_manifest


def resolve_dataset_manifest(args: argparse.Namespace) -> Path | None:
    if args.dataset_manifest is not None:
        if args.out is None:
            raise SystemExit("--dataset-manifest requires --out")
        return args.dataset_manifest
    if args.out is None:
        return None
    return args.out.parent / f"{args.out.name}.dataset-manifest.json"


def validate_artifact_paths(
    args: argparse.Namespace,
    *,
    dataset_manifest: Path | None,
    checkpoint_dir: Path | None = None,
    execution_manifest: Path | None = None,
) -> None:
    named_paths: list[tuple[str, Path]] = []
    for name, path in (
        ("--out", args.out),
        ("--expected-keys", args.expected_keys),
        ("--request-plan", args.request_plan),
        ("--split-values-file", args.split_values_file),
        ("--dataset-manifest", dataset_manifest),
        ("--execution-manifest", execution_manifest),
    ):
        if path is not None:
            named_paths.append((name, path.resolve()))
    for index, (left_name, left_path) in enumerate(named_paths):
        for right_name, right_path in named_paths[index + 1 :]:
            if left_path == right_path:
                raise SystemExit(
                    f"{left_name} and {right_name} resolve to the same path: {left_path}"
                )

    if checkpoint_dir is None:
        return
    checkpoint = checkpoint_dir.resolve()
    if checkpoint.exists() and not checkpoint.is_dir():
        raise SystemExit(f"checkpoint directory is an existing file: {checkpoint}")
    for name, path in named_paths:
        if name == "--execution-manifest":
            continue
        if path == checkpoint or checkpoint in path.parents:
            raise SystemExit(
                f"{name} must not be the checkpoint directory or live inside it: {path}"
            )


def validate_cli_contract(
    args: argparse.Namespace,
    *,
    params: Mapping[str, Any],
    split_values: list[Any],
    key_fields: tuple[str, ...],
    group_fields: tuple[str, ...],
) -> None:
    reject_secret_params(params)
    if args.split_by and _is_secret_key(args.split_by):
        raise SystemExit(
            "--split-by cannot name a secret-bearing parameter; pass authentication "
            "through DATACUBE_TOKEN or --token"
        )
    if args.request_plan is not None and args.split_by:
        raise SystemExit("--request-plan cannot be combined with --split-by")
    if args.partition_workers <= 0:
        raise SystemExit("--partition-workers must be positive")
    if args.partition_workers > 1 and args.concurrent:
        raise SystemExit(
            "partition and page concurrency cannot be combined; choose "
            "--partition-workers or --concurrent"
        )
    if args.request_plan is not None and args.sleep_seconds > 0:
        raise SystemExit(
            "--sleep-seconds is unsupported by the verified request-plan executor; "
            "it will not be silently ignored"
        )
    if split_values and args.sleep_seconds > 0:
        raise SystemExit(
            "--sleep-seconds is unsupported after --split-by is translated to the "
            "verified request-plan executor; it will not be silently ignored"
        )
    if args.expected_keys is not None and not key_fields:
        raise SystemExit("--expected-keys requires --key-fields")
    if args.filter_to_expected_keys and (
        args.expected_keys is None or not key_fields
    ):
        raise SystemExit(
            "--filter-to-expected-keys requires --expected-keys and --key-fields"
        )
    if group_fields and not key_fields:
        raise SystemExit("--group-fields requires --key-fields")
    if not set(group_fields).issubset(key_fields):
        raise SystemExit("--group-fields must be a subset of --key-fields")
    if args.expected_group_cardinality is not None:
        if not group_fields:
            raise SystemExit(
                "--expected-group-cardinality requires --group-fields"
            )
        if args.expected_group_cardinality < 0:
            raise SystemExit("--expected-group-cardinality must be non-negative")
        if args.expected_keys is not None:
            raise SystemExit(
                "--expected-group-cardinality is redundant with --expected-keys; "
                "group expectations are derived from the expected-key table"
            )
    if args.validation_sample_limit < 0:
        raise SystemExit("--validation-sample-limit must be non-negative")


def resolve_partition_chunks(
    args: argparse.Namespace,
    *,
    split_values: list[Any],
) -> list[dict[str, Any]]:
    if args.request_plan is not None:
        return load_request_plan(args.request_plan)
    if split_values:
        return [{str(args.split_by): value} for value in split_values]
    return [{}]


def _read_partition(path: Path, *, key_fields: Iterable[str] = ()) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(
                path,
                dtype={str(field): "string" for field in key_fields},
            )
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"unexpected checkpoint partition format: {path}")


def _partition_status(partition: Any) -> str:
    return str(getattr(partition, "status", "")).lower().rsplit(".", 1)[-1]


def combine_execution_partitions(
    result: Any,
    *,
    fallback_columns: Iterable[str] = (),
    key_fields: Iterable[str] = (),
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    expected_columns: list[Any] | None = None
    for partition in sorted(result.partitions, key=lambda item: int(item.index)):
        if _partition_status(partition) not in {"written", "resumed"}:
            continue
        path_value = getattr(partition, "path", None)
        if path_value is None:
            raise ValueError(
                f"verified partition {partition.index} has no artifact path"
            )
        path = Path(path_value)
        if not path.is_file():
            raise ValueError(
                f"verified partition {partition.index} artifact is missing: {path}"
            )
        expected_hash = getattr(partition, "sha256", None)
        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        ):
            raise ValueError(
                f"verified partition {partition.index} has no valid sha256 contract"
            )
        expected_rows = getattr(partition, "row_count", None)
        if (
            isinstance(expected_rows, bool)
            or not isinstance(expected_rows, int)
            or expected_rows < 0
        ):
            raise ValueError(
                f"verified partition {partition.index} has no valid row_count contract"
            )
        hash_before_read = sha256_file(path)
        if hash_before_read != expected_hash:
            raise ValueError(
                f"verified partition {partition.index} sha256 mismatch before read"
            )
        frame = _read_partition(path, key_fields=key_fields)
        hash_after_read = sha256_file(path)
        if hash_after_read != expected_hash or hash_after_read != hash_before_read:
            raise ValueError(
                f"verified partition {partition.index} sha256 mismatch after read"
            )
        if len(frame) != expected_rows:
            raise ValueError(
                f"verified partition {partition.index} row_count mismatch: "
                f"expected {expected_rows}, observed {len(frame)}"
            )
        columns = list(frame.columns)
        if frame.empty and not columns:
            # A verified empty response can have no recoverable CSV header.  It
            # contributes no rows and must not establish or alter panel schema.
            continue
        if expected_columns is None:
            expected_columns = columns
        elif columns != expected_columns:
            raise ValueError(
                f"partition schema mismatch at index {partition.index}: "
                f"expected {expected_columns}, observed {columns}"
            )
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=list(fallback_columns))
    return pd.concat(frames, ignore_index=True)


def _pagination_payload(report: Any) -> dict[str, Any] | None:
    if report is None:
        return None
    if isinstance(report, Mapping):
        return dict(report)
    if hasattr(report, "to_dict"):
        value = report.to_dict()
        return dict(value) if isinstance(value, Mapping) else None
    return None


def audit_source_coverage(
    *,
    partition_result: Any | None,
    single_report: Any | None,
    expected_keys_provided: bool,
    auto_paging: bool,
) -> dict[str, Any]:
    if expected_keys_provided:
        return {
            "basis": "exact_expected_keys",
            "reports_checked": 0,
            "unproven_reports": 0,
            "passed": True,
        }

    if not auto_paging:
        return {
            "basis": "explicit_no_auto_paging",
            "reports_checked": 0,
            "unproven_reports": 0,
            "passed": True,
        }

    reports: list[dict[str, Any] | None] = []
    if partition_result is not None:
        for partition in partition_result.partitions:
            if _partition_status(partition) not in {"written", "resumed"}:
                continue
            reports.append(
                _pagination_payload(getattr(partition, "pagination_report", None))
            )
    else:
        reports.append(_pagination_payload(single_report))

    if not reports:
        return {
            "basis": "unproven",
            "reports_checked": 0,
            "unproven_reports": 1,
            "passed": False,
        }

    unproven = [
        (
            {"reason": "missing_pagination_report"}
            if payload is None
            else {
                "termination_reason": payload.get("termination_reason"),
                "source_exhausted": payload.get("source_exhausted"),
                "exhaustion_inferred": payload.get("exhaustion_inferred"),
            }
        )
        for payload in reports
        if payload is None
        or (
            not bool(payload.get("source_exhausted"))
            and not bool(payload.get("exhaustion_inferred"))
        )
    ]
    return {
        "basis": "pagination_source_exhaustion",
        "reports_checked": len(reports),
        "unproven_reports": len(unproven),
        "unproven_sample": unproven[:20],
        "passed": not unproven,
    }


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


def run_single_request_with_report(
    client: DataCubeAPI,
    args: argparse.Namespace,
    params: dict[str, Any],
    *,
    primary_key: tuple[str, ...],
) -> tuple[Any, Any | None]:
    signature = inspect.signature(client.get_data)
    supports_strict_report = "return_report" in signature.parameters
    kwargs: dict[str, Any] = {
        "fields": args.fields,
        "auto_paging": not args.no_auto_paging,
        "concurrent": args.concurrent,
        "max_pages": args.max_pages,
        "limit_per_request": args.limit_per_request,
        "detect_limit": not args.no_detect_limit,
        **params,
    }
    if supports_strict_report:
        kwargs.update(
            {
                "primary_key": primary_key or None,
                "strict_paging": True,
                "return_report": True,
            }
        )
        frame, report = client.get_data(args.api_name, **kwargs)
        return frame, report
    if args.max_pages is not None and args.out is not None:
        raise RuntimeError(
            "strict max_pages truncation detection requires tushare_plus>=0.1.9"
        )
    return client.get_data(args.api_name, **kwargs), None


def run_split_requests(
    client: DataCubeAPI,
    args: argparse.Namespace,
    params: dict[str, Any],
    split_values: list[Any],
    secrets: Iterable[str | None] = (),
) -> tuple[Any, int]:
    frames: list[Any] = []
    failures = 0

    for index, value in enumerate(split_values, start=1):
        batch_params = dict(params)
        batch_params[args.split_by] = value
        label = _safe_text(f"{args.split_by}={value}", secrets)

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
                f"[{index}/{len(split_values)}] failed: {label} -> "
                f"{_safe_error_text(exc, secrets)}",
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
        return pd.DataFrame(), failures

    merged = pd.concat(frames, ignore_index=True)
    print(
        f"Split requests: {len(frames)}/{len(split_values)} succeeded",
        file=sys.stderr,
    )
    return merged, failures


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    params = merge_params(args.param, args.params_json)
    split_values = resolve_split_values(args)
    key_fields = parse_field_names(args.key_fields, option="--key-fields")
    group_fields = parse_field_names(args.group_fields, option="--group-fields")
    requested_fields = parse_field_names(args.fields, option="--fields")
    if requested_fields and not set(key_fields).issubset(requested_fields):
        raise SystemExit("--key-fields must be included in --fields when fields are explicit")
    validate_cli_contract(
        args,
        params=params,
        split_values=split_values,
        key_fields=key_fields,
        group_fields=group_fields,
    )
    metadata = _dataset_metadata(args.dataset_metadata_json)
    if args.doc_id is not None:
        metadata["doc_id"] = int(args.doc_id)
    dataset_manifest_path = resolve_dataset_manifest(args)
    validate_artifact_paths(args, dataset_manifest=dataset_manifest_path)
    output_format = resolve_format(args.out, args.format) if args.out is not None else None
    expected_keys: pd.DataFrame | None = None
    expected_keys_sha256: str | None = None
    request_plan_chunks: list[dict[str, Any]] | None = None
    request_plan_sha256: str | None = None
    frozen_contract_inputs: list[tuple[str, Path, str]] = []
    if args.expected_keys is not None:
        expected_keys, expected_keys_sha256 = load_frozen_contract_input(
            args.expected_keys,
            label="--expected-keys",
            loader=lambda path: load_table(path, all_strings=True),
        )
        frozen_contract_inputs.append(
            ("--expected-keys", args.expected_keys, expected_keys_sha256)
        )
    if args.request_plan is not None:
        request_plan_chunks, request_plan_sha256 = load_frozen_contract_input(
            args.request_plan,
            label="--request-plan",
            loader=load_request_plan,
        )
        frozen_contract_inputs.append(
            ("--request-plan", args.request_plan, request_plan_sha256)
        )
    if args.no_detect_limit and args.limit_per_request is None:
        print(
            "Warning: --no-detect-limit without --limit-per-request uses the client fallback "
            "page size. Keep detection enabled for first-time interface use.",
            file=sys.stderr,
        )

    secrets = [args.token, os.environ.get("DATACUBE_TOKEN")]
    plan_api_available = PartitionPlan is not None
    plan_only_requested = bool(
        args.request_plan is not None
        or args.checkpoint_dir is not None
        or args.execution_manifest is not None
        or args.partition_workers != 1
        or not args.resume
    )
    if plan_only_requested and not plan_api_available:
        print(
            "Verified request plans/checkpoints require tushare_plus>=0.1.9; "
            "upgrade the installed library before using these options.",
            file=sys.stderr,
        )
        return 1

    dataframe: pd.DataFrame | None = None
    execution_complete = False
    execution_manifest_path: Path | None = None
    execution_error: BaseException | None = None
    report: Any | None = None
    partition_execution_result: Any | None = None
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

        use_plan = bool(
            plan_api_available
            and (
                args.out is not None
                or args.request_plan is not None
                or split_values
                or plan_only_requested
            )
        )
        if use_plan:
            checkpoint_dir, execution_manifest_path = resolve_checkpoint_paths(args)
            validate_artifact_paths(
                args,
                dataset_manifest=dataset_manifest_path,
                checkpoint_dir=checkpoint_dir,
                execution_manifest=execution_manifest_path,
            )
            chunks = (
                request_plan_chunks
                if request_plan_chunks is not None
                else resolve_partition_chunks(args, split_values=split_values)
            )
            plan = PartitionPlan(
                api_name=args.api_name,
                param_chunks=chunks,
                output_dir=checkpoint_dir,
                fields=args.fields,
                file_format=args.partition_format,
                base_params=dict(params),
                auto_paging=not args.no_auto_paging,
                concurrent=args.concurrent,
                max_pages=args.max_pages,
                limit_per_request=args.limit_per_request,
                detect_limit=not args.no_detect_limit,
                primary_key=key_fields or None,
                strict_paging=True,
                partition_workers=args.partition_workers,
            )
            try:
                result = client.execute_partition_plan(
                    plan,
                    resume=args.resume,
                    continue_on_error=args.continue_on_error,
                    manifest_path=execution_manifest_path,
                )
            except Exception as exc:  # PartitionExecutionError carries partial result.
                result = getattr(exc, "result", None)
                execution_error = exc
                if result is None:
                    raise
            partition_execution_result = result
            fallback_columns = requested_fields
            if not fallback_columns:
                fallback_columns = key_fields
            dataframe = combine_execution_partitions(
                result,
                fallback_columns=fallback_columns,
                key_fields=key_fields,
            )
            execution_complete = bool(result.complete)
            if not execution_complete and execution_error is None:
                execution_error = RuntimeError("one or more request partitions failed")
        elif split_values:
            # Safe fallback for tushare_plus 0.1.8: it has no verified checkpoints,
            # but a partial split still returns non-zero and never publishes --out.
            dataframe, failures = run_split_requests(
                client=client,
                args=args,
                params=params,
                split_values=split_values,
                secrets=secrets,
            )
            execution_complete = failures == 0
            if failures:
                execution_error = RuntimeError(
                    f"{failures} of {len(split_values)} split requests failed"
                )
            elif (
                not plan_api_available
                and args.out is not None
                and not args.no_auto_paging
                and expected_keys is None
            ):
                execution_complete = False
                execution_error = RuntimeError(
                    "publishing an auto-paged split pull requires tushare_plus>=0.1.9 "
                    "or an independent --expected-keys exact audit"
                )
        else:
            dataframe, report = run_single_request_with_report(
                client,
                args,
                params=params,
                primary_key=key_fields,
            )
            execution_complete = bool(
                getattr(report, "complete", True) if report is not None else True
            )
            if (
                report is None
                and args.out is not None
                and not args.no_auto_paging
                and expected_keys is None
            ):
                execution_complete = False
                execution_error = RuntimeError(
                    "publishing an auto-paged pull with tushare_plus 0.1.8 requires "
                    "an independent --expected-keys exact audit or a library upgrade"
                )
    except Exception as exc:  # noqa: BLE001
        execution_error = exc
        execution_complete = False
        if dataframe is None:
            fallback_columns = list(
                requested_fields or key_fields
            )
            dataframe = pd.DataFrame(columns=fallback_columns)

    assert dataframe is not None
    for key_field in key_fields:
        if dataframe.empty and key_field not in dataframe.columns:
            dataframe[key_field] = pd.Series(dtype="string")

    filter_audit: dict[str, Any] | None = None
    validation_error: BaseException | None = None
    try:
        verify_frozen_contract_inputs(frozen_contract_inputs)
        if args.filter_to_expected_keys:
            assert expected_keys is not None
            dataframe, filter_audit = filter_to_expected_keys(
                dataframe,
                key_fields=key_fields,
                expected_keys=expected_keys,
            )
        if key_fields:
            audit = audit_dataset(
                dataframe,
                key_fields=key_fields,
                expected_keys=expected_keys,
                group_fields=group_fields,
                expected_group_cardinality=args.expected_group_cardinality,
                sample_limit=args.validation_sample_limit,
            )
        else:
            audit = {
                "schema_version": 1,
                "row_count": int(len(dataframe)),
                "columns": [str(column) for column in dataframe.columns],
                "key_fields": [],
                "all_hard_checks_pass": True,
            }
        if filter_audit is not None:
            audit["exact_expected_key_filter"] = filter_audit
        source_coverage = audit_source_coverage(
            partition_result=partition_execution_result,
            single_report=report,
            expected_keys_provided=expected_keys is not None,
            auto_paging=not args.no_auto_paging,
        )
        audit["source_coverage"] = source_coverage
        audit["all_hard_checks_pass"] = bool(
            audit.get("all_hard_checks_pass", False)
            and source_coverage["passed"]
        )
    except Exception as exc:  # Dataset validation must fail closed.
        validation_error = exc
        audit = {
            "schema_version": 1,
            "row_count": int(len(dataframe)),
            "columns": [str(column) for column in dataframe.columns],
            "key_fields": list(key_fields),
            "all_hard_checks_pass": False,
            "validation_error_type": type(exc).__name__,
            "validation_error": _safe_error_text(exc, secrets),
        }
        if filter_audit is not None:
            audit["exact_expected_key_filter"] = filter_audit

    # Recheck independent contract inputs after dataset validation and as close
    # as possible to publication.  Manifests below retain the frozen hashes,
    # never hashes of a potentially replaced file.
    try:
        verify_frozen_contract_inputs(frozen_contract_inputs)
    except Exception as exc:  # Contract mutation must withhold publication.
        validation_error = exc
        audit["all_hard_checks_pass"] = False
        audit["validation_error_type"] = type(exc).__name__
        audit["validation_error"] = _safe_error_text(exc, secrets)

    if execution_error is not None:
        audit["execution_error_type"] = type(execution_error).__name__
        audit["execution_error"] = _safe_error_text(execution_error, secrets)

    validation_passed = bool(audit.get("all_hard_checks_pass", False))
    output_published = False
    output_existed_before = bool(args.out is not None and args.out.exists())
    if args.out is not None and dataset_manifest_path is not None:
        manifest_metadata = dict(metadata)
        manifest_metadata.update(
            {
                "request_plan_sha256": request_plan_sha256,
                "output_existed_before_run": output_existed_before,
                "preexisting_output_protected_by_transaction": output_existed_before,
            }
        )
        staged_output: Path | None = None
        try:
            verified_execution_manifest = (
                execution_manifest_path
                if execution_manifest_path is not None
                and execution_manifest_path.is_file()
                else None
            )
            if execution_complete and validation_passed:
                assert output_format is not None
                staged_output = stage_output(dataframe, args.out, output_format)
                try:
                    verify_frozen_contract_inputs(frozen_contract_inputs)
                except Exception as exc:
                    validation_error = exc
                    validation_passed = False
                    audit["all_hard_checks_pass"] = False
                    audit["validation_error_type"] = type(exc).__name__
                    audit["validation_error"] = _safe_error_text(exc, secrets)

            if execution_complete and validation_passed:
                assert staged_output is not None
                dataset_manifest = build_dataset_manifest(
                    api_name=args.api_name,
                    output_path=args.out,
                    output_published=True,
                    artifact_path=staged_output,
                    audit=audit,
                    execution_complete=True,
                    execution_manifest_path=verified_execution_manifest,
                    expected_keys_path=args.expected_keys,
                    expected_keys_sha256=expected_keys_sha256,
                    metadata=manifest_metadata,
                )
                commit_staged_dataset(
                    staged_output=staged_output,
                    output_path=args.out,
                    manifest_path=dataset_manifest_path,
                    final_manifest=_redact_known_values(dataset_manifest, secrets),
                )
                staged_output = None
                output_published = True
            else:
                if staged_output is not None:
                    staged_output.unlink()
                    staged_output = None
                dataset_manifest = build_dataset_manifest(
                    api_name=args.api_name,
                    output_path=args.out,
                    output_published=False,
                    audit=audit,
                    execution_complete=execution_complete,
                    execution_manifest_path=verified_execution_manifest,
                    expected_keys_path=args.expected_keys,
                    expected_keys_sha256=expected_keys_sha256,
                    metadata=manifest_metadata,
                )
                dataset_manifest["publication_state"] = "withheld"
                write_withheld_manifest_locked(
                    output_path=args.out,
                    manifest_path=dataset_manifest_path,
                    payload=_redact_known_values(dataset_manifest, secrets),
                )
        except Exception as exc:  # noqa: BLE001
            if staged_output is not None and staged_output.exists():
                staged_output.unlink()
            validation_error = exc
            audit["all_hard_checks_pass"] = False
            audit["publication_error_type"] = type(exc).__name__
            audit["publication_error"] = _safe_error_text(exc, secrets)
            validation_passed = False

    print(f"Rows: {len(dataframe)}")
    print(f"Columns: {len(dataframe.columns)}")
    if len(dataframe.columns) > 0:
        print("Column names:", ", ".join(str(name) for name in dataframe.columns))
    if report is not None:
        report_payload = report.to_dict() if hasattr(report, "to_dict") else report
        print("Pagination:", json.dumps(report_payload, ensure_ascii=False, sort_keys=True))

    if args.preview_rows > 0:
        if dataframe.empty:
            print("Preview: <empty dataframe>")
        else:
            print("\nPreview:")
            print(dataframe.head(args.preview_rows).to_string(index=False))

    if output_published and args.out is not None:
        print(f"\nSaved: {args.out.resolve()}")
    elif args.out is not None:
        print(
            "Output withheld: execution or dataset validation was incomplete. "
            f"See {dataset_manifest_path}.",
            file=sys.stderr,
        )
    if execution_error is not None:
        print(
            "DataCube execution failed: " + _safe_error_text(execution_error, secrets),
            file=sys.stderr,
        )
    if validation_error is not None:
        print(
            "Dataset validation/publication failed: "
            + _safe_error_text(validation_error, secrets),
            file=sys.stderr,
        )

    return 0 if execution_complete and validation_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
