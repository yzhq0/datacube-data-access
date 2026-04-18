# Contract Extraction

Read this file before you lock an API or field list.

## Capture this contract

For the chosen page, confirm:

- `api_name`
- required parameters
- optional filters
- field list
- row-limit or paging constraints
- provider-specific caveats
- whether the table behaves like daily, monthly snapshot, or mixed-frequency data in realistic samples

When code families may mix, also confirm the observed identifier format before downstream joins.
If the table is Wind-mounted and field comments are sparse, missing, or obviously hand-authored, do not infer business semantics from those comments alone. Ask for the original WIND table data dictionary when the field meaning matters.

## Preferred extractor

Use the bundled contract extractor when the page structure is standard:

```bash
python scripts/extract_datacube_contract.py 10303
python scripts/extract_datacube_contract.py 10303 --format json
```

## Runtime mismatch discipline

Do not stop at the doc page when accuracy matters. On a realistic sample, verify:

- parameter names and parameter case
- whether documented filters are actually accepted
- whether ETF, index, or Wind-style codes return rows
- whether row limits or paging behavior match the doc
- whether field comments are complete enough to support the required business interpretation

Record the mismatch in the final answer if it changes the API choice, parameter shape, or extraction pattern.
If the interface lacks time-range filters that a time-series table should have, complete the task when feasible, but explicitly recommend backend add proper range parameters.

## When two APIs look similar

- Choose the one that best matches the user's required scope and fields
- Prefer the interface with simpler filters and less post-processing
- Load a domain, provider, or pattern reference only if it changes the choice materially
