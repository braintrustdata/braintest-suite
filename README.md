# Braintest Load Test Suite

A load testing suite for running benchmarks on self-hosted Braintrust data planes.

## Overview

This suite currently supports four types of tests:

- **Load Test**: Spawns simulated users to bombard the data plane with logs, simulating production traffic

- **Large Eval Test**: Generates a large synthetic dataset and runs an eval against it

- **Functional Test**: Exercises core API create/read/delete flows across key Braintrust resources

- **Smoke Test**: Exercises the Topics pipeline on a disposable project with a small synthetic trace set

The suite can be extended to support additional test types in the future, and that is a goal.

Each test is highly configurable via the `braintest.yaml` config file. The tests should be configured to simulate a customer's expected load and usage patterns. We want to ensure that the infra Braintrust is hosted on can handle the customer's use case, and size up components accordingly if the tests fail.

## Getting Started

1. Install uv if you don't have it:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```
3. Activate the virtual env uv creates if it isn't already activated
   ```bash
   source .venv/bin/activate
   ```

4. Create a `.env` file (see `example.env` for reference)

5. Configure `braintest.yaml` with your environment details and test parameters.

6. Execute the test suite:
   ```bash
   python main.py
   ```

7. If you are running over SSH on a remote server, use `nohup` so the test keeps running if your session disconnects:
   ```bash
   nohup python main.py &
   ```
   This will write output to a default log file. To write `nohup` output to a specific file:
   ```bash
   nohup python main.py > loadtest.out 2>&1 &
   ```

## Configuration

Configuration is loaded from `braintest.yaml` using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Environment variables take priority over YAML values.

To override any config value via environment variable, use `__` (double underscore) as the nested separator. For example:

| YAML path | Environment variable |
|---|---|
| `braintrust.api_url` | `BRAINTRUST__API_URL` |
| `braintrust.project_name` | `BRAINTRUST__PROJECT_NAME` |
| `loadtest.processes` | `LOADTEST__PROCESSES` |
| `evaltest.trial_count` | `EVALTEST__TRIAL_COUNT` |
| `functionaltest.name_prefix` | `FUNCTIONALTEST__NAME_PREFIX` |
| `smoketest.count` | `SMOKETEST__COUNT` |

Example:
```bash
BRAINTRUST__API_URL=https://my-api.example.com LOADTEST__PROCESSES=8 python main.py
```

The Topics smoke test is disabled by default because it creates a disposable
project and exercises model-backed Topics processing. Enable it with
`smoketest.run: True`, or run it directly with:

```bash
uv run python smoke_test/run.py --dry-run
```

## Important Notes
- Load, eval, and functional tests do not make actual LLM calls. The Topics smoke test exercises model-backed Topics processing, so keep it disabled unless you intentionally want to test that path.
