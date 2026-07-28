# Download And Validation

Read this file before a verified job and again before reporting that job.

## Entry points

- Use `pull` for bounded, explicitly unverified exploration.
- Use `check` followed by `run` for a publishable dataset.
- Read `references/core/job-spec.md` for the verified JSON contract.
- Authenticate only through `DATACUBE_TOKEN`.

## Download habits

- Keep verified-job `auto_paging=true` unless the contract is intentionally one-page
- Treat automatic paging as an execution convenience, never as independent proof that all intended records were returned
- For production auto-paging jobs, derive an explicit `max_pages` from expected rows and page size; an abnormal service can otherwise emit indefinitely many distinct non-terminal pages, and `tushare_plus>=0.1.9` strict mode fails closed on the bound
- Keep request-limit detection enabled on first use of an interface; documented limits are often useful hints but can lag runtime behavior
- Set `limit_per_request` only after a prior run has verified the safe page size
- Disable limit detection only on repeat runs against a verified interface
- For flaky long pulls, tune the job retry settings before splitting more finely
- Narrow `fields` early so the pull stays small and inspection stays cheap
- Save to an explicit output path and report that path back to the user
- Use materialized partitions, verified checkpoints, and resume for large pulls. A partial execution may retain checkpoints but must not publish a merged output as complete.

The plan executor owns partition fingerprints, verified resume, atomic checkpoints, and the execution manifest. The skill owns expected-key filtering, dataset validation, and final publication. It never copies token values into job data, request params, or manifests.

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
