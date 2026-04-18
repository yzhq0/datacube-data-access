from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_user_skill_routes_layered_references() -> None:
    skill_text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "references/core/source-selection.md" in skill_text
    assert "references/core/doc-lookup.md" in skill_text
    assert "references/core/contract-extraction.md" in skill_text
    assert "references/core/download-validation.md" in skill_text
    assert "references/domains/etf.md" in skill_text
    assert "references/domains/index-moneyflow.md" in skill_text
    assert "references/providers/wind.md" in skill_text
    assert "references/patterns/interval-first.md" in skill_text
    assert "references/patterns/monthly-snapshot.md" in skill_text
    assert "references/patterns/mixed-market-normalization.md" in skill_text


def test_user_skill_stays_pure_use() -> None:
    skill_text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8").lower()

    for forbidden in ("pull request", "branch prefix", "runtime note", "git workflow"):
        assert forbidden not in skill_text


def test_user_skill_embeds_source_and_dictionary_guidance() -> None:
    skill_text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "default to Wind" in skill_text
    assert "通联" in skill_text
    assert "original WIND table data dictionary" in skill_text
    assert "Known code-format defaults" in skill_text


def test_maintainer_skill_exists_and_mentions_private_notes() -> None:
    skill_text = (REPO_ROOT / "maintainer-skill" / "SKILL.md").read_text(encoding="utf-8")

    assert "name: datacube-data-access-maintainer" in skill_text
    assert "~/.codex/state/datacube-data-access/runtime-notes/" in skill_text
    assert "$CODEX_HOME/skills/datacube-data-access/references/" in skill_text
    assert "feat/<topic>" in skill_text
    assert "docs/<topic>" in skill_text
    assert "Current-task warnings" in skill_text


def test_reference_layout_exists() -> None:
    expected_files = [
        "references/core/source-selection.md",
        "references/core/doc-lookup.md",
        "references/core/contract-extraction.md",
        "references/core/download-validation.md",
        "references/domains/etf.md",
        "references/domains/index-moneyflow.md",
        "references/providers/wind.md",
        "references/patterns/interval-first.md",
        "references/patterns/monthly-snapshot.md",
        "references/patterns/mixed-market-normalization.md",
        "references/patterns/anchor-and-drift.md",
        "maintainer-skill/agents/openai.yaml",
    ]

    for relative_path in expected_files:
        assert (REPO_ROOT / relative_path).is_file(), relative_path
