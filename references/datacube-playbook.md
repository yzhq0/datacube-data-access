# Datacube data dictionary and download playbook

## Document entry points

- Root index: `https://datacube.foundersc.com/document/2`
- Specific page pattern: `https://datacube.foundersc.com/document/2?doc_id=<doc_id>`

## Source families

DataCube documentation covers several families of datasets:

- DataCube native data
- High-frequency data
- Mounted third-party sources such as Wind, 通联, 东财, and CYYX

Selection rule:

- Prefer DataCube native data when it already satisfies the requirement, because it is usually easier to query and less likely to require cross-table joins.
- Switch to mounted providers when the native dataset is missing fields, coverage, or the user explicitly wants that provider.
- Expect higher friction on some Wind tables because internal codes such as industry mappings may need post-processing.
- Expect mounted-table behavior to evolve over time. A filter that was missing last month may exist now, and an older per-day workaround may no longer be the best extraction pattern.

## Terminal-first dictionary lookup

Use `lynx` to search the root index when only a concept or catalog label is known:

```bash
lynx -dump -listonly 'https://datacube.foundersc.com/document/2' | rg 'A股日行情'
```

Use `w3m` to inspect a known page in plain text:

```bash
w3m -dump 'https://datacube.foundersc.com/document/2?doc_id=10303' | sed -n '600,760p'
```

Use `rg` on the plain-text dump to jump to contract sections:

```bash
w3m -dump 'https://datacube.foundersc.com/document/2?doc_id=10303' | rg -n '接口|输入参数|输出参数'
```

Prefer the bundled `scripts/search_datacube_docs.sh` wrapper when working inside this skill.

## Browser-based lookup

Use the installed `playwright` skill when the DataCube site is easier to inspect in a real browser, for example:

- Menu structures that are easier to navigate visually
- Pages that render or update dynamically
- Tasks that require repeated drill-down and backtracking

The curated OpenAI `playwright` skill installs to `~/.codex/skills/playwright` and exposes a CLI wrapper at:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
```

## Downloading data with tushare_plus

The local environment already has `tushare_plus` installed. The main entry point is:

```python
from tushare_plus import DataCubeAPI

dc = DataCubeAPI()
df = dc.get_data(
    api_name="daily",
    ts_code="000001.SZ",
    fields="ts_code,trade_date,open,high,low,close,vol",
)
```

Confirmed `get_data` signature:

```python
def get_data(self, api_name, fields="", auto_paging=True, concurrent=False, max_pages=None, **params):
```

Important runtime note:

- `DataCubeAPI` reads `DATACUBE_TOKEN` from the environment when no token is passed explicitly.
- If `DATACUBE_TOKEN` is missing, client initialization fails.

## Download habits

- Keep `auto_paging=True` unless a bounded sample is enough.
- If a bounded sample is enough and `DataCubeAPI` is slow because it is probing the per-request cap, use `auto_paging=False` with an explicit `limit` equal to the documented single-call cap.
- Limit `fields` early so the pull stays small and the output is easier to inspect.
- Use `concurrent=True` only for large result sets where extra requests are worthwhile.
- Save outputs to an explicit file path and report that path back to the user.
- Validate date range, duplicates, and null-heavy columns after every pull.
- Prefer a range-first extraction pattern when interval params work. Use per-code or per-date splitting only when the live API truly lacks the needed range filter or the table's natural shape is not daily.
- If a range query is merely flaky on large windows, add timeout/retry and split on retry before hard-coding a fully daily loop.
- If a mounted interface throws transient transport errors such as `HTTP Error 503` or `IncompleteRead(...)`, retry before changing the table choice or extraction pattern. Distinguish "table is flaky right now" from "table lacks the required filter."

## Pattern selection by observed data shape

Do not choose the extraction pattern from the doc title alone.

Check the live data shape on a realistic sample:

- Is the table really daily, or is it effectively monthly snapshots?
- Do non-month-end rows exist, and do they matter for the target universe?
- Does a market-window pull work, or is per-code filtering still required?
- Is a previous anchor date needed for downstream point-in-time calculations?

Practical examples:

- A nominally daily or "weight" table may still be best queried only on month-end dates if the target universe only uses monthly official snapshots.
- "Month-end" in mounted financial-market tables often means the effective month-end trading day, not the literal last calendar day.
- A mounted interface may accept range params for the whole market even when older notes assumed per-code loops.
- A flaky long-window call should not immediately force a per-day loop if timeout/retry plus adaptive splitting can preserve efficiency.
- A constituent or holdings table may mix multiple code families such as A-share and Hong Kong securities. Inspect the observed code format before building local filters or normalizers.

## Parameter-gap escalation rule

If a table lacks the filtering parameters needed to make the pull correct or efficient:

- Say so explicitly as soon as you notice it.
- Continue with the best available parameters if the task is still feasible.
- Tell the user which exact filter would help, so they can ask maintainers to add it.
- Re-check the table later because some DataCube tables do gain new filters over time.

This matters especially for large Wind-mounted tables where the difference between "has date filter" and "no date filter" completely changes whether the task is practical.

## Runtime mismatch discipline

Do not stop at the doc page when accuracy matters. On a realistic sample, verify:

- parameter names and parameter case
- whether documented filters are actually accepted
- whether ETF codes, index codes, or Wind codes return rows
- whether metadata coverage implies quote coverage
- whether row limits or paging behavior match the doc

Record the mismatch in the final answer if it affects API choice or downstream processing.

Also record when the doc is technically correct but operationally misleading, for example:

- the table is documented as daily but only month-end snapshots are useful for the target task
- the interface accepts range params now, making an old split-by-day workaround obsolete
- the table mixes security-code families even though downstream code initially assumed a single market
- a provider-specific calendar table is a better source of trade dates than inferring the calendar from quote data

## Topic-specific references

Keep this file general. Put domain-specific runtime notes in dedicated reference files under `references/topics/`.

Current topic files:

- `references/topics/etf-wind.md`: ETF-specific, Wind-mounted, and ETF high-frequency interface notes
- `references/topics/index-moneyflow.md`: derived index-moneyflow, constituent-weight, and weight-drift notes
