from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
MODULE_PATH = SCRIPTS_DIR / "download_datacube.py"


def _load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "download_datacube_execution", MODULE_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


cli = _load_module()


class FakePlan:
    latest = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        FakePlan.latest = self


def _report(*, exhausted: bool = True) -> dict:
    return {
        "complete": True,
        "source_exhausted": exhausted,
        "exhaustion_inferred": False,
        "termination_reason": "has_more_false" if exhausted else "user_limit",
    }


def _partition(
    index: int,
    status: str,
    path: Path | None,
    *,
    exhausted=True,
    sha256: str | None = None,
    row_count: int | None = None,
):
    if path is not None and path.is_file():
        if sha256 is None:
            sha256 = cli.sha256_file(path)
        if row_count is None:
            row_count = len(cli._read_partition(path))
    return SimpleNamespace(
        index=index,
        status=status,
        path=path,
        sha256=sha256,
        row_count=row_count,
        pagination_report=_report(exhausted=exhausted),
    )


def test_plan_success_filters_interval_overfetch_and_publishes_manifests(
    tmp_path: Path, monkeypatch
) -> None:
    plan_path = tmp_path / "requests.jsonl"
    plan_path.write_text(
        '{"code":"A","start_date":"20260101","end_date":"20260105"}\n',
        encoding="utf-8",
    )
    expected_path = tmp_path / "expected.csv"
    expected_path.write_text(
        "trade_date,code\n20260102,A\n20260105,A\n", encoding="utf-8"
    )
    output = tmp_path / "panel.csv"
    checkpoint_dir = tmp_path / "checkpoints"
    execution_manifest = checkpoint_dir / "execution.json"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            partition_path = plan.output_dir / "part.csv"
            pd.DataFrame(
                {
                    "trade_date": ["20260102", "20260103", "20260105"],
                    "code": ["A", "A", "A"],
                    "close": [1.0, 99.0, 1.1],
                }
            ).to_csv(partition_path, index=False)
            Path(kwargs["manifest_path"]).write_text(
                '{"complete":true}\n', encoding="utf-8"
            )
            return SimpleNamespace(
                complete=True,
                partitions=[
                    _partition(0, "written", partition_path, exhausted=False)
                ],
            )

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--request-plan",
            str(plan_path),
            "--checkpoint-dir",
            str(checkpoint_dir),
            "--execution-manifest",
            str(execution_manifest),
            "--out",
            str(output),
            "--fields",
            "trade_date,code,close",
            "--key-fields",
            "trade_date,code",
            "--expected-keys",
            str(expected_path),
            "--filter-to-expected-keys",
            "--group-fields",
            "trade_date",
            "--doc-id",
            "10303",
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 0
    assert pd.read_csv(output)["trade_date"].astype(str).tolist() == [
        "20260102",
        "20260105",
    ]
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "complete"
    assert manifest["publishable"] is True
    assert manifest["metadata"]["doc_id"] == 10303
    assert manifest["metadata"]["request_plan_sha256"] == cli.sha256_file(plan_path)
    assert manifest["expected_keys_sha256"] == cli.sha256_file(expected_path)
    assert manifest["output_sha256"] == cli.sha256_file(output)
    assert manifest["audit"]["expected_key_comparison"]["missing_keys"] == 0
    assert manifest["audit"]["group_cardinality"]["mismatched_groups"] == 0
    assert manifest["audit"]["exact_expected_key_filter"][
        "rows_removed_outside_expected_keys"
    ] == 1
    assert FakePlan.latest.param_chunks == [
        {"code": "A", "start_date": "20260101", "end_date": "20260105"}
    ]


def test_incomplete_plan_withholds_output_and_records_key_violations(
    tmp_path: Path, monkeypatch
) -> None:
    expected_path = tmp_path / "expected.csv"
    expected_path.write_text(
        "trade_date,code\n20260102,A\n20260105,B\n", encoding="utf-8"
    )
    output = tmp_path / "panel.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            first = plan.output_dir / "first.csv"
            pd.DataFrame(
                {"trade_date": ["20260102"], "code": ["A"]}
            ).to_csv(first, index=False)
            stale = plan.output_dir / "stale.csv"
            pd.DataFrame(
                {"trade_date": ["20260105"], "code": ["B"]}
            ).to_csv(stale, index=False)
            Path(kwargs["manifest_path"]).write_text(
                '{"complete":false}\n', encoding="utf-8"
            )
            return SimpleNamespace(
                complete=False,
                partitions=[
                    _partition(0, "written", first),
                    _partition(1, "failed", stale),
                ],
            )

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--split-by",
            "code",
            "--split-values",
            "A,B",
            "--continue-on-error",
            "--out",
            str(output),
            "--fields",
            "trade_date,code",
            "--key-fields",
            "trade_date,code",
            "--expected-keys",
            str(expected_path),
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["publishable"] is False
    assert manifest["execution_complete"] is False
    assert manifest["output_sha256"] is None
    assert manifest["audit"]["expected_key_comparison"]["missing_keys"] == 1


def test_complete_plan_without_expected_keys_requires_source_exhaustion(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "limited.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            part = plan.output_dir / "limited.csv"
            pd.DataFrame({"code": ["A"]}).to_csv(part, index=False)
            Path(kwargs["manifest_path"]).write_text("{}\n", encoding="utf-8")
            return SimpleNamespace(
                complete=True,
                partitions=[_partition(0, "written", part, exhausted=False)],
            )

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--out",
            str(output),
            "--fields",
            "code",
            "--key-fields",
            "code",
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "limited.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["audit"]["source_coverage"]["unproven_reports"] == 1


def test_verified_empty_partition_can_publish_header_only_output(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "empty.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            part = plan.output_dir / "empty.csv"
            part.write_text("\n", encoding="utf-8")
            Path(kwargs["manifest_path"]).write_text("{}\n", encoding="utf-8")
            return SimpleNamespace(
                complete=True,
                partitions=[_partition(0, "written", part)],
            )

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--out",
            str(output),
            "--fields",
            "trade_date,code",
            "--key-fields",
            "trade_date,code",
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 0
    assert output.read_text(encoding="utf-8-sig").strip() == "trade_date,code"


def test_partition_merge_preserves_leading_zero_key_fields(tmp_path: Path) -> None:
    part = tmp_path / "part.csv"
    part.write_text("trade_date,code\n20260102,000001\n", encoding="utf-8")
    result = SimpleNamespace(partitions=[_partition(0, "written", part)])

    combined = cli.combine_execution_partitions(
        result,
        key_fields=("trade_date", "code"),
    )

    assert combined.loc[0, "trade_date"] == "20260102"
    assert combined.loc[0, "code"] == "000001"


def test_partition_merge_rejects_missing_verified_artifact(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    result = SimpleNamespace(
        partitions=[
            _partition(
                0,
                "written",
                missing,
                sha256="0" * 64,
                row_count=0,
            )
        ]
    )

    with pytest.raises(ValueError, match="artifact is missing"):
        cli.combine_execution_partitions(result)


def test_partition_merge_rejects_tampered_artifact_hash(tmp_path: Path) -> None:
    part = tmp_path / "part.csv"
    part.write_text("code\nA\n", encoding="utf-8")
    partition = _partition(0, "written", part)
    part.write_text("code\nB\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch before read"):
        cli.combine_execution_partitions(
            SimpleNamespace(partitions=[partition]),
            key_fields=("code",),
        )


def test_partition_merge_rejects_artifact_changed_while_reading(
    tmp_path: Path, monkeypatch
) -> None:
    part = tmp_path / "part.csv"
    part.write_text("code\nA\n", encoding="utf-8")
    partition = _partition(0, "written", part)
    original_read = cli._read_partition

    def mutate_after_read(path, *, key_fields=()):
        frame = original_read(path, key_fields=key_fields)
        path.write_text("code\nB\n", encoding="utf-8")
        return frame

    monkeypatch.setattr(cli, "_read_partition", mutate_after_read)

    with pytest.raises(ValueError, match="sha256 mismatch after read"):
        cli.combine_execution_partitions(
            SimpleNamespace(partitions=[partition]),
            key_fields=("code",),
        )


def test_partition_merge_rejects_wrong_row_count(tmp_path: Path) -> None:
    part = tmp_path / "part.csv"
    part.write_text("code\nA\n", encoding="utf-8")
    result = SimpleNamespace(partitions=[_partition(0, "written", part, row_count=2)])

    with pytest.raises(ValueError, match="row_count mismatch"):
        cli.combine_execution_partitions(result, key_fields=("code",))


@pytest.mark.parametrize(
    ("failure_mode", "error_fragment"),
    [
        ("missing", "artifact is missing"),
        ("tampered", "sha256 mismatch before read"),
        ("row_count", "row_count mismatch"),
    ],
)
def test_partition_contract_failure_withholds_publication(
    tmp_path: Path,
    monkeypatch,
    failure_mode: str,
    error_fragment: str,
) -> None:
    output = tmp_path / f"{failure_mode}.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            part = plan.output_dir / "part.csv"
            part.write_text("code\nA\n", encoding="utf-8")
            Path(kwargs["manifest_path"]).write_text("{}\n", encoding="utf-8")
            partition = _partition(0, "written", part)
            if failure_mode == "missing":
                part.unlink()
            elif failure_mode == "tampered":
                part.write_text("code\nB\n", encoding="utf-8")
            else:
                partition.row_count += 1
            return SimpleNamespace(complete=True, partitions=[partition])

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--out",
            str(output),
            "--fields",
            "code",
            "--key-fields",
            "code",
            "--preview-rows",
            "0",
        ],
    )

    assert cli.main() == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / f"{failure_mode}.csv.dataset-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["publishable"] is False
    assert error_fragment in manifest["audit"]["execution_error"]


def test_expected_key_mutation_during_execution_withholds_publication(
    tmp_path: Path, monkeypatch
) -> None:
    expected_path = tmp_path / "expected.csv"
    expected_path.write_text("code\nA\n", encoding="utf-8")
    frozen_sha256 = cli.sha256_file(expected_path)
    output = tmp_path / "panel.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            part = plan.output_dir / "part.csv"
            part.write_text("code\nA\n", encoding="utf-8")
            Path(kwargs["manifest_path"]).write_text("{}\n", encoding="utf-8")
            partition = _partition(0, "written", part)
            expected_path.write_text("code\nB\n", encoding="utf-8")
            return SimpleNamespace(complete=True, partitions=[partition])

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--out",
            str(output),
            "--fields",
            "code",
            "--key-fields",
            "code",
            "--expected-keys",
            str(expected_path),
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["publishable"] is False
    assert manifest["expected_keys_sha256"] == frozen_sha256
    assert "changed during execution" in manifest["audit"]["validation_error"]


def test_expected_key_mutation_while_staging_withholds_publication(
    tmp_path: Path, monkeypatch
) -> None:
    expected_path = tmp_path / "expected.csv"
    expected_path.write_text("code\nA\n", encoding="utf-8")
    frozen_sha256 = cli.sha256_file(expected_path)
    output = tmp_path / "panel.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            part = plan.output_dir / "part.csv"
            part.write_text("code\nA\n", encoding="utf-8")
            Path(kwargs["manifest_path"]).write_text("{}\n", encoding="utf-8")
            return SimpleNamespace(
                complete=True,
                partitions=[_partition(0, "written", part)],
            )

    original_stage = cli.stage_output

    def mutate_contract_after_stage(dataframe, path, output_format):
        staged = original_stage(dataframe, path, output_format)
        expected_path.write_text("code\nB\n", encoding="utf-8")
        return staged

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(cli, "stage_output", mutate_contract_after_stage)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--out",
            str(output),
            "--fields",
            "code",
            "--key-fields",
            "code",
            "--expected-keys",
            str(expected_path),
            "--preview-rows",
            "0",
        ],
    )

    assert cli.main() == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["expected_keys_sha256"] == frozen_sha256
    assert "changed during execution" in manifest["audit"]["validation_error"]


def test_request_plan_mutation_during_execution_withholds_publication(
    tmp_path: Path, monkeypatch
) -> None:
    plan_path = tmp_path / "requests.jsonl"
    plan_path.write_text('{"code":"A"}\n', encoding="utf-8")
    frozen_sha256 = cli.sha256_file(plan_path)
    output = tmp_path / "panel.csv"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def execute_partition_plan(self, plan, **kwargs):
            assert plan.param_chunks == [{"code": "A"}]
            plan.output_dir.mkdir(parents=True, exist_ok=True)
            part = plan.output_dir / "part.csv"
            part.write_text("code\nA\n", encoding="utf-8")
            Path(kwargs["manifest_path"]).write_text("{}\n", encoding="utf-8")
            partition = _partition(0, "written", part)
            plan_path.write_text('{"code":"B"}\n', encoding="utf-8")
            return SimpleNamespace(complete=True, partitions=[partition])

    monkeypatch.setattr(cli, "PartitionPlan", FakePlan)
    monkeypatch.setattr(cli, "DataCubeAPI", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--request-plan",
            str(plan_path),
            "--out",
            str(output),
            "--fields",
            "code",
            "--key-fields",
            "code",
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "panel.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["publishable"] is False
    assert manifest["metadata"]["request_plan_sha256"] == frozen_sha256
    assert "changed during execution" in manifest["audit"]["validation_error"]


def test_legacy_split_partial_never_publishes_even_with_continue_on_error(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "legacy.csv"

    class LegacyClient:
        def __init__(self, **kwargs):
            pass

        def get_data(self, api_name, **kwargs):
            if kwargs["trade_date"] == 20260105:
                raise RuntimeError("backend failure")
            return pd.DataFrame(
                {"trade_date": [kwargs["trade_date"]], "code": ["A"]}
            )

    monkeypatch.setattr(cli, "PartitionPlan", None)
    monkeypatch.setattr(cli, "DataCubeAPI", LegacyClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--split-by",
            "trade_date",
            "--split-values",
            "20260102,20260105",
            "--continue-on-error",
            "--out",
            str(output),
            "--fields",
            "trade_date,code",
            "--no-auto-paging",
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "legacy.csv.dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publishable"] is False
    assert manifest["execution_complete"] is False


def test_legacy_auto_paging_without_expected_keys_cannot_publish(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "legacy-auto.csv"

    class LegacyClient:
        def __init__(self, **kwargs):
            pass

        def get_data(self, api_name, **kwargs):
            return pd.DataFrame({"trade_date": ["20260102"], "code": ["A"]})

    monkeypatch.setattr(cli, "PartitionPlan", None)
    monkeypatch.setattr(cli, "DataCubeAPI", LegacyClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_datacube.py",
            "fake",
            "--out",
            str(output),
            "--fields",
            "trade_date,code",
            "--preview-rows",
            "0",
        ],
    )

    exit_code = cli.main()

    assert exit_code == 1
    assert not output.exists()
    manifest = json.loads(
        (tmp_path / "legacy-auto.csv.dataset-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["publication_state"] == "withheld"
    assert manifest["publishable"] is False
    assert "requires" in manifest["audit"]["execution_error"]


def test_manifest_commit_failure_rolls_back_preexisting_output_and_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "panel.csv"
    output.write_text("old-output\n", encoding="utf-8")
    manifest = tmp_path / "panel.manifest.json"
    manifest.write_text('{"old":true}\n', encoding="utf-8")
    staged = tmp_path / ".panel.staged.csv"
    staged.write_text("new-output\n", encoding="utf-8")
    original_write = cli.write_json_atomic
    calls = 0

    def fail_final_manifest(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated final manifest failure")
        original_write(path, payload)

    monkeypatch.setattr(cli, "write_json_atomic", fail_final_manifest)

    with pytest.raises(OSError, match="simulated final manifest failure"):
        cli.commit_staged_dataset(
            staged_output=staged,
            output_path=output,
            manifest_path=manifest,
            final_manifest={"publishable": True},
        )

    assert output.read_text(encoding="utf-8") == "old-output\n"
    assert json.loads(manifest.read_text(encoding="utf-8")) == {"old": True}


def test_backup_copy_failure_cleans_partial_backup_without_touching_output(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "panel.csv"
    output.write_text("old-output\n", encoding="utf-8")
    manifest = tmp_path / "panel.manifest.json"
    staged = tmp_path / ".panel.staged.csv"
    staged.write_text("new-output\n", encoding="utf-8")

    def fail_copy(source, target):
        Path(target).write_text("partial-backup", encoding="utf-8")
        raise OSError("simulated backup failure")

    monkeypatch.setattr(cli.shutil, "copy2", fail_copy)

    with pytest.raises(OSError, match="simulated backup failure"):
        cli.commit_staged_dataset(
            staged_output=staged,
            output_path=output,
            manifest_path=manifest,
            final_manifest={"publishable": True},
        )

    assert output.read_text(encoding="utf-8") == "old-output\n"
    assert not manifest.exists()
    assert not list(tmp_path.glob("*.bak"))


def test_artifact_paths_must_be_distinct(tmp_path: Path) -> None:
    parser = cli.build_parser()
    shared = tmp_path / "same.csv"
    args = parser.parse_args(
        [
            "fake",
            "--out",
            str(shared),
            "--expected-keys",
            str(shared),
            "--key-fields",
            "trade_date,code",
        ]
    )

    with pytest.raises(SystemExit, match="resolve to the same path"):
        cli.validate_artifact_paths(
            args,
            dataset_manifest=cli.resolve_dataset_manifest(args),
        )


def test_missing_report_on_any_successful_partition_is_unproven() -> None:
    result = SimpleNamespace(
        partitions=[
            _partition(0, "written", Path("first.csv")),
            SimpleNamespace(
                index=1,
                status="resumed",
                path=Path("second.csv"),
                pagination_report=None,
            ),
        ]
    )

    audit = cli.audit_source_coverage(
        partition_result=result,
        single_report=None,
        expected_keys_provided=False,
        auto_paging=True,
    )

    assert audit["reports_checked"] == 2
    assert audit["unproven_reports"] == 1
    assert audit["passed"] is False


def test_no_auto_paging_has_consistent_explicit_single_request_basis() -> None:
    audit = cli.audit_source_coverage(
        partition_result=SimpleNamespace(
            partitions=[
                _partition(0, "written", Path("first.csv"), exhausted=False)
            ]
        ),
        single_report=None,
        expected_keys_provided=False,
        auto_paging=False,
    )

    assert audit == {
        "basis": "explicit_no_auto_paging",
        "reports_checked": 0,
        "unproven_reports": 0,
        "passed": True,
    }


def test_existing_publication_lock_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "panel.csv"
    manifest = tmp_path / "panel.manifest.json"
    lock = cli._publication_lock_paths(output, manifest)[-1]
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("pid=other\n", encoding="ascii")

    with pytest.raises(RuntimeError, match="publication lock already exists"):
        cli.write_withheld_manifest_locked(
            output_path=output,
            manifest_path=manifest,
            payload={"publishable": False},
        )

    assert lock.read_text(encoding="ascii") == "pid=other\n"
    assert not manifest.exists()
