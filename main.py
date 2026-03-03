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
    headless = loadtest_config.get("headless", False)
    port = str(loadtest_config.get("web_ui_port", 8089))
    braintrust_config = config.get("braintrust", {})
    host = braintrust_config.get("api_url")
    if not host:
        raise ValueError(
            "Missing required config: braintrust.api_url in braintest.yaml"
        )
    processes = str(loadtest_config.get("processes", 1))
    bt_logger_config = loadtest_config.get("braintrust_logger", {})
    params = loadtest_config.get("params", {})

    cmd = [
        "locust",
        "-f",
        locustfile_path,
        "--web-port",
        port,
        "--host",
        host,
    ]

    if "peak_concurrency" in params:
        cmd.extend(["--users", str(params["peak_concurrency"])])

    if "ramp_up" in params:
        cmd.extend(["--spawn-rate", str(params["ramp_up"])])

    if "run_time" in params:
        cmd.extend(["--run-time", str(params["run_time"])])

    # Logs
    if loadtest_config["logs"].get("html", False):
        cmd.extend(
            [
                "--html",
                "{u}_users_{r}_ramp_{t}_time.html",
            ]
        )
    if loadtest_config["logs"].get("json", False):
        cmd.extend(["--json-file", f"json_{datetime.now().timestamp()}.json"])
    if loadtest_config["logs"].get("csv", False):
        cmd.extend(["--csv", f"csv_{datetime.now().timestamp()}"])

    if headless:
        cmd.append("--headless")
    else:
        cmd.extend(["--autostart", "--autoquit", "10"])

    loadtest_env = {**os.environ, "PYTHONPATH": "."}
    if "flush_size" in bt_logger_config:
        loadtest_env["BRAINTRUST_DEFAULT_BATCH_SIZE"] = str(
            bt_logger_config["flush_size"]
        )
    if "queue_size" in bt_logger_config:
        loadtest_env["BRAINTRUST_QUEUE_SIZE"] = str(bt_logger_config["queue_size"])

    is_macos = sys.platform == "darwin"
    try:
        if is_macos:
            cmd.extend(["--processes", processes])
            print(f"Running load test with command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=False, env=loadtest_env)
        else:
            worker_count = int(processes)
            if worker_count < 1:
                raise ValueError(
                    "Invalid config: loadtest.processes must be >= 1 for distributed mode"
                )

            master_cmd = [*cmd, "--master"]
            worker_cmd = [
                "locust",
                "-f",
                locustfile_path,
                "--worker",
                "--master-host",
                "127.0.0.1",
            ]

            print(f"Windows sys detected. Running load test (master) with command: {' '.join(master_cmd)}")
            print(f"Running load test with {worker_count} worker process(es)")

            workers = []
            try:
                for _ in range(worker_count):
                    workers.append(
                        subprocess.Popen(
                            worker_cmd,
                            env=loadtest_env,
                        )
                    )

                subprocess.run(
                    master_cmd, check=True, capture_output=False, env=loadtest_env
                )
            finally:
                for worker in workers:
                    if worker.poll() is None:
                        worker.terminate()
                for worker in workers:
                    try:
                        worker.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        worker.kill()

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
