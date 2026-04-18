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

## Decision discipline

- retry transient transport failures before changing the extraction pattern
- do not claim a filter is unsupported until you have separated interface gaps from flakiness
- mark unresolved coverage gaps honestly instead of forcing a route through the wrong table
- re-test old split-by-day workarounds because range support on mounted tables can improve over time
- if the same field-annotation gap or parameter-design issue recurs across tasks, capture it for maintainer promotion into shared references
