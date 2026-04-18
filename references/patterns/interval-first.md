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

## Interfaces re-validated for interval-first use

- `china_etf_money_flow`
- `ashare_moneyflow`
- `hk_shareeodprices`
- `cb_index_eodprices`
- `hk_index_eodprices`

Use these as reminders to re-check old assumptions, not as license to skip runtime validation.
