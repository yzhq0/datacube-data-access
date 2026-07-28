# Verified Job Specification

Read this file only when creating, checking, or running a verified download job.

## Commands

```bash
python scripts/download_datacube.py check jobs/a_daily.json
python scripts/download_datacube.py run jobs/a_daily.json
```

`check` is read-only. It validates and hashes every contract input without initializing a DataCube client.
`run` requires `tushare_plus>=0.1.9` and reads authentication only from `DATACUBE_TOKEN`.

## JSON v1

```json
{
  "schema_version": 1,
  "api": {
    "name": "a_daily",
    "doc_id": 10303,
    "fields": ["trade_date", "code", "close"],
    "base_params": {}
  },
  "requests": {
    "partitions_file": "requests.jsonl"
  },
  "execution": {
    "auto_paging": true,
    "max_pages": 20,
    "partition_workers": 4,
    "resume": true
  },
  "validation": {
    "key_fields": ["trade_date", "code"],
    "expected_keys_file": "expected_keys.parquet",
    "filter_to_expected_keys": true,
    "group_fields": ["trade_date"]
  },
  "output": {
    "path": "output/a_daily.parquet"
  },
  "metadata": {}
}
```

All relative paths resolve from the job file directory.
Unknown keys are errors.
Secret-bearing keys are rejected recursively.

## Required sections

- `schema_version`: must equal `1`
- `api`: requires `name`, positive integer `doc_id`, and a non-empty unique `fields` list; `base_params` defaults to `{}`
- `requests`: requires exactly one of `partitions` or `partitions_file`
- `validation`: requires non-empty unique `key_fields`
- `output`: requires `path`; infer `format` from the suffix unless set explicitly

Use `"partitions": [{}]` for a verified single-partition job.
Each partition is a complete parameter override merged over `api.base_params`.
JSONL, JSON, CSV, and TSV partition files are supported.

## Execution defaults

- `auto_paging`: `true`
- `detect_limit`: `true`
- `partition_workers`: `1`
- `partition_format`: `"csv"`
- `resume`: `true`
- `request_timeout`: `60`
- `max_retries`: `3`
- `retry_delay`: `1`
- `retry_backoff`: `2`
- `retry_jitter`: `0.1`
- `max_retry_delay`: `60`

Set a positive `max_pages` whenever `auto_paging` is enabled.
Derive `checkpoint_dir` as `.<output-name>.partitions/` and `execution_manifest` inside it unless explicitly provided.
Do not combine page-level concurrency with partition concurrency; verified jobs expose partition concurrency only.

## Validation and publication

Optional validation fields are:

- `expected_keys_file`
- `filter_to_expected_keys` (default `false`)
- `group_fields` (default `[]`)
- `expected_group_cardinality`
- `sample_limit` (default `20`)

`filter_to_expected_keys` requires `expected_keys_file`.
Without expected keys, every pagination report must prove source exhaustion.
Derive the dataset manifest beside the output unless `output.dataset_manifest` is set.

The job file, partition file, and expected-key file are frozen by SHA-256.
Recheck their hashes before publication.
Publish output and the complete dataset manifest atomically only after all execution and validation checks pass.
