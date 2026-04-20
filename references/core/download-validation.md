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
- Keep request-limit detection enabled on first use of an interface; documented limits are often useful hints but can lag runtime behavior
- Use `--limit-per-request` only after a prior run has verified the safe page size, or for small bounded smoke tests where the chosen page size cannot over-fetch
- Use `--no-detect-limit` only for repeat runs against a verified interface; if it is used without `--limit-per-request`, the client fallback page size is applied
- For flaky long pulls, tune `--request-timeout`, `--max-retries`, `--retry-backoff`, `--retry-jitter`, and `--max-retry-delay` before assuming the interface must be split more finely
- Narrow `fields` early so the pull stays small and inspection stays cheap
- Use `concurrent=True` only when the request volume is large enough to justify the extra complexity
- Save to an explicit output path and report that path back to the user
- For custom Python pipelines, `DataCubeAPI.get_data(..., return_type="pandas|polars|arrow|raw")` can avoid unnecessary downstream conversion; the CLI still writes tabular outputs through pandas

## Validation checklist

Before finishing:

- confirm row count
- confirm min and max dates
- check duplicates on the expected key
- note null-heavy columns
- call out doc/runtime mismatches that affected the pull
- distinguish structural gaps from transient transport errors

If the pull is flaky rather than structurally impossible, say so explicitly.

## Pattern routing

Load pattern references only when needed:

- `references/patterns/interval-first.md`: range vs split loops
- `references/patterns/monthly-snapshot.md`: anchor-style or month-end tables
- `references/patterns/mixed-market-normalization.md`: multiple code families
- `references/patterns/anchor-and-drift.md`: monthly-to-daily drift estimation
