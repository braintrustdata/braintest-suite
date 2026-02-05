from locust import HttpUser, task, between
import requests
import os
import random
from mock_default_task import mock_answer_question

class BraintrustUser(HttpUser):

    wait_time = between(1, 5)

    def on_start(self):
        requests.Session = lambda: self.client
        from braintrust import init_logger

        logger = init_logger(
            project=os.getenv("BRAINTRUST_PROJECT_NAME") or "load-testing-project",
            async_flush=False,
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
