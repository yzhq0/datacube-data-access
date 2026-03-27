# ETF and Wind runtime notes

Read this file when the task involves any of these:

- ETF data preparation
- Wind-mounted datasets
- ETF high-frequency or microstructure data
- commodity, futures, or overseas ETF benchmarks

These notes are empirical and may drift over time. Re-test on a realistic sample when the interface choice matters.

For derived index moneyflow, constituent-weight aggregation, or monthly weight drift, also read `references/topics/index-moneyflow.md`.

## ETF daily data notes

- `mf_trackingindex`: doc examples may use `.OF`, but runtime validation accepted listed trading codes such as `510300.SH` and `159901.SZ`.
- `a_daily` was re-validated as a workable constituent-quote source for A-share ETF/index workflows.
  - The reliable pattern in this project was `start_date/end_date` range pull for the market window plus local code filtering.
  - Do not default to per-code loops for A-share constituent quotes when the downstream task only needs a bounded date window.
- Some useful ETF tables gained better date filters over time:
  - `mf_closedfund_eodprice`
  - `mf_floatshare`
  - `mf_iopvnav`
- `mf_nav` is still a special case:
  - use `start_end_date` and `stop_end_date`, not `start_date` and `end_date`
  - the interface can stall on larger windows, so the preferred pattern is interval-first with explicit timeout/retry and only split the range on retry
- When a table is missing the filters you need, raise it early to the user. In this environment, maintainers may add the missing filter, which can change the recommended extraction pattern.
- For ETF share data, same-day values may be incomplete if the pull is too early. Prefer a "latest complete trading day" convention for production snapshots.
- `china_etf_money_flow` was re-validated on `2026-03-19` to accept `start_date/end_date`.
  - The preferred pattern is now interval query plus local ETF-code filtering.
  - Do not keep using an old one-trading-day loop just because that workaround used to be necessary.
- `mf_floatshare` docs implied Shenzhen-only coverage, but runtime validation returned Shanghai ETFs too. Do not trust the exchange wording without sampling.

## Trading-calendar notes

- Prefer explicit calendar tables over inferring trading dates from quote tables when future dates matter.
- Current validated priority for this ETF/Wind workflow:
  - `a_calendar` first
  - `trade_cal` second
  - quote-table fallback only as a last resort
- `trade_cal` was validated to return future open dates. This matters when the task involves scheduling, future rebalance calendars, or pre-building date scaffolding.

## Wind-mounted table caveats

- Wind tables can differ from the doc in parameter names or parameter case.
- Verified example: `windexchange` used uppercase params such as `CRNCY_CODE`, `TRADE_DT`, `START_DT`, and `END_DT` in runtime.
- Wind-mounted tables can also fail transiently even when the interface choice is correct.
  - In this project, transient `HTTP Error 503: Service Unavailable` and `IncompleteRead(...)` were observed on otherwise usable interfaces.
  - Retry before changing the extraction pattern or declaring the table unusable.
- Do not assume metadata coverage implies quote coverage.
  - Verified example: some `.MI`, `.SPI`, and `.CI` codes existed in `aindex_desc` but returned zero rows in `aindex_daily`.
- If a code family only has metadata but no quote coverage in the obvious table, prefer marking it unresolved over forcing an incorrect route.
- Some mounted tables have gained range support over time. Re-test old assumptions instead of blindly reusing a per-day workaround.

## Commodity and futures ETF benchmark notes

- `commodity_index` looked relevant but returned `接口不存在` in runtime. Do not rely on it without re-validation.
- Verified usable replacements were:
  - `wind_gold_eod`
  - `wd_future_eod`
  - `wind_future_des`
- `wd_future_eod` later validated `start_date/end_date` interval filtering for market-window pulls, but still did not reliably accept the ETF benchmark code itself as the `code` filter. The workable pattern remained "fetch the date window and filter locally on mapped `s_info_windcode`."
- `wind_future_des` worked well as a metadata lookup table for futures-style ETF benchmarks.
- `wind_gold_eod` was re-validated on `2026-03-15` and accepted `code` for tested benchmarks:
  - `Au9999.SGE`
  - `SHAU.SGE`
  The tested combinations `code + trade_dt` and `code + start_date/end_date` both returned 1 row. Keep a note of this because earlier runtime behavior was inconsistent.

## Index-weight and constituent-moneyflow notes

- `index_weight_close` is the preferred same-day weight source for exchange indices.
  - Runtime note: the `code` input should be passed without exchange suffix, for example `000300`, not `000300.SH`.
- `swindex_close_weight` remains the preferred same-day weight source for Shenwan indices.
- `index_weight` should be treated as a monthly snapshot table in ETF/index-moneyflow workflows.
  - In this project, month-end full-market pulls worked for the relevant public-index use case.
  - "Month-end" means the effective month-end trading day, not necessarily the literal last calendar day.
  - Non-month-end rows were observed only in a small side set and were not relevant to the active ETF index pool.
  - Do not default to a full daily pull pattern just because the table contains a `trade_date` field.
- Absence of `index_weight_close` does not imply absence of `index_weight`.
  - Verified examples in this project included `000001.SH`, `000010.SH`, and `000300.SH`: tested dates returned 0 rows in `index_weight_close` but nonzero rows in `index_weight`.
  - Do not prune monthly fallback candidates just because the same code was empty in `index_weight_close`.
- `index_weight` constituents are not guaranteed to be A-share only.
  - Hong Kong constituents were observed in live monthly snapshots, for example on `930931.CSI`.
  - Do not normalize every `con_code` as an A-share code or assume downstream A-share-only money-flow coverage.
- The best practical pattern for `index_weight` in this workflow was:
  - fetch month-end dates only
  - reuse already stored month-end snapshots across windows
  - if the previous month-end anchor is missing, fetch it once
  - keep per-index fallback only for unresolved unknown codes
- `ashare_moneyflow` was re-validated to support `start_date/end_date` interval pulls for a full market window without per-code parameters. This made an older per-date or per-code loop unnecessary for the current project.
- If the downstream logic depends on drifting monthly weights forward, confirm that the previous official anchor date is included. Missing the prior month-end snapshot can invalidate the whole next month of derived index-moneyflow output.

## Constituent quote notes for weight drift

- For A-share constituents in ETF/index workflows, use Wind `a_daily`.
- For Hong Kong constituents in ETF/index workflows, use Wind `hk_shareeodprices`.
- Do not substitute `trad_sk_hkdaily` in this workflow. The current project explicitly validated and standardized on `hk_shareeodprices`.
- `hk_shareeodprices` was re-validated on `2026-03-19` to accept `start_date/end_date`.
  - The preferred pattern is now bounded interval pull plus local code filtering.
  - Direct per-code pulls were inconsistent on tested samples, so do not assume per-code is the safer option.
- Normalize Hong Kong codes early.
  - Runtime samples used Wind-style formats such as `0700.HK`, `2892.HK`, and `80700.HK`.
  - Do not assume 5-digit padding such as `00700.HK` unless the live table actually returns it.
- `hk_shareeodprices` uses `date`, not `trade_date`, and adjusted fields such as `s_dq_adjclose` / `s_dq_adjpreclose` are suitable for weight-drift estimation.
- When mixing A-share and Hong Kong constituents for drift estimation, normalize codes and dates early and validate key uniqueness on `(con_code, trade_date)` before aggregation or joins.
- `cb_index_eodprices` and `hk_index_eodprices` were also re-validated on `2026-03-19` to accept `start_date/end_date` for bounded market-window pulls.
  - Prefer interval pull plus local code filtering over an old trade-date loop when the task only needs a contiguous window.

## ETF high-frequency coverage notes

Verified useful ETF interfaces:

- `level2_sh_new`
- `level2_sz_new`
- `china_closed_fund_auction`

Verified useful Shenzhen ETF microstructure interfaces:

- `tick`
- `order`

Verified unreliable-for-ETF interfaces despite suggestive docs:

- `k1min`
- `tick_new`
- `level1`

Interpretation:

- Build cross-market ETF high-frequency pipelines around `level2_sh_new`, `level2_sz_new`, and `china_closed_fund_auction`.
- Treat `tick` and `order` as Shenzhen-only enhancement layers.
- Do not assume an interface that works for stocks also works for ETFs.

## Volume and operational notes

- Shenzhen ETF `tick` and `order` can be very large even on a 5-minute sample. Treat them as selective research inputs, not default full-universe pulls.
- If `DataCubeAPI` spends too long probing request limits and you only need a bounded sample, using `auto_paging=False` with an explicit `limit` can be materially faster.
- Keep dated runtime notes. In this project, several Wind-mounted interfaces changed from "missing range params" to "range params now work", and that materially changed the correct extraction pattern.
