---
name: datacube-data-access
description: Find the correct DataCube data dictionary page or API from a data requirement and download datasets with tushare_plus. Use when tasks mention DataCube, 数据字典, doc_id lookup, 接口选择, 字段确认, or downloading DataCube-mounted sources such as Wind, 通联, 东财, or CYYX.
---

# Datacube Data Access

## Purpose

Turn a data need into a confirmed DataCube contract and either an exploratory pull or a verified dataset.
Run bundled commands from this skill root and use repo-relative paths.

## Workflow

### 1. Clarify the requirement

Capture the subject, frequency, date range, entity identifiers, source preference, required fields, output format, and destination.
Ask or state an assumption only when a missing item changes the API or dataset contract.

### 2. Select the source

Read `references/core/source-selection.md`.
State the chosen source family before locking an API.

Load these references only when the subject requires them:

- `references/domains/etf.md`: ETF, ETF benchmark, or ETF high-frequency data
- `references/domains/industries.md`: industry classification or hierarchy joins
- `references/domains/index-moneyflow.md`: constituent weights or derived index moneyflow
- `references/providers/wind.md`: Wind-mounted tables or mounted-table mismatches

### 3. Find and confirm the dictionary page

Read `references/core/doc-lookup.md`.
Search by business concept when the API is unknown:

```bash
python scripts/search_datacube_docs.py "A股日行情"
```

Dump a known page with `python scripts/search_datacube_docs.py --doc-id <id>`.
Do not infer a contract from a similar page.

### 4. Extract the live contract

Read `references/core/contract-extraction.md`.
Confirm the `api_name`, parameters, fields, paging constraints, identifier format, and observed table frequency.
Use `python scripts/extract_datacube_contract.py <doc_id>` when the page follows the standard layout.

Load a pattern only when it changes execution:

- `references/patterns/interval-first.md`: interval versus partition plans
- `references/patterns/monthly-snapshot.md`: monthly anchor tables
- `references/patterns/mixed-market-normalization.md`: mixed code families
- `references/patterns/anchor-and-drift.md`: monthly-to-daily weight estimates

### 5. Execute

Use `pull` for bounded exploration:

```bash
python scripts/download_datacube.py pull daily --param ts_code=000001.SZ --fields ts_code,trade_date,close --out output/sample.csv
```

Use a verified job for publishable data. Read `references/core/job-spec.md` and `references/core/download-validation.md`, validate it without network access, then run it:

```bash
python scripts/download_datacube.py check jobs/a_daily.json
python scripts/download_datacube.py run jobs/a_daily.json
```

### 6. Validate and report

For exploratory pulls, report their bounded and unverified status.
For verified jobs, publish only when execution, source coverage, and the dataset contract all pass.
Report the source, API, `doc_id`, key parameters, output path, validation status, and remaining caveats.

## Resources

- `scripts/search_datacube_docs.py`: search or render DataCube dictionary pages
- `scripts/extract_datacube_contract.py`: extract a structured contract
- `scripts/download_datacube.py`: run `pull`, `check`, or `run`
- `references/core/*.md`: source, lookup, contract, job, and validation rules
- `references/domains/*.md`: domain-specific guidance
- `references/providers/*.md`: provider-specific evidence
- `references/patterns/*.md`: reusable extraction and modeling patterns

## Guardrails

- Confirm the actual dictionary page and a realistic runtime sample before relying on a contract.
- Do not guess business-field semantics from sparse provider comments.
- Keep secrets out of parameters, job files, logs, and manifests; use `DATACUBE_TOKEN`.
- Treat automatic paging as execution behavior, not completeness evidence.
- Distinguish structural interface gaps from transient transport failures.
- Load only the references needed for the current decision.
