import os
from braintrust import init_dataset, Eval
from autoevals import Levenshtein, ExactMatch
from faker import Faker
import random

fake = Faker()


def create_project(config: dict) -> dict:
    from braintest_suite.util import http_client

    api_url = config["braintrust"]["api_url"]
    payload = {
        "name": config["braintrust"]["project_name"],
        "description": "Project for testing a large eval",
    }
    headers = {
        "Authorization": f"Bearer {os.getenv('BRAINTRUST_API_KEY')}",
        "Content-Type": "application/json",
    }

    response = http_client(
        "post", url=f"{api_url}/v1/project", payload=payload, headers=headers
    )
    print(f"Project {response.json().get('name')} created/loaded successfully")
    return response.json()


def initialize_dataset(config: dict) -> dict:
    from braintest_suite.util import http_client

    print(
        "Creating dataset. If dataset already exists, new rows will be appended to existing one."
    )
    api_url = config["braintrust"]["api_url"]
    project_id = config["evaltest"]["project_id"]
    dataset_config = config["evaltest"]["dataset"]

    payload = {
        "project_id": project_id,
        "name": f"{config['evaltest'].get('name')}-dataset",
        "description": dataset_config.get("description"),
    }
    headers = {
        "Authorization": f"Bearer {os.getenv('BRAINTRUST_API_KEY')}",
        "Content-Type": "application/json",
    }

    response = http_client(
        "post", url=f"{api_url}/v1/dataset", payload=payload, headers=headers
    )
    return response.json()


def generate_event():
    return {
        "input": {
            "name": fake.name(),
            "address": fake.address(),
            "message": fake.paragraph(nb_sentences=random.randint(1, 10)),
        },
        "expected": {
            "sentiment": fake.word(ext_word_list=["postive", "negative", "neutral"]),
            "summary": fake.paragraph(nb_sentences=random.randint(1, 3)),
        },
        "metadata": {
            "model": fake.word(
                ext_word_list=["sonnet-4", "sonnet-5", "gpt-4", "gpt-5"]
            ),
            "tokens": random.randint(100, 10000),
        },
    }


def insert_events(config: dict, dataset_id: str, events: list):
    from braintest_suite.util import http_client

    print(f"Inserting batch of {len(events)} events to dataset")

    api_url = config["braintrust"]["api_url"]

    payload = {"events": events}
    headers = {
        "Authorization": f"Bearer {os.getenv('BRAINTRUST_API_KEY')}",
        "Content-Type": "application/json",
    }

    http_client(
        method="post",
        url=f"{api_url}/v1/dataset/{dataset_id}/insert",
        payload=payload,
        headers=headers,
    )


def mock_task(input: dict) -> dict:
    return {
        "sentiment": fake.word(ext_word_list=["postive", "negative", "neutral"]),
        "summary": fake.paragraph(nb_sentences=random.randint(1, 3)),
    }


def summary_levenshtein(input, output: dict, expected: dict):
    scorer = Levenshtein()
    return scorer.eval(output=output.get("summary"), expected=expected.get("summary"))


def sentiment_exact_match(input, output: dict, expected: dict):
    scorer = ExactMatch()
    return scorer.eval(
        output=output.get("sentiment"), expected=expected.get("sentiment")
    )


def run(config: dict | None = None) -> bool:
    if config is None:
        from dotenv import load_dotenv
        from braintest_suite.config import load_config

        load_dotenv()
        config = load_config()

    try:
        if config["evaltest"].get("project_id") is None:
            print("No project provided, one will be created")
            project_details = create_project(config)
            config["evaltest"]["project_id"] = project_details["id"]

        dataset = initialize_dataset(config)

        dataset_size = config["evaltest"]["dataset"]["size"]
        flush_batch_size = config["evaltest"]["dataset"]["flush_batch_size"]
        event_queue = []

        for _ in range(dataset_size):
            mock_event = generate_event()
            event_queue.append(mock_event)
            if len(event_queue) == flush_batch_size:
                insert_events(config, dataset_id=dataset["id"], events=event_queue)
                event_queue.clear()
        if len(event_queue) > 0:
            insert_events(config, dataset_id=dataset["id"], events=event_queue)
            event_queue.clear()

        Eval(
            f"{config['evaltest']['name']}-eval",
            project_id=config["evaltest"]["project_id"],
            data=init_dataset(project_id=dataset["project_id"], name=dataset["name"]),
            task=mock_task,
            scores=[summary_levenshtein, sentiment_exact_match],
            trial_count=config["evaltest"]["trial_count"],
        )
        return True
    except Exception as e:
        print(f"Evaltest failed: {e}")
        return False


if __name__ == "__main__":
    success = run()
    raise SystemExit(0 if success else 1)
