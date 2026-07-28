from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from datacube_download.cli import build_parser  # noqa: E402
from datacube_download.workflow import run_check, run_pull, run_verified  # noqa: E402


class FakePlan:
    latest = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        FakePlan.latest = self


def _job_payload(*, expected_keys: bool = True) -> dict:
    payload = {
        "schema_version": 1,
        "api": {
            "name": "fake",
            "doc_id": 10303,
            "fields": ["trade_date", "code", "close"],
        },
        "requests": {"partitions": [{"code": "A"}]},
        "execution": {"max_pages": 5},
        "validation": {"key_fields": ["trade_date", "code"]},
        "output": {"path": "panel.csv"},
    }
    if expected_keys:
        payload["validation"].update(
            {
                "expected_keys_file": "expected.csv",
                "filter_to_expected_keys": True,
            }
        )
    return payload


def _write_job(tmp_path: Path, *, expected_keys: bool = True) -> Path:
    if expected_keys:
        (tmp_path / "expected.csv").write_text(
            "trade_date,code\n20260102,A\n20260105,A\n",
            encoding="utf-8",
        )
    path = tmp_path / "job.json"
    path.write_text(json.dumps(_job_payload(expected_keys=expected_keys)), encoding="utf-8")
    return path


def _partition(path: Path, *, exhausted: bool) -> SimpleNamespace:
    digest = sha256(path.read_bytes()).hexdigest()
    return SimpleNamespace(
        index=0,
        status="written",
        path=path,
        sha256=digest,
        row_count=len(pd.read_csv(path)),
        pagination_report={
            "source_exhausted": exhausted,
            "exhaustion_inferred": False,
            "termination_reason": "server_exhausted" if exhausted else "max_pages",
        },
    )


class SuccessfulClient:
    last_kwargs = None

    def execute_partition_plan(self, plan, **kwargs):
        type(self).last_kwargs = kwargs
        plan.output_dir.mkdir(parents=True, exist_ok=True)
        part = plan.output_dir / "part.csv"
        pd.DataFrame(
            {
                "trade_date": ["20260102", "20260103", "20260105"],
                "code": ["A", "A", "A"],
                "close": [1.0, 99.0, 1.1],
            }
        ).to_csv(part, index=False)
        manifest = Path(kwargs["manifest_path"])
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text('{"complete":true}\n', encoding="utf-8")
        return SimpleNamespace(
            complete=True,
            partitions=[_partition(part, exhausted=False)],
        )


def test_pull_is_bounded_and_exploratory(tmp_path: Path, capsys) -> None:
    class PullClient:
        kwargs = None

        def get_data(self, api_name, **kwargs):
            type(self).kwargs = kwargs
            return pd.DataFrame({"code": ["A"], "close": [1.0]})

    output = tmp_path / "sample.csv"
    args = build_parser().parse_args(
        [
            "pull",
            "fake",
            "--param",
            "code=A",
            "--fields",
            "code,close",
            "--out",
            str(output),
            "--preview-rows",
            "0",
        ]
    )

    assert run_pull(args, client=PullClient()) == 0
    assert PullClient.kwargs["auto_paging"] is False
    assert PullClient.kwargs["max_pages"] is None
    assert output.is_file()
    assert not output.with_name(output.name + ".dataset-manifest.json").exists()
    assert "not a verified dataset" in capsys.readouterr().out


def test_pull_all_pages_requires_a_bound() -> None:
    args = build_parser().parse_args(["pull", "fake", "--all-pages"])

    from datacube_download.job import JobError
    import pytest

    with pytest.raises(JobError, match="requires a positive"):
        run_pull(args, client=object())


def test_check_is_read_only_and_reports_hashes(tmp_path: Path, capsys) -> None:
    job = _write_job(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    assert run_check(job) == 0

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert after == before
    output = capsys.readouterr().out
    assert "SHA256 job:" in output
    assert "SHA256 expected_keys_file:" in output


def test_verified_run_filters_overfetch_and_publishes(tmp_path: Path) -> None:
    job = _write_job(tmp_path)

    assert run_verified(
        job,
        client=SuccessfulClient(),
        partition_plan_class=FakePlan,
    ) == 0

    output = tmp_path / "panel.csv"
    assert pd.read_csv(output)["trade_date"].tolist() == [20260102, 20260105]
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "complete"
    assert manifest["publishable"] is True
    assert manifest["metadata"]["doc_id"] == 10303
    assert FakePlan.latest.concurrent is False
    assert FakePlan.latest.max_pages == 5
    assert SuccessfulClient.last_kwargs["resume"] is True


def test_verified_run_requires_source_exhaustion_without_expected_keys(
    tmp_path: Path,
) -> None:
    job = _write_job(tmp_path, expected_keys=False)

    assert run_verified(
        job,
        client=SuccessfulClient(),
        partition_plan_class=FakePlan,
    ) == 1

    assert not (tmp_path / "panel.csv").exists()
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["audit"]["source_coverage"]["passed"] is False


def test_verified_run_accepts_proven_source_exhaustion(tmp_path: Path) -> None:
    job = _write_job(tmp_path, expected_keys=False)

    class ExhaustedClient(SuccessfulClient):
        def execute_partition_plan(self, plan, **kwargs):
            result = super().execute_partition_plan(plan, **kwargs)
            result.partitions[0].pagination_report["source_exhausted"] = True
            return result

    assert run_verified(
        job,
        client=ExhaustedClient(),
        partition_plan_class=FakePlan,
    ) == 0
    assert (tmp_path / "panel.csv").is_file()


def test_job_mutation_during_execution_withholds_and_protects_output(
    tmp_path: Path,
) -> None:
    job = _write_job(tmp_path)
    output = tmp_path / "panel.csv"
    output.write_text("old\nvalue\n", encoding="utf-8")

    class MutatingClient(SuccessfulClient):
        def execute_partition_plan(self, plan, **kwargs):
            result = super().execute_partition_plan(plan, **kwargs)
            job.write_text(job.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return result

    assert run_verified(
        job,
        client=MutatingClient(),
        partition_plan_class=FakePlan,
    ) == 1
    assert output.read_text(encoding="utf-8") == "old\nvalue\n"


def test_partition_failure_withholds_output_and_keeps_checkpoint(
    tmp_path: Path,
) -> None:
    job = _write_job(tmp_path)

    class FailedClient:
        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            checkpoint = plan.output_dir / "partial.csv"
            checkpoint.write_text("trade_date,code,close\n", encoding="utf-8")
            return SimpleNamespace(
                complete=False,
                partitions=[
                    SimpleNamespace(
                        index=0,
                        status="failed",
                        path=None,
                        sha256=None,
                        row_count=0,
                        pagination_report=None,
                    )
                ],
            )

    assert run_verified(
        job,
        client=FailedClient(),
        partition_plan_class=FakePlan,
    ) == 1
    assert not (tmp_path / "panel.csv").exists()
    assert (tmp_path / ".panel.csv.partitions/partial.csv").is_file()


def test_missing_execution_manifest_fails_closed(tmp_path: Path) -> None:
    job = _write_job(tmp_path)

    class NoManifestClient(SuccessfulClient):
        def execute_partition_plan(self, plan, **kwargs):
            result = super().execute_partition_plan(plan, **kwargs)
            Path(kwargs["manifest_path"]).unlink()
            return result

    assert run_verified(
        job,
        client=NoManifestClient(),
        partition_plan_class=FakePlan,
    ) == 1
    assert not (tmp_path / "panel.csv").exists()


def test_runtime_secret_is_redacted_from_logs_and_manifest(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    job = _write_job(tmp_path)
    secret = "highly-sensitive-token"
    monkeypatch.setenv("DATACUBE_TOKEN", secret)

    class LeakingClient:
        def execute_partition_plan(self, plan, **kwargs):
            raise RuntimeError(f"transport rejected {secret}")

    assert run_verified(
        job,
        client=LeakingClient(),
        partition_plan_class=FakePlan,
    ) == 1

    captured = capsys.readouterr()
    manifest_text = (
        tmp_path / "panel.csv.dataset-manifest.json"
    ).read_text(encoding="utf-8")
    assert secret not in captured.out
    assert secret not in captured.err
    assert secret not in manifest_text
    assert "<redacted>" in captured.err
