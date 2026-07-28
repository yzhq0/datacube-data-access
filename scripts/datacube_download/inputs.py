from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .job import JobError, JobSpec, reject_secret_keys
from .validation import audit_dataset, load_table, sha256_file


@dataclass(frozen=True)
class FrozenInput:
    label: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class PreparedInputs:
    partitions: tuple[dict[str, Any], ...]
    expected_keys: pd.DataFrame | None
    frozen: tuple[FrozenInput, ...]

    def hash_for(self, label: str) -> str | None:
        for item in self.frozen:
            if item.label == label:
                return item.sha256
        return None


def _records_from_json(value: Any, *, path: Path) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("requests", "partitions"):
            if key in value:
                records = value[key]
                if not isinstance(records, list):
                    raise JobError(f"{path}: '{key}' must be an array")
                return records
        return [value]
    raise JobError(f"{path}: partition file must contain an object or array")


def load_partitions(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        raise JobError(f"partition file does not exist: {path}")
    suffix = path.suffix.lower()
    records: list[Any]
    if suffix == ".json":
        try:
            records = _records_from_json(
                json.loads(path.read_text(encoding="utf-8")),
                path=path,
            )
        except json.JSONDecodeError as exc:
            raise JobError(f"invalid partition JSON {path}: {exc}") from exc
    elif suffix in {".jsonl", ".ndjson"}:
        records = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise JobError(
                    f"invalid JSON on line {line_number} of {path}: {exc}"
                ) from exc
    elif suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise JobError(f"partition table has no header: {path}")
            records = [
                {
                    str(key): value.strip()
                    for key, value in row.items()
                    if key is not None and value is not None and value != ""
                }
                for row in reader
            ]
    else:
        raise JobError(
            "partitions_file must be .json, .jsonl, .ndjson, .csv, or .tsv"
        )
    return normalize_partitions(records)


def normalize_partitions(records: list[Any] | tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    if not records:
        raise JobError("request partitions must not be empty")
    result: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise JobError(f"partition {index} must be an object")
        reject_secret_keys(record, context=f"partition {index}")
        normalized = {str(key): value for key, value in record.items()}
        try:
            canonical = json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise JobError(f"partition {index} is not canonical JSON: {exc}") from exc
        fingerprint = sha256(canonical.encode("utf-8")).hexdigest()
        if fingerprint in fingerprints:
            raise JobError(f"request partitions contain duplicate record {index}")
        fingerprints.add(fingerprint)
        result.append(normalized)
    return tuple(result)


def validate_artifact_paths(job: JobSpec) -> None:
    named_paths: list[tuple[str, Path]] = [
        ("job", job.source_path),
        ("output.path", job.output.path),
        ("output.dataset_manifest", job.output.dataset_manifest),
        ("execution.execution_manifest", job.execution.execution_manifest),
    ]
    if job.requests.partitions_file is not None:
        named_paths.append(
            ("requests.partitions_file", job.requests.partitions_file)
        )
    if job.validation.expected_keys_file is not None:
        named_paths.append(
            ("validation.expected_keys_file", job.validation.expected_keys_file)
        )
    for index, (left_name, left_path) in enumerate(named_paths):
        for right_name, right_path in named_paths[index + 1 :]:
            if left_path == right_path:
                raise JobError(
                    f"{left_name} and {right_name} resolve to the same path: {left_path}"
                )
    checkpoint = job.execution.checkpoint_dir
    if checkpoint.exists() and not checkpoint.is_dir():
        raise JobError(f"checkpoint directory is an existing file: {checkpoint}")
    for name, path in named_paths:
        if name == "execution.execution_manifest":
            continue
        if path == checkpoint or checkpoint in path.parents:
            raise JobError(f"{name} must not live inside checkpoint_dir: {path}")


def _freeze(path: Path, *, label: str) -> FrozenInput:
    if not path.is_file():
        raise JobError(f"{label} does not exist: {path}")
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise JobError(f"{label} is unavailable: {path}") from exc
    return FrozenInput(label=label, path=path, sha256=digest)


def prepare_inputs(job: JobSpec) -> PreparedInputs:
    validate_artifact_paths(job)
    frozen: list[FrozenInput] = [
        FrozenInput(
            label="job",
            path=job.source_path,
            sha256=job.source_sha256,
        )
    ]
    verify_frozen(frozen)
    if job.requests.partitions_file is not None:
        frozen.append(
            _freeze(job.requests.partitions_file, label="partitions_file")
        )
        partitions = load_partitions(job.requests.partitions_file)
        verify_frozen(frozen)
    else:
        assert job.requests.partitions is not None
        partitions = normalize_partitions(job.requests.partitions)

    expected_keys: pd.DataFrame | None = None
    if job.validation.expected_keys_file is not None:
        frozen.append(
            _freeze(job.validation.expected_keys_file, label="expected_keys_file")
        )
        try:
            expected_keys = load_table(
                job.validation.expected_keys_file,
                all_strings=True,
            )
            expected_audit = audit_dataset(
                expected_keys,
                key_fields=job.validation.key_fields,
                expected_keys=expected_keys,
                group_fields=job.validation.group_fields,
                sample_limit=job.validation.sample_limit,
            )
        except ValueError as exc:
            raise JobError(f"invalid expected_keys_file: {exc}") from exc
        if not expected_audit["all_hard_checks_pass"]:
            observed = expected_audit["observed"]
            comparison = expected_audit["expected_key_comparison"]
            raise JobError(
                "expected_keys_file must contain unique non-null keys; "
                f"null rows={observed['null_key_rows']}, "
                f"duplicate rows={comparison['expected_duplicate_key_rows']}"
            )
        verify_frozen(frozen)
    return PreparedInputs(
        partitions=partitions,
        expected_keys=expected_keys,
        frozen=tuple(frozen),
    )


def verify_frozen(inputs: list[FrozenInput] | tuple[FrozenInput, ...]) -> None:
    for item in inputs:
        if not item.path.is_file():
            raise JobError(f"{item.label} changed during execution: {item.path}")
        try:
            observed = sha256_file(item.path)
        except OSError as exc:
            raise JobError(
                f"{item.label} changed during execution: {item.path}"
            ) from exc
        if observed != item.sha256:
            raise JobError(f"{item.label} changed during execution: {item.path}")
