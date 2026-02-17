import os
from braintrust import init_logger, init_dataset, Eval
from autoevals import Levenshtein, ExactMatch
from dotenv import load_dotenv
import yaml
from faker import Faker
import random
from util import http_client

fake = Faker()


def load_config() -> dict:
    load_dotenv()
    with open("./braintest.yaml", "r") as f:
        config = yaml.safe_load(f)

    return config


config = load_config()


def create_project() -> str:
    api_url = config["braintrust"]["api_url"]
    payload = {
        "name": config["braintrust"]["project_name"],
        "description": "Project for testing a large eval"
    }
    headers = {
        "Authorization": f"Bearer {os.getenv("BRAINTRUST_API_KEY")}",
        "Content-Type": "application/json",
    }
    
    try:
        response = http_client(
            "post", url=f"{api_url}/v1/project", payload=payload, headers=headers
        )
        print(f"Project {response.json().get("name")} created successfully")
    except Exception as e:
        print(f"Fatal error while creating project: {e}")
        exit(1)

    return response.json()


def initialize_dataset() -> dict:
    print("Creating dataset")
    print("=" * 50)
    api_url = config["braintrust"]["api_url"]
    project_id = config["evaltest"]["project_id"]
    dataset_config = config["evaltest"]["dataset"]

    payload = {
        "project_id": project_id,
        "name": f"{config["evaltest"].get("name")}-dataset",
        "description": dataset_config.get("description"),
    }
    headers = {
        "Authorization": f"Bearer {os.getenv("BRAINTRUST_API_KEY")}",
        "Content-Type": "application/json",
    }
    try:
        response = http_client(
            "post", url=f"{api_url}/v1/dataset", payload=payload, headers=headers
        )
    except Exception as e:
        print(f"Fatal error while creating dataset: {e}")
        exit(1)

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


def insert_events(dataset_id: str, events: list):
    print(f"Inserting batch of {len(events)} events to dataset")

    api_url = config["braintrust"]["api_url"]

    payload = {"events": events}
    headers = {
        "Authorization": f"Bearer {os.getenv("BRAINTRUST_API_KEY")}",
        "Content-Type": "application/json",
    }
    try:
        response = http_client(
            method="post",
            url=f"{api_url}/v1/dataset/{dataset_id}/insert",
            payload=payload,
            headers=headers,
        )
    except Exception as e:
        print(f"Fatal error: {e}")
        exit(1)


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


def run():

    if config["evaltest"].get("project_id") == None:
        print("No project provided, one will be created")
        project_details = create_project()
        config["evaltest"]["project_id"] = project_details["id"]

    dataset = initialize_dataset()

    dataset_size = config["evaltest"]["dataset"]["size"]
    flush_batch_size = config["evaltest"]["dataset"]["flush_batch_size"]
    event_queue = []

    # Insert mock events into dataset
    for _ in range(dataset_size):
        mock_event = generate_event()
        event_queue.append(mock_event)
        if len(event_queue) == flush_batch_size:
            insert_events(dataset_id=dataset["id"], events=event_queue)
            event_queue.clear()
    if len(event_queue) > 0:
        insert_events(dataset_id=dataset["id"], events=event_queue)
        event_queue.clear()

    # Execute eval on this dataset
    print(f"Executing an eval on this dataset")
    print("=" * 50)
    Eval(
        f"{config["evaltest"]["name"]}-eval",
        project_id=config["evaltest"]["project_id"],
        data=init_dataset(project_id=dataset["project_id"], name=dataset["name"]),
        task=mock_task,
        scores=[summary_levenshtein, sentiment_exact_match],
        trial_count=config["evaltest"]["trial_count"]
    )


if __name__ == "__main__":
    run()
