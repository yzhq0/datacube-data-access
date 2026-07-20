from __future__ import annotations

import importlib.util
from pathlib import Path
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
            "download_datacube_integration", MODULE_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


cli = _load_module()


@pytest.mark.skipif(
    cli.PartitionPlan is None,
    reason="verified partition execution requires tushare_plus>=0.1.9",
)
def test_real_partition_engine_sidecars_and_resume(tmp_path: Path, monkeypatch) -> None:
    from tushare_plus import DataCubeAPI as RealDataCubeAPI
    from tushare_plus import PaginationReport

    class OfflineDataCubeAPI(RealDataCubeAPI):
        calls = 0

        def __init__(self, **kwargs):
            kwargs["api_limits_file"] = str(tmp_path / "limits.csv")
            super().__init__(**kwargs)

        def get_data(self, api_name, **kwargs):
            type(self).calls += 1
            code = str(kwargs["code"])
            frame = pd.DataFrame(
                {
                    "trade_date": ["20260102"],
                    "code": [code],
                    "close": [1.0 if code == "A" else 2.0],
                }
            )
            report = PaginationReport(
                api_name=api_name,
                mode="sequential",
                page_size=100,
                pages_requested=1,
                pages_completed=1,
                rows_fetched=1,
                termination_reason="server_exhausted",
                complete=True,
                request_satisfied=True,
                source_exhausted=True,
            )
            return frame, report

    plan_path = tmp_path / "requests.jsonl"
    plan_path.write_text('{"code":"A"}\n{"code":"B"}\n', encoding="utf-8")
    expected_path = tmp_path / "expected.csv"
    expected_path.write_text(
        "trade_date,code\n20260102,A\n20260102,B\n", encoding="utf-8"
    )
    output = tmp_path / "panel.csv"
    checkpoint_dir = tmp_path / "parts"
    argv = [
        "download_datacube.py",
        "fake",
        "--token",
        "integration-secret",
        "--request-plan",
        str(plan_path),
        "--checkpoint-dir",
        str(checkpoint_dir),
        "--limit-per-request",
        "100",
        "--out",
        str(output),
        "--fields",
        "trade_date,code,close",
        "--key-fields",
        "trade_date,code",
        "--expected-keys",
        str(expected_path),
        "--preview-rows",
        "0",
    ]
    monkeypatch.setattr(cli, "DataCubeAPI", OfflineDataCubeAPI)
    monkeypatch.setattr(sys, "argv", argv)

    assert cli.main() == 0
    assert OfflineDataCubeAPI.calls == 2
    sidecars = sorted(checkpoint_dir.glob("*.meta.json"))
    assert len(sidecars) == 2
    assert "integration-secret" not in "".join(
        path.read_text(encoding="utf-8") for path in checkpoint_dir.rglob("*.json")
    )
    assert "integration-secret" not in (
        tmp_path / "panel.csv.dataset-manifest.json"
    ).read_text(encoding="utf-8")

    OfflineDataCubeAPI.calls = 0
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    assert OfflineDataCubeAPI.calls == 0
    assert len(pd.read_csv(output)) == 2
