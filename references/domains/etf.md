# ETF Workflows

Read this file when the task involves any of these:

- ETF daily data
- ETF high-frequency or microstructure data
- ETF benchmark or commodity/futures ETF mapping
- ETF workflows that depend on mounted Wind tables

Load `references/providers/wind.md` when the task uses Wind-mounted tables or hits mounted-table runtime mismatch.

## ETF daily notes

- `mf_trackingindex`: doc examples may use `.OF`, but runtime validation accepted listed trading codes such as `510300.SH` and `159901.SZ`
- `mf_closedfund_eodprice`, `mf_floatshare`, and `mf_iopvnav` gained more useful date filtering over time
- `mf_nav` is still a special case:
  - use `start_end_date` and `stop_end_date`, not `start_date` and `end_date`
  - prefer interval-first with timeout or retry before splitting the range
- ETF share data can be incomplete too early in the day; prefer a latest-complete-trading-day convention for production snapshots
- `mf_floatshare` docs implied Shenzhen-only coverage, but runtime validation returned Shanghai ETFs too

## Trading calendar notes

- Prefer explicit calendar tables over inferring trading dates from quote tables when future dates matter
- Current priority for ETF workflows:
  - `a_calendar` first
  - `trade_cal` second
  - quote-table fallback only as a last resort

## Commodity and futures ETF benchmarks

- `commodity_index` looked relevant but returned `接口不存在` in runtime; do not rely on it without re-validation
- Validated replacements were:
  - `wind_gold_eod`
  - `wd_future_eod`
  - `wind_future_des`
- `wind_gold_eod` accepted `code` on tested benchmarks such as `Au9999.SGE` and `SHAU.SGE`

## ETF high-frequency coverage

Verified useful cross-market ETF interfaces:

- `level2_sh_new`
- `level2_sz_new`
- `china_closed_fund_auction`

Verified Shenzhen-only enhancement layers:

- `tick`
- `order`

Verified unreliable for ETF coverage despite suggestive docs:

- `k1min`
- `tick_new`
- `level1`

## Operational notes

- Shenzhen ETF `tick` and `order` can be huge even on short windows; treat them as selective research inputs
- If the table choice or coverage matters, re-test on a realistic sample because mounted ETF behavior can drift over time
