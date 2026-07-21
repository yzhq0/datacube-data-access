from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "dataset_validation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("dataset_validation", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validation = _load_module()


def test_exact_expected_key_and_group_cardinality_audit_passes() -> None:
    observed = pd.DataFrame(
        {
            "trade_date": [20260102, 20260102, 20260105, 20260105],
            "code": ["A", "B", "A", "B"],
            "close": [1.0, 2.0, 1.1, 2.1],
        }
    )
    expected = pd.DataFrame(
        {
            "trade_date": ["20260102", "20260102", "20260105", "20260105"],
            "code": ["A", "B", "A", "B"],
        }
    )

    audit = validation.audit_dataset(
        observed,
        key_fields=("trade_date", "code"),
        expected_keys=expected,
        group_fields=("trade_date",),
    )

    assert audit["all_hard_checks_pass"] is True
    assert audit["observed"]["duplicate_key_rows"] == 0
    assert audit["expected_key_comparison"]["missing_keys"] == 0
    assert audit["expected_key_comparison"]["extra_keys"] == 0
    assert audit["group_cardinality"]["mismatched_groups"] == 0


def test_key_audit_reports_missing_extra_duplicate_and_null_rows() -> None:
    observed = pd.DataFrame(
        {
            "trade_date": ["20260102", "20260102", "20260102", None],
            "code": ["A", "A", "C", "B"],
        }
    )
    expected = pd.DataFrame(
        {
            "trade_date": ["20260102", "20260102"],
            "code": ["A", "B"],
        }
    )

    audit = validation.audit_dataset(
        observed,
        key_fields=("trade_date", "code"),
        expected_keys=expected,
        sample_limit=10,
    )

    assert audit["all_hard_checks_pass"] is False
    assert audit["observed"]["null_key_rows"] == 1
    assert audit["observed"]["duplicate_key_rows"] == 1
    assert audit["expected_key_comparison"]["missing_keys"] == 1
    assert audit["expected_key_comparison"]["extra_keys"] == 1
    assert audit["expected_key_comparison"]["missing_key_sample"] == [
        {"trade_date": "20260102", "code": "B"}
    ]


def test_fixed_group_cardinality_uses_unique_keys() -> None:
    observed = pd.DataFrame(
        {
            "trade_date": ["20260102", "20260102", "20260105"],
            "code": ["A", "B", "A"],
        }
    )

    audit = validation.audit_dataset(
        observed,
        key_fields=("trade_date", "code"),
        group_fields=("trade_date",),
        expected_group_cardinality=2,
    )

    assert audit["all_hard_checks_pass"] is False
    assert audit["group_cardinality"]["mismatched_groups"] == 1
    assert audit["group_cardinality"]["mismatch_sample"] == [
        {"trade_date": "20260105", "observed_count": 1, "expected_count": 2}
    ]


def test_dataset_manifest_requires_execution_and_key_audits(tmp_path: Path) -> None:
    output = tmp_path / "panel.csv"
    output.write_text("trade_date,code\n20260102,A\n", encoding="utf-8")
    audit = validation.audit_dataset(
        pd.DataFrame({"trade_date": ["20260102"], "code": ["A"]}),
        key_fields=("trade_date", "code"),
    )

    complete = validation.build_dataset_manifest(
        api_name="fake",
        output_path=output,
        audit=audit,
        execution_complete=True,
        metadata={"doc_id": 10303},
    )
    partial = validation.build_dataset_manifest(
        api_name="fake",
        output_path=output,
        audit=audit,
        execution_complete=False,
    )

    assert complete["publishable"] is True
    assert complete["output_sha256"] == validation.sha256_file(output)
    assert complete["metadata"]["doc_id"] == 10303
    assert partial["publishable"] is False


def test_atomic_dataset_manifest_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "dataset-manifest.json"
    payload = {"schema_version": 1, "publishable": True}

    validation.write_json_atomic(target, payload)

    assert validation.load_json(target) == payload
    assert not target.with_suffix(target.suffix + ".tmp").exists()


def test_expected_key_csv_preserves_leading_zeroes(tmp_path: Path) -> None:
    expected_path = tmp_path / "expected.csv"
    expected_path.write_text(
        "trade_date,code\n20260102,000001\n", encoding="utf-8"
    )

    frame = validation.load_table(expected_path, all_strings=True)

    assert frame.loc[0, "code"] == "000001"
    assert frame.loc[0, "trade_date"] == "20260102"


def test_exact_expected_key_filter_removes_interval_overfetch() -> None:
    observed = pd.DataFrame(
        {
            "trade_date": ["20260102", "20260103", "20260105"],
            "code": ["A", "A", "A"],
            "close": [1.0, 99.0, 1.1],
        }
    )
    expected = pd.DataFrame(
        {
            "trade_date": ["20260102", "20260105"],
            "code": ["A", "A"],
        }
    )

    filtered, filter_audit = validation.filter_to_expected_keys(
        observed,
        key_fields=("trade_date", "code"),
        expected_keys=expected,
    )
    audit = validation.audit_dataset(
        filtered,
        key_fields=("trade_date", "code"),
        expected_keys=expected,
    )

    assert filtered["trade_date"].tolist() == ["20260102", "20260105"]
    assert filter_audit["rows_removed_outside_expected_keys"] == 1
    assert audit["all_hard_checks_pass"] is True


def test_dataset_manifest_redacts_secret_metadata_and_can_withhold_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "withheld.csv"
    audit = {"all_hard_checks_pass": False, "missing_keys": 2}

    manifest = validation.build_dataset_manifest(
        api_name="fake",
        output_path=output,
        output_published=False,
        audit=audit,
        execution_complete=False,
        metadata={"doc_id": 1, "nested": {"token": "do-not-leak"}},
    )

    assert manifest["publishable"] is False
    assert manifest["output_published"] is False
    assert manifest["output_sha256"] is None
    assert manifest["metadata"]["nested"]["token"] == "<redacted>"
