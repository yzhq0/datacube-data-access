from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd

from .cli import build_parser, parse_fields, parse_params, validate_pull_args
from .execution import (
    PartitionPlan,
    audit_source_coverage,
    execute_job,
    execute_pull,
)
from .inputs import PreparedInputs, prepare_inputs, verify_frozen
from .job import JobError, JobSpec, load_job
from .publication import (
    commit_staged_dataset,
    publish_exploratory,
    redact_known_values,
    safe_text,
    stage_output,
    write_withheld_manifest,
)
from .validation import (
    audit_dataset,
    build_dataset_manifest,
    filter_to_expected_keys,
)


def _output_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _print_frame(frame: pd.DataFrame, *, preview_rows: int) -> None:
    print(f"Rows: {len(frame)}")
    print(f"Columns: {len(frame.columns)}")
    if len(frame.columns):
        print("Column names:", ", ".join(str(item) for item in frame.columns))
    if preview_rows > 0:
        if frame.empty:
            print("Preview: <empty dataframe>")
        else:
            print("\nPreview:")
            print(frame.head(preview_rows).to_string(index=False))


def run_pull(args: argparse.Namespace, *, client: Any | None = None) -> int:
    validate_pull_args(args)
    params = parse_params(args.param)
    fields = parse_fields(args.fields)
    frame, report = execute_pull(
        api_name=args.api_name,
        params=params,
        fields=fields,
        all_pages=args.all_pages,
        max_pages=args.max_pages,
        client=client,
    )
    _print_frame(frame, preview_rows=args.preview_rows)
    if report is not None:
        payload = report.to_dict() if hasattr(report, "to_dict") else report
        print("Pagination:", json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if args.out is not None:
        publish_exploratory(frame, args.out, _output_format(args.out))
        print(f"\nSaved exploratory output: {args.out.resolve()}")
    print("Status: exploratory and not a verified dataset")
    return 0


def _print_check(job: JobSpec, inputs: PreparedInputs) -> None:
    print(f"Job: {job.source_path}")
    print(f"API: {job.api.name}")
    print(f"doc_id: {job.api.doc_id}")
    print(f"Partitions: {len(inputs.partitions)}")
    print(f"Output: {job.output.path}")
    for item in inputs.frozen:
        print(f"SHA256 {item.label}: {item.sha256}  {item.path}")
    print("Status: valid")


def run_check(path: Path) -> int:
    job = load_job(path)
    inputs = prepare_inputs(job)
    _print_check(job, inputs)
    return 0


def _failed_audit(
    frame: pd.DataFrame,
    job: JobSpec,
    error: BaseException,
    secrets: list[str | None],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "key_fields": list(job.validation.key_fields),
        "all_hard_checks_pass": False,
        "validation_error_type": type(error).__name__,
        "validation_error": safe_text(error, secrets),
    }


def _manifest_metadata(job: JobSpec, inputs: PreparedInputs) -> dict[str, Any]:
    metadata = dict(job.metadata)
    metadata.update(
        {
            "doc_id": job.api.doc_id,
            "job_sha256": inputs.hash_for("job"),
            "partitions_file_sha256": inputs.hash_for("partitions_file"),
            "output_existed_before_run": job.output.path.exists(),
            "preexisting_output_protected_by_transaction": job.output.path.exists(),
        }
    )
    return metadata


def run_verified(
    path: Path,
    *,
    client: Any | None = None,
    partition_plan_class: Any = PartitionPlan,
) -> int:
    job = load_job(path)
    inputs = prepare_inputs(job)
    secrets = [os.environ.get("DATACUBE_TOKEN")]
    execution_error: BaseException | None = None
    try:
        outcome = execute_job(
            job,
            inputs,
            client=client,
            partition_plan_class=partition_plan_class,
        )
        frame = outcome.frame
        execution_complete = outcome.complete
        execution_error = outcome.error
        partition_result = outcome.result
        if execution_complete and not job.execution.execution_manifest.is_file():
            execution_complete = False
            execution_error = RuntimeError(
                "partition execution completed without an execution manifest"
            )
    except Exception as exc:
        frame = pd.DataFrame(columns=list(job.api.fields))
        execution_complete = False
        execution_error = exc
        partition_result = None

    filter_audit: dict[str, Any] | None = None
    validation_error: BaseException | None = None
    try:
        verify_frozen(inputs.frozen)
        if job.validation.filter_to_expected_keys:
            assert inputs.expected_keys is not None
            frame, filter_audit = filter_to_expected_keys(
                frame,
                key_fields=job.validation.key_fields,
                expected_keys=inputs.expected_keys,
            )
        audit = audit_dataset(
            frame,
            key_fields=job.validation.key_fields,
            expected_keys=inputs.expected_keys,
            group_fields=job.validation.group_fields,
            expected_group_cardinality=(
                job.validation.expected_group_cardinality
            ),
            sample_limit=job.validation.sample_limit,
        )
        if filter_audit is not None:
            audit["exact_expected_key_filter"] = filter_audit
        source_coverage = audit_source_coverage(
            partition_result=partition_result,
            expected_keys_provided=inputs.expected_keys is not None,
        )
        audit["source_coverage"] = source_coverage
        audit["all_hard_checks_pass"] = bool(
            audit.get("all_hard_checks_pass", False)
            and source_coverage["passed"]
        )
        verify_frozen(inputs.frozen)
    except Exception as exc:
        validation_error = exc
        audit = _failed_audit(frame, job, exc, secrets)
        if filter_audit is not None:
            audit["exact_expected_key_filter"] = filter_audit

    if execution_error is not None:
        audit["execution_error_type"] = type(execution_error).__name__
        audit["execution_error"] = safe_text(execution_error, secrets)

    validation_passed = bool(audit.get("all_hard_checks_pass", False))
    execution_manifest = (
        job.execution.execution_manifest
        if job.execution.execution_manifest.is_file()
        else None
    )
    metadata = _manifest_metadata(job, inputs)
    staged: Path | None = None
    published = False
    try:
        if execution_complete and validation_passed:
            staged = stage_output(frame, job.output.path, job.output.format)
            verify_frozen(inputs.frozen)
            manifest = build_dataset_manifest(
                api_name=job.api.name,
                output_path=job.output.path,
                output_published=True,
                artifact_path=staged,
                audit=audit,
                execution_complete=True,
                execution_manifest_path=execution_manifest,
                expected_keys_path=job.validation.expected_keys_file,
                expected_keys_sha256=inputs.hash_for("expected_keys_file"),
                metadata=metadata,
            )
            commit_staged_dataset(
                staged_output=staged,
                output_path=job.output.path,
                manifest_path=job.output.dataset_manifest,
                final_manifest=redact_known_values(manifest, secrets),
            )
            staged = None
            published = True
        else:
            manifest = build_dataset_manifest(
                api_name=job.api.name,
                output_path=job.output.path,
                output_published=False,
                audit=audit,
                execution_complete=execution_complete,
                execution_manifest_path=execution_manifest,
                expected_keys_path=job.validation.expected_keys_file,
                expected_keys_sha256=inputs.hash_for("expected_keys_file"),
                metadata=metadata,
            )
            manifest["publication_state"] = "withheld"
            write_withheld_manifest(
                output_path=job.output.path,
                manifest_path=job.output.dataset_manifest,
                payload=redact_known_values(manifest, secrets),
            )
    except Exception as exc:
        validation_error = exc
        validation_passed = False
        if staged is not None and staged.exists():
            staged.unlink()

    _print_frame(frame, preview_rows=0)
    if published:
        print(f"Saved verified dataset: {job.output.path}")
        print(f"Dataset manifest: {job.output.dataset_manifest}")
    else:
        print(
            f"Output withheld; see {job.output.dataset_manifest}",
            file=sys.stderr,
        )
    if execution_error is not None:
        print(
            "DataCube execution failed: " + safe_text(execution_error, secrets),
            file=sys.stderr,
        )
    if validation_error is not None:
        print(
            "Dataset validation/publication failed: "
            + safe_text(validation_error, secrets),
            file=sys.stderr,
        )
    return 0 if published else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "pull":
            return run_pull(args)
        if args.command == "check":
            return run_check(args.job)
        if args.command == "run":
            return run_verified(args.job)
        raise AssertionError(f"unexpected command: {args.command}")
    except JobError as exc:
        print(f"Invalid job: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        secrets = [os.environ.get("DATACUBE_TOKEN")]
        print("Error: " + safe_text(exc, secrets), file=sys.stderr)
        return 1
