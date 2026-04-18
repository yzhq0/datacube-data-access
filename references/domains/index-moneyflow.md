# Index Moneyflow

Read this file when the task involves any of these:

- derived index moneyflow
- constituent moneyflow aggregated to index level
- index constituent weights
- monthly-to-daily weight drift estimation
- validation against the next official snapshot

Load `references/patterns/anchor-and-drift.md` when the workflow needs monthly anchor drift.

## Mental model

- In this workflow, index moneyflow is usually a derived series rather than a vendor-supplied field
- Treat the result as a model-based proxy, not as an official exchange or provider series

## Weight-source priority

Use official weights first. Recommended priority:

1. `swindex_close_weight` for Shenwan indices
2. `index_weight_close` for exchange or public indices with same-day coverage
3. `index_weight` as the monthly anchor table

Important caveats:

- `index_weight_close` absence does not imply `index_weight` absence
- `index_weight` behaves like a monthly snapshot table for this workflow
- the previous official anchor snapshot is mandatory when the downstream calculation drifts weights into the next month

## Constituent coverage

- `index_weight` is not guaranteed to be A-share only
- live monthly snapshots may contain Hong Kong constituents
- do not assume every `con_code` can join directly to A-share quote or moneyflow tables

Practical mapping:

- A-share constituent quotes: Wind `a_daily`
- Hong Kong constituent quotes: Wind `hk_shareeodprices`
- A-share constituent moneyflow: Wind `ashare_moneyflow`

## Diagnostics to keep

When you build a derived index-moneyflow series, keep:

- `weight_mode`
- `anchor_weight_date`
- `anchor_weight_source`
- `days_since_anchor`
- `constituent_count`
- `weighted_constituent_count`
- `moneyflow_weight_coverage_ratio`

Do not expose only the final aggregated value.

## What to report back

- the exact weight-source priority used
- whether weights were official daily or monthly drifted
- which quote tables were used for drift estimation
- whether the index universe included multiple markets
- the main caveats, especially cross-market coverage gaps
