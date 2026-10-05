# Braintest Load Test Suite

A load testing suite for running benchmarks on self-hosted Braintrust data planes.

## Overview

This suite currently supports four types of tests:

- **Functional Test** (`functional`): Exercises core API create/read/delete flows across key Braintrust resources
- **Eval Test** (`evaltest`): Generates a large synthetic dataset and runs an eval against it
- **Load Test** (`loadtest`): Spawns simulated users to bombard the data plane with logs, simulating production traffic
- **Topics Smoke Test** (`smoketest`): Exercises the Topics pipeline on a disposable project with synthetic traces

The suite can be extended to support additional test types in the future, and that is a goal.

Each test is highly configurable via the `braintest.yaml` config file. The tests should be configured to simulate a customer's expected load and usage patterns. We want to ensure that the infra Braintrust is hosted on can handle the customer's use case, and size up components accordingly if the tests fail.

## Installation

### From source (local development)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone <repo-url> && cd braintest-suite
uv sync
```

### From git (remote install)

```bash
uv pip install git+<repo-url>
```

A `braintest.yaml` file is expected in the current working directory by default. You can override this with `--config-file path/to/config.yaml`.

## Getting Started

1. Create a `.env` file (see `example.env` for reference)

2. Configure `braintest.yaml` with your environment details and test parameters.

3. Run a test suite:
   ```bash
   braintest run all
   ```

## CLI Usage

The `braintest` CLI is the main entry point. Running it with no arguments shows help. Use `run` to execute suites.

```bash
# Show help
braintest

# List available test suites
braintest list

# Run specific suites
braintest run functional
braintest run functional evaltest
braintest run loadtest
braintest run smoketest
braintest run all

# Use a different config file
braintest --config-file custom.yaml run loadtest
braintest run --config-file custom.yaml loadtest
braintest run --config-file custom.yaml all
```

Each test suite is also runnable as a standalone Python module:

```bash
python -m braintest_suite.functional_test
python -m braintest_suite.evaltest
python -m braintest_suite.loadtest
python -m braintest_suite.smoke_test --dry-run
```

If you are running over SSH on a remote server, use `nohup` so the test keeps running if your session disconnects:

```bash
nohup braintest run all > braintest.out 2>&1 &
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
BRAINTRUST__API_URL=https://my-api.example.com LOADTEST__PROCESSES=8 uv run braintest run loadtest
```

The `all` selection excludes the Topics smoke test. The test creates a disposable project and uses model-backed Topics processing.

Run a local preview with this command:

```bash
uv run python -m braintest_suite.smoke_test --dry-run
```

Run the real test with `uv run braintest run smoketest`.

## Important Notes
- Load, eval, and functional tests do not make actual LLM calls.
- The Topics smoke test uses model-backed Topics processing.
