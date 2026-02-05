from locust import HttpUser, task, between
import requests
import os
import random
import yaml
from mock_default_task import mock_answer_question
from dotenv import load_dotenv


load_dotenv()
def load_config():
    with open("./braintest.yaml", "r") as f:
        config = yaml.safe_load(f)
    return config

config = load_config()
print(config)

class BraintrustUser(HttpUser):
    min_wait = config["loadtest"]["params"]["wait_time"]["min"]
    max_wait = config["loadtest"]["params"]["wait_time"]["max"]
    wait_time = between(min_wait, max_wait)

    def on_start(self):
        requests.Session = lambda: self.client # Monkey patch request.Session to locust client's. BT SDK uses requests under the hood
        from braintrust import init_logger

        project = config["braintrust"]["project_name"]
        logger = init_logger(
            project=project,
            async_flush=False,
            api_key=os.getenv("BRAINTRUST_API_KEY")
        )
        self.logger = logger

    @task
    def ask_question(self):
        from faker import Faker
        fake = Faker()

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

        response = mock_answer_question(query)
