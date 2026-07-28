from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from datacube_download.inputs import prepare_inputs  # noqa: E402
from datacube_download.job import JobError, load_job  # noqa: E402


def _payload() -> dict:
    return {
        "schema_version": 1,
        "api": {
            "name": "a_daily",
            "doc_id": 10303,
            "fields": ["trade_date", "code", "close"],
        },
        "requests": {"partitions": [{}]},
        "execution": {"max_pages": 10},
        "validation": {"key_fields": ["trade_date", "code"]},
        "output": {"path": "output/panel.csv"},
    }


def _write_job(tmp_path: Path, payload: dict | None = None) -> Path:
    path = tmp_path / "job.json"
    path.write_text(
        json.dumps(payload if payload is not None else _payload()),
        encoding="utf-8",
    )
    return path


def test_job_defaults_and_relative_paths(tmp_path: Path) -> None:
    job = load_job(_write_job(tmp_path))

    assert job.api.base_params == {}
    assert job.execution.auto_paging is True
    assert job.execution.partition_workers == 1
    assert job.execution.resume is True
    assert job.output.path == (tmp_path / "output/panel.csv").resolve()
    assert job.execution.checkpoint_dir == (
        tmp_path / "output/.panel.csv.partitions"
    ).resolve()
    assert job.output.dataset_manifest == (
        tmp_path / "output/panel.csv.dataset-manifest.json"
    ).resolve()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unknown": True}), "unknown keys"),
        (lambda value: value.update({"schema_version": 2}), "must equal 1"),
        (
            lambda value: value["requests"].update(
                {"partitions_file": "requests.jsonl"}
            ),
            "exactly one",
        ),
        (
            lambda value: value["execution"].pop("max_pages"),
            "max_pages is required",
        ),
        (
            lambda value: value["api"].update({"base_params": {"token": "bad"}}),
            "secret-bearing",
        ),
    ],
)
def test_job_rejects_invalid_contract(
    tmp_path: Path, mutate, message: str
) -> None:
    payload = _payload()
    mutate(payload)

    with pytest.raises(JobError, match=message):
        load_job(_write_job(tmp_path, payload))


def test_partition_file_preserves_codes_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "requests.csv"
    plan.write_text("code\n000001\n000002.SZ\n", encoding="utf-8")
    payload = _payload()
    payload["requests"] = {"partitions_file": "requests.csv"}
    inputs = prepare_inputs(load_job(_write_job(tmp_path, payload)))

    assert inputs.partitions == ({"code": "000001"}, {"code": "000002.SZ"})
    assert inputs.hash_for("partitions_file")

    plan.write_text("code\n000001\n000001\n", encoding="utf-8")
    with pytest.raises(JobError, match="duplicate"):
        prepare_inputs(load_job(_write_job(tmp_path, payload)))


def test_expected_keys_and_filter_contract(tmp_path: Path) -> None:
    payload = _payload()
    payload["validation"]["filter_to_expected_keys"] = True

    with pytest.raises(JobError, match="requires expected_keys_file"):
        load_job(_write_job(tmp_path, payload))


def test_check_rejects_invalid_expected_key_table(tmp_path: Path) -> None:
    expected = tmp_path / "expected.csv"
    expected.write_text(
        "trade_date,code\n20260102,A\n20260102,A\n",
        encoding="utf-8",
    )
    payload = _payload()
    payload["validation"]["expected_keys_file"] = "expected.csv"

    with pytest.raises(JobError, match="unique non-null keys"):
        prepare_inputs(load_job(_write_job(tmp_path, payload)))


def test_job_hash_detects_change_between_parse_and_prepare(tmp_path: Path) -> None:
    path = _write_job(tmp_path)
    job = load_job(path)
    payload = _payload()
    payload["metadata"] = {"changed": True}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JobError, match="changed during execution"):
        prepare_inputs(job)
