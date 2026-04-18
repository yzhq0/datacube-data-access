---
name: datacube-data-access-maintainer
description: Maintain the datacube-data-access skill by reviewing local runtime notes, promoting durable findings into shared references, cleaning repo noise, and preparing small branch-scoped PRs. Use when tasks mention datacube skill maintenance, evolution, 经验整理, reference promotion, cleanup, or GitHub submission for the Datacube skill.
---

# Datacube Data Access Maintainer

## Overview

This is the maintainer-only companion skill for `datacube-data-access`.
Use it to review private runtime notes, decide what is durable enough for the shared repo, update the versioned references, clean repository noise, and prepare small PR-scoped changes.

Do not use this skill for ordinary data pulls. The user-facing skill stays pure-use and should not absorb git or maintenance workflow.

## Quick Start

1. Read private runtime notes from `~/.codex/state/datacube-data-access/runtime-notes/`.
2. Keep tentative or task-local observations in private state. Promote only durable findings that change source choice, API choice, parameter shape, extraction pattern, or risk judgment.
3. Update the narrowest shared file in `$CODEX_HOME/skills/datacube-data-access/references/`:
   - `$CODEX_HOME/skills/datacube-data-access/references/core/*.md` for stable workflow rules
   - `$CODEX_HOME/skills/datacube-data-access/references/domains/*.md` for domain-specific guidance
   - `$CODEX_HOME/skills/datacube-data-access/references/providers/*.md` for provider-specific runtime quirks
   - `$CODEX_HOME/skills/datacube-data-access/references/patterns/*.md` for reusable extraction or modeling patterns
4. Use `$CODEX_HOME/skills/datacube-data-access/scripts/capture_runtime_note.py` to record new observations into private state without touching the repo.
5. Keep repo hygiene tight: clean caches, update tests, and prefer branch-scoped small PRs.

## Workflow

### 1. Review local notes

Look in `~/.codex/state/datacube-data-access/runtime-notes/`.
Each note should include:

- date
- task and topic
- API name
- `doc_id` or page source
- key params
- observed behavior
- evidence
- decision impact
- `tentative` or `durable`

If the evidence is weak, contradictory, or specific to one transient run, keep the note private.

### 2. Apply promotion rules

Promote a finding into the shared repo only when all of these are true:

- it has concrete evidence
- it is likely to matter across tasks
- it changes source selection, API choice, parameter shape, extraction pattern, or risk judgment
- it is stable enough that other users benefit from seeing it

Examples that usually belong in the shared repo after confirmation:

- Wind should be preferred over native for a recurring data class
- 通联 availability risk changes long-term source selection
- a provider-specific code format default is stable enough to stop re-discovery
- repeated Wind field-annotation gaps mean the skill should tell users to request the original WIND dictionary
- repeated missing range filters on a time-series interface mean the skill should warn about efficiency and recommend backend parameter fixes

Do not promote:

- notes with no evidence
- task-specific dead ends
- transient failures that were not separated from transport flakiness
- personal scratch work or user-private context

### 3. Pick the right destination

- `$CODEX_HOME/skills/datacube-data-access/references/core/*.md`: stable, general rules
- `$CODEX_HOME/skills/datacube-data-access/references/domains/*.md`: ETF, index-moneyflow, or other domain logic
- `$CODEX_HOME/skills/datacube-data-access/references/providers/*.md`: Wind or other provider quirks
- `$CODEX_HOME/skills/datacube-data-access/references/patterns/*.md`: interval-first, monthly snapshots, mixed-market normalization, or anchor-and-drift style techniques

Prefer editing one narrow file over creating a new catch-all document.
Current-task warnings about inefficient parameter design or missing field semantics belong in the user-facing skill and provider references, because they affect ordinary execution.
Use this maintainer skill to promote repeated cases into those shared docs after they are validated.

### 4. Record new notes privately

Use the helper script:

```bash
python "$CODEX_HOME/skills/datacube-data-access/scripts/capture_runtime_note.py" \
  --task "ETF share snapshot validation" \
  --topic etf \
  --summary "mf_floatshare returned Shanghai ETFs despite Shenzhen wording" \
  --evidence "Runtime sample on 2026-03-19 returned 510300.SH rows" \
  --impact "Keep exchange wording out of the selection rule and treat docs as coverage hints only."
```

By default, notes go to `~/.codex/state/datacube-data-access/runtime-notes/`.
They are private state, not shared knowledge.

### 5. Git workflow

Only this maintainer skill should touch git workflow for the shared skill repo.

Branch prefixes:

- `feat/<topic>`
- `fix/<topic>`
- `docs/<topic>`
- `chore/<topic>`

PR rules:

- keep PRs small and topic-scoped
- cleanup changes stay separate from knowledge promotion
- do not mix script refactors with unrelated reference edits unless the change is one indivisible fix

## Guardrails

- Keep the user-facing skill free of maintenance instructions.
- Shrink the shared write surface instead of growing catch-all topic files.
- Prefer private note capture first and promotion later.
- Do not publish unstable observations just because they are recent.
