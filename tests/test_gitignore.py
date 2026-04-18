from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_covers_generated_noise() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".local/",
        "output/",
    ):
        assert pattern in gitignore
