#!/usr/bin/env python3
"""
Main script to orchestrate functionaltest, evaltest, and loadtest execution
based on braintest.yaml config.
"""

import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_DEFAULT_LOCUSTFILE = str(Path(__file__).resolve().parent / "run.py")


def run(config: dict) -> bool:
    print("Load Test")

    loadtest_config = config.get("loadtest", {})

    locustfile_path = _DEFAULT_LOCUSTFILE
    headless = loadtest_config.get("headless", False)
    port = str(loadtest_config.get("web_ui_port", 8089))
    braintrust_config = config.get("braintrust", {})
    host = braintrust_config.get("api_url")
    if not host:
        raise ValueError("Missing required config: braintrust.api_url in braintest.yaml")
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
        read_concurrency = max(0, int(params.get("read_traffic", {}).get("peak_concurrency", 0)))
        cutover_concurrency = max(
            0, int(params.get("cutover_traffic", {}).get("peak_concurrency", 0))
        )
        total_users = params["peak_concurrency"] + read_concurrency + cutover_concurrency
        cmd.extend(["--users", str(total_users)])

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
        loadtest_env["BRAINTRUST_DEFAULT_BATCH_SIZE"] = str(bt_logger_config["flush_size"])
    if "queue_size" in bt_logger_config:
        loadtest_env["BRAINTRUST_QUEUE_SIZE"] = str(bt_logger_config["queue_size"])

    def _terminate_process_group(process: subprocess.Popen, label: str) -> None:
        if process.poll() is not None:
            return
        print(f"Stopping {label}...")
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as e:
            print(f"Failed to send SIGTERM to {label}: {e}")
            return

        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"{label} did not exit after SIGTERM. Sending SIGKILL...")
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except Exception as e:
                print(f"Failed to send SIGKILL to {label}: {e}")

    is_windows = sys.platform == "win32"
    try:
        if not is_windows:
            cmd.extend(["--processes", processes])
            print(f"Running load test with command: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                env=loadtest_env,
                start_new_session=True,
            )
            try:
                returncode = process.wait()
                if returncode != 0:
                    raise subprocess.CalledProcessError(returncode, cmd)
            finally:
                _terminate_process_group(process, "locust process group")
        else:
            worker_count = int(processes)
            if worker_count < 1:
                raise ValueError("Invalid config: loadtest.processes must be >= 1 for distributed mode")

            master_cmd = [*cmd, "--master"]
            worker_cmd = [
                "locust",
                "-f",
                locustfile_path,
                "--worker",
                "--master-host",
                "127.0.0.1",
            ]

            print(f"Windows detected. Running load test (master) with command: {' '.join(master_cmd)}")
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

                subprocess.run(master_cmd, check=True, capture_output=False, env=loadtest_env)
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


__all__ = ["run"]
