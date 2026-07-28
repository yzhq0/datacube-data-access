from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from datacube_download import publication  # noqa: E402


def test_atomic_publication_replaces_output_and_completes_manifest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "panel.csv"
    manifest = tmp_path / "panel.manifest.json"
    staged = publication.stage_output(
        pd.DataFrame({"code": ["A"]}),
        output,
        "csv",
    )

    publication.commit_staged_dataset(
        staged_output=staged,
        output_path=output,
        manifest_path=manifest,
        final_manifest={"publishable": True, "output_published": True},
    )

    assert pd.read_csv(output)["code"].tolist() == ["A"]
    assert json.loads(manifest.read_text(encoding="utf-8"))[
        "publication_state"
    ] == "complete"


def test_publication_rolls_back_existing_output_on_final_manifest_failure(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "panel.csv"
    output.write_text("old\nvalue\n", encoding="utf-8")
    manifest = tmp_path / "panel.manifest.json"
    manifest.write_text('{"old":true}\n', encoding="utf-8")
    staged = publication.stage_output(
        pd.DataFrame({"code": ["A"]}),
        output,
        "csv",
    )
    real_write = publication.write_json_atomic
    calls = 0

    def fail_second_write(path: Path, payload) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("manifest failure")
        real_write(path, payload)

    monkeypatch.setattr(publication, "write_json_atomic", fail_second_write)

    with pytest.raises(OSError, match="manifest failure"):
        publication.commit_staged_dataset(
            staged_output=staged,
            output_path=output,
            manifest_path=manifest,
            final_manifest={"publishable": True, "output_published": True},
        )

    assert output.read_text(encoding="utf-8") == "old\nvalue\n"
    assert json.loads(manifest.read_text(encoding="utf-8")) == {"old": True}


def test_publication_lock_rejects_concurrent_writer(tmp_path: Path) -> None:
    output = tmp_path / "panel.csv"
    manifest = tmp_path / "panel.manifest.json"

    with publication.publication_lock(output, manifest):
        with pytest.raises(RuntimeError, match="lock already exists"):
            with publication.publication_lock(output, manifest):
                pass
