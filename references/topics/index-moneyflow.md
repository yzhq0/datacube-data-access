# Index moneyflow and weight-drift notes

Read this file when the task involves any of these:

- derived index moneyflow
- constituent moneyflow aggregated to index level
- index constituent weights
- monthly-to-daily weight drift estimation
- validation of estimated daily weights against the next official snapshot

These notes are empirical and may drift over time. Re-test on a realistic sample when the interface choice or the derived formula matters.

## Recommended mental model

- In this workflow, "index moneyflow" is not a direct vendor-supplied index field.
- It is a derived series built from constituent-level moneyflow and constituent weights.
- Treat the result as a model-based proxy, not as an official exchange or provider index-moneyflow series.

## Weight-source priority

Use official weights first and only estimate when the official daily source is unavailable.

Recommended priority:

1. `swindex_close_weight` for Shenwan indices
2. `index_weight_close` for exchange/public indices with same-day weight coverage
3. `index_weight` as the monthly anchor table

Important caveats:

- `index_weight_close` absence does not imply `index_weight` absence.
- `index_weight` behaves like a monthly snapshot table for this workflow. Query it on effective month-end trading dates, not by naive daily loops.
- If the downstream calculation needs monthly weights drifted into the next month, the previous official anchor snapshot is mandatory.

## Constituent-market coverage

- `index_weight` is not guaranteed to be A-share only.
- Live monthly snapshots may contain Hong Kong constituents, for example on cross-market CSI/CNI indices.
- Do not assume every `con_code` can be joined directly to A-share quote or A-share moneyflow tables.

Practical implication:

- A-share constituent quote drift: use Wind `a_daily`
- Hong Kong constituent quote drift: use Wind `hk_shareeodprices`
- A-share constituent moneyflow: use Wind `ashare_moneyflow`
- Hong Kong constituent moneyflow may still be missing from the active workflow, so cross-market indices can have valid drifted weights but incomplete moneyflow coverage

## Reliable extraction patterns observed in this project

- `ashare_moneyflow` supported `start_date/end_date` interval pulls for market-window extraction. Per-code loops were unnecessary for the validated use case.
- `a_daily` worked well as a market-window quote source for A-share constituents when followed by local code filtering.
- `hk_shareeodprices` was most reliable as a date-only full-market pull plus local code filtering.
- `hk_shareeodprices` uses `date`, not `trade_date`.
- Wind-mounted transport errors such as `HTTP Error 503` and `IncompleteRead(...)` were observed on valid interfaces. Retry before changing the table or pattern.

## Drifted-weight estimation

When only monthly official weights are available, a useful approximation is to drift the anchor weights forward with constituent returns.

One practical formulation:

- Let the latest official anchor date be `tau`
- Let the official anchor weight be `w_i,tau`
- Let daily constituent return be `r_i,s`
- Drift forward with:
  - `raw_w_i,t = w_i,tau * product(1 + r_i,s)`
  - `w_hat_i,t = raw_w_i,t / sum_j raw_w_j,t`

Recommended implementation details:

- Prefer adjusted prices or adjusted return fields when available.
- Use the previous trading day's drifted weight with today's moneyflow to reduce same-day leakage.
- Re-normalize weights within the live constituent universe on every estimated day.
- If a constituent is missing quote history after the anchor, exclude it from the estimated universe and record the coverage loss.

## Derived index-moneyflow formula

One workable proxy used in this project:

- `weighted_net_inflow_t = sum_i (w_hat_i,t-1 * stock_inflow_i,t)`

Where:

- `w_hat_i,t-1` is official same-day weight when available, otherwise the drifted estimate from the latest official anchor
- `stock_inflow_i,t` comes from constituent-level moneyflow such as `s_mfd_inflow`

Useful companion diagnostics:

- `weight_mode`: `official_daily`, `monthly_drift`, or similar
- `anchor_weight_date`
- `anchor_weight_source`
- `days_since_anchor`
- `constituent_count`
- `weighted_constituent_count`
- `moneyflow_weight_coverage_ratio`

Do not expose only the final aggregated index-moneyflow value. Keep the diagnostics, or later debugging becomes expensive.

## Error evaluation against the next official snapshot

If the task uses monthly-to-daily drift, validate the estimate against the next official monthly snapshot.

Recommended pattern:

1. Take the official month-end weights at `tau`
2. Drift them forward to the next official snapshot date `tau_next`
3. Compare the estimated weights with the official weights observed at `tau_next`

Useful error metrics:

- `mae_union`: mean absolute error on the union of estimated and official constituents
- `max_abs_error`
- optional top-holding overlap metrics such as top-10 overlap ratio
- optional weight coverage metrics such as estimated weight mass with quote support

Interpretation:

- Wide-market cap indices usually behave better under drift than equal-weight or optimizer-driven strategy indices.
- Cross-market indices can show good weight-drift error but poor moneyflow coverage if Hong Kong constituent moneyflow is missing.
- A low drift error does not guarantee good moneyflow quality if the constituent moneyflow coverage ratio is low.

## Common failure modes

- Missing the prior month-end anchor and then attempting to drift the whole next month anyway
- Treating `index_weight_close` emptiness as proof that no weight data exists
- Assuming all constituents are A-share and silently dropping Hong Kong rows
- Using raw close instead of adjusted close when corporate actions matter
- Joining A-share and Hong Kong quotes without normalizing code format and date columns first
- Reporting a derived index-moneyflow series without any coverage diagnostics

## What to report back to the user

When the task involves derived index moneyflow, report:

- the exact weight-source priority used
- whether weights were official daily or monthly drifted
- which quote tables were used for drift estimation
- whether the index universe included multiple markets
- whether constituent moneyflow covered only A-share or a broader universe
- the main drift-error metrics if monthly drift was involved
- remaining caveats, especially around cross-market coverage gaps
