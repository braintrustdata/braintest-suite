import json
import os
import time
from pathlib import Path

from braintest_suite.util import http_client

ONLINE_RULE_NAME = "async-scorer-loadtest"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixture.json"
_ROW_WAIT_SECONDS = 120


def prepare(config: dict) -> Path:
    api_key = os.getenv("BRAINTRUST_API_KEY")
    if not api_key:
        raise RuntimeError("BRAINTRUST_API_KEY is required")

    api_url = config["braintrust"]["api_url"].rstrip("/")
    settings = config["asyncscorer"]
    project_name = settings["project_name"]
    flush_batch_size = int(settings["flush_batch_size"])
    scorers = _scorer_names(settings["scorers"])
    if flush_batch_size < 1:
        raise RuntimeError("asyncscorer.flush_batch_size must be >= 1")

    os.environ["BRAINTRUST_API_URL"] = api_url
    os.environ["BRAINTRUST_SYNC_FLUSH"] = "1"
    os.environ["BRAINTRUST_DEFAULT_BATCH_SIZE"] = str(flush_batch_size)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    import braintrust

    logger = braintrust.init_logger(
        project=project_name,
        async_flush=False,
        api_key=api_key,
    )
    project_id = logger.project.id
    print(f"Project {project_name} ({project_id})")

    _ensure_online_scorers(
        api_url=api_url,
        headers=headers,
        project_id=project_id,
        scorers=scorers,
    )

    print("Logging 1 root span to confirm the online scorer stamps a token")
    with logger.start_span(name="root") as span:
        span.log(input="foo", output="bar", expected="bar")
    braintrust.flush()
    _wait_for_scored_row(api_url=api_url, headers=headers, project_id=project_id)

    fixture = {
        "api_url": api_url,
        "project_id": project_id,
        "project_name": project_name,
        "flush_batch_size": flush_batch_size,
    }
    FIXTURE_PATH.write_text(json.dumps(fixture))
    print(f"Wrote fixture to {FIXTURE_PATH}")
    return FIXTURE_PATH


def _scorer_names(raw: object) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("asyncscorer.scorers must be a non-empty list")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise RuntimeError("asyncscorer.scorers entries must be non-empty strings")
        if item not in names:
            names.append(item)
    return names


def _ensure_online_scorers(
    api_url: str,
    headers: dict[str, str],
    project_id: str,
    scorers: list[str],
) -> None:
    response = http_client(
        "GET",
        f"{api_url}/v1/project_score?project_id={project_id}",
        headers=headers,
    )
    body = response.json()
    objects = body.get("objects") if isinstance(body, dict) else None
    if not isinstance(objects, list):
        raise RuntimeError(f"Unexpected project_score list response: {type(body).__name__}")

    existing = next(
        (
            score
            for score in objects
            if isinstance(score, dict) and score.get("name") == ONLINE_RULE_NAME and _same_project(score, project_id)
        ),
        None,
    )
    if existing is None:
        print(f"Creating online scorer rule {ONLINE_RULE_NAME} for {', '.join(scorers)}")
        http_client(
            "POST",
            f"{api_url}/v1/project_score",
            payload={
                "project_id": project_id,
                "name": ONLINE_RULE_NAME,
                "score_type": "online",
                "config": {
                    "online": {
                        "sampling_rate": 1,
                        "apply_to_root_span": True,
                        "scorers": [
                            {
                                "type": "global",
                                "name": name,
                                "function_type": "scorer",
                            }
                            for name in scorers
                        ],
                    }
                },
            },
            headers=headers,
        )
        return

    existing_names = _configured_scorer_names(existing)
    if existing_names != scorers:
        raise RuntimeError(
            f"Project already has {ONLINE_RULE_NAME} with scorers {existing_names}. "
            f"Config asked for {scorers}. Delete that rule or match asyncscorer.scorers."
        )
    print(f"Using existing online scorer rule {ONLINE_RULE_NAME}")


def _same_project(score: dict, project_id: str) -> bool:
    owner = score.get("project_id")
    return not isinstance(owner, str) or owner == project_id


def _configured_scorer_names(score: dict) -> list[str]:
    config = score.get("config")
    if not isinstance(config, dict):
        return []
    online = config.get("online")
    if not isinstance(online, dict):
        return []
    scorers = online.get("scorers")
    if not isinstance(scorers, list):
        return []
    names: list[str] = []
    for scorer in scorers:
        if isinstance(scorer, dict) and isinstance(scorer.get("name"), str):
            names.append(scorer["name"])
    return names


def _wait_for_scored_row(api_url: str, headers: dict[str, str], project_id: str) -> None:
    query = (
        "select: id, _async_scoring_state "
        f"| from: project_logs('{project_id}') spans "
        "| filter: is_root = true "
        "| sort: created desc "
        "| limit: 20"
    )
    deadline = time.monotonic() + _ROW_WAIT_SECONDS
    while True:
        response = http_client(
            "POST",
            f"{api_url}/btql",
            payload={"query": query, "fmt": "json"},
            headers=headers,
        )
        body = response.json()
        events = body.get("data") if isinstance(body, dict) else None
        if isinstance(events, list) and any(_has_scoring_token(event) for event in events):
            print("Online scorer stamped a token on a root span")
            return
        if time.monotonic() >= deadline:
            break
        print("Waiting for a root span with an async scoring token")
        time.sleep(2)

    raise RuntimeError(
        "Timed out waiting for a root span with an async scoring token. "
        "The online scorer has to exist before the span is logged, "
        "and the span has to be queryable in brainstore."
    )


def _has_scoring_token(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    state = event.get("_async_scoring_state")
    if not isinstance(state, dict):
        return False
    token = state.get("token")
    return isinstance(token, str) and bool(token)
