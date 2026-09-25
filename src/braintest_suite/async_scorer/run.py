import os
import signal
import subprocess
import sys
from pathlib import Path

from braintest_suite.async_scorer.setup import prepare
from braintest_suite.config import load_config

_LOCUSTFILE = str(Path(__file__).resolve().parent / "locustfile.py")


def run(config: dict | None = None) -> bool:
    print("Async scorer load test")
    resolved = config if config is not None else load_config()
    try:
        fixture_path = prepare(resolved)
    except Exception as exc:
        print(f"Async scorer setup failed: {exc}")
        return False

    settings = resolved["asyncscorer"]
    host = resolved["braintrust"]["api_url"]
    cmd = [
        "locust",
        "-f",
        _LOCUSTFILE,
        "--web-port",
        str(settings["web_ui_port"]),
        "--host",
        host,
        "--users",
        str(settings["peak_concurrency"]),
        "--spawn-rate",
        str(settings["ramp_up"]),
        "--run-time",
        str(settings["run_time"]),
        "--html",
        "async_scorer_{u}_users_{r}_ramp_{t}_time.html",
    ]
    if settings["headless"]:
        cmd.append("--headless")
    else:
        cmd.extend(["--autostart", "--autoquit", "10"])

    loadtest_env = {
        **os.environ,
        "PYTHONPATH": ".",
        "ASYNC_SCORER_FIXTURE": str(fixture_path),
        "BRAINTRUST_API_URL": host,
        "BRAINTRUST_SYNC_FLUSH": "1",
        "BRAINTRUST_DEFAULT_BATCH_SIZE": str(settings["flush_batch_size"]),
    }
    print(f"{settings['peak_concurrency']} in-flight log flushes, {settings['flush_batch_size']} new root spans each")
    return _run_locust(cmd, loadtest_env, str(settings["processes"]))


def _run_locust(cmd: list[str], env: dict[str, str], processes: str) -> bool:
    def _terminate_process_group(process: subprocess.Popen, label: str) -> None:
        if process.poll() is not None:
            return
        print(f"Stopping {label}...")
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as exc:
            print(f"Failed to send SIGTERM to {label}: {exc}")
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"{label} did not exit after SIGTERM. Sending SIGKILL...")
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return

    is_windows = sys.platform == "win32"
    try:
        if not is_windows:
            cmd.extend(["--processes", processes])
            print(f"Running async scorer load test with command: {' '.join(cmd)}")
            process = subprocess.Popen(cmd, env=env, start_new_session=True)
            try:
                returncode = process.wait()
                if returncode != 0:
                    raise subprocess.CalledProcessError(returncode, cmd)
            finally:
                _terminate_process_group(process, "locust process group")
        else:
            worker_count = int(processes)
            if worker_count < 1:
                raise ValueError("asyncscorer.processes must be >= 1")
            master_cmd = [*cmd, "--master"]
            worker_cmd = [
                "locust",
                "-f",
                _LOCUSTFILE,
                "--worker",
                "--master-host",
                "127.0.0.1",
            ]
            workers = []
            try:
                for _ in range(worker_count):
                    workers.append(subprocess.Popen(worker_cmd, env=env))
                subprocess.run(master_cmd, check=True, env=env)
            finally:
                for worker in workers:
                    if worker.poll() is None:
                        worker.terminate()
                for worker in workers:
                    try:
                        worker.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        worker.kill()
        print("Async scorer load test completed successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"Async scorer load test failed with error code {exc.returncode}")
        return False
    except Exception as exc:
        print(f"Unexpected error. {exc}")
        return False
