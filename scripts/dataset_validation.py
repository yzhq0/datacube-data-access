#!/usr/bin/env python3
"""Pure dataset-contract validation helpers for the DataCube download CLI.

Transport execution and checkpoint integrity belong to ``tushare_plus``.  This
module validates the task-level dataset assembled from those checkpoints:
exact keys, duplicate/null keys, optional group cardinality, and publication
metadata.  It deliberately contains no Wind- or interface-specific semantics.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from numbers import Integral, Real
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

import pandas as pd


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, pd.Index, pd.Series)):
        return [_jsonable(item) for item in list(value)]
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    return str(value)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    _jsonable(payload),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_parent(path)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_table(path: Path, *, all_strings: bool = False) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"table does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        frame = pd.read_parquet(path)
        return frame.astype("string") if all_strings else frame
    if suffix == ".csv":
        return pd.read_csv(path, dtype="string" if all_strings else None)
    if suffix == ".tsv":
        return pd.read_csv(
            path, sep="\t", dtype="string" if all_strings else None
        )
    if suffix in {".json", ".jsonl", ".ndjson"}:
        frame = pd.read_json(path, lines=suffix in {".jsonl", ".ndjson"})
        return frame.astype("string") if all_strings else frame
    raise ValueError(
        "table format must be csv, tsv, json, jsonl, ndjson, parquet, or pq"
    )


def _canonical_key(value: Any) -> str | None:
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    if missing:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number.is_integer():
            return str(int(number))
        return format(number, ".17g")
    return str(value)


def _normalize_fields(fields: Iterable[str], *, name: str) -> tuple[str, ...]:
    normalized = tuple(str(field).strip() for field in fields if str(field).strip())
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} contains duplicate columns")
    return normalized


def _canonical_key_frame(frame: pd.DataFrame, fields: Sequence[str]) -> pd.DataFrame:
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"table is missing key fields: {sorted(missing)}")
    canonical = frame.loc[:, list(fields)].copy()
    for field in fields:
        canonical[field] = canonical[field].map(_canonical_key).astype("string")
    return canonical


def _records(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if frame.empty or limit == 0:
        return []
    return [
        {str(key): _jsonable(value) for key, value in row.items()}
        for row in frame.head(limit).to_dict(orient="records")
    ]


def filter_to_expected_keys(
    frame: pd.DataFrame,
    *,
    key_fields: Iterable[str],
    expected_keys: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Keep only exact expected keys after an entity-interval over-fetch.

    The expected-key contract must itself be non-null and unique.  Observed
    duplicate keys are intentionally retained so the subsequent hard audit can
    reject them rather than hiding source duplication.
    """

    keys = _normalize_fields(key_fields, name="key_fields")
    observed = _canonical_key_frame(frame.reset_index(drop=True), keys)
    expected = _canonical_key_frame(expected_keys, keys)
    expected_null = expected.isna().any(axis=1)
    if expected_null.any():
        raise ValueError("expected keys contain null key rows")
    if expected.duplicated(list(keys)).any():
        raise ValueError("expected keys contain duplicate keys")
    expected_unique = expected.drop_duplicates(list(keys)).copy()
    expected_unique["__expected_key"] = True
    matched = observed.merge(
        expected_unique,
        on=list(keys),
        how="left",
        sort=False,
        validate="many_to_one",
    )["__expected_key"].eq(True)
    filtered = frame.reset_index(drop=True).loc[matched.to_numpy(dtype=bool)].copy()
    filtered.reset_index(drop=True, inplace=True)
    audit = {
        "applied": True,
        "rows_before": int(len(frame)),
        "rows_after": int(len(filtered)),
        "rows_removed_outside_expected_keys": int(len(frame) - len(filtered)),
        "expected_unique_keys": int(len(expected_unique)),
    }
    return filtered, audit


def audit_dataset(
    frame: pd.DataFrame,
    *,
    key_fields: Iterable[str],
    expected_keys: pd.DataFrame | None = None,
    group_fields: Iterable[str] = (),
    expected_group_cardinality: int | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Audit exact keys and optional per-group cardinality.

    Group counts are based on unique, non-null keys rather than raw rows.  When
    ``expected_keys`` is supplied, expected group sizes are derived from that
    independent contract.  Otherwise a fixed cardinality can be declared.
    """

    if sample_limit < 0:
        raise ValueError("sample_limit must be non-negative")
    keys = _normalize_fields(key_fields, name="key_fields")
    groups = tuple(str(field).strip() for field in group_fields if str(field).strip())
    if len(set(groups)) != len(groups):
        raise ValueError("group_fields contains duplicate columns")
    if not set(groups).issubset(keys):
        raise ValueError("group_fields must be a subset of key_fields")
    if expected_group_cardinality is not None:
        if not groups:
            raise ValueError("expected_group_cardinality requires group_fields")
        if expected_group_cardinality < 0:
            raise ValueError("expected_group_cardinality must be non-negative")
        if expected_keys is not None:
            raise ValueError(
                "expected_group_cardinality is redundant when expected_keys is supplied"
            )

    observed = _canonical_key_frame(frame, keys)
    observed_null = observed.isna().any(axis=1)
    observed_valid = observed.loc[~observed_null].copy()
    observed_duplicate_rows = int(observed_valid.duplicated(list(keys)).sum())
    observed_unique = (
        observed_valid.drop_duplicates(list(keys))
        .sort_values(list(keys), kind="stable")
        .reset_index(drop=True)
    )
    audit: dict[str, Any] = {
        "schema_version": 1,
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "key_fields": list(keys),
        "observed": {
            "null_key_rows": int(observed_null.sum()),
            "duplicate_key_rows": observed_duplicate_rows,
            "unique_non_null_keys": int(len(observed_unique)),
            "null_key_sample": _records(observed.loc[observed_null], sample_limit),
        },
        "expected_key_comparison": None,
        "group_cardinality": None,
    }

    expected_unique: pd.DataFrame | None = None
    expected_hard_pass = True
    if expected_keys is not None:
        expected = _canonical_key_frame(expected_keys, keys)
        expected_null = expected.isna().any(axis=1)
        expected_valid = expected.loc[~expected_null].copy()
        expected_duplicate_rows = int(expected_valid.duplicated(list(keys)).sum())
        expected_unique = (
            expected_valid.drop_duplicates(list(keys))
            .sort_values(list(keys), kind="stable")
            .reset_index(drop=True)
        )
        comparison = expected_unique.merge(
            observed_unique,
            on=list(keys),
            how="outer",
            indicator=True,
            validate="one_to_one",
        )
        missing = comparison.loc[comparison["_merge"].eq("left_only"), list(keys)]
        extra = comparison.loc[comparison["_merge"].eq("right_only"), list(keys)]
        audit["expected_key_comparison"] = {
            "expected_rows": int(len(expected_keys)),
            "expected_null_key_rows": int(expected_null.sum()),
            "expected_duplicate_key_rows": expected_duplicate_rows,
            "expected_unique_non_null_keys": int(len(expected_unique)),
            "missing_keys": int(len(missing)),
            "extra_keys": int(len(extra)),
            "coverage": (
                float((len(expected_unique) - len(missing)) / len(expected_unique))
                if len(expected_unique)
                else 1.0
            ),
            "missing_key_sample": _records(missing, sample_limit),
            "extra_key_sample": _records(extra, sample_limit),
        }
        expected_hard_pass = bool(
            not expected_null.any()
            and expected_duplicate_rows == 0
            and missing.empty
            and extra.empty
        )

    group_hard_pass = True
    if groups:
        observed_counts = (
            observed_unique.groupby(list(groups), dropna=False, observed=True)
            .size()
            .rename("observed_count")
            .reset_index()
        )
        if expected_unique is not None:
            expected_counts = (
                expected_unique.groupby(list(groups), dropna=False, observed=True)
                .size()
                .rename("expected_count")
                .reset_index()
            )
            group_comparison = expected_counts.merge(
                observed_counts,
                on=list(groups),
                how="outer",
                validate="one_to_one",
            )
            group_comparison[["expected_count", "observed_count"]] = group_comparison[
                ["expected_count", "observed_count"]
            ].fillna(0).astype(int)
            basis = "expected_keys"
        else:
            group_comparison = observed_counts.copy()
            group_comparison["expected_count"] = int(expected_group_cardinality)
            basis = "fixed"
        mismatches = group_comparison.loc[
            group_comparison["observed_count"].ne(group_comparison["expected_count"]),
            [*groups, "observed_count", "expected_count"],
        ].sort_values(list(groups), kind="stable")
        audit["group_cardinality"] = {
            "group_fields": list(groups),
            "basis": basis,
            "groups_observed": int(len(observed_counts)),
            "mismatched_groups": int(len(mismatches)),
            "mismatch_sample": _records(mismatches, sample_limit),
        }
        group_hard_pass = mismatches.empty

    audit["all_hard_checks_pass"] = bool(
        not observed_null.any()
        and observed_duplicate_rows == 0
        and expected_hard_pass
        and group_hard_pass
    )
    return audit


def build_dataset_manifest(
    *,
    api_name: str,
    output_path: Path,
    audit: Mapping[str, Any],
    execution_complete: bool,
    output_published: bool = True,
    artifact_path: Path | None = None,
    execution_manifest_path: Path | None = None,
    expected_keys_path: Path | None = None,
    expected_keys_sha256: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    hash_path = artifact_path if artifact_path is not None else output_path
    if output_published and not hash_path.is_file():
        raise ValueError(f"dataset artifact does not exist: {hash_path}")
    if execution_manifest_path is not None and not execution_manifest_path.is_file():
        raise ValueError(f"execution manifest does not exist: {execution_manifest_path}")
    if (
        expected_keys_path is not None
        and expected_keys_sha256 is None
        and not expected_keys_path.is_file()
    ):
        raise ValueError(f"expected-key file does not exist: {expected_keys_path}")

    validation_passed = bool(audit.get("all_hard_checks_pass", False))
    payload = {
        "schema_version": 1,
        "kind": "datacube_dataset_manifest",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_name": str(api_name),
        "execution_complete": bool(execution_complete),
        "validation_passed": validation_passed,
        "output_published": bool(output_published),
        "publishable": bool(
            execution_complete and validation_passed and output_published
        ),
        "output": str(output_path),
        "output_sha256": sha256_file(hash_path) if output_published else None,
        "execution_manifest": (
            str(execution_manifest_path) if execution_manifest_path is not None else None
        ),
        "execution_manifest_sha256": (
            sha256_file(execution_manifest_path)
            if execution_manifest_path is not None
            else None
        ),
        "expected_keys": str(expected_keys_path) if expected_keys_path else None,
        "expected_keys_sha256": (
            expected_keys_sha256
            if expected_keys_sha256 is not None
            else sha256_file(expected_keys_path) if expected_keys_path else None
        ),
        "metadata": _redact_secrets(dict(metadata or {})),
        "audit": dict(audit),
    }
    return payload


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


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _is_secret_key(key) else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_secrets(item) for item in value]
    return _jsonable(value)
