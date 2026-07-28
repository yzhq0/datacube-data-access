from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import pandas as pd
from tushare_plus import DataCubeAPI

try:
    from tushare_plus import PartitionPlan
except ImportError:
    PartitionPlan = None  # type: ignore[assignment]

from .inputs import PreparedInputs
from .job import JobSpec
from .validation import sha256_file


@dataclass(frozen=True)
class ExecutionOutcome:
    frame: pd.DataFrame
    complete: bool
    result: Any | None
    error: BaseException | None


def build_client(job: JobSpec | None = None) -> DataCubeAPI:
    if job is None:
        return DataCubeAPI(
            request_timeout=60,
            max_retries=3,
            retry_delay=1,
            retry_backoff=2,
            retry_jitter=0.1,
            max_retry_delay=60,
        )
    execution = job.execution
    return DataCubeAPI(
        request_timeout=execution.request_timeout,
        max_retries=execution.max_retries,
        retry_delay=execution.retry_delay,
        retry_backoff=execution.retry_backoff,
        retry_jitter=execution.retry_jitter,
        max_retry_delay=execution.max_retry_delay,
    )


def execute_pull(
    *,
    api_name: str,
    params: dict[str, Any],
    fields: tuple[str, ...],
    all_pages: bool,
    max_pages: int | None,
    client: DataCubeAPI | None = None,
) -> tuple[pd.DataFrame, Any | None]:
    active_client = client if client is not None else build_client()
    kwargs: dict[str, Any] = {
        "fields": ",".join(fields),
        "auto_paging": all_pages,
        "concurrent": False,
        "max_pages": max_pages,
        "detect_limit": True,
        **params,
    }
    signature = inspect.signature(active_client.get_data)
    if all_pages and "return_report" in signature.parameters:
        kwargs.update({"strict_paging": True, "return_report": True})
        frame, report = active_client.get_data(api_name, **kwargs)
        return pd.DataFrame(frame), report
    return pd.DataFrame(active_client.get_data(api_name, **kwargs)), None


def _read_partition(path: Path, *, key_fields: Iterable[str]) -> pd.DataFrame:
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
    fallback_columns: Iterable[str],
    key_fields: Iterable[str],
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
        before = sha256_file(path)
        if before != expected_hash:
            raise ValueError(
                f"verified partition {partition.index} sha256 mismatch before read"
            )
        frame = _read_partition(path, key_fields=key_fields)
        after = sha256_file(path)
        if after != before or after != expected_hash:
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
    expected_keys_provided: bool,
) -> dict[str, Any]:
    if expected_keys_provided:
        return {
            "basis": "exact_expected_keys",
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
    if not reports:
        return {
            "basis": "unproven",
            "reports_checked": 0,
            "unproven_reports": 1,
            "unproven_sample": [{"reason": "missing_pagination_report"}],
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


def execute_job(
    job: JobSpec,
    inputs: PreparedInputs,
    *,
    client: DataCubeAPI | None = None,
    partition_plan_class: Any = PartitionPlan,
) -> ExecutionOutcome:
    if partition_plan_class is None:
        raise RuntimeError("verified jobs require tushare_plus>=0.1.9")
    active_client = client if client is not None else build_client(job)
    plan = partition_plan_class(
        api_name=job.api.name,
        param_chunks=list(inputs.partitions),
        output_dir=job.execution.checkpoint_dir,
        fields=",".join(job.api.fields),
        file_format=job.execution.partition_format,
        base_params=dict(job.api.base_params),
        auto_paging=job.execution.auto_paging,
        concurrent=False,
        max_pages=job.execution.max_pages,
        limit_per_request=job.execution.limit_per_request,
        detect_limit=job.execution.detect_limit,
        primary_key=job.validation.key_fields,
        strict_paging=True,
        partition_workers=job.execution.partition_workers,
    )
    error: BaseException | None = None
    try:
        result = active_client.execute_partition_plan(
            plan,
            resume=job.execution.resume,
            continue_on_error=False,
            manifest_path=job.execution.execution_manifest,
        )
    except Exception as exc:
        result = getattr(exc, "result", None)
        if result is None:
            raise
        error = exc
    frame = combine_execution_partitions(
        result,
        fallback_columns=job.api.fields,
        key_fields=job.validation.key_fields,
    )
    complete = bool(getattr(result, "complete", False))
    if not complete and error is None:
        error = RuntimeError("one or more request partitions failed")
    return ExecutionOutcome(
        frame=frame,
        complete=complete,
        result=result,
        error=error,
    )
