---
name: datacube-data-access
description: Find the correct DataCube data dictionary page or API from a data requirement and download datasets with tushare_plus. Use when tasks mention DataCube, 数据字典, doc_id lookup, 接口选择, 字段确认, or downloading DataCube-mounted sources such as Wind, 通联, 东财, or CYYX.
---

# Datacube Data Access

## Overview

Turn a vague data need into a concrete DataCube API choice, confirm parameters and fields from the DataCube docs, and download the result through `tushare_plus`.
Prefer DataCube self-owned datasets when they cover the requirement; switch to mounted sources like Wind only when the coverage or fields require it.

## Quick Start

1. Clarify the requirement into subject, frequency, time range, identifiers, source preference, and output fields.
2. Read `references/datacube-playbook.md` for the core workflow. If the request involves ETF, Wind-mounted tables, or high-frequency market data, also read `references/topics/etf-wind.md`. If the request involves derived index moneyflow, constituent weights, or weight drift, also read `references/topics/index-moneyflow.md`.
3. Search the docs with `python "$CODEX_HOME/skills/datacube-data-access/scripts/search_datacube_docs.py" "<keyword>"`. The script auto-selects a page renderer by platform, preferring `w3m` or `lynx` on Unix when available and the bundled Python renderer on Windows or minimal environments. Use `$playwright` when the site is easier to navigate in a real browser.
4. Extract the contract from the chosen `doc_id` page and confirm `api_name`, required params, optional params, and field names.
5. Decide the extraction pattern from both the contract and the table's observed data shape: range-first when interval filters work, split mode only when the API truly requires a per-code or per-date loop, and month-end snapshot mode when the table is effectively monthly. Also confirm the observed code format if the workflow may mix A-share, Hong Kong, or other markets.
6. Download the dataset with `scripts/download_datacube.py`, using split mode only when the live API or the data shape really requires it.
7. Verify row count, date coverage, duplicates, null-heavy columns, and output path before reporting back.

## Workflow

### 1. Clarify the request

Extract these items before picking an API:

- Data domain: quote, financial statement, holdings, industry, macro, fund, bond, or another domain
- Granularity: daily, intraday, announcement-level, security-level, fund-level, industry-level
- Time scope: exact dates, rolling window, or full history
- Entity filter: `ts_code`, list of codes, market, industry, fund, or index
- Source constraint: prefer DataCube native, require Wind, or source-agnostic
- Output contract: columns to keep, file format, and destination path

If any of these are missing and they affect API choice, ask for them or state the assumption explicitly.

### 2. Choose the source family

Prefer DataCube native data when both of these are true:

- The dataset appears to cover the requirement.
- The native interface avoids extra code mapping or multi-table joins.

Use mounted sources such as Wind, 通联, 东财, or CYYX when at least one of these is true:

- The native dataset is missing the required field or coverage.
- The user explicitly asks for that provider.
- The mounted source has the canonical version of the dataset the user expects.

Treat Wind interfaces as higher-friction by default because internal code mapping is often required.

### 3. Locate the dictionary page

If the API name is unknown:

- Run `python "$CODEX_HOME/skills/datacube-data-access/scripts/search_datacube_docs.py" "<keyword>"` to search the DataCube document index. The script uses Python for index search and auto-selects a doc-page renderer by platform.
- Use `$playwright` or the installed Playwright CLI skill when the navigation depends on live menus, JavaScript rendering, or repeated drilling through the site.

If `doc_id` is already known:

- Run `python "$CODEX_HOME/skills/datacube-data-access/scripts/search_datacube_docs.py" --doc-id <id>` to dump the page text.
- Add `--pattern "输入参数|输出参数|接口"` to jump to the contract faster.

Do not guess `api_name`, field names, or parameter semantics from a similar page. Confirm them on the actual page you intend to use.

### 4. Extract the API contract

Capture these details from the chosen page:

- `api_name`
- Required parameters and whether they accept single values, ranges, or lists
- Optional filters
- Field list and any naming quirks
- Pagination or row-limit constraints
- Provider-specific caveats such as internal industry-code mappings
- Whether the table behaves like a true daily table, a monthly snapshot table, or a mixed-frequency table in realistic samples
- Whether the live rows use one code family or mixed code families that require normalization before downstream joins

When multiple APIs look similar, explain why one is the better fit.
For ETF, high-frequency, and Wind-mounted tables, cross-check `references/topics/etf-wind.md` before finalizing the interface because the live API may differ from the doc page in filter support, parameter case, or ETF coverage. For derived index-moneyflow and weight-drift work, also cross-check `references/topics/index-moneyflow.md`.

Prefer the bundled contract extractor when the page structure is standard:

```bash
python "$CODEX_HOME/skills/datacube-data-access/scripts/extract_datacube_contract.py" 10303
```

Use `--format json` when the contract needs to be piped into another script.

### 5. Download the data

Prefer the bundled script:

```bash
python "$CODEX_HOME/skills/datacube-data-access/scripts/download_datacube.py" \
  daily \
  --param ts_code=000001.SZ \
  --fields ts_code,trade_date,open,high,low,close,vol \
  --out output/daily.csv
```

For APIs that must be queried one code or one trading date at a time:

```bash
python "$CODEX_HOME/skills/datacube-data-access/scripts/download_datacube.py" \
  fund_daily \
  --split-by trade_date \
  --split-values 20260309,20260310 \
  --param ts_code=510300.SH \
  --fields ts_code,trade_date,open,high,low,close,vol \
  --out output/fund_daily.csv
```

Important defaults:

- `auto_paging` stays enabled unless there is a reason to cap the query.
- If you only need a bounded sample and `DataCubeAPI` spends too long probing request limits, prefer `auto_paging=False` plus an explicit `limit` that matches the documented single-call cap.
- Narrow `fields` aggressively to avoid pulling unnecessary columns.
- Use `--concurrent` only for large pulls where extra requests are worth the complexity.
- Ensure `DATACUBE_TOKEN` exists in the environment, or pass `--token` explicitly.
- Prefer interval-first plus timeout/retry before defaulting to fine-grained day-by-day loops when a mounted interface is merely unstable rather than structurally missing range support.
- For monthly snapshot tables, validate the distinct dates and code coverage before defaulting to a daily pull pattern.
- For mixed-market constituent workflows, validate the observed code format early and build local filters from runtime samples instead of assumed code padding rules.

### 6. Validate and report

Before finishing:

- Check row count and whether it matches the intended filters.
- Confirm the min and max dates in the result.
- Check duplicates on the expected key columns.
- Note null-heavy columns or provider-specific oddities.
- Call out any doc/runtime mismatch, such as a documented filter not working, case-sensitive parameter names, or ETF codes returning zero rows on an ostensibly supported table.
- Call out data-shape mismatches, such as a nominally daily table that is only practically useful on month-end snapshots for the target universe.
- Distinguish structural interface gaps from transient transport errors. If the real problem is repeated `503` or `IncompleteRead(...)`, say that the table is flaky rather than claiming the filter is unsupported.
- If the table is missing a filter that would materially improve correctness or efficiency, say so explicitly, continue with the best currently available parameters when feasible, and suggest the missing filter to the user so they can ask maintainers to add it.
- Report the chosen source, API name, key parameters, output file path, and remaining caveats.

## Scripts

- `scripts/search_datacube_docs.py`: cross-platform search and plain-text dump for DataCube doc pages, auto-switching between `w3m`, `lynx`, and a bundled Python renderer
- `scripts/search_datacube_docs.sh`: thin Unix shell wrapper around `scripts/search_datacube_docs.py`
- `scripts/extract_datacube_contract.py`: fetch a specific `doc_id` page and extract `api_name`, parameter tables, output fields, and sample code
- `scripts/download_datacube.py`: call `tushare_plus.DataCubeAPI.get_data()` from the command line and save the result

## References

- `references/datacube-playbook.md`: source-selection rules, document browsing patterns, and `tushare_plus` notes
- `references/topics/etf-wind.md`: observed ETF and Wind runtime caveats, interface selection notes, and high-frequency ETF coverage
- `references/topics/index-moneyflow.md`: derived index-moneyflow, constituent-weight, and monthly weight-drift notes

## Guardrails

- Prefer confirming doc pages over inferring from memory.
- Prefer DataCube native data when it avoids unnecessary joins or code mapping.
- Call out when Wind or other mounted sources may require extra mapping logic after download.
- Do not assume the documented parameter names, case, or ETF coverage are accurate until you verify them in runtime on a realistic sample.
- Do not assume all `con_code` or ETF/index identifiers belong to the same market or use the same code-padding rule until you inspect real rows.
- When a missing filter is the real blocker, raise it early instead of silently accepting an expensive or incomplete pull.
- Keep outputs reproducible by stating the exact API, parameters, and file path used.
