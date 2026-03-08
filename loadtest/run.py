from locust import HttpUser, task, between, events
import requests
import os
import random
import time
import yaml
from faker import Faker
from requests.adapters import HTTPAdapter
from loadtest.mock_conversation_task import mock_multiturn_conversation
from dotenv import load_dotenv


load_dotenv()

fake = Faker()


def load_config():
    with open("./braintest.yaml", "r") as f:
        config = yaml.safe_load(f)
    return config


config = load_config()
_LOGGER_INITIALIZED = False


@events.test_start.add_listener
def _init_braintrust_logger(environment, **kwargs):
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    # In distributed mode, only workers execute user tasks.
    # Skip logger init on master to avoid unnecessary setup.
    if environment.runner and environment.runner.__class__.__name__ == "MasterRunner":
        return

    from braintrust import init_logger, set_http_adapter

    project = config["braintrust"]["project_name"]
    pool_maxsize = config["loadtest"]["connection_pool_size"]
    set_http_adapter(HTTPAdapter(pool_maxsize=pool_maxsize))
    init_logger(
        project=project,
        async_flush=True,
        api_key=os.getenv("BRAINTRUST_API_KEY"),
    )
    _LOGGER_INITIALIZED = True


@events.test_stop.add_listener
def _flush_braintrust_logger(environment, **kwargs):
    if not _LOGGER_INITIALIZED:
        return
    if environment.runner and environment.runner.__class__.__name__ == "MasterRunner":
        return
    from braintrust import flush
    flush()


class BraintrustUser(HttpUser):
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
        start = time.perf_counter()
        exc = None
        response = None
        try:
            response = mock_multiturn_conversation(query)
            return response
        except Exception as e:
            exc = e
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            response_length = (
                response.get("output_size", 0)
                if isinstance(response, dict)
                else len(str(response)) if response is not None else 0
            )
            events.request.fire(
                request_type="POST",
                name="log",
                response_time=elapsed_ms,
                response_length=response_length,
                exception=exc,
                context={},
            )
