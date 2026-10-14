# Topics Smoke Test

> **Note:** The Topics test makes LLM calls as part of the Topics pipeline through Braintrust models. `topics.dry_run: true` does not make LLM calls.

This test exercises Braintrust Topics in a new disposable project.

## What It Does

`braintest_suite.topics`:

1. Discovers the org from `BRAINTRUST_API_KEY` and reads the dataplane URL from
   the shared configuration.
2. Creates a disposable timestamped project, the built-in `Task` facet
   reference, and a project-local topic-map function.
3. Inserts one preflight trace and calls the facet through the direct and
   async-batch gateway paths.
4. Inserts the remaining synthetic traces and waits for all 105 to become
   replayable.
5. Registers and executes a Topics automation after the trace idle window.
6. Waits for 100 facet summaries, then drives topic-map generation.
7. Waits for the facet outputs to become replayable, rewinds the same automation
   to its classification-backfill cursor, and verifies 100 classifications.

The default count is 105 because topic generation needs at least 100 facet summaries.

The generated spans use `span_attributes.type = "llm"` because Topics builds
facet input through Brainstore's thread preprocessor, which only includes LLM
spans or spans with no explicit type.

The script intentionally does not expose facet or model override flags. It uses
the product's built-in `Task` facet and lets the backend choose the supported
facet model for the dataplane.

The preflight catches model-route and preprocessor failures before inserting the
remaining 104 traces. Its async call uses the same gateway path as automation
workers.

If you only want the automation path, skip the extra preflight calls:

```bash
TOPICS__SKIP_FACET_PREFLIGHT=true braintest run topics
```

## Usage

Use the repository's `braintest` CLI to run the Topics test:

```bash
export BRAINTRUST_API_KEY=...
braintest run topics
```

When working from this repository, activate its virtual environment or prefix
the command with `uv run`.

The `braintest run all` command includes this test and therefore makes LLM calls.

Configure Topics under the `topics` key in `braintest.yaml`, or use
`TOPICS__...` environment variables. Pydantic settings gives environment variables
priority over YAML. Topics-specific CLI flags are not supported.
Use `--config-file path/to/config.yaml` to select another configuration file.
These settings also apply to Topics when running `all`.

The dataplane URL comes from `braintrust.api_url` (or `BRAINTRUST__API_URL`).
The API key comes from `BRAINTRUST_API_KEY`.

For example, edit these entries in the existing configuration:

```yaml
topics:
  dry_run: false
  count: 105
  compaction_timeout: 300
  compaction_interval: 5
  automation_execution_timeout: 30
  running_check_timeout: 600
  running_check_interval: 5
  classification_timeout: 900
  classification_interval: 5
  skip_facet_preflight: false
```

Dry run without creating projects, traces, automations, or making LLM calls:

```bash
TOPICS__DRY_RUN=true braintest run topics
```

Dry run prints the resolved project name and connection settings. A real run
ends with a link to the project's Topics page.

By default, the script waits up to 600 seconds for the initial facet work to
finish processing:

```bash
TOPICS__RUNNING_CHECK_TIMEOUT=120 TOPICS__RUNNING_CHECK_INTERVAL=5 braintest run topics
```

The script waits for the 100-summary generation threshold, drives topic-map
generation, and rewinds the same automation to the backfill cursor published by
Topics. Before rewinding, it waits for the facet-bearing automation spans to
reach compacted Brainstore data. The Topics UI can display realtime facet results
before segment replay can read them.

The execute endpoint can outlive the client request while model work continues.
After `topics.automation_execution_timeout`, the test treats the request as in
progress and polls the resulting facet summaries and classifications.

Skip that verification only when you want the old fire-and-forget behavior:

```bash
TOPICS__SKIP_RUNNING_CHECK=true braintest run topics
```

If the API key belongs to multiple orgs:

```bash
TOPICS__ORG=braintrustdata.com braintest run topics
```

To override the configured dataplane for this run:

```bash
TOPICS__ORG=braintrustdata.com BRAINTRUST__API_URL=https://example.cloudfront.net braintest run topics
```

Check the project after creation by passing its required name:

```bash
braintest status topics topics-smoke-20260515-143022
```

Status includes facet counts, pending segment work, execution cursors, and the
Topics runtime state. If facet counts remain zero while segment work is pending,
facet processing has not started; topic generation cannot begin until enough
facet summaries are ready. Facet counts cover traces created in the last hour.

## Expected States

Topics may move through these states:

- `waiting_for_facets`: facet summaries are still being processed or fewer than
  100 summaries are ready.
- `recomputing_topic_maps`: the system generates new topic maps from the facet data.
- `pending_topic_classification_backfill`: new topic maps exist, and replay preparation starts.
- `backfilling_topic_classifications`: the system applies the topic maps to existing logs.
- `idle`: the automation has no immediate work queued.

## Cost Guardrails

- Default traces: 105.
- Facet: built-in `Task` only.
- No facet model override is sent; the backend default is used.
- Direct and async-batch preflight calls are run before the remaining traces are
  seeded.
- Counts below 100 are rejected unless `topics.allow_below_threshold` is true.
- Each run creates a fresh project so results are isolated and easy to inspect.
- The post-queue running check fails at timeout if rows are still attempted but
  not completed.

## Local Checks

```bash
braintest run --help
braintest status --help
TOPICS__DRY_RUN=true braintest run topics
```
