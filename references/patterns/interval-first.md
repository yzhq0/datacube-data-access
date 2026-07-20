# Interval-First Pattern

Read this file when choosing between range queries and split-by-code or split-by-date loops.

## Default rule

Prefer interval-first when the live API supports workable range parameters.

Use split mode only when at least one of these is true:

- the API truly requires one code or one date at a time
- the table lacks the filter needed for a correct interval pull
- a bounded retry strategy still fails on realistic windows

## Practical guidance

- retry flakiness before assuming the table requires a loop
- if the table gained `start_date/end_date` support, drop the older per-day workaround
- keep the interval bounded and filter locally when that is materially simpler than many fine-grained calls
- use `range pull -> key audit -> anomalous natural-partition re-fetch`: first pull the widest reliable range, compare observed keys with the independent expected-key set, and re-fetch only affected dates, entities, or months
- after every repair, rebuild the combined result and repeat the full key audit; never infer completeness from the repaired partition alone

## Entity-interval panels

When an external membership or universe table defines the required panel:

1. derive each entity's inclusive minimum and maximum required dates
2. query one workable interval per entity
3. filter the returned rows to the exact expected `(date, entity)` keys
4. audit missing, extra, and duplicate keys after the filter

Rows outside active membership are expected interval over-fetch, not automatically bad source data. They must not leak into the final panel.

## Interfaces re-validated for interval-first use

- `china_etf_money_flow`
- `ashare_moneyflow`
- `hk_shareeodprices`
- `cb_index_eodprices`
- `hk_index_eodprices`

Use these as reminders to re-check old assumptions, not as license to skip runtime validation.
