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
    assert "references/domains/industries.md" in skill_text
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
    assert "python scripts/search_datacube_docs.py" in skill_text


def test_user_skill_requires_key_level_completeness_evidence() -> None:
    skill_text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "`auto_paging=True` is an execution setting, not completeness evidence" in skill_text
    assert "range pull -> key audit -> anomalous natural-partition re-fetch" in skill_text
    assert "entity interval -> exact expected-key filter" in skill_text


def test_download_reference_separates_execution_from_dataset_completeness() -> None:
    text = (REPO_ROOT / "references" / "core" / "download-validation.md").read_text(
        encoding="utf-8"
    )

    assert "execution manifest" in text
    assert "dataset manifest" in text
    assert "expected-key" in text
    assert "group-cardinality" in text
    assert "partial" in text
    assert "--request-plan" in text
    assert "--checkpoint-dir" in text
    assert "--expected-keys" in text
    assert "--doc-id" in text
    assert "tushare_plus>=0.1.9" in text
    assert "cannot detect an entirely absent group" in text


def test_wind_reference_records_confirmed_price_semantics() -> None:
    text = (REPO_ROOT / "references" / "providers" / "wind.md").read_text(
        encoding="utf-8"
    )

    assert "aindex_csi1000weight.closevalue" in text
    assert "unadjusted closing price" in text
    assert "a_daily" in text
    assert "doc_id 10303" in text
    assert "round(close * adjfactor, 2)" in text
    assert "original WIND table data dictionary takes precedence" in text


def test_skill_docs_avoid_codex_home_shell_paths() -> None:
    user_skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    maintainer_skill = (REPO_ROOT / "maintainer-skill" / "SKILL.md").read_text(encoding="utf-8")

    assert "$CODEX_HOME/skills/datacube-data-access" not in user_skill
    assert "$CODEX_HOME/skills/datacube-data-access" not in maintainer_skill


def test_maintainer_skill_exists_and_mentions_private_notes() -> None:
    skill_text = (REPO_ROOT / "maintainer-skill" / "SKILL.md").read_text(encoding="utf-8")

    assert "name: datacube-data-access-maintainer" in skill_text
    assert "~/.codex/state/datacube-data-access/runtime-notes/" in skill_text
    assert "work from the `datacube-data-access` skill root" in skill_text
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
        "references/domains/industries.md",
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


def test_industry_reference_captures_shenwan_join_rules() -> None:
    text = (REPO_ROOT / "references" / "domains" / "industries.md").read_text(encoding="utf-8")

    assert "a_share_swindustriesclass" in text
    assert "a_share_Industriescode" in text
    assert "first 4 characters" in text
    assert "levelnum" in text
    assert "ashare_ind_class_citics" in text
    assert "citics_ind_code" in text
