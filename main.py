#!/usr/bin/env python3
"""
Main script to orchestrate evaltest and loadtest execution based on braintest.yaml config.
"""
import yaml
import subprocess
import sys
import os
from datetime import datetime


def load_config(config_path="braintest.yaml"):
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config


def run_evaltest(config):
    print("Eval Test")
    print("=" * 50)
    try:
        subprocess.run(
            [sys.executable, "evaltest/run.py"],
            check=True,
            capture_output=False,
            env={**os.environ, "PYTHONPATH": "."},
        )
        print("Eval test completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Evaltest failed with error code {e.returncode}")
        return False


def run_loadtest(config):
    print("Load Test")
    print("=" * 50)

    loadtest_config = config.get("loadtest", {})

    locustfile_path = loadtest_config.get("locustfile_path", "loadtest/run.py")
    autostart = loadtest_config.get("autostart", False)
    port = str(loadtest_config.get("web_ui_port", 8089))
    host = config.get("braintrust").get("api_url", "https://api.braintrust.dev")
    params = loadtest_config.get("params", {})

    cmd = [
        "locust",
        "-f",
        locustfile_path,
        "--web-port",
        port,
        "--host",
        host,
        "--csv",
        f"./loadtest_results/{datetime.now()}",
    ]

    if "peak_concurrency" in params:
        cmd.extend(["--users", str(params["peak_concurrency"])])

    if "ramp_up" in params:
        cmd.extend(["--spawn-rate", str(params["ramp_up"])])

    if "run_time" in params:
        cmd.extend(["--run-time", str(params["run_time"])])

    if loadtest_config["logs"].get("html", False):
        cmd.extend(["--html", f"./results/interactive_report_{datetime.now().timestamp()}.html"])

    if loadtest_config["logs"].get("json", False):
        cmd.extend(["--json-file", f"./results/json_{datetime.now().timestamp()}.json"])
        
    if loadtest_config["logs"].get("csv", False):
        cmd.extend(["--csv", f"./results/{datetime.now().timestamp()}"])
        
    # Add autostart flag if enabled
    if autostart:
        cmd.append("--autostart")
        cmd.extend(["--autoquit", "10"])
        print(
            f"Auto start enabled. Test will close 10 seconds after completion. Navigate to web UI to monitor: http://localhost:{port}"
        )
    else:
        print(
            f"Auto start is disabled. Navigate to the web UI to start and monitor: http://localhost:{port}"
        )

    print(f"Running load test with command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=False)
        print("Loadtest completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Loadtest failed with error code {e.returncode}")
        return False
    except Exception as e:
        print(f"Unexpected error. {e}")
        return False


def main():
    print("Braintest")
    print("=" * 50)

    try:
        print("Loading configuration from braintest.yaml...")
        config = load_config()

        results = {}

        if config.get("evaltest", {}).get("run", False):
            evaltest_success = run_evaltest(config)
            results["evaltest"] = "SUCCESS" if evaltest_success else "FAILED"
        else:
            print("Evaltest is not enabled. Skipping...")
            results["evaltest"] = "SKIPPED"

        if config.get("loadtest", {}).get("run", False):
            loadtest_success = run_loadtest(config)
            results["loadtest"] = "SUCCESS" if loadtest_success else "FAILED"
        else:
            print("\nLoadtest is not enabled. Skipping...")
            results["loadtest"] = "SKIPPED"

        print("Test Summary:")
        print("=" * 50)
        for test_name, status in results.items():
            print(f"{test_name}: {status}")

    except FileNotFoundError as e:
        print(f"Error: Configuration file not found - {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Failed to parse YAML configuration - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
