from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/search_datacube_docs.py",
        "scripts/extract_datacube_contract.py",
        "scripts/download_datacube.py",
        "scripts/capture_runtime_note.py",
    ],
)
def test_cli_help_smoke(relative_path: str) -> None:
    script_path = REPO_ROOT / relative_path
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "usage:" in result.stdout.lower()
