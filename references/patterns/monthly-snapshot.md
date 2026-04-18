# Monthly Snapshot Pattern

Read this file when the table title says daily or weight, but the live workflow behaves more like month-end anchors.

## Recognition signs

- distinct dates cluster on effective month-end trading days
- non-month-end rows are sparse or irrelevant for the target universe
- the downstream workflow only needs official monthly anchors

## Preferred pattern

- query month-end dates only
- reuse stored month-end snapshots across windows
- fetch the previous month-end anchor once when it is missing
- keep per-index fallback only for unresolved unknown codes

## Important caveats

- effective month-end often means the last trading day, not the last calendar day
- do not default to daily pulls just because the table contains a `trade_date` field
- emptiness in `index_weight_close` does not imply emptiness in `index_weight`

This pattern is especially important for `index_weight` style workflows.
