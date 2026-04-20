from __future__ import annotations

import os
import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "capture_runtime_note.py"


def test_capture_runtime_note_writes_markdown(tmp_path) -> None:
    note_dir = tmp_path / "runtime-notes"
    env = os.environ.copy()
    env["DATACUBE_RUNTIME_NOTE_DIR"] = str(note_dir)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--task",
            "ETF coverage check",
            "--topic",
            "etf",
            "--summary",
            "mf_floatshare returned Shanghai ETF rows",
            "--evidence",
            "2026-03-19 sample returned 510300.SH",
            "--impact",
            "Treat exchange wording as a hint rather than a hard filter.",
            "--api-name",
            "mf_floatshare",
            "--doc-id",
            "12345",
            "--param",
            "trade_date=20260319",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    note_path = Path(result.stdout.strip())
    assert note_path.parent == note_dir
    assert note_path.exists()

    content = note_path.read_text(encoding="utf-8")
    assert "# Runtime Note: ETF coverage check" in content
    assert "- Topic: `etf`" in content
    assert "- Status: `tentative`" in content
    assert "- API Name: `mf_floatshare`" in content
    assert "- `doc_id`: `12345`" in content
    assert "- `trade_date` = `20260319`" in content
    assert "mf_floatshare returned Shanghai ETF rows" in content
    assert "Treat exchange wording as a hint rather than a hard filter." in content


def test_capture_runtime_note_does_not_overwrite_same_second_topic(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location("capture_runtime_note", SCRIPT_PATH)
    assert spec and spec.loader
    capture_runtime_note = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture_runtime_note)

    note_dir = tmp_path / "runtime-notes"
    timestamp = capture_runtime_note.datetime(2026, 4, 20, 10, 25, 53)
    first = capture_runtime_note.next_note_path(note_dir, timestamp, "a-share-risk-model")
    note_dir.mkdir(parents=True)
    first.write_text("first", encoding="utf-8")

    second = capture_runtime_note.next_note_path(note_dir, timestamp, "a-share-risk-model")
    second.write_text("second", encoding="utf-8")
    third = capture_runtime_note.next_note_path(note_dir, timestamp, "a-share-risk-model")

    assert first.name == "20260420-102553-a-share-risk-model.md"
    assert second.name == "20260420-102553-a-share-risk-model-2.md"
    assert third.name == "20260420-102553-a-share-risk-model-3.md"
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"
