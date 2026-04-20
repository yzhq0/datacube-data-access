# Wind Runtime Notes

Read this file when the task uses Wind-mounted tables or a mounted-table doc/runtime mismatch could change the API choice.

## General caveats

- Wind tables can differ from the doc page in parameter names or parameter case
- Wind interface pages and field comments are often hand-maintained and may be incomplete or inconsistent
- mounted tables can fail transiently even when the interface choice is correct
- metadata coverage does not guarantee quote coverage
- old assumptions about missing range filters can go stale as mounted tables evolve

## Field semantics discipline

- do not guess business meaning from a sparse Chinese comment, a shortened alias, or an obviously incomplete annotation
- if the task depends on the precise business meaning of a field and the current page is weak, ask for the original WIND table data dictionary
- treat the interface page as a starting point, not the final authority, when field annotations are missing

## Parameter design discipline

- many Wind interfaces are hand-designed, so parameter shape is not always ideal
- if a time-series table lacks `start_date/end_date` style filters and this forces day-by-day extraction, finish the task when feasible but flag the efficiency problem explicitly
- recommend backend add proper range parameters rather than normalizing an inefficient loop as the permanent pattern

## Verified patterns

- `windexchange` used uppercase params such as `CRNCY_CODE`, `TRADE_DT`, `START_DT`, and `END_DT` in runtime
- transient `HTTP Error 503` and `IncompleteRead(...)` occurred on otherwise valid tables
- some `.MI`, `.SPI`, and `.CI` codes existed in `aindex_desc` but returned zero rows in `aindex_daily`

## A-share risk-model table notes

Use these notes when building A-share universes, factor models, or historical panels from Wind-mounted tables:

- prefer `a_desc` over a current listed-only master table for historical backtests; normalize `code` to the security id, keep `listdate` and `delistdate`, and include delisted names before applying an as-of listed filter
- do not treat `list_status='L'` from a current snapshot as a historical universe definition; it can introduce survivorship bias when the downstream task needs dates before today
- `a_share_eod_derivativeIndicator` is the Wind valuation/derivative source for fields such as market value, float market value, PB, PE TTM, and free-float turnover; use it instead of native `daily_basic` when the project standard is Wind
- for `a_daily`, prefer `tradestatuscode` over the Chinese `tradestatus` label when deciding tradeability; observed active labels include `交易`, `XD`, `XR`, and `DR`, while `tradestatuscode = 0` indicates suspension
- do not interpret all null `resump_date` values in `a_suspension` as open-ended suspensions without cross-checking quotes; historical one-day suspensions can have null `resump_date`, so validate against `a_daily.tradestatuscode`
- for `ashare_fin_indicators`, keep point-in-time financial snapshots anchored on `ann_dt <= trade_date` and then the latest `report_period`; if field comments are missing, confirm factor semantics from the original WIND dictionary before using the columns
- before replacing a third-party consensus source with a Wind consensus table, sample the latest available date and coverage first; do not assume the Wind-mounted table is fresher or operationally equivalent

## Decision discipline

- retry transient transport failures before changing the extraction pattern
- do not claim a filter is unsupported until you have separated interface gaps from flakiness
- mark unresolved coverage gaps honestly instead of forcing a route through the wrong table
- re-test old split-by-day workarounds because range support on mounted tables can improve over time
- if the same field-annotation gap or parameter-design issue recurs across tasks, capture it for maintainer promotion into shared references
