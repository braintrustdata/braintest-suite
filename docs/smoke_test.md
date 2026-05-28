# Topics Smoke Test

This folder contains a small support-only script for exercising Braintrust
Topics on a fresh disposable project.

## What It Does

`smoke_test/run.py`:

1. Uses `BRAINTRUST_API_KEY` to call the fixed app URL,
   `https://www.braintrust.dev/api/apikey/login`.
2. Discovers the org and dataplane `api_url` from that login response.
3. Creates a fresh project named like `topics-smoke-20260515-143022`.
4. Uses the built-in `Task` facet and creates a project-local topic-map function.
5. Inserts one synthetic root LLM trace and runs direct and async-batch gateway
   preflights through the normal Topics path.
6. Inserts the remaining traces to reach 105 total.
7. Enables a minimal Topics automation using those saved functions.
8. Queues the Topics automation to run.
9. Polls until the `Task` facet shows the expected 105 running or processed traces.

The default count is 105 because topic generation needs at least 100 facet
summaries. One facet keeps the model work and Baseten traffic as small as
possible while still exercising the pipeline.

The generated spans use `span_attributes.type = "llm"` because Topics builds
facet input through Brainstore's thread preprocessor, which only includes LLM
spans or spans with no explicit type.

The script intentionally does not expose facet or model override flags. It uses
the product's built-in `Task` facet and lets the backend choose the supported
facet model for the dataplane.

The preflight catches model routing or preprocessor failures before the
remaining 104 traces are inserted and before Topics is queued. It also calls
`/function/invoke-async-batch` with the gateway header because that is the path
used by automation workers. Skip it only when testing the automation path
without extra preflight calls:

```bash
uv run python smoke_test/run.py --skip-facet-preflight
```

## Usage

Dry run without creating projects, traces, or automations:

```bash
uv run python smoke_test/run.py --dry-run
```

The dry-run output includes the fixed app URL plus the org and dataplane API URL
that would be used. If no API key is present, those fields are only populated
from explicit arguments or environment variables.

Real run:

```bash
export BRAINTRUST_API_KEY=...
uv run python smoke_test/run.py
```

Run through the full suite by enabling the `smoketest` section in
`braintest.yaml`:

```yaml
smoketest:
  run: True
```

The direct CLI and `main.py` entrypoint both use `braintest.yaml` defaults.
CLI flags still override those defaults for one-off runs.

The real run prints the app URL, org, and dataplane API URL before creating the
project. On success, the final line is a clickable Topics results link for the
created project.

By default, the script waits up to 90 seconds for the initial facet work to show
the expected running or processed count:

```bash
uv run python smoke_test/run.py --running-check-timeout 120 --running-check-interval 5
```

The Topics status query can temporarily move while the automation cursor
advances. The script keeps polling until the expected traces are either running
or already processed, and fails if neither count appears before the timeout.

After the running or processed count appears, full topic results are not
necessarily immediate. With the default `--idle-seconds 10`, the runtime
rechecks active Topics states about every 10 seconds. A healthy tiny project
should usually move from `waiting_for_facets` to topic generation and backfill
within a few minutes, but vendor/model latency and retry behavior can stretch
that. If it remains in `waiting_for_facets` with `ready_topic_maps: 0` after
several checks, the facet summaries are not becoming ready.

Skip that verification only when you want the old fire-and-forget behavior:

```bash
uv run python smoke_test/run.py --skip-running-check
```

If the API key belongs to multiple orgs:

```bash
uv run python smoke_test/run.py --org braintrustdata.com
```

If discovery fails or you need to force a dataplane:

```bash
uv run python smoke_test/run.py --org braintrustdata.com --api-url https://example.cloudfront.net
```

Check the project after creation:

```bash
uv run python smoke_test/run.py status --project topics-smoke-20260515-143022
```

## Expected States

Topics may move through these states:

- `waiting_for_facets`: facet summaries are still being processed or fewer than
  100 summaries are ready.
- `recomputing_topics`: topic maps are being generated from the summaries.
- `pending_logs_processing`: topics are ready and classifications are being
  prepared.
- `processing_logs`: classifications are being written back to logs.
- `idle`: the automation has no immediate work queued.

## Cost Guardrails

- Default traces: 105.
- Facet: built-in `Task` only.
- No facet model override is sent; the backend default is used.
- Direct and async-batch preflight calls are run before the remaining traces are
  seeded.
- Counts below 100 are rejected unless `--allow-below-threshold` is passed.
- Each run creates a fresh project so results are isolated and easy to inspect.
- The post-queue running check fails at timeout if rows are still attempted but
  not completed.

## Local Checks

```bash
uv run python -m py_compile smoke_test/run.py
uv run python -m unittest smoke_test/test_topics_smoke.py
uv run python smoke_test/run.py --dry-run
```
