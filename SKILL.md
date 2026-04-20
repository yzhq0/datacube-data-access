---
name: datacube-data-access
description: Find the correct DataCube data dictionary page or API from a data requirement and download datasets with tushare_plus. Use when tasks mention DataCube, 数据字典, doc_id lookup, 接口选择, 字段确认, or downloading DataCube-mounted sources such as Wind, 通联, 东财, or CYYX.
---

# Datacube Data Access

## Overview

Turn a vague data need into a concrete DataCube API choice, confirm the live contract from the DataCube docs, and download the result through `tushare_plus`.
This skill is the pure-use entrypoint. It only covers API selection, contract validation, extraction pattern choice, download, and result validation.
When running bundled commands, prefer executing them from the `datacube-data-access` skill root and use repo-relative paths. This keeps examples portable across Unix shells, PowerShell, and `cmd.exe`.

## Quick Start

1. Clarify the requirement into subject, frequency, time range, identifiers, source preference, and output fields.
2. Start with `references/core/source-selection.md` and `references/core/doc-lookup.md`.
3. Load additional references only when the task needs them:
   - `references/core/contract-extraction.md`: before locking the API or field contract
   - `references/core/download-validation.md`: before download or final reporting
   - `references/domains/etf.md`: ETF, ETF high-frequency, or ETF benchmark workflows
   - `references/domains/industries.md`: industry classification, Shenwan industry mapping, or industry-code joins
   - `references/domains/index-moneyflow.md`: derived index moneyflow, constituent weights, or weight drift
   - `references/providers/wind.md`: Wind-mounted tables or doc/runtime mismatch on mounted data
   - `references/patterns/interval-first.md`: choosing between range-first and split loops
   - `references/patterns/monthly-snapshot.md`: the table behaves like monthly snapshots
   - `references/patterns/mixed-market-normalization.md`: the workflow mixes A-share, Hong Kong, or other code families
   - `references/patterns/anchor-and-drift.md`: monthly-to-daily weight drift estimation
4. Search the docs with `python scripts/search_datacube_docs.py "<keyword>"`.
5. Extract the contract from the chosen `doc_id` page and confirm `api_name`, required params, optional params, field names, and paging constraints.
6. Choose the extraction pattern from the live contract and the observed data shape, then download with `scripts/download_datacube.py`.
7. Verify row count, date coverage, duplicates, null-heavy columns, and output path before reporting back.

## Workflow

### 1. Clarify the request

Extract these items before picking an API:

- Data domain: quote, financial statement, holdings, industry classification, macro, fund, bond, or another domain
- Granularity: daily, intraday, announcement-level, security-level, fund-level, industry-level
- Time scope: exact dates, rolling window, or full history
- Entity filter: `ts_code`, list of codes, market, industry, fund, or index
- Source constraint: prefer Wind, prefer DataCube native, require Wind, or source-agnostic
- Output contract: columns to keep, file format, and destination path

If any of these are missing and they affect API choice, ask for them or state the assumption explicitly.

### 2. Choose the source family

Read `references/core/source-selection.md`.

When Wind and DataCube native both cover the same data class, default to Wind unless the mounted interface is operationally unusable for the task or the user explicitly prefers native.

Prefer DataCube native data when at least one of these is true:

- Wind coverage is weaker or operationally unusable for the current task
- The native interface materially simplifies the work without sacrificing the required coverage
- The user explicitly prefers native over mounted data

Use mounted sources such as Wind, 通联, 东财, or CYYX when at least one of these is true:

- The native dataset is missing the required field or coverage.
- The user explicitly asks for that provider.
- The mounted source has the canonical version of the dataset the user expects.

Treat Wind interfaces as higher-friction in integration work, but still preferred over native for same-class long-lived datasets because coverage is usually broader and expected data quality is higher.
Do not choose 通联 as a default long-term dependency unless there is no acceptable alternative and the user explicitly accepts the availability risk.

### 2.1 Known code-format defaults

Do not rediscover code formats from scratch when the table family is already known. Start from these defaults, then validate on a realistic sample if the table is unfamiliar:

- DataCube native A-share, fund, and index tables usually use Tushare-style suffixed codes such as `000001.SZ`, `510300.SH`, and `000300.SH`
- Wind-mounted A-share quote and moneyflow tables commonly use the same suffixed style in returned rows
- Some Wind index-weight interfaces expect raw index codes without exchange suffix for input, for example `000300` rather than `000300.SH`
- Wind Hong Kong quote tables can use unpadded HK codes such as `0700.HK`, `2892.HK`, and `80700.HK`
- Some Wind commodity and futures tables use venue-style codes such as `Au9999.SGE`
- Industry-classification workflows can require normalized prefixes rather than raw full-code equality; read `references/domains/industries.md` before designing the join

### 3. Locate the dictionary page

Read `references/core/doc-lookup.md`.

If the API name is unknown:

- Run `python scripts/search_datacube_docs.py "<keyword>"` to search the DataCube document index. The script uses Python for index search and auto-selects a doc-page renderer by platform.
- Use `$playwright` or the installed Playwright CLI skill when the navigation depends on live menus, JavaScript rendering, or repeated drilling through the site.

If `doc_id` is already known:

- Run `python scripts/search_datacube_docs.py --doc-id <id>` to dump the page text.
- Add `--pattern "输入参数|输出参数|接口"` to jump to the contract faster.

Do not guess `api_name`, field names, or parameter semantics from a similar page. Confirm them on the actual page you intend to use.

### 4. Extract the API contract

Read `references/core/contract-extraction.md`.

Capture these details from the chosen page:

- `api_name`
- Required parameters and whether they accept single values, ranges, or lists
- Optional filters
- Field list and any naming quirks
- Pagination or row-limit constraints
- Provider-specific caveats such as internal industry-code mappings
- Whether the table behaves like a true daily table, a monthly snapshot table, or a mixed-frequency table in realistic samples
- Whether the live rows use one code family or mixed code families that require normalization before downstream joins

Do not guess business field semantics from incomplete comments, especially on Wind-mounted tables. If field comments are missing, ambiguous, or clearly hand-written rather than authoritative, ask for the original WIND table data dictionary instead of inventing meanings.

When multiple APIs look similar, explain why one is the better fit.
Load extra references only when they materially affect the decision:

- `references/domains/etf.md`: ETF-specific table coverage or ETF high-frequency interfaces
- `references/domains/industries.md`: industry classification tables, dictionary joins, or Shenwan code hierarchy
- `references/domains/index-moneyflow.md`: index weights, constituent coverage, or drift-based derived series
- `references/providers/wind.md`: mounted-table parameter quirks, transport flakiness, or coverage mismatch
- `references/patterns/mixed-market-normalization.md`: mixed code families or cross-market constituent joins

Prefer the bundled contract extractor when the page structure is standard:

```bash
python scripts/extract_datacube_contract.py 10303
```

Use `--format json` when the contract needs to be piped into another script.

### 5. Choose the extraction pattern

Use the live interface behavior and sampled data shape, not the doc title alone.

- Load `references/patterns/interval-first.md` when deciding between range-first and split loops.
- Load `references/patterns/monthly-snapshot.md` when the table is effectively anchor snapshots rather than true daily observations.
- Load `references/patterns/mixed-market-normalization.md` when identifiers may mix markets or code families.
- Load `references/patterns/anchor-and-drift.md` only for monthly-to-daily weight drift or similar derived workflows.

Prefer interval-first when the API supports workable ranges.
Use split mode only when the live API truly requires a per-code or per-date loop.
Treat repeated `503` or `IncompleteRead(...)` as flakiness first, not proof that the filter is unsupported.
If a time-series interface is missing start or end range filters and that forces day-by-day extraction, finish the task when feasible but call out the efficiency cost and recommend that backend add proper range parameters.

### 6. Download the data

Read `references/core/download-validation.md`.

Prefer the bundled script:

```bash
python scripts/download_datacube.py daily --param ts_code=000001.SZ --fields ts_code,trade_date,open,high,low,close,vol --out output/daily.csv
```

For APIs that must be queried one code or one trading date at a time:

```bash
python scripts/download_datacube.py fund_daily --split-by trade_date --split-values 20260309,20260310 --param ts_code=510300.SH --fields ts_code,trade_date,open,high,low,close,vol --out output/fund_daily.csv
```

Important defaults:

- `auto_paging` stays enabled unless there is a reason to cap the query.
- Keep request-limit detection enabled on first use of an interface. DataCube docs can lag the runtime contract, so page limits shown on the page are hints rather than authority.
- Use `--limit-per-request` only after the interface limit has been verified by a prior run or for bounded smoke tests. Use `--no-detect-limit` only as an advanced repeat-run option; do not skip detection before a new large pull.
- For flaky long pulls, prefer explicit `--request-timeout`, `--max-retries`, `--retry-backoff`, and `--retry-jitter` before falling back to finer split loops.
- Narrow `fields` aggressively to avoid pulling unnecessary columns.
- Use `--concurrent` only for large pulls where extra requests are worth the complexity.
- Ensure `DATACUBE_TOKEN` exists in the environment, or pass `--token` explicitly.
- Prefer interval-first plus timeout/retry before defaulting to fine-grained day-by-day loops when a mounted interface is merely unstable rather than structurally missing range support.
- For monthly snapshot tables, validate the distinct dates and code coverage before defaulting to a daily pull pattern.
- For mixed-market constituent workflows, validate the observed code format early and build local filters from runtime samples instead of assumed code padding rules.

### 7. Validate and report

Before finishing:

- Check row count and whether it matches the intended filters.
- Confirm the min and max dates in the result.
- Check duplicates on the expected key columns.
- Note null-heavy columns or provider-specific oddities.
- Call out any doc/runtime mismatch, such as a documented filter not working, case-sensitive parameter names, or ETF codes returning zero rows on an ostensibly supported table.
- Call out data-shape mismatches, such as a nominally daily table that is only practically useful on month-end snapshots for the target universe.
- Distinguish structural interface gaps from transient transport errors. If the real problem is repeated `503` or `IncompleteRead(...)`, say that the table is flaky rather than claiming the filter is unsupported.
- If the table is missing a filter that would materially improve correctness or efficiency, say so explicitly, continue with the best currently available parameters when feasible, and suggest the missing filter to the user so they can ask maintainers to add it.
- If Wind field comments are missing or ambiguous, say that the field meaning should be confirmed from the original WIND table data dictionary instead of guessing from the current interface page.
- Report the chosen source, API name, key parameters, output file path, and remaining caveats.

## Scripts

- `scripts/search_datacube_docs.py`: cross-platform search and plain-text dump for DataCube doc pages, auto-switching between `w3m`, `lynx`, and a bundled Python renderer
- `scripts/search_datacube_docs.sh`: thin Unix shell wrapper around `scripts/search_datacube_docs.py`
- `scripts/extract_datacube_contract.py`: fetch a specific `doc_id` page and extract `api_name`, parameter tables, output fields, and sample code
- `scripts/download_datacube.py`: call `tushare_plus.DataCubeAPI.get_data()` from the command line and save the result

## References

- `references/core/*.md`: general workflow, doc lookup, contract extraction, and download validation
- `references/domains/*.md`: domain-specific tables and derived-series guidance
- `references/providers/*.md`: provider-specific runtime quirks
- `references/patterns/*.md`: reusable extraction and modeling patterns

## Guardrails

- Prefer confirming doc pages over inferring from memory.
- Prefer Wind over DataCube native when both cover the same data class and long-lived quality or completeness matters.
- Use DataCube native when it materially simplifies the task without losing required coverage, or when Wind is operationally unsuitable.
- Treat 通联 as a risky long-term dependency unless the user explicitly accepts that tradeoff.
- Call out when Wind or other mounted sources may require extra mapping logic after download.
- Load the narrowest reference set that can decide the current step.
- Do not assume the documented parameter names, case, or ETF coverage are accurate until you verify them in runtime on a realistic sample.
- Do not assume all `con_code` or ETF/index identifiers belong to the same market or use the same code-padding rule until you inspect real rows, but start from the known source-specific defaults in this skill before re-exploring.
- Do not guess Wind business field semantics from sparse comments; request the original WIND dictionary when needed.
- When a missing filter is the real blocker, raise it early instead of silently accepting an expensive or incomplete pull.
- Keep outputs reproducible by stating the exact API, parameters, and file path used.
