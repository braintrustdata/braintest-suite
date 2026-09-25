import json
import os
from pathlib import Path

from locust import User, constant, task

_FIXTURE_PATH = os.environ.get("ASYNC_SCORER_FIXTURE") or str(Path(__file__).resolve().parent / "fixture.json")


def _load_fixture() -> dict:
    path = Path(_FIXTURE_PATH)
    if not path.exists():
        raise RuntimeError(
            f"Missing async scorer fixture at {path}. Run `braintest run asyncscorer` "
            "so it can create the project and online scorer first."
        )
    with path.open() as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Async scorer fixture at {path} is not an object")
    project_id = payload.get("project_id")
    flush_batch_size = payload.get("flush_batch_size")
    if not isinstance(project_id, str) or not project_id:
        raise RuntimeError(f"Async scorer fixture at {path} is missing project_id")
    if not isinstance(flush_batch_size, int) or flush_batch_size < 1:
        raise RuntimeError(f"Async scorer fixture at {path} is missing flush_batch_size")
    return payload


_FIXTURE = _load_fixture()
_FLUSH_BATCH_SIZE = int(_FIXTURE["flush_batch_size"])

os.environ["BRAINTRUST_SYNC_FLUSH"] = "1"
os.environ["BRAINTRUST_DEFAULT_BATCH_SIZE"] = str(_FLUSH_BATCH_SIZE)
if not os.environ.get("BRAINTRUST_API_URL") and isinstance(_FIXTURE.get("api_url"), str):
    os.environ["BRAINTRUST_API_URL"] = _FIXTURE["api_url"]


class LogBatchUser(User):
    # One user is one in-flight SDK flush of new root spans.
    wait_time = constant(0)

    def on_start(self):
        from braintrust.logger import BraintrustState, init_logger

        api_key = os.getenv("BRAINTRUST_API_KEY")
        if not api_key:
            raise RuntimeError("BRAINTRUST_API_KEY is required")
        self._batch_size = _FLUSH_BATCH_SIZE
        self._next = 0
        self._logger = init_logger(
            project_id=_FIXTURE["project_id"],
            async_flush=False,
            api_key=api_key,
            set_current=False,
            state=BraintrustState(),
        )

    @task
    def log_batch(self):
        with self.environment.events.request.measure("SDK", "log_batch"):
            for offset in range(self._batch_size):
                output = "bar" if (self._next + offset) % 2 == 0 else "baz"
                with self._logger.start_span(name="root") as span:
                    span.log(input="foo", output=output, expected="bar")
            self._next += self._batch_size
            self._logger.flush()
