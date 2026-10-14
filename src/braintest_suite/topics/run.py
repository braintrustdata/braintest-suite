#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Create a tiny disposable Braintrust project for Topics smoke testing.

This script discovers the dataplane API URL from the API key when possible,
creates a fresh timestamped project, enables a minimal Topics automation,
inserts enough traces to cross the Topics generation threshold, and queues the
automation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

APP_URL = "https://www.braintrust.dev"
DEFAULT_COUNT = 105
MIN_TOPIC_SUMMARIES = 100
DEFAULT_FACET = "Task"
AUTOMATION_NAME = "Topics smoke"
TOPIC_MAP_EMBEDDING_MODEL = "brain-embedding-1"
DEFAULT_PROJECT_PREFIX = "topics-smoke"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RUNNING_CHECK_TIMEOUT_SECONDS = 90
DEFAULT_RUNNING_CHECK_INTERVAL_SECONDS = 5
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 30
DEFAULT_FUNCTION_VISIBILITY_TIMEOUT_SECONDS = 60
DEFAULT_FUNCTION_VISIBILITY_INTERVAL_SECONDS = 2
DEFAULT_COMPACTION_TIMEOUT_SECONDS = 300
DEFAULT_COMPACTION_INTERVAL_SECONDS = 5
DEFAULT_AUTOMATION_EXECUTION_TIMEOUT_SECONDS = 30
DEFAULT_CLASSIFICATION_TIMEOUT_SECONDS = 900
DEFAULT_CLASSIFICATION_INTERVAL_SECONDS = 5
TOPIC_AUTOMATION_EXECUTION_PASSES = 2
TOPIC_AUTOMATION_MAX_CONCURRENCY = 10
PREFLIGHT_MAX_ATTEMPTS = 3
PREFLIGHT_RETRY_SECONDS = 2


class SmokeError(Exception):
    """Raised for expected user-facing failures."""


@dataclass(frozen=True)
class AuthContext:
    api_key: str
    org_id: str
    org_name: str
    api_url: str


@dataclass(frozen=True)
class Project:
    id: str
    name: str


def json_request(
    method: str,
    url: str,
    *,
    api_key: str | None = None,
    body: Any | None = None,
    org_name: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "User-Agent": "braintrust-topics-smoke/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if org_name:
        headers["x-bt-org-name"] = org_name
    if extra_headers:
        headers.update(extra_headers)

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise SmokeError(f"{method} {url} failed with HTTP {exc.code}: {error_text}") from exc
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise SmokeError(f"{method} {url} failed: {reason}") from exc

    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{method} {url} returned non-JSON response: {text[:500]}") from exc


def require_api_key(args: argparse.Namespace) -> str:
    api_key = args.api_key or os.environ.get("BRAINTRUST_API_KEY")
    if not api_key:
        raise SmokeError("BRAINTRUST_API_KEY is required")
    return api_key


def discover_auth(args: argparse.Namespace) -> AuthContext:
    api_key = require_api_key(args)
    requested_org = args.org or os.environ.get("TOPICS__ORG")
    forced_api_url = args.api_url or os.environ.get("BRAINTRUST__API_URL")

    org_info: list[dict[str, Any]] = []
    discovery_error: SmokeError | None = None
    try:
        login = json_request(
            "POST",
            f"{APP_URL}/api/apikey/login",
            api_key=api_key,
            timeout=args.timeout,
        )
        org_info = list(login.get("org_info") or [])
    except SmokeError as exc:
        discovery_error = exc

    selected = select_org(org_info, requested_org) if org_info else None

    if selected is None and discovery_error and not (forced_api_url and requested_org):
        raise SmokeError(
            "Could not discover org/api_url from the API key. Set topics.org and braintrust.api_url "
            "or TOPICS__ORG and BRAINTRUST__API_URL.\n"
            f"Discovery error: {discovery_error}"
        )

    if selected is None:
        selected = {
            "id": "",
            "name": requested_org,
            "api_url": forced_api_url,
        }

    api_url = (forced_api_url or selected.get("api_url") or "").rstrip("/")
    org_name = selected.get("name") or requested_org
    if not org_name:
        raise SmokeError("Could not determine org. Set topics.org or TOPICS__ORG.")
    if not api_url:
        raise SmokeError("Could not determine API URL. Set braintrust.api_url or BRAINTRUST__API_URL.")

    return AuthContext(
        api_key=api_key,
        org_id=str(selected.get("id") or ""),
        org_name=str(org_name),
        api_url=api_url,
    )


def select_org(org_info: list[dict[str, Any]], requested_org: str | None) -> dict[str, Any] | None:
    if not org_info:
        return None
    if requested_org:
        for org in org_info:
            if org.get("name") == requested_org:
                return org
        names = ", ".join(str(org.get("name")) for org in org_info)
        raise SmokeError(f"Organization {requested_org!r} was not found. Must be one of: {names}")
    if len(org_info) == 1:
        return org_info[0]
    names = ", ".join(str(org.get("name")) for org in org_info)
    raise SmokeError(
        f"API key belongs to multiple organizations. Set topics.org or TOPICS__ORG. Available orgs: {names}"
    )


def api_url(ctx: AuthContext, path: str, query: dict[str, str] | None = None) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    url = f"{ctx.api_url}{suffix}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def app_project_topics_url(org_name: str, project_name: str) -> str:
    return f"{APP_URL}/app/{quote(org_name, safe='')}/p/{quote(project_name, safe='')}/topics"


def terminal_hyperlink(label: str, url: str) -> str:
    return f"\033]8;;{url}\a{label}\033]8;;\a ({url})"


def api_get(ctx: AuthContext, path: str, query: dict[str, str] | None = None) -> Any:
    return json_request(
        "GET",
        api_url(ctx, path, query),
        api_key=ctx.api_key,
        org_name=ctx.org_name,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


def api_post(
    ctx: AuthContext,
    path: str,
    body: Any,
    *,
    extra_headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    return json_request(
        "POST",
        api_url(ctx, path),
        api_key=ctx.api_key,
        org_name=ctx.org_name,
        body=body,
        extra_headers=extra_headers,
        timeout=timeout,
    )


def preflight_api_post(
    ctx: AuthContext,
    path: str,
    body: Any,
    *,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    """Retry transient gateway failures for the small preflight requests."""
    for attempt in range(1, PREFLIGHT_MAX_ATTEMPTS + 1):
        try:
            return api_post(ctx, path, body, extra_headers=extra_headers)
        except SmokeError as exc:
            message = str(exc)
            transient = any(code in message for code in ("HTTP 502", "HTTP 503", "HTTP 504", "timed out"))
            if not transient or attempt == PREFLIGHT_MAX_ATTEMPTS:
                raise
            print(f"Preflight request failed transiently; retrying ({attempt}/{PREFLIGHT_MAX_ATTEMPTS})")
            time.sleep(PREFLIGHT_RETRY_SECONDS)
    raise AssertionError("unreachable")


def create_project(ctx: AuthContext, name: str) -> Project:
    response = api_post(ctx, "/v1/project", {"name": name, "org_name": ctx.org_name})
    return Project(id=str(response["id"]), name=str(response["name"]))


def get_project_by_name(ctx: AuthContext, name: str) -> Project | None:
    response = api_get(
        ctx,
        "/v1/project",
        {"org_name": ctx.org_name, "project_name": name},
    )
    objects = response.get("objects") or []
    if not objects:
        return None
    return Project(id=str(objects[0]["id"]), name=str(objects[0]["name"]))


def create_fresh_project(ctx: AuthContext, base_name: str) -> Project:
    for attempt in range(5):
        name = base_name if attempt == 0 else f"{base_name}-{attempt + 1}"
        existing = get_project_by_name(ctx, name)
        if existing is None:
            return create_project(ctx, name)
    raise SmokeError(f"Could not find an unused project name based on {base_name!r}")


def list_topic_automations(ctx: AuthContext, project_id: str) -> list[dict[str, Any]]:
    response = api_post(ctx, "/api/project_automation/get", {"project_id": project_id})
    rows = response if isinstance(response, list) else response.get("objects") or []
    return [row for row in rows if isinstance(row.get("config"), dict) and row["config"].get("event_type") == "topic"]


def create_topic_function_refs(
    ctx: AuthContext,
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    facet_function = {"type": "global", "name": DEFAULT_FACET, "function_type": "facet"}
    topic_map_function = create_topic_map_function(ctx, project_id, facet_function)
    return facet_function, topic_map_function


def register_topics_automation(
    ctx: AuthContext,
    project: Project,
    args: argparse.Namespace,
    *,
    facet_function: dict[str, Any],
    topic_map_function: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "project_automation_name": AUTOMATION_NAME,
        "description": "Minimal disposable Topics smoke-test automation",
        "project_id": project.id,
        "config": {
            "event_type": "topic",
            "sampling_rate": 1.0,
            "facet_functions": [facet_function],
            "topic_map_functions": [topic_map_function],
            "scope": {"type": "trace", "idle_seconds": args.idle_seconds},
            "rerun_seconds": args.generation_cadence_seconds,
            "backfill_time_range": format_duration_seconds(args.topic_window_seconds),
        },
        "update": False,
    }
    response = api_post(ctx, "/api/project_automation/register", body)
    automation = response.get("project_automation") or response
    seed_topic_automation_cursors(ctx, project.id, automation, args.topic_window_seconds)
    return automation


def create_topic_map_function(
    ctx: AuthContext,
    project_id: str,
    facet_function: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "functions": [
            {
                "project_id": project_id,
                "name": DEFAULT_FACET,
                "slug": slugify_topic_map_name(f"{DEFAULT_FACET}-topic-map"),
                "function_type": "classifier",
                "function_data": {
                    "type": "topic_map",
                    "source_facet": DEFAULT_FACET,
                    "source_facet_function": facet_function,
                    "embedding_model": TOPIC_MAP_EMBEDDING_MODEL,
                },
                "if_exists": "ignore",
            }
        ]
    }
    response = api_post(ctx, "/insert-functions", body)
    functions = response.get("functions") or []
    if len(functions) != 1:
        raise SmokeError("Failed to create the topic map function")
    # Topic generation creates new versions of these functions. Keep the
    # automation reference unversioned so classification resolves the newly
    # generated current version rather than the empty bootstrap version.
    return {"function": {"type": "function", "id": str(functions[0]["id"])}}


def saved_function_ref_to_use_body(function_ref: dict[str, Any]) -> dict[str, Any]:
    if function_ref.get("type") == "function":
        function_id = function_ref.get("id")
        if not function_id:
            raise SmokeError("saved function reference is missing id")
        body = {"function_id": str(function_id)}
        if function_ref.get("version") is not None:
            body["version"] = str(function_ref["version"])
        return body
    if function_ref.get("type") == "global":
        name = function_ref.get("name")
        if not name:
            raise SmokeError("global function reference is missing name")
        return {
            "global_function": str(name),
            "function_type": function_ref.get("function_type") or "scorer",
        }
    raise SmokeError(f"unsupported saved function reference: {function_ref!r}")


def verify_function_refs_resolve(
    ctx: AuthContext,
    project_id: str,
    facet_function: dict[str, Any],
    topic_map_function: dict[str, Any],
    *,
    timeout_seconds: int,
    interval_seconds: int,
) -> None:
    refs = [
        ("facet", facet_function, "facet"),
        ("topic map", topic_map_function["function"], "topic_map"),
    ]

    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while True:
        try:
            for label, ref, expected_type in refs:
                resolved = api_post(
                    ctx,
                    "/function/use",
                    saved_function_ref_to_use_body(ref),
                    extra_headers={"x-bt-project-id": project_id},
                )
                function_data = resolved.get("function_data") if isinstance(resolved, dict) else None
                actual_type = function_data.get("type") if isinstance(function_data, dict) else None
                if actual_type != expected_type:
                    raise SmokeError(
                        f"/function/use resolved {label} {saved_function_ref_key(ref)!r} "
                        f"as function_data.type={actual_type!r}, expected {expected_type!r}"
                    )
            print(f"Verified /function/use visibility for {len(refs)} saved function reference(s)")
            return
        except SmokeError as exc:
            last_error = str(exc)
            if time.monotonic() >= deadline:
                raise SmokeError(
                    "Saved function references did not become visible through /function/use "
                    f"within {timeout_seconds}s for project {project_id}. Last error: {last_error}"
                ) from exc
            time.sleep(interval_seconds)


def seed_topic_automation_cursors(
    ctx: AuthContext,
    project_id: str,
    automation: dict[str, Any],
    window_seconds: int,
) -> None:
    automation_id = str(automation["id"])
    config = automation.get("config") or {}
    object_id = topic_automation_object_id(project_id, config.get("data_scope"))
    start_xact_id = inclusive_start_xact_id_from_epoch_ms(int(time.time() * 1000) - window_seconds * 1000)
    api_post(
        ctx,
        "/brainstore/automation/reset-cursors",
        {
            "automation_id": automation_id,
            "object_id": object_id,
            "start_xact_id": start_xact_id,
        },
    )
    poke_topic_automation(ctx, automation_id, object_id)


def poke_topic_automation(ctx: AuthContext, automation_id: str, object_id: str) -> None:
    api_post(
        ctx,
        "/brainstore/automation/upsert-object-cursor",
        {"automation_id": automation_id, "object_id": object_id},
    )


def reset_topic_automation_cursor(
    ctx: AuthContext,
    automation_id: str,
    object_id: str,
    start_xact_id: str,
) -> None:
    api_post(
        ctx,
        "/brainstore/automation/reset-cursors",
        {
            "automation_id": automation_id,
            "object_id": object_id,
            "start_xact_id": start_xact_id,
        },
    )


def start_topic_classification_backfill(
    ctx: AuthContext,
    project: Project,
    automation: dict[str, Any],
    start_xact_id: str,
) -> None:
    """Rewind and queue the original automation for generated-map backfill."""
    automation_id = str(automation["id"])
    object_id = topic_automation_object_id(
        project.id,
        (automation.get("config") or {}).get("data_scope"),
    )
    reset_topic_automation_cursor(ctx, automation_id, object_id, start_xact_id)
    try:
        poke_topic_automation(ctx, automation_id, object_id)
    except SmokeError as exc:
        if not is_transient_api_error(exc):
            raise
        print("Classification backfill was rewound; requeue will be retried while polling")


def is_transient_api_error(exc: SmokeError) -> bool:
    message = str(exc)
    return any(
        marker in message
        for marker in ("HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "timed out", "temporarily unavailable")
    )


def execute_topic_automation(
    ctx: AuthContext,
    project_id: str,
    automation: dict[str, Any],
    *,
    timeout_seconds: int = DEFAULT_AUTOMATION_EXECUTION_TIMEOUT_SECONDS,
) -> dict[str, int]:
    """Explicitly process the facet replay instead of waiting for the background worker."""
    totals = {"successful": 0, "failed": 0, "rows_matched": 0}
    for _ in range(TOPIC_AUTOMATION_EXECUTION_PASSES):
        try:
            response = api_post(
                ctx,
                "/brainstore/automation/execute",
                {
                    "automation_id": str(automation["id"]),
                    "project_id": project_id,
                    "max_concurrency": TOPIC_AUTOMATION_MAX_CONCURRENCY,
                },
                timeout=timeout_seconds,
            )
        except SmokeError as exc:
            message = str(exc)
            if "timed out" in message or "HTTP 504" in message:
                print("Topics execution is still running server-side; polling its results")
                break
            raise
        for key in totals:
            totals[key] += read_count(response, key)
    if totals["failed"]:
        raise SmokeError(f"Topics automation execution reported failures: {totals}")
    return totals


def wait_for_trace_idle(inserted_at: float, idle_seconds: int) -> None:
    """Wait until newly ingested traces are eligible for trace-scoped automation."""
    remaining = idle_seconds + 1 - (time.monotonic() - inserted_at)
    if remaining <= 0:
        return
    print(f"Waiting {remaining:.1f}s for inserted traces to pass the Topics idle window")
    time.sleep(remaining)


def insert_smoke_traces(ctx: AuthContext, project: Project, events: list[dict[str, Any]]) -> Any:
    return api_post(ctx, f"/v1/project_logs/{quote(project.id, safe='')}/insert", {"events": events})


def wait_for_compacted_traces(
    ctx: AuthContext,
    project: Project,
    run_id: str,
    expected: int,
    *,
    timeout_seconds: int,
    interval_seconds: int,
) -> None:
    """Wait until replay can see every synthetic trace in compacted Brainstore data."""
    deadline = time.monotonic() + timeout_seconds
    last_count = 0
    last_error: SmokeError | None = None
    query = (
        f"from: project_logs('{escape_btql_literal(project.id)}') spans | "
        "measures: count(1) as count | "
        f"filter: metadata.run_id = '{escape_btql_literal(run_id)}'"
    )
    print(f"Waiting for {expected} synthetic trace(s) to become replayable...")
    while True:
        try:
            response = api_post(
                ctx,
                "/btql",
                {
                    "query": query,
                    "fmt": "json",
                    "use_brainstore": True,
                    "brainstore_realtime": False,
                    "brainstore_ephemeral_wal": False,
                    "use_columnstore": True,
                    "api_version": 1,
                    "query_source": "topics-smoke-compaction-check",
                },
            )
            row = (response.get("data") or [{}])[0]
            count = read_count(row, "count")
            if count != last_count:
                print(f"Compacted synthetic traces: {count}/{expected}")
            last_count = count
            last_error = None
            if count >= expected:
                return
        except SmokeError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            error_note = f" Last query error: {last_error}" if last_error else ""
            raise SmokeError(
                f"Timed out waiting for synthetic traces to become replayable: {last_count}/{expected}.{error_note}"
            )
        time.sleep(interval_seconds)


def build_trace_events(count: int, *, project_name: str, run_id: str) -> list[dict[str, Any]]:
    now = time.time()
    events: list[dict[str, Any]] = []
    for index in range(count):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        variant = index // len(SCENARIOS)
        root_id = f"topics-smoke-{run_id}-{index:04d}"
        created = datetime.fromtimestamp(now - (count - index), UTC).isoformat()
        user_message = scenario["user"].format(n=variant + 1)
        assistant_message = scenario["assistant"].format(n=variant + 1)
        events.append(
            {
                "id": root_id,
                "span_id": root_id,
                "root_span_id": root_id,
                "created": created,
                "input": [{"role": "user", "content": user_message}],
                "output": [{"role": "assistant", "content": assistant_message}],
                "metadata": {
                    "source": "braintest_suite.topics",
                    "run_id": run_id,
                    "project_name": project_name,
                    "scenario": scenario["name"],
                    "variant": variant + 1,
                    "synthetic": True,
                },
                "tags": ["topics-smoke", scenario["name"]],
                "span_attributes": {
                    "name": f"Topics smoke chat: {scenario['title']}",
                    "type": "llm",
                },
                "metrics": {
                    "start": now - (count - index) - 0.25,
                    "end": now - (count - index),
                    "tokens": 120 + (index % 7),
                },
            }
        )
    return events


SCENARIOS = [
    {
        "name": "billing-refund",
        "title": "Billing refund",
        "user": "I was charged twice for my subscription invoice #{n}. Can you refund the duplicate charge?",
        "assistant": "I found the duplicate billing event and opened a refund request for invoice #{n}.",
    },
    {
        "name": "dataset-import",
        "title": "Dataset import",
        "user": "Help me import {n} CSV files into a Braintrust dataset and validate the columns.",
        "assistant": (
            "I created a dataset import checklist, validated the required columns, and flagged one malformed row."
        ),
    },
    {
        "name": "api-debugging",
        "title": "API debugging",
        "user": "My API request returns 401 when I run the eval job #{n}. What should I check?",
        "assistant": (
            "I checked the auth header, org selection, and project scope, then suggested rotating the API key."
        ),
    },
    {
        "name": "deployment-troubleshooting",
        "title": "Deployment troubleshooting",
        "user": "The self-hosted dataplane health check is failing after deploy attempt {n}.",
        "assistant": "I reviewed the service URL, Redis connectivity, and object-store settings for the dataplane.",
    },
    {
        "name": "feature-request",
        "title": "Feature request",
        "user": "Can Braintrust add a dashboard that groups support conversations by product area? Request {n}.",
        "assistant": (
            "I captured the product-area dashboard request and suggested using Topics classifications meanwhile."
        ),
    },
]


def run_create(args: argparse.Namespace) -> int:
    validate_args(args)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    project_name = timestamped_project_name(args.project_prefix, run_id)
    events = build_trace_events(args.count, project_name=project_name, run_id=run_id)

    if args.dry_run:
        auth_preview = preview_auth(args)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "app_url": APP_URL,
                    "org": auth_preview["org"],
                    "api_url": auth_preview["api_url"],
                    "project_name": project_name,
                    "trace_count": len(events),
                    "facet": DEFAULT_FACET,
                    "sample_event": events[0],
                    "note": auth_preview["note"],
                },
                indent=2,
            )
        )
        return 0

    ctx = discover_auth(args)
    print(f"App URL: {APP_URL}")
    print(f"Org: {ctx.org_name}")
    print(f"Dataplane API URL: {ctx.api_url}")
    project = create_fresh_project(ctx, project_name)
    print(f"Created project: {ctx.org_name} / {project.name} ({project.id})")

    existing = list_topic_automations(ctx, project.id)
    if existing:
        raise SmokeError(
            f"Project {project.name!r} already has {len(existing)} Topics automation(s); "
            "fresh smoke projects should start empty."
        )
    facet_function, topic_map_function = create_topic_function_refs(
        ctx,
        project.id,
    )
    print(f"Using built-in Topics facet: {DEFAULT_FACET}")
    print(f"Created topic map function: {topic_map_function['function']['id']}")
    verify_function_refs_resolve(
        ctx,
        project.id,
        facet_function,
        topic_map_function,
        timeout_seconds=args.function_visibility_timeout,
        interval_seconds=args.function_visibility_interval,
    )

    if args.skip_facet_preflight:
        insert_smoke_traces(ctx, project, events)
        print(f"Inserted {len(events)} synthetic trace(s)")
    else:
        insert_smoke_traces(ctx, project, events[:1])
        print("Inserted 1 synthetic preflight trace")
        preflight_topics_pipeline(
            ctx,
            project,
            events[0],
            args,
            facet_function,
        )
        remaining_events = events[1:]
        if remaining_events:
            insert_smoke_traces(ctx, project, remaining_events)
        print(f"Inserted {len(events)} synthetic trace(s)")
    inserted_at = time.monotonic()
    wait_for_compacted_traces(
        ctx,
        project,
        run_id,
        len(events),
        timeout_seconds=args.compaction_timeout,
        interval_seconds=args.compaction_interval,
    )

    automation = register_topics_automation(
        ctx,
        project,
        args,
        facet_function=facet_function,
        topic_map_function=topic_map_function,
    )
    print(f"Enabled Topics automation: {automation.get('name', 'Topics')} ({automation['id']})")
    wait_for_trace_idle(inserted_at, args.idle_seconds)
    execution = execute_topic_automation(
        ctx,
        project.id,
        automation,
        timeout_seconds=args.automation_execution_timeout,
    )
    print(
        "Executed queued Topics processing: "
        f"successful={execution['successful']} failed={execution['failed']} "
        f"rows_matched={execution['rows_matched']}"
    )
    if not args.skip_running_check:
        verify_expected_running(ctx, project, automation, args)
        topic_map_function_id = str(topic_map_function["function"]["id"])
        generated_version, classification_start_xact_id = wait_for_generated_topic_map(
            ctx,
            project,
            automation,
            topic_map_function_id,
            args,
        )
        print(f"Generated topic map version: {generated_version}")
        wait_for_compacted_facet_outputs(
            ctx,
            project,
            str(automation.get("name") or AUTOMATION_NAME),
            DEFAULT_FACET,
            min(args.count, MIN_TOPIC_SUMMARIES),
            timeout_seconds=args.classification_timeout,
            interval_seconds=args.classification_interval,
        )
        start_topic_classification_backfill(ctx, project, automation, classification_start_xact_id)
        wait_for_topic_classifications(ctx, project, automation, DEFAULT_FACET, args)
    print(f"Project name for status checks: {project.name}")
    topics_url = app_project_topics_url(ctx.org_name, project.name)
    print(f"Open Topics results: {terminal_hyperlink('Topics results', topics_url)}")
    return 0


def preview_auth(args: argparse.Namespace) -> dict[str, str | None]:
    if args.api_key or os.environ.get("BRAINTRUST_API_KEY"):
        try:
            ctx = discover_auth(args)
            return {
                "org": ctx.org_name,
                "api_url": ctx.api_url,
                "note": "No project, traces, or automations were created.",
            }
        except SmokeError as exc:
            return {
                "org": args.org or os.environ.get("TOPICS__ORG"),
                "api_url": args.api_url or os.environ.get("BRAINTRUST__API_URL"),
                "note": f"No project, traces, or automations were created. Discovery failed: {exc}",
            }
    return {
        "org": args.org or os.environ.get("TOPICS__ORG"),
        "api_url": args.api_url or os.environ.get("BRAINTRUST__API_URL"),
        "note": "No network calls were made because no API key was provided.",
    }


def run_status(args: argparse.Namespace) -> int:
    if not args.project:
        raise SmokeError("status requires a project name: braintest status topics <project-name>")
    ctx = discover_auth(args)
    project = get_project_by_name(ctx, args.project)
    if project is None:
        raise SmokeError(f"Project {args.project!r} was not found in org {ctx.org_name!r}")
    automations = list_topic_automations(ctx, project.id)
    summary: dict[str, Any] = {
        "org": ctx.org_name,
        "project": {"id": project.id, "name": project.name},
        "topics_url": app_project_topics_url(ctx.org_name, project.name),
        "automations": [],
    }
    for automation in automations:
        automation_id = str(automation["id"])
        object_id = topic_automation_object_id(project.id, (automation.get("config") or {}).get("data_scope"))
        object_cursor = api_post(
            ctx,
            "/brainstore/automation/get-object-cursors",
            {"automation_id": automation_id, "project_id": project.id},
        )
        facet_counts = get_topic_facet_status_counts(
            ctx,
            project.id,
            automation_id,
            DEFAULT_FACET,
            facet_function_key(automation),
        )
        segment_cursor = api_post(
            ctx,
            "/brainstore/automation/get-cursors",
            {"automation_id": automation_id, "project_id": project.id},
        )
        summary["automations"].append(
            {
                "id": automation_id,
                "facet_counts": facet_counts,
                "segment_cursor": segment_cursor,
                "name": automation.get("name", "Topics"),
                "object_id": object_id,
                "next_run_at": object_cursor.get("next_run_at"),
                "last_run_at": object_cursor.get("last_run_at"),
                "last_error": object_cursor.get("last_error"),
                "topic_runtime": object_cursor.get("topic_runtime"),
            }
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def preflight_topics_pipeline(
    ctx: AuthContext,
    project: Project,
    event: dict[str, Any],
    args: argparse.Namespace,
    facet_function: dict[str, Any],
) -> None:
    root_span_id = str(event["root_span_id"])
    saved_body = {
        "api_version": 1,
        "project_id": project.id,
        "org_name": ctx.org_name,
        **saved_function_ref_to_use_body(facet_function),
        "input": {
            "trace_ref": {
                "object_type": "project_logs",
                "object_id": project.id,
                "root_span_id": root_span_id,
            }
        },
        "stream": False,
        "timeout_ms": args.facet_preflight_timeout * 1000,
    }
    saved_response = preflight_api_post(ctx, "/function/invoke", saved_body)
    if saved_response is None:
        raise SmokeError(f"Saved facet preflight for {DEFAULT_FACET!r} returned no response")
    print(f"Saved facet preflight succeeded for {DEFAULT_FACET!r}")

    async_batch_response = preflight_api_post(
        ctx,
        "/function/invoke-async-batch",
        [{"request": saved_body}],
        extra_headers={"x-bt-use-gateway": "true"},
    )
    if not isinstance(async_batch_response, dict) or async_batch_response.get("failed", 0) != 0:
        raise SmokeError(
            f"Async-batch gateway preflight failed before bulk trace insert. Response: {async_batch_response!r}"
        )
    print(f"Async-batch saved-facet preflight succeeded for {DEFAULT_FACET!r}")


def verify_expected_running(
    ctx: AuthContext,
    project: Project,
    automation: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    expected = min(args.count, MIN_TOPIC_SUMMARIES)
    deadline = time.monotonic() + args.running_check_timeout
    last_counts: dict[str, int] | None = None
    function_key = facet_function_key(automation)
    print(f"Waiting for Topics facet {DEFAULT_FACET!r} to process {expected} trace(s)...")
    while True:
        counts = get_topic_facet_status_counts(
            ctx,
            project.id,
            str(automation["id"]),
            DEFAULT_FACET,
            function_key,
        )
        last_counts = counts
        running = counts["running"]
        errors = counts["errors"]
        processed = counts["processed"]
        matched = counts["matched"]
        print(f"Facet {DEFAULT_FACET}: matched={matched} processed={processed} running={running} errors={errors}")
        if errors == 0 and processed >= expected:
            print(f"Verified Topics processed count: {processed}")
            return
        if errors >= expected:
            raise SmokeError(
                f"Topics facet {DEFAULT_FACET!r} reported {errors} error(s), which is at or above "
                f"the expected {expected} trace(s). Last counts: {last_counts}"
            )
        if time.monotonic() >= deadline:
            error_note = f"; last reported errors={errors}" if errors > 0 else ""
            raise SmokeError(
                f"Timed out waiting for Topics facet {DEFAULT_FACET!r} to process {expected} "
                f"trace(s){error_note}. Last counts: {last_counts}"
            )
        execute_topic_automation(
            ctx,
            project.id,
            automation,
            timeout_seconds=args.automation_execution_timeout,
        )
        time.sleep(args.running_check_interval)


def get_topic_classification_count(
    ctx: AuthContext,
    project_id: str,
    facet: str,
    automation_name: str,
) -> int:
    """Count traces classified by the automation under test."""
    facet_path = quote_btql_path_piece(facet)
    query = (
        f"from: project_logs('{escape_btql_literal(project_id)}') spans | "
        f"measures: count(classifications.{facet_path}) as count | "
        f"filter: classifications.{facet_path} is not null "
        "AND span_attributes.type = 'automation' "
        f"AND name = '{escape_btql_literal(automation_name)}'"
    )
    response = api_post(
        ctx,
        "/btql",
        {
            "query": query,
            "fmt": "json",
            "use_brainstore": True,
            "api_version": 1,
            "query_source": "topics-smoke-classification-check",
        },
    )
    row = (response.get("data") or [{}])[0]
    return read_count(row, "count")


def wait_for_compacted_facet_outputs(
    ctx: AuthContext,
    project: Project,
    automation_name: str,
    facet: str,
    expected: int,
    *,
    timeout_seconds: int,
    interval_seconds: int,
) -> None:
    """Wait until classification replay can read the completed facet outputs."""
    deadline = time.monotonic() + timeout_seconds
    facet_path = quote_btql_path_piece(facet)
    query = (
        f"from: project_logs('{escape_btql_literal(project.id)}') spans | "
        f"measures: count(facets.{facet_path}) as count | "
        f"filter: facets.{facet_path} is not null "
        "AND span_attributes.type = 'automation' "
        f"AND name = '{escape_btql_literal(automation_name)}'"
    )
    last_count = 0
    last_error: SmokeError | None = None
    print(f"Waiting for {expected} facet output(s) to become replayable for classification...")
    while True:
        try:
            response = api_post(
                ctx,
                "/btql",
                {
                    "query": query,
                    "fmt": "json",
                    "use_brainstore": True,
                    "brainstore_realtime": False,
                    "brainstore_ephemeral_wal": False,
                    "brainstore_skip_backfill_check": False,
                    "use_columnstore": True,
                    "api_version": 1,
                    "query_source": "topics-smoke-facet-compaction-check",
                },
            )
            row = (response.get("data") or [{}])[0]
            count = read_count(row, "count")
            if count != last_count:
                print(f"Compacted facet outputs: {count}/{expected}")
            last_count = count
            last_error = None
            if count >= expected:
                return
        except SmokeError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            error_note = f" Last query error: {last_error}" if last_error else ""
            raise SmokeError(
                "Timed out waiting for facet outputs to become replayable for "
                f"classification: {last_count}/{expected}.{error_note}"
            )
        time.sleep(interval_seconds)


def wait_for_topic_classifications(
    ctx: AuthContext,
    project: Project,
    automation: dict[str, Any],
    facet: str,
    args: argparse.Namespace,
) -> None:
    """Drive topic generation/backfill until the synthetic traces are classified."""
    expected = min(args.count, MIN_TOPIC_SUMMARIES)
    deadline = time.monotonic() + args.classification_timeout
    last_count = 0
    last_error: SmokeError | None = None
    automation_id = str(automation["id"])
    object_id = topic_automation_object_id(project.id, (automation.get("config") or {}).get("data_scope"))
    print(f"Waiting for Topics classification {facet!r} on {expected} trace(s)...")

    while True:
        try:
            count = get_topic_classification_count(
                ctx,
                project.id,
                facet,
                str(automation.get("name") or AUTOMATION_NAME),
            )
            last_count = count
            last_error = None
            if count >= expected:
                print(f"Verified Topics classification count: {count}")
                return

            poke_topic_automation(ctx, automation_id, object_id)
            execution = execute_topic_automation(
                ctx,
                project.id,
                automation,
                timeout_seconds=args.automation_execution_timeout,
            )
            print(f"Classification {facet}: classified={count}/{expected} rows_matched={execution['rows_matched']}")
        except SmokeError as exc:
            last_error = exc
            print(f"Topics classification check is not ready: {exc}")

        if time.monotonic() >= deadline:
            error_note = f" Last execution/query error: {last_error}" if last_error else ""
            raise SmokeError(
                f"Timed out waiting for Topics classification {facet!r}: "
                f"{last_count}/{expected} classified.{error_note}"
            )
        time.sleep(args.classification_interval)


def wait_for_generated_topic_map(
    ctx: AuthContext,
    project: Project,
    automation: dict[str, Any],
    topic_map_function_id: str,
    args: argparse.Namespace,
) -> tuple[str, str]:
    """Drive object work until Topics publishes a generated map version."""
    deadline = time.monotonic() + args.classification_timeout
    automation_id = str(automation["id"])
    object_id = topic_automation_object_id(project.id, (automation.get("config") or {}).get("data_scope"))
    last_state = "unknown"
    last_error: SmokeError | None = None
    print("Waiting for Topics to generate a topic map...")

    while True:
        try:
            cursor = api_post(
                ctx,
                "/brainstore/automation/get-object-cursors",
                {"automation_id": automation_id, "project_id": project.id},
            )
            runtime = cursor.get("topic_runtime") or (cursor.get("stats") or {}).get("runtime") or {}
            last_state = str(runtime.get("state") or "unknown")
            active_versions = runtime.get("active_topic_map_versions") or {}
            version = active_versions.get(topic_map_function_id)
            start_xact_id = runtime.get("topic_classification_backfill_start_xact_id")
            print(f"Topics runtime: {last_state}")
            last_error = None
            if version is not None and start_xact_id is not None:
                return str(version), str(start_xact_id)

            poke_topic_automation(ctx, automation_id, object_id)
            execute_topic_automation(
                ctx,
                project.id,
                automation,
                timeout_seconds=args.automation_execution_timeout,
            )
        except SmokeError as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            error_note = f" Last execution/status error: {last_error}" if last_error else ""
            raise SmokeError(
                f"Timed out waiting for Topics to generate map {topic_map_function_id!r}. "
                f"Last runtime state: {last_state}.{error_note}"
            )
        time.sleep(args.classification_interval)


def get_topic_facet_status_counts(
    ctx: AuthContext,
    project_id: str,
    automation_id: str,
    facet: str,
    function_key: str | None = None,
) -> dict[str, int]:
    cursor = api_post(
        ctx,
        "/brainstore/automation/get-cursors",
        {"automation_id": automation_id, "project_id": project_id},
    )
    pending_min_executed_xact_id = cursor.get("pending_min_executed_xact_id")
    key = function_key or f"global:facet:{facet}"
    base = f"_async_scoring_state.triggered_functions.{quote_btql_path_piece(key)}"
    attempted = f"{base}.triggered_xact_id IS NOT NULL"
    completed = f"{base}.completed_xact_id >= {base}.triggered_xact_id"
    inflight = (
        f"{attempted} AND ({base}.completed_xact_id IS NULL OR {base}.completed_xact_id < {base}.triggered_xact_id)"
    )
    if pending_min_executed_xact_id is None:
        error_condition = f"{base}.attempts > 0"
    else:
        escaped_xact = escape_btql_literal(str(pending_min_executed_xact_id))
        error_condition = f"{base}.attempts > 0 AND {base}.triggered_xact_id < '{escaped_xact}'"
    facet_path = f"facets.{quote_btql_path_piece(facet)}"
    matched = f"{facet_path} != 'NO_MATCH' AND {facet_path} != 'SKIPPED' AND {facet_path} != 'skipped'"
    query = (
        f"from: project_logs('{escape_btql_literal(project_id)}') spans | "
        "measures: "
        f"count(({matched}) ? 1 : null) as matched, "
        f"count({facet_path}) as processed, "
        f"count(({inflight}) ? 1 : null) as inflight, "
        f"count(({inflight} AND {error_condition}) ? 1 : null) as errors, "
        f"count(({completed}) ? 1 : null) as completed | "
        "filter: created >= NOW() - INTERVAL 3600 SECOND"
    )
    response = api_post(
        ctx,
        "/btql",
        {
            "query": query,
            "fmt": "json",
            "use_brainstore": True,
            "brainstore_realtime": True,
            "brainstore_ephemeral_wal": True,
            "brainstore_skip_backfill_check": False,
            "use_columnstore": True,
            "api_version": 1,
            "query_source": "topics-smoke-running-check",
        },
    )
    row = (response.get("data") or [{}])[0]
    errors = read_count(row, "errors")
    inflight_count = read_count(row, "inflight")
    return {
        "matched": read_count(row, "matched"),
        "processed": read_count(row, "processed"),
        "running": max(0, inflight_count - errors),
        "errors": errors,
        "completed": read_count(row, "completed"),
    }


def saved_function_ref_key(function_ref: dict[str, Any]) -> str:
    if function_ref.get("type") == "function":
        function_id = function_ref.get("id")
        if not function_id:
            raise SmokeError("saved function reference is missing id")
        return f"function_id:{function_id}"
    function_type = function_ref.get("function_type") or "scorer"
    name = function_ref.get("name")
    if not name:
        raise SmokeError("global function reference is missing name")
    return f"global:{function_type}:{name}"


def facet_function_key(automation: dict[str, Any]) -> str:
    return saved_function_ref_key(automation["config"]["facet_functions"][0])


def validate_args(args: argparse.Namespace) -> None:
    if args.count < MIN_TOPIC_SUMMARIES and not args.allow_below_threshold:
        raise SmokeError(
            f"topics.count must be at least {MIN_TOPIC_SUMMARIES} for Topics generation. "
            "Use topics.allow_below_threshold only when intentionally testing pre-generation behavior."
        )
    if args.idle_seconds < 10:
        raise SmokeError("topics.idle_seconds must be at least 10")
    if args.running_check_timeout < 0:
        raise SmokeError("topics.running_check_timeout must be non-negative")
    if args.running_check_interval < 1:
        raise SmokeError("topics.running_check_interval must be at least 1")
    if args.facet_preflight_timeout < 1:
        raise SmokeError("topics.facet_preflight_timeout must be at least 1")
    if args.function_visibility_timeout < 0:
        raise SmokeError("topics.function_visibility_timeout must be non-negative")
    if args.function_visibility_interval < 1:
        raise SmokeError("topics.function_visibility_interval must be at least 1")
    if args.compaction_timeout < 0:
        raise SmokeError("topics.compaction_timeout must be non-negative")
    if args.compaction_interval < 1:
        raise SmokeError("topics.compaction_interval must be at least 1")
    if args.automation_execution_timeout < 1:
        raise SmokeError("topics.automation_execution_timeout must be at least 1")
    if args.classification_timeout < 0:
        raise SmokeError("topics.classification_timeout must be non-negative")
    if args.classification_interval < 1:
        raise SmokeError("topics.classification_interval must be at least 1")


def timestamped_project_name(prefix: str, run_id: str | None = None) -> str:
    safe_prefix = slugify_project_prefix(prefix)
    timestamp = run_id or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{safe_prefix}-{timestamp}"


def slugify_project_prefix(value: str) -> str:
    out = []
    previous_dash = False
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
            previous_dash = False
        elif not previous_dash:
            out.append("-")
            previous_dash = True
    slug = "".join(out).strip("-")
    return slug or DEFAULT_PROJECT_PREFIX


def slugify_topic_map_name(value: str) -> str:
    out = []
    previous_dash = False
    for ch in value.strip().lower():
        if ("a" <= ch <= "z") or ch.isdigit():
            out.append(ch)
            previous_dash = False
        elif not previous_dash:
            out.append("-")
            previous_dash = True
    slug = "".join(out).strip("-")
    return slug or "topic-map"


def parse_duration_seconds(value: str) -> int:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("duration cannot be empty")
    unit = value[-1].lower() if value[-1].isalpha() else "s"
    number = value[:-1] if value[-1].isalpha() else value
    try:
        amount = int(number)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid duration {value!r}") from exc
    multipliers = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
    }
    if unit not in multipliers:
        raise argparse.ArgumentTypeError(f"invalid duration unit {unit!r}")
    return amount * multipliers[unit]


def format_duration_seconds(seconds: int) -> str:
    for suffix, scale in (
        ("w", 7 * 24 * 60 * 60),
        ("d", 24 * 60 * 60),
        ("h", 60 * 60),
        ("m", 60),
        ("s", 1),
    ):
        if seconds > 0 and seconds % scale == 0:
            return f"{seconds // scale}{suffix}"
    return f"{seconds}s"


def inclusive_start_xact_id_from_epoch_ms(epoch_ms: int) -> str:
    xact_namespace = 0x0DE1
    epoch_seconds = max(0, epoch_ms // 1000)
    transaction_id = (xact_namespace << 48) | ((epoch_seconds & 0x0000FFFFFFFF) << 16)
    if transaction_id <= 0:
        return "0"
    return str(transaction_id - 1)


def escape_btql_literal(value: str) -> str:
    return value.replace("'", "''")


def quote_btql_path_piece(value: str) -> str:
    if value and value.replace("_", "").isalnum() and not value[0].isdigit():
        return value
    return '"' + value.replace('"', '""') + '"'


def read_count(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def topic_automation_object_id(project_id: str, data_scope: Any | None) -> str:
    if not isinstance(data_scope, dict):
        return f"project_logs:{project_id}"
    scope_type = data_scope.get("type")
    if scope_type in (None, "project_logs"):
        return f"project_logs:{project_id}"
    if scope_type == "project_experiments":
        return f"project_experiments:{project_id}"
    if scope_type == "experiment":
        experiment_id = data_scope.get("experiment_id")
        if not experiment_id:
            raise SmokeError("topic automation experiment data scope is missing experiment_id")
        return f"experiment:{experiment_id}"
    raise SmokeError(f"unsupported topic automation data scope: {scope_type}")


def build_args(config: dict[str, Any]) -> argparse.Namespace:
    from braintest_suite.config import TopicsConfig

    values = TopicsConfig.model_validate(config.get("topics", {})).model_dump()
    topic_window = values.pop("topic_window")
    generation_cadence = values.pop("generation_cadence")
    values.update(
        api_key=None,
        api_url=config.get("braintrust", {}).get("api_url"),
        topic_window_seconds=parse_duration_seconds(topic_window),
        generation_cadence_seconds=parse_duration_seconds(generation_cadence),
    )
    return argparse.Namespace(**values)


def main(argv: list[str] | None = None) -> int:
    from braintest_suite import cli

    cli.main(args=["run", "topics", *(sys.argv[1:] if argv is None else argv)], prog_name="braintest")
    return 0


def run(config: dict[str, Any]) -> bool:
    """Run the Topics smoke test with values from the suite configuration."""
    try:
        args = build_args(config)
        return run_create(args) == 0
    except SmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    raise SystemExit(main())
