import os
import random

import requests
from dotenv import load_dotenv
from faker import Faker
from locust import HttpUser, task, between, constant_pacing, events
from braintest_suite.loadtest.mock_conversation_task import mock_multiturn_conversation
from braintest_suite.loadtest.braintrust_http_metrics import (
    BraintrustMetricsAdapter,
    BraintrustMetricsEmitter,
)
from braintest_suite.config import load_config
from braintest_suite.util import http_client
from dotenv import load_dotenv
from urllib.parse import urlparse


load_dotenv()

fake = Faker()


config = load_config()
_LOGGER_INITIALIZED = False
_BT_METRICS_EMITTER = None


def _collect_braintrust_hosts() -> set[str]:
    hosts = set()
    api_url = config.get("braintrust", {}).get("api_url")
    if api_url:
        parsed = urlparse(api_url)
        if parsed.netloc:
            hosts.add(parsed.netloc.lower())

    for env_key in ("BRAINTRUST_API_URL", "BRAINTRUST_PROXY_URL", "BRAINTRUST_APP_URL"):
        env_url = os.getenv(env_key)
        if env_url:
            parsed = urlparse(env_url)
            if parsed.netloc:
                hosts.add(parsed.netloc.lower())
    return hosts


@events.test_start.add_listener
def _init_braintrust_logger(environment, **kwargs):
    global _LOGGER_INITIALIZED, _BT_METRICS_EMITTER
    if _LOGGER_INITIALIZED:
        return

    # In distributed mode, only workers execute user tasks.
    # Skip logger init on master to avoid unnecessary setup.
    if environment.runner and environment.runner.__class__.__name__ == "MasterRunner":
        return

    from braintrust import init_logger, set_http_adapter

    project = config["braintrust"]["project_name"]
    pool_maxsize = config["loadtest"]["connection_pool_size"]
    _BT_METRICS_EMITTER = BraintrustMetricsEmitter(environment=environment)
    _BT_METRICS_EMITTER.start()
    set_http_adapter(
        BraintrustMetricsAdapter(
            emitter=_BT_METRICS_EMITTER,
            known_braintrust_hosts=_collect_braintrust_hosts(),
            pool_maxsize=pool_maxsize,
        )
    )
    init_logger(
        project=project,
        async_flush=True,
        api_key=os.getenv("BRAINTRUST_API_KEY"),
    )
    _LOGGER_INITIALIZED = True


@events.test_stop.add_listener
def _flush_braintrust_logger(environment, **kwargs):
    global _BT_METRICS_EMITTER, _LOGGER_INITIALIZED
    if not _LOGGER_INITIALIZED:
        return
    if environment.runner and environment.runner.__class__.__name__ == "MasterRunner":
        return
    from braintrust import flush

    try:
        flush()
    finally:
        if _BT_METRICS_EMITTER is not None:
            _BT_METRICS_EMITTER.stop()
            _BT_METRICS_EMITTER = None
        _LOGGER_INITIALIZED = False


_read_traffic_config = config["loadtest"]["params"]["read_traffic"]
_read_peak_concurrency = max(0, int(_read_traffic_config.get("peak_concurrency", 0)))
_read_btql_calls_per_min = float(
    _read_traffic_config.get("btql_calls_per_min", 20) or 20
)
_read_effective_limit_per_user = _read_btql_calls_per_min / max(
    _read_peak_concurrency, 1
)
_read_pacing_seconds = 60 / max(_read_effective_limit_per_user, 0.01)


class AdminUser(HttpUser):
    fixed_count = _read_peak_concurrency
    wait_time = constant_pacing(_read_pacing_seconds)

    def on_start(self):
        self.headers = {
            "Authorization": f"Bearer {os.getenv('BRAINTRUST_API_KEY')}",
            "Content-Type": "application/json",
        }
        try:
            response = http_client(
                "POST",
                f"{config['braintrust']['api_url']}/v1/project",
                payload={"name": config["braintrust"]["project_name"]},
                headers=self.headers,
            )
            self.project_id = response.json().get("id")
        except requests.exceptions.RequestException:
            self.project_id = None

    @task(1)
    def query_recent_traces(self):
        if not self.project_id:
            return
        query = f"""
            SELECT * FROM project_logs('{self.project_id}') ORDER BY created DESC LIMIT 50
        """
        self.client.post(
            "/btql",
            json={"query": query, "fmt": "json"},
            headers=self.headers,
            name="btql_recent_traces",
        )

    @task(1)
    def query_span_aggregates(self):
        if not self.project_id:
            return
        query = f"""
            SELECT span_attributes.type, COUNT(*) as span_count, AVG(metrics.tokens) as avg_tokens
            FROM project_logs('{self.project_id}')
            WHERE created > now() - interval 3
            GROUP BY span_attributes.type
        """
        self.client.post(
            "/btql",
            json={"query": query, "fmt": "json"},
            headers=self.headers,
            name="btql_span_aggregates",
        )


class BraintrustUser(HttpUser):
    fixed_count = config["loadtest"]["params"]["peak_concurrency"]
    min_wait = config["loadtest"]["params"]["wait_time"]["min"]
    max_wait = config["loadtest"]["params"]["wait_time"]["max"]
    wait_time = between(min_wait, max_wait)

    @task
    def ask_question(self):
        query_templates = [
            lambda: fake.sentence(),
            lambda: f"How do I {fake.word()} {fake.word()}?",
            lambda: f"What is the {fake.word()} of {fake.word()}?",
            lambda: f"Explain {fake.catch_phrase()}",
            lambda: f"Write code to {fake.word()} {fake.word()}",
            lambda: f"Analyze {fake.word()} and provide {fake.word()}",
            lambda: f"Compare {fake.word()} and {fake.word()}",
        ]
        query = random.choice(query_templates)()
        mock_multiturn_conversation(query)


_cutover_traffic_config = config["loadtest"]["params"].get("cutover_traffic") or {}
_cutover_peak_concurrency = max(0, int(_cutover_traffic_config.get("peak_concurrency", 0)))
_cutover_calls_per_min = float(_cutover_traffic_config.get("calls_per_min", 6) or 6)
_cutover_effective_limit_per_user = _cutover_calls_per_min / max(
    _cutover_peak_concurrency, 1
)
_cutover_pacing_seconds = 60 / max(_cutover_effective_limit_per_user, 0.01)
_cutover_proxy_model = _cutover_traffic_config.get("proxy_model", "gpt-4o-mini")
_cutover_eval_timeout = float(
    _cutover_traffic_config.get("eval_timeout_seconds", 120) or 120
)


class CutoverPathUser(HttpUser):
    """Hit ECS cutover paths with authenticated eval/proxy traffic.

    Inspired by evaltest: creates/loads a project, then posts small inline-data
    evals and a cheap proxy chat completion. Useful while flipping
    EnableEcsApi / UseECSForApiTraffic.
    """

    fixed_count = _cutover_peak_concurrency
    wait_time = constant_pacing(_cutover_pacing_seconds)

    def on_start(self):
        self.headers = {
            "Authorization": f"Bearer {os.getenv('BRAINTRUST_API_KEY')}",
            "Content-Type": "application/json",
        }
        self.project_id = None
        if self.fixed_count <= 0:
            return
        try:
            response = http_client(
                "POST",
                f"{config['braintrust']['api_url']}/v1/project",
                payload={
                    "name": config["braintrust"]["project_name"],
                    "description": "Project for cutover-path load traffic",
                },
                headers=self.headers,
            )
            self.project_id = response.json().get("id")
        except requests.exceptions.RequestException:
            self.project_id = None

    def _eval_payload(self) -> dict:
        return {
            "project_id": self.project_id,
            "data": {
                "data": [
                    {
                        "input": fake.sentence(),
                        "expected": fake.sentence(),
                    }
                ]
            },
            # Reuse autoevals globals the same way proxy function tests do.
            "task": {"global_function": "Levenshtein"},
            "scores": [{"global_function": "ExactMatch"}],
            "stream": False,
            "parent": "",
            "experiment_name": f"loadtest-cutover-{fake.uuid4()[:8]}",
            "max_concurrency": 1,
            "trial_count": 1,
        }

    def _post_cutover_path(self, path: str, payload: dict, name: str, timeout: float):
        with self.client.post(
            path,
            json=payload,
            headers=self.headers,
            name=name,
            timeout=timeout,
            catch_response=True,
        ) as response:
            # 2xx/4xx still prove routing + auth; 5xx/0 are cutover failures.
            if response.status_code == 0 or response.status_code >= 500:
                response.failure(
                    f"{name} returned {response.status_code}: {response.text[:200]}"
                )
            else:
                response.success()

    @task(1)
    def post_v1_eval(self):
        if not self.project_id:
            return
        self._post_cutover_path(
            "/v1/eval",
            self._eval_payload(),
            "cutover_v1_eval",
            _cutover_eval_timeout,
        )

    @task(1)
    def post_function_eval(self):
        if not self.project_id:
            return
        self._post_cutover_path(
            "/function/eval",
            self._eval_payload(),
            "cutover_function_eval",
            _cutover_eval_timeout,
        )

    # Weight proxy higher: it is fast, so constant_pacing can actually fire near
    # calls_per_min. Slow evals would otherwise dominate the interval and hide blips.
    @task(8)
    def post_proxy_chat_completions(self):
        payload = {
            "model": _cutover_proxy_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with the single word pong.",
                }
            ],
            "max_tokens": 5,
            "stream": False,
        }
        self._post_cutover_path(
            "/v1/proxy/chat/completions",
            payload,
            "cutover_proxy_chat_completions",
            60,
        )
