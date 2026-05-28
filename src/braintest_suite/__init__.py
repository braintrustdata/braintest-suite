#!/usr/bin/env python3
"""
CLI tool to run Braintest test suites: functional tests, eval tests, and load tests.
"""

import os
import sys

import click
from pydantic import ValidationError

from braintest_suite.config import load_config

AVAILABLE_SUITES = {
    "functional": "Functional API CRUD tests against Braintrust",
    "evaltest": "Evaluation test with synthetic dataset and scorers",
    "loadtest": "Locust-based load test with concurrent users",
}


def _load_config() -> dict:
    try:
        return load_config()
    except FileNotFoundError:
        config_file = os.environ.get("BRAINTEST_CONFIG_FILE", "braintest.yaml")
        click.echo(f"Error: Configuration file not found: {config_file}", err=True)
        sys.exit(1)
    except ValidationError as exc:
        config_file = os.environ.get("BRAINTEST_CONFIG_FILE", "braintest.yaml")
        click.echo(f"Error: Invalid configuration in {config_file}", err=True)
        click.echo(str(exc), err=True)
        sys.exit(1)


def _run_suite(name: str, config: dict) -> str:
    """Run a single test suite by name. Returns status string."""
    if name == "functional":
        click.echo("\n-----Running Functional Test-----")
        from braintest_suite.functional_test import run as run_fn

        return "SUCCESS" if run_fn(config) else "FAILED"
    elif name == "evaltest":
        click.echo("\n-----Running Eval Test-----")
        from braintest_suite.evaltest import run as run_fn

        return "SUCCESS" if run_fn(config) else "FAILED"
    elif name == "loadtest":
        click.echo("\n-----Running Locust Load Test-----")
        from braintest_suite.loadtest import run as run_fn

        return "SUCCESS" if run_fn(config) else "FAILED"
    else:
        return "UNKNOWN"


def _print_results(results: dict):
    click.echo("\n-----Test Summary-----")
    for test_name, status in results.items():
        click.echo(f"{test_name}: {status}")


@click.group()
@click.option(
    "--config-file",
    default=None,
    help="Path to the YAML configuration file.",
)
@click.pass_context
def cli(ctx, config_file):
    """Braintest - test suite runner for Braintrust.

    Use 'braintest run <suite> ...' to run specific suites.
    Use 'braintest run all' to run every suite.
    Use 'braintest list' to see available suites.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_file"] = config_file


@cli.command("run")
@click.option(
    "--config-file",
    default=None,
    help="Path to the YAML configuration file.",
)
@click.argument("suites", nargs=-1, required=True)
@click.pass_context
def run_suites(ctx, config_file, suites):
    """Run specific test suites by name.

    Examples:

        braintest run functional

        braintest run functional evaltest

        braintest run all

        braintest run loadtest

        braintest run --config-file custom.yaml loadtest
    """
    resolved_config = config_file or ctx.obj.get("config_file") or "braintest.yaml"
    os.environ["BRAINTEST_CONFIG_FILE"] = resolved_config
    click.echo(f'Using config file "{resolved_config}"')

    if "all" in suites:
        if len(suites) > 1:
            click.echo(
                "Error: 'all' cannot be combined with other suite names.",
                err=True,
            )
            sys.exit(1)
        selected_suites = list(AVAILABLE_SUITES.keys())
    else:
        invalid = [s for s in suites if s not in AVAILABLE_SUITES]
        if invalid:
            click.echo(f"Error: Unknown suite(s): {', '.join(invalid)}", err=True)
            click.echo(f"Available: {', '.join(AVAILABLE_SUITES.keys())}", err=True)
            sys.exit(1)

        # Preserve user order while removing duplicates.
        selected_suites = list(dict.fromkeys(suites))

    config = _load_config()
    results = {}

    click.echo("=" * 50)
    click.echo("Braintest")
    click.echo("=" * 50 + "\n")

    for name in selected_suites:
        results[name] = _run_suite(name, config)

    _print_results(results)

    has_failure = any(s == "FAILED" for s in results.values())
    sys.exit(1 if has_failure else 0)


@cli.command("list")
def list_suites():
    """List available test suites."""
    click.echo("Available test suites:\n")
    for name, description in AVAILABLE_SUITES.items():
        click.echo(f"  {name:<15} {description}")


main = cli

if __name__ == "__main__":
    cli()
