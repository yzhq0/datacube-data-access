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
- If a bounded sample is enough and limit probing is slow, use `auto_paging=False` plus an explicit documented `limit`
- Narrow `fields` early so the pull stays small and inspection stays cheap
- Use `concurrent=True` only when the request volume is large enough to justify the extra complexity
- Save to an explicit output path and report that path back to the user

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
