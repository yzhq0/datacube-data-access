# Source Selection

Read this file at the start of almost every task.

## Source families

DataCube requests usually fall into one of these source families:

- DataCube native data
- High-frequency data
- Mounted third-party sources such as Wind, 通联, 东财, and CYYX

## Selection rule

When Wind and DataCube native both cover the same data class, default to Wind for long-lived work:

- Wind tables are usually broader for the same data type
- Wind is the safer default when completeness or expected data quality matters

Prefer DataCube native instead when at least one of these is true:

- the native dataset covers the requirement and materially simplifies integration
- the mounted Wind path is operationally unusable or disproportionately fragile for the current task
- the user explicitly prefers native

Use mounted providers when at least one of these is true:

- The native dataset is missing the needed field or coverage
- The user explicitly asks for that provider
- The mounted source is the canonical dataset the user expects

Treat mounted providers as higher-friction by default. Wind is the main example:

- parameter names or parameter case can drift from the doc page
- metadata coverage does not guarantee quote coverage
- transport behavior can be flaky on otherwise valid interfaces

Treat 通联 conservatively:

- availability cannot be assumed stable
- do not choose it as a default dependency for long-running projects unless there is no acceptable alternative
- if you must use it, say explicitly that the project is taking on provider availability risk

## Decision discipline

- State the chosen source family explicitly before you lock the API
- When Wind and native are both viable, prefer Wind unless native has a concrete task-local advantage that matters more than coverage or data quality
- Re-check old assumptions on mounted tables because filters and range support can evolve over time
- If the real blocker is a missing filter, say so early instead of hiding it behind a slow workaround
