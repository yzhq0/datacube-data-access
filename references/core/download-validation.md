# Download And Validation

Read this file before the first pull and again before final reporting.

## Main entry point

The preferred CLI is:

```bash
python scripts/download_datacube.py daily --param ts_code=000001.SZ --out output/daily.csv
```

Important runtime note:

- `DataCubeAPI` reads `DATACUBE_TOKEN` from the environment when no token is passed explicitly
- if `DATACUBE_TOKEN` is missing, client initialization fails

## Download habits

- Keep `auto_paging=True` unless you have a reason to cap the query
- Treat automatic paging as an execution convenience, never as independent proof that all intended records were returned
- For production auto-paging plans, derive an explicit `--max-pages` from expected rows and page size; an abnormal service can otherwise emit indefinitely many distinct non-terminal pages, and `tushare_plus>=0.1.9` strict mode fails closed on the bound
- Keep request-limit detection enabled on first use of an interface; documented limits are often useful hints but can lag runtime behavior
- Use `--limit-per-request` only after a prior run has verified the safe page size, or for small bounded smoke tests where the chosen page size cannot over-fetch
- Use `--no-detect-limit` only for repeat runs against a verified interface; if it is used without `--limit-per-request`, the client fallback page size is applied
- For flaky long pulls, tune `--request-timeout`, `--max-retries`, `--retry-backoff`, `--retry-jitter`, and `--max-retry-delay` before assuming the interface must be split more finely
- Narrow `fields` early so the pull stays small and inspection stays cheap
- Use `concurrent=True` only when the request volume is large enough to justify the extra complexity
- Save to an explicit output path and report that path back to the user
- For custom Python pipelines, `DataCubeAPI.get_data(..., return_type="pandas|polars|arrow|raw")` can avoid unnecessary downstream conversion; the CLI still writes tabular outputs through pandas

For large split pulls, use a materialized request plan with verified checkpoints and resume. A partial execution may retain valid partition checkpoints for a later run, but it must not publish a merged output as complete.

Plan execution requires `tushare_plus>=0.1.9`. For example, given a JSONL request plan in which every line is a complete parameter mapping:

```json
{"code":"000001.SZ","start_date":"20260101","end_date":"20260131"}
{"code":"000002.SZ","start_date":"20260101","end_date":"20260131"}
```

run:

```bash
python scripts/download_datacube.py a_daily --request-plan requests.jsonl --checkpoint-dir output/a_daily.parts --partition-workers 4 --execution-manifest output/a_daily.execution.json --fields code,trade_date,close,adjclose,adjfactor --out output/a_daily.parquet --key-fields trade_date,code --expected-keys expected_keys.parquet --filter-to-expected-keys --group-fields trade_date --dataset-manifest output/a_daily.dataset.json --doc-id 10303
```

The plan executor owns partition fingerprints, verified resume, atomic checkpoints, and the execution manifest. The skill CLI owns exact expected-key filtering, dataset validation, and final publication. It never copies token values into request params or either manifest.

## Validation checklist

Before finishing:

- compare observed keys with an independent expected-key set when one exists
- report missing, extra, and duplicate expected-key counts
- check group-cardinality rules such as constituents per date or observations per entity
- confirm row count, but do not use it as the only completeness test
- confirm min and max dates
- note null-heavy columns
- call out doc/runtime mismatches that affected the pull
- distinguish structural gaps from transient transport errors

Use the natural partition containing an anomaly as the repair unit. Re-fetch only the affected date, entity, month, or other stable partition, replace it deterministically, and then repeat the complete key audit.

## Two manifests, two claims

The `tushare_plus` execution manifest describes the request plan and its execution: request fingerprints, partition status, resume decisions, row counts, paging termination, failures, and artifact hashes. `complete=true` means every declared request completed and its checkpoint passed transport-level integrity checks.

The skill-level dataset manifest describes the intended dataset contract: dictionary evidence, target universe and dates, expected keys, missing/extra/duplicate keys, group-cardinality checks, business-field semantics, and the final artifact hash. It alone decides whether the merged dataset is publishable for the task.

An execution manifest cannot prove that a request plan covered the intended dataset. Never promote partial execution to a complete dataset manifest.

Without an expected-key table, fixed group cardinality can validate only groups that appear in the observed output; it cannot detect an entirely absent group. Use exact expected keys when missing whole dates, entities, or months must fail the dataset contract.

Likewise, a completed request plan is not automatically evidence that an uncapped source was exhausted. When exact expected keys are absent, require every pagination report to establish `source_exhausted` or the library's explicit `exhaustion_inferred` state (for example, an empty-page inference after sequential offset progress) before publishing.

If the pull is flaky rather than structurally impossible, say so explicitly.

## Pattern routing

Load pattern references only when needed:

- `references/patterns/interval-first.md`: range vs split loops
- `references/patterns/monthly-snapshot.md`: anchor-style or month-end tables
- `references/patterns/mixed-market-normalization.md`: multiple code families
- `references/patterns/anchor-and-drift.md`: monthly-to-daily drift estimation
