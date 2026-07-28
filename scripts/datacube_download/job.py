from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


class JobError(ValueError):
    """Raised when a verified job violates the v1 contract."""


def is_secret_key(key: Any) -> bool:
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


def reject_secret_keys(value: Any, *, context: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if is_secret_key(key):
                raise JobError(f"{context} contains secret-bearing key '{key}'")
            reject_secret_keys(item, context=context)
    elif isinstance(value, list):
        for item in value:
            reject_secret_keys(item, context=context)


@dataclass(frozen=True)
class ApiSpec:
    name: str
    doc_id: int
    fields: tuple[str, ...]
    base_params: dict[str, Any]


@dataclass(frozen=True)
class RequestsSpec:
    partitions: tuple[dict[str, Any], ...] | None
    partitions_file: Path | None


@dataclass(frozen=True)
class ExecutionSpec:
    auto_paging: bool
    max_pages: int | None
    detect_limit: bool
    limit_per_request: int | None
    partition_workers: int
    partition_format: str
    resume: bool
    request_timeout: float
    max_retries: int
    retry_delay: float
    retry_backoff: float
    retry_jitter: float
    max_retry_delay: float
    checkpoint_dir: Path
    execution_manifest: Path


@dataclass(frozen=True)
class ValidationSpec:
    key_fields: tuple[str, ...]
    expected_keys_file: Path | None
    filter_to_expected_keys: bool
    group_fields: tuple[str, ...]
    expected_group_cardinality: int | None
    sample_limit: int


@dataclass(frozen=True)
class OutputSpec:
    path: Path
    format: str
    dataset_manifest: Path


@dataclass(frozen=True)
class JobSpec:
    source_path: Path
    source_sha256: str
    api: ApiSpec
    requests: RequestsSpec
    execution: ExecutionSpec
    validation: ValidationSpec
    output: OutputSpec
    metadata: dict[str, Any]


def _object(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JobError(f"{name} must be an object")
    return value


def _unknown_keys(value: Mapping[str, Any], allowed: set[str], *, name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise JobError(f"{name} contains unknown keys: {', '.join(unknown)}")


def _string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JobError(f"{name} must be a non-empty string")
    return value.strip()


def _bool(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise JobError(f"{name} must be a boolean")
    return value


def _int(
    value: Any,
    *,
    name: str,
    minimum: int = 0,
    optional: bool = False,
) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "positive" if minimum == 1 else f">= {minimum}"
        raise JobError(f"{name} must be an integer {qualifier}")
    return value


def _number(
    value: Any,
    *,
    name: str,
    minimum: float = 0.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobError(f"{name} must be a number")
    result = float(value)
    if result < minimum:
        raise JobError(f"{name} must be >= {minimum}")
    return result


def _string_list(value: Any, *, name: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise JobError(f"{name} must be an array of strings")
    result = tuple(_string(item, name=f"{name} item") for item in value)
    if not result and not allow_empty:
        raise JobError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise JobError(f"{name} contains duplicates")
    return result


def _path(value: Any, *, name: str, base: Path) -> Path:
    raw = _string(value, name=name)
    path = Path(raw)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _optional_path(value: Any, *, name: str, base: Path) -> Path | None:
    if value is None:
        return None
    return _path(value, name=name, base=base)


def _infer_format(path: Path, explicit: Any) -> str:
    if explicit is not None:
        result = _string(explicit, name="output.format").lower()
    else:
        result = path.suffix.lower().lstrip(".")
    if result not in {"csv", "json", "parquet"}:
        raise JobError("output.format must be csv, json, or parquet")
    return result


def _parse_api(raw: Any) -> ApiSpec:
    value = _object(raw, name="api")
    _unknown_keys(value, {"name", "doc_id", "fields", "base_params"}, name="api")
    base_params = _object(value.get("base_params", {}), name="api.base_params")
    reject_secret_keys(base_params, context="api.base_params")
    doc_id = _int(value.get("doc_id"), name="api.doc_id", minimum=1)
    assert doc_id is not None
    return ApiSpec(
        name=_string(value.get("name"), name="api.name"),
        doc_id=doc_id,
        fields=_string_list(value.get("fields"), name="api.fields"),
        base_params=dict(base_params),
    )


def _parse_requests(raw: Any, *, base: Path) -> RequestsSpec:
    value = _object(raw, name="requests")
    _unknown_keys(value, {"partitions", "partitions_file"}, name="requests")
    has_inline = "partitions" in value
    has_file = "partitions_file" in value
    if has_inline == has_file:
        raise JobError("requests requires exactly one of partitions or partitions_file")
    if has_file:
        return RequestsSpec(
            partitions=None,
            partitions_file=_path(
                value["partitions_file"],
                name="requests.partitions_file",
                base=base,
            ),
        )
    raw_partitions = value["partitions"]
    if not isinstance(raw_partitions, list) or not raw_partitions:
        raise JobError("requests.partitions must be a non-empty array")
    partitions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_partitions, start=1):
        partition = _object(item, name=f"requests.partitions[{index}]")
        reject_secret_keys(partition, context=f"requests.partitions[{index}]")
        partitions.append(dict(partition))
    return RequestsSpec(partitions=tuple(partitions), partitions_file=None)


def _parse_output(raw: Any, *, base: Path) -> OutputSpec:
    value = _object(raw, name="output")
    _unknown_keys(value, {"path", "format", "dataset_manifest"}, name="output")
    path = _path(value.get("path"), name="output.path", base=base)
    dataset_manifest = _optional_path(
        value.get("dataset_manifest"),
        name="output.dataset_manifest",
        base=base,
    )
    if dataset_manifest is None:
        dataset_manifest = path.parent / f"{path.name}.dataset-manifest.json"
    return OutputSpec(
        path=path,
        format=_infer_format(path, value.get("format")),
        dataset_manifest=dataset_manifest,
    )


def _parse_execution(raw: Any, *, base: Path, output: OutputSpec) -> ExecutionSpec:
    value = _object(raw if raw is not None else {}, name="execution")
    allowed = {
        "auto_paging",
        "max_pages",
        "detect_limit",
        "limit_per_request",
        "partition_workers",
        "partition_format",
        "resume",
        "request_timeout",
        "max_retries",
        "retry_delay",
        "retry_backoff",
        "retry_jitter",
        "max_retry_delay",
        "checkpoint_dir",
        "execution_manifest",
    }
    _unknown_keys(value, allowed, name="execution")
    auto_paging = _bool(value.get("auto_paging", True), name="execution.auto_paging")
    max_pages = _int(
        value.get("max_pages"),
        name="execution.max_pages",
        minimum=1,
        optional=True,
    )
    if auto_paging and max_pages is None:
        raise JobError("execution.max_pages is required when auto_paging is true")
    checkpoint_dir = _optional_path(
        value.get("checkpoint_dir"),
        name="execution.checkpoint_dir",
        base=base,
    )
    if checkpoint_dir is None:
        checkpoint_dir = output.path.parent / f".{output.path.name}.partitions"
    execution_manifest = _optional_path(
        value.get("execution_manifest"),
        name="execution.execution_manifest",
        base=base,
    )
    if execution_manifest is None:
        execution_manifest = checkpoint_dir / "execution-manifest.json"
    partition_format = _string(
        value.get("partition_format", "csv"),
        name="execution.partition_format",
    ).lower()
    if partition_format not in {"csv", "parquet"}:
        raise JobError("execution.partition_format must be csv or parquet")
    partition_workers = _int(
        value.get("partition_workers", 1),
        name="execution.partition_workers",
        minimum=1,
    )
    limit_per_request = _int(
        value.get("limit_per_request"),
        name="execution.limit_per_request",
        minimum=1,
        optional=True,
    )
    max_retries = _int(
        value.get("max_retries", 3),
        name="execution.max_retries",
        minimum=0,
    )
    assert partition_workers is not None and max_retries is not None
    return ExecutionSpec(
        auto_paging=auto_paging,
        max_pages=max_pages,
        detect_limit=_bool(
            value.get("detect_limit", True),
            name="execution.detect_limit",
        ),
        limit_per_request=limit_per_request,
        partition_workers=partition_workers,
        partition_format=partition_format,
        resume=_bool(value.get("resume", True), name="execution.resume"),
        request_timeout=_number(
            value.get("request_timeout", 60),
            name="execution.request_timeout",
            minimum=0.001,
        ),
        max_retries=max_retries,
        retry_delay=_number(
            value.get("retry_delay", 1),
            name="execution.retry_delay",
        ),
        retry_backoff=_number(
            value.get("retry_backoff", 2),
            name="execution.retry_backoff",
            minimum=1,
        ),
        retry_jitter=_number(
            value.get("retry_jitter", 0.1),
            name="execution.retry_jitter",
        ),
        max_retry_delay=_number(
            value.get("max_retry_delay", 60),
            name="execution.max_retry_delay",
        ),
        checkpoint_dir=checkpoint_dir,
        execution_manifest=execution_manifest,
    )


def _parse_validation(raw: Any, *, base: Path, api: ApiSpec) -> ValidationSpec:
    value = _object(raw, name="validation")
    allowed = {
        "key_fields",
        "expected_keys_file",
        "filter_to_expected_keys",
        "group_fields",
        "expected_group_cardinality",
        "sample_limit",
    }
    _unknown_keys(value, allowed, name="validation")
    key_fields = _string_list(value.get("key_fields"), name="validation.key_fields")
    if not set(key_fields).issubset(api.fields):
        raise JobError("validation.key_fields must be included in api.fields")
    expected_keys_file = _optional_path(
        value.get("expected_keys_file"),
        name="validation.expected_keys_file",
        base=base,
    )
    filter_to_expected = _bool(
        value.get("filter_to_expected_keys", False),
        name="validation.filter_to_expected_keys",
    )
    if filter_to_expected and expected_keys_file is None:
        raise JobError(
            "validation.filter_to_expected_keys requires expected_keys_file"
        )
    group_fields = _string_list(
        value.get("group_fields", []),
        name="validation.group_fields",
        allow_empty=True,
    )
    if not set(group_fields).issubset(key_fields):
        raise JobError("validation.group_fields must be included in key_fields")
    expected_group_cardinality = _int(
        value.get("expected_group_cardinality"),
        name="validation.expected_group_cardinality",
        minimum=1,
        optional=True,
    )
    if expected_keys_file is not None and expected_group_cardinality is not None:
        raise JobError(
            "validation.expected_group_cardinality is redundant with expected_keys_file"
        )
    sample_limit = _int(
        value.get("sample_limit", 20),
        name="validation.sample_limit",
        minimum=1,
    )
    assert sample_limit is not None
    return ValidationSpec(
        key_fields=key_fields,
        expected_keys_file=expected_keys_file,
        filter_to_expected_keys=filter_to_expected,
        group_fields=group_fields,
        expected_group_cardinality=expected_group_cardinality,
        sample_limit=sample_limit,
    )


def load_job(path: Path) -> JobSpec:
    source_path = path.resolve()
    if not source_path.is_file():
        raise JobError(f"job file does not exist: {source_path}")
    try:
        source_bytes = source_path.read_bytes()
        source_sha256 = sha256(source_bytes).hexdigest()
        payload = json.loads(source_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise JobError(f"job file is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JobError(f"invalid job JSON: {exc}") from exc
    root = _object(payload, name="job")
    _unknown_keys(
        root,
        {
            "schema_version",
            "api",
            "requests",
            "execution",
            "validation",
            "output",
            "metadata",
        },
        name="job",
    )
    if root.get("schema_version") != 1:
        raise JobError("schema_version must equal 1")
    base = source_path.parent
    api = _parse_api(root.get("api"))
    output = _parse_output(root.get("output"), base=base)
    execution = _parse_execution(root.get("execution"), base=base, output=output)
    validation = _parse_validation(root.get("validation"), base=base, api=api)
    metadata = _object(root.get("metadata", {}), name="metadata")
    reject_secret_keys(metadata, context="metadata")
    return JobSpec(
        source_path=source_path,
        source_sha256=source_sha256,
        api=api,
        requests=_parse_requests(root.get("requests"), base=base),
        execution=execution,
        validation=validation,
        output=output,
        metadata=dict(metadata),
    )
