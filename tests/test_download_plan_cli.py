from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
MODULE_PATH = SCRIPTS_DIR / "download_datacube.py"


def _load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location("download_datacube", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


cli = _load_module()


def test_jsonl_request_plan_accepts_complete_multi_parameter_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plan.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"code":"000001.SZ","start_date":"20260101","end_date":"20260131"}',
                '{"params":{"code":"000002.SZ","start_date":"20260201","end_date":"20260228"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    chunks = cli.load_request_plan(path)

    assert chunks == [
        {
            "code": "000001.SZ",
            "start_date": "20260101",
            "end_date": "20260131",
        },
        {
            "code": "000002.SZ",
            "start_date": "20260201",
            "end_date": "20260228",
        },
    ]


def test_csv_request_plan_parses_each_row_as_complete_params(tmp_path: Path) -> None:
    path = tmp_path / "plan.csv"
    path.write_text(
        "code,start_date,end_date,active\n"
        "000001,20260101,20260131,true\n"
        "000002.SZ,20260201,20260228,false\n",
        encoding="utf-8",
    )

    chunks = cli.load_request_plan(path)

    assert chunks[0] == {
        "code": "000001",
        "start_date": "20260101",
        "end_date": "20260131",
        "active": "true",
    }
    assert chunks[1]["active"] == "false"


def test_request_plan_rejects_duplicate_records(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text('[{"code":"A"},{"code":"A"}]', encoding="utf-8")

    with pytest.raises(SystemExit, match="duplicate record"):
        cli.load_request_plan(path)


def test_request_plan_rejects_secret_bearing_params(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        '[{"code":"A","token":"must-not-enter-manifest"}]', encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="secret-bearing key 'token'"):
        cli.load_request_plan(path)


def test_cli_exposes_resumable_plan_and_dataset_contract_options() -> None:
    help_text = cli.build_parser().format_help()

    for option in (
        "--request-plan",
        "--checkpoint-dir",
        "--partition-workers",
        "--execution-manifest",
        "--expected-keys",
        "--filter-to-expected-keys",
        "--dataset-manifest",
    ):
        assert option in help_text
