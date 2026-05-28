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
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

APP_URL = "https://www.braintrust.dev"
DEFAULT_COUNT = 105
MIN_TOPIC_SUMMARIES = 100
DEFAULT_FACET = "Task"
TOPIC_MAP_EMBEDDING_MODEL = "brain-embedding-1"
DEFAULT_PROJECT_PREFIX = "topics-smoke"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RUNNING_CHECK_TIMEOUT_SECONDS = 90
DEFAULT_RUNNING_CHECK_INTERVAL_SECONDS = 3
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 30
DEFAULT_FUNCTION_VISIBILITY_TIMEOUT_SECONDS = 60
DEFAULT_FUNCTION_VISIBILITY_INTERVAL_SECONDS = 2
TASK_FACET_PROMPT = """What is the user's overall request or goal in this conversation?

Respond with a single sentence starting with "User wants to..."

Focus on the high-level intent, not specific details. If multiple requests, describe the main one.

Examples:
- "User wants to debug why their API calls are returning errors"
- "User wants to create a new LLM-based evaluation scorer"
- "User wants to understand how to interpret experiment results"
- "User wants to optimize their prompt for better accuracy"

If no clear request is present, respond: "NONE"
"""


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
    except URLError as exc:
        raise SmokeError(f"{method} {url} failed: {exc.reason}") from exc

    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{method} {url} returned non-JSON response: {text[:500]}") from exc


def require_api_key(args: argparse.Namespace) -> str:
    api_key = args.api_key or os.environ.get("BRAINTRUST_API_KEY")
    if not api_key:
        raise SmokeError("BRAINTRUST_API_KEY or --api-key is required")
    return api_key


def discover_auth(args: argparse.Namespace) -> AuthContext:
    api_key = require_api_key(args)
    requested_org = args.org or os.environ.get("BRAINTRUST_ORG_NAME")
    forced_api_url = args.api_url or os.environ.get("BRAINTRUST_API_URL")

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
            "Could not discover org/api_url from the API key. Provide --org and --api-url "
            "or BRAINTRUST_ORG_NAME and BRAINTRUST_API_URL.\n"
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
        raise SmokeError("Could not determine org. Provide --org or BRAINTRUST_ORG_NAME.")
    if not api_url:
        raise SmokeError("Could not determine API URL. Provide --api-url or BRAINTRUST_API_URL.")

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
        "API key belongs to multiple organizations. Provide --org or BRAINTRUST_ORG_NAME. "
        f"Available orgs: {names}"
    )


def api_url(ctx: AuthContext, path: str, query: dict[str, str] | None = None) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    url = f"{ctx.api_url}{suffix}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def app_project_topics_url(org_name: str, project_name: str) -> str:
    return (
        f"{APP_URL}/app/{quote(org_name, safe='')}/p/"
        f"{quote(project_name, safe='')}/topics"
    )


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
) -> Any:
    return json_request(
        "POST",
        api_url(ctx, path),
        api_key=ctx.api_key,
        org_name=ctx.org_name,
        body=body,
        extra_headers=extra_headers,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


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
    response = api_get(ctx, "/v1/project_automation", {"project_id": project_id})
    rows = response.get("objects") or []
    return [
        row
        for row in rows
        if isinstance(row.get("config"), dict) and row["config"].get("event_type") == "topic"
    ]


def enable_topics(ctx: AuthContext, project: Project, args: argparse.Namespace) -> dict[str, Any]:
    existing = list_topic_automations(ctx, project.id)
    if existing:
        raise SmokeError(
            f"Project {project.name!r} already has {len(existing)} Topics automation(s); "
            "fresh smoke projects should start empty."
        )

    facet_names, facet_functions, topic_map_functions = create_topic_function_refs(
        ctx,
        project.id,
    )
    return register_topics_automation(
        ctx,
        project,
        args,
        facet_functions=facet_functions,
        topic_map_functions=topic_map_functions,
    )


def create_topic_function_refs(
    ctx: AuthContext,
    project_id: str,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    facet_names = [DEFAULT_FACET]
    facet_functions = [
        {"type": "global", "name": DEFAULT_FACET, "function_type": "facet"}
    ]
    topic_map_functions = create_topic_map_functions(
        ctx,
        project_id,
        facet_names,
    )
    return facet_names, facet_functions, topic_map_functions


def register_topics_automation(
    ctx: AuthContext,
    project: Project,
    args: argparse.Namespace,
    *,
    facet_functions: list[dict[str, Any]],
    topic_map_functions: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "project_automation_name": "Topics smoke",
        "description": "Minimal disposable Topics smoke-test automation",
        "project_id": project.id,
        "config": {
            "event_type": "topic",
            "sampling_rate": 1.0,
            "facet_functions": facet_functions,
            "topic_map_functions": topic_map_functions,
            "scope": {"type": "trace", "idle_seconds": args.idle_seconds},
            "rerun_seconds": args.generation_cadence_seconds,
            "relabel_overlap_seconds": args.relabel_overlap_seconds,
            "backfill_time_range": format_duration_seconds(args.topic_window_seconds),
        },
        "update": True,
    }
    response = api_post(ctx, "/api/project_automation/register", body)
    automation = response.get("project_automation") or response
    seed_topic_automation_cursors(ctx, project.id, automation, args.topic_window_seconds)
    return automation


def create_topic_map_functions(
    ctx: AuthContext,
    project_id: str,
    facet_names: list[str],
) -> list[dict[str, Any]]:
    body = {
        "functions": [
            {
                "project_id": project_id,
                "name": facet,
                "slug": slugify_topic_map_name(f"{facet}-topic-map"),
                "function_type": "classifier",
                "function_data": {
                    "type": "topic_map",
                    "source_facet": facet,
                    "embedding_model": TOPIC_MAP_EMBEDDING_MODEL,
                },
                "if_exists": "ignore",
            }
            for facet in facet_names
        ]
    }
    response = api_post(ctx, "/insert-functions", body)
    functions = response.get("functions") or []
    if len(functions) != len(facet_names):
        raise SmokeError("Failed to create the expected topic map functions")
    return [
        {"function": saved_function_ref_from_inserted_function(function_row, response)}
        for function_row in functions
    ]


def saved_function_ref_from_inserted_function(
    function_row: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, str]:
    ref = {"type": "function", "id": str(function_row["id"])}
    version = function_row.get("_xact_id") or function_row.get("version") or response.get("xact_id")
    if version is not None:
        ref["version"] = str(version)
    return ref


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
    facet_functions: list[dict[str, Any]],
    topic_map_functions: list[dict[str, Any]],
    *,
    timeout_seconds: int,
    interval_seconds: int,
) -> None:
    refs: list[tuple[str, dict[str, Any], str]] = []
    for ref in facet_functions:
        refs.append(("facet", ref, "facet"))
    for entry in topic_map_functions:
        ref = entry.get("function")
        if not isinstance(ref, dict):
            raise SmokeError(f"topic map entry is missing function reference: {entry!r}")
        refs.append(("topic map", ref, "topic_map"))

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
    start_xact_id = inclusive_start_xact_id_from_epoch_ms(
        int(time.time() * 1000) - window_seconds * 1000
    )
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


def insert_smoke_traces(ctx: AuthContext, project: Project, events: list[dict[str, Any]]) -> Any:
    return api_post(ctx, f"/v1/project_logs/{quote(project.id, safe='')}/insert", {"events": events})


def format_function_refs(function_refs: list[dict[str, Any]]) -> str:
    return ", ".join(str(ref.get("id")) for ref in function_refs) or "(none)"


def format_topic_map_refs(topic_map_refs: list[dict[str, Any]]) -> str:
    ids = [
        str((ref.get("function") or {}).get("id"))
        for ref in topic_map_refs
        if isinstance(ref.get("function"), dict)
    ]
    return ", ".join(ids) or "(none)"


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
                    "source": "smoke_test/run.py",
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
    facet_names, facet_functions, topic_map_functions = create_topic_function_refs(
        ctx,
        project.id,
    )
    print(f"Using built-in Topics facet: {DEFAULT_FACET}")
    print(f"Created topic map function(s): {format_topic_map_refs(topic_map_functions)}")
    verify_function_refs_resolve(
        ctx,
        project.id,
        facet_functions,
        topic_map_functions,
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
            facet_names,
            facet_functions,
            topic_map_functions,
        )
        remaining_events = events[1:]
        if remaining_events:
            insert_smoke_traces(ctx, project, remaining_events)
        print(f"Inserted {len(events)} synthetic trace(s)")

    automation = register_topics_automation(
        ctx,
        project,
        args,
        facet_functions=facet_functions,
        topic_map_functions=topic_map_functions,
    )
    print(f"Enabled Topics automation: {automation.get('name', 'Topics')} ({automation['id']})")
    object_id = topic_automation_object_id(project.id, (automation.get("config") or {}).get("data_scope"))
    poke_topic_automation(ctx, str(automation["id"]), object_id)
    print("Queued Topics processing")
    if not args.skip_running_check:
        verify_expected_running(ctx, project, automation, [DEFAULT_FACET], args)
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
                "org": args.org or os.environ.get("BRAINTRUST_ORG_NAME"),
                "api_url": args.api_url or os.environ.get("BRAINTRUST_API_URL"),
                "note": f"No project, traces, or automations were created. Discovery failed: {exc}",
            }
    return {
        "org": args.org or os.environ.get("BRAINTRUST_ORG_NAME"),
        "api_url": args.api_url or os.environ.get("BRAINTRUST_API_URL"),
        "note": "No network calls were made because no API key was provided.",
    }


def run_status(args: argparse.Namespace) -> int:
    if not args.project:
        raise SmokeError("status requires --project <created-project-name>")
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
        summary["automations"].append(
            {
                "id": automation_id,
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
    facets: list[str],
    facet_functions: list[dict[str, Any]],
    topic_map_functions: list[dict[str, Any]],
) -> None:
    if len(facets) != 1:
        print("Skipping facet preflight because multiple facets were configured")
        return

    facet = facets[0]
    root_span_id = str(event["root_span_id"])
    saved_body = {
        "api_version": 1,
        "project_id": project.id,
        "org_name": ctx.org_name,
        **saved_function_ref_to_use_body(facet_functions[0]),
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
    saved_response = api_post(ctx, "/function/invoke", saved_body)
    if saved_response is None:
        raise SmokeError(f"Saved facet preflight for {facet!r} returned no response")
    print(f"Saved facet preflight succeeded for {facet!r}")

    pipeline_body = {
        "api_version": 1,
        "project_id": project.id,
        "org_name": ctx.org_name,
        "inline_function": build_batched_facet_inline_function(
            facet,
            topic_map_functions[0],
        ),
        "function_type": "facet",
        "name": "Topics smoke pipeline preflight",
        "input": {
            "trace_ref": {
                "object_type": "project_logs",
                "object_id": project.id,
                "root_span_id": root_span_id,
            },
        },
        "stream": False,
        "timeout_ms": args.facet_preflight_timeout * 1000,
    }
    pipeline_response = api_post(ctx, "/function/invoke", pipeline_body)
    if not isinstance(pipeline_response, dict) or facet not in pipeline_response:
        raise SmokeError(
            f"Pipeline preflight for {facet!r} returned unexpected response: {pipeline_response!r}"
        )
    print(f"Pipeline preflight succeeded for {facet!r}")

    async_batch_response = api_post(
        ctx,
        "/function/invoke-async-batch",
        [{"request": pipeline_body}],
        extra_headers={"x-bt-use-gateway": "true"},
    )
    if not isinstance(async_batch_response, dict) or async_batch_response.get("failed", 0) != 0:
        raise SmokeError(
            "Async-batch gateway preflight failed before bulk trace insert. "
            f"Response: {async_batch_response!r}"
        )
    print(f"Async-batch gateway preflight succeeded for {facet!r}")


def build_batched_facet_inline_function(
    facet: str,
    topic_map_function: dict[str, Any],
) -> dict[str, Any]:
    topic_map_id = str((topic_map_function.get("function") or {})["id"])
    return {
        "type": "batched_facet",
        "preprocessor": {
            "type": "global",
            "name": "thread",
            "function_type": "preprocessor",
        },
        "facets": [
            {
                "name": facet,
                "prompt": facet_prompt_for_name(facet),
                "embedding_model": TOPIC_MAP_EMBEDDING_MODEL,
                "no_match_pattern": "^NONE",
            }
        ],
        "topic_maps": {
            facet: [
                {
                    "function_name": facet,
                    "topic_map_id": topic_map_id,
                    "topic_map_data": {
                        "type": "topic_map",
                        "source_facet": facet,
                        "embedding_model": TOPIC_MAP_EMBEDDING_MODEL,
                    },
                }
            ]
        },
    }


def verify_expected_running(
    ctx: AuthContext,
    project: Project,
    automation: dict[str, Any],
    facets: list[str],
    args: argparse.Namespace,
) -> None:
    if len(facets) != 1:
        print("Skipping running-count check because multiple facets were configured")
        return

    facet = facets[0]
    expected = args.count
    deadline = time.monotonic() + args.running_check_timeout
    last_counts: dict[str, int] | None = None
    function_keys = facet_function_keys_for_running_check(automation, facets)
    print(
        f"Waiting for Topics facet {facet!r} to show {expected} running or processed trace(s)..."
    )
    while True:
        counts = get_topic_facet_status_counts(
            ctx,
            project.id,
            str(automation["id"]),
            facet,
            function_keys,
        )
        last_counts = counts
        running = counts["running"]
        errors = counts["errors"]
        processed = counts["processed"]
        matched = counts["matched"]
        print(
            f"Facet {facet}: matched={matched} processed={processed} running={running} errors={errors}"
        )
        if errors == 0 and (running >= expected or processed >= expected):
            if processed >= expected:
                print(f"Verified Topics processed count: {processed}")
            else:
                print(f"Verified Topics running count: {running}")
            return
        if errors >= expected:
            raise SmokeError(
                f"Topics facet {facet!r} reported {errors} error(s), which is at or above "
                f"the expected {expected} trace(s). Last counts: {last_counts}"
            )
        if time.monotonic() >= deadline:
            error_note = (
                f"; last reported errors={errors}" if errors > 0 else ""
            )
            raise SmokeError(
                f"Timed out waiting for Topics facet {facet!r} to reach {expected} running or processed "
                f"trace(s){error_note}. Last counts: {last_counts}"
            )
        time.sleep(args.running_check_interval)


def get_topic_facet_status_counts(
    ctx: AuthContext,
    project_id: str,
    automation_id: str,
    facet: str,
    function_keys: list[str] | None = None,
) -> dict[str, int]:
    cursor = api_post(
        ctx,
        "/brainstore/automation/get-cursors",
        {"automation_id": automation_id, "project_id": project_id},
    )
    pending_min_executed_xact_id = cursor.get("pending_min_executed_xact_id")
    keys = function_keys or [f"global:facet:{facet}"]
    inflight_parts = []
    error_parts = []
    completed_parts = []
    for function_key in keys:
        base = f'_async_scoring_state.triggered_functions.{quote_btql_path_piece(function_key)}'
        attempted = f"{base}.triggered_xact_id IS NOT NULL"
        completed = f"{base}.completed_xact_id >= {base}.triggered_xact_id"
        inflight = (
            f"{attempted} AND "
            f"({base}.completed_xact_id IS NULL OR {base}.completed_xact_id < {base}.triggered_xact_id)"
        )
        if pending_min_executed_xact_id is None:
            error_condition = f"{base}.attempts > 0"
        else:
            escaped_xact = escape_btql_literal(str(pending_min_executed_xact_id))
            error_condition = f"{base}.attempts > 0 AND {base}.triggered_xact_id < '{escaped_xact}'"
        inflight_parts.append(f"({inflight})")
        error_parts.append(f"({inflight} AND {error_condition})")
        completed_parts.append(f"({completed})")
    inflight_any = " OR ".join(inflight_parts)
    error_any = " OR ".join(error_parts)
    completed_any = " OR ".join(completed_parts)
    facet_path = f"facets.{quote_btql_path_piece(facet)}"
    matched = f"{facet_path} != 'NO_MATCH' AND {facet_path} != 'SKIPPED' AND {facet_path} != 'skipped'"
    query = (
        f"from: project_logs('{escape_btql_literal(project_id)}') spans | "
        "measures: "
        f"count(({matched}) ? 1 : null) as matched, "
        f"count({facet_path}) as processed, "
        f"count(({inflight_any}) ? 1 : null) as inflight, "
        f"count(({error_any}) ? 1 : null) as errors, "
        f"count(({completed_any}) ? 1 : null) as completed | "
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


def facet_prompt_for_name(facet: str) -> str:
    if facet == DEFAULT_FACET:
        return TASK_FACET_PROMPT
    return (
        f"Classify this conversation for the {facet} facet. "
        "Return a concise label, or NONE if there is no clear match."
    )


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


def facet_function_keys_for_running_check(
    automation: dict[str, Any],
    facets: list[str],
) -> list[str]:
    refs = (automation.get("config") or {}).get("facet_functions") or []
    if len(refs) == len(facets):
        return [saved_function_ref_key(ref) for ref in refs]
    if len(facets) == 1:
        return [f"global:facet:{facets[0]}"]
    raise SmokeError("could not determine Topics facet function keys for running check")


def validate_args(args: argparse.Namespace) -> None:
    if args.count < MIN_TOPIC_SUMMARIES and not args.allow_below_threshold:
        raise SmokeError(
            f"--count must be at least {MIN_TOPIC_SUMMARIES} for Topics generation. "
            "Use --allow-below-threshold only when intentionally testing pre-generation behavior."
        )
    if args.idle_seconds < 10:
        raise SmokeError("--idle-seconds must be at least 10")
    if getattr(args, "running_check_timeout", 0) < 0:
        raise SmokeError("--running-check-timeout must be non-negative")
    if getattr(args, "running_check_interval", 1) < 1:
        raise SmokeError("--running-check-interval must be at least 1")
    if getattr(args, "facet_preflight_timeout", 1) < 1:
        raise SmokeError("--facet-preflight-timeout must be at least 1")
    if getattr(args, "function_visibility_timeout", 0) < 0:
        raise SmokeError("--function-visibility-timeout must be non-negative")
    if getattr(args, "function_visibility_interval", 1) < 1:
        raise SmokeError("--function-visibility-interval must be at least 1")


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


def load_configured_defaults() -> dict[str, Any]:
    """Load smoke test CLI defaults from braintest.yaml when available."""
    try:
        from config import load_config
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        try:
            from config import load_config
        except ModuleNotFoundError:
            return {}

    try:
        config = load_config()
    except Exception:
        return {}

    smoketest = config.get("smoketest", {})
    if not isinstance(smoketest, dict):
        return {}

    defaults: dict[str, Any] = {}
    direct_keys = [
        "api_url",
        "org",
        "project_prefix",
        "count",
        "idle_seconds",
        "timeout",
        "allow_below_threshold",
        "skip_facet_preflight",
        "skip_running_check",
        "facet_preflight_timeout",
        "function_visibility_timeout",
        "function_visibility_interval",
        "running_check_timeout",
        "running_check_interval",
    ]
    for key in direct_keys:
        value = smoketest.get(key)
        if value is not None:
            defaults[key] = value

    duration_keys = {
        "topic_window": "topic_window_seconds",
        "generation_cadence": "generation_cadence_seconds",
        "relabel_overlap": "relabel_overlap_seconds",
    }
    for config_key, parser_key in duration_keys.items():
        value = smoketest.get(config_key)
        if value is not None:
            defaults[parser_key] = parse_duration_seconds(str(value))

    return defaults


def build_parser(defaults: dict[str, Any] | None = None) -> argparse.ArgumentParser:
    defaults = defaults or {}
    parser = argparse.ArgumentParser(
        description="Create a disposable Braintrust project for minimal Topics smoke testing."
    )
    subparsers = parser.add_subparsers(dest="command")

    def add_common_auth_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--api-key",
            default=defaults.get("api_key"),
            help="Braintrust API key. Defaults to BRAINTRUST_API_KEY.",
        )
        p.add_argument(
            "--org",
            default=defaults.get("org"),
            help="Braintrust org name. Defaults to BRAINTRUST_ORG_NAME.",
        )
        p.add_argument(
            "--api-url",
            default=defaults.get("api_url"),
            help="Override discovered dataplane API URL. Defaults to BRAINTRUST_API_URL.",
        )
        p.add_argument(
            "--timeout",
            type=int,
            default=defaults.get("timeout", DEFAULT_TIMEOUT_SECONDS),
        )

    create = subparsers.add_parser("create", help="Create a project, seed traces, and queue Topics.")
    add_common_auth_flags(create)
    add_create_flags(create, defaults)

    status = subparsers.add_parser("status", help="Show minimal Topics automation status.")
    add_common_auth_flags(status)
    status.add_argument("--project", required=True, help="Project name created by this script.")

    add_common_auth_flags(parser)
    add_create_flags(parser, defaults)
    return parser


def add_create_flags(parser: argparse.ArgumentParser, defaults: dict[str, Any] | None = None) -> None:
    defaults = defaults or {}
    parser.add_argument(
        "--project-prefix",
        default=defaults.get("project_prefix", DEFAULT_PROJECT_PREFIX),
    )
    parser.add_argument("--count", type=int, default=defaults.get("count", DEFAULT_COUNT))
    parser.add_argument("--idle-seconds", type=int, default=defaults.get("idle_seconds", 10))
    parser.add_argument(
        "--topic-window",
        dest="topic_window_seconds",
        type=parse_duration_seconds,
        default=defaults.get("topic_window_seconds", parse_duration_seconds("1h")),
    )
    parser.add_argument(
        "--generation-cadence",
        dest="generation_cadence_seconds",
        type=parse_duration_seconds,
        default=defaults.get("generation_cadence_seconds", parse_duration_seconds("1h")),
    )
    parser.add_argument(
        "--relabel-overlap",
        dest="relabel_overlap_seconds",
        type=parse_duration_seconds,
        default=defaults.get("relabel_overlap_seconds", parse_duration_seconds("10m")),
    )
    parser.add_argument(
        "--allow-below-threshold",
        action="store_true",
        default=defaults.get("allow_below_threshold", False),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-facet-preflight",
        action="store_true",
        default=defaults.get("skip_facet_preflight", False),
        help="Do not run a one-trace direct facet invocation before queueing Topics.",
    )
    parser.add_argument(
        "--facet-preflight-timeout",
        type=int,
        default=defaults.get("facet_preflight_timeout", DEFAULT_PREFLIGHT_TIMEOUT_SECONDS),
        help="Seconds to allow for the one-trace direct facet preflight.",
    )
    parser.add_argument(
        "--function-visibility-timeout",
        type=int,
        default=defaults.get(
            "function_visibility_timeout",
            DEFAULT_FUNCTION_VISIBILITY_TIMEOUT_SECONDS,
        ),
        help="Seconds to wait for saved functions to resolve through /function/use.",
    )
    parser.add_argument(
        "--function-visibility-interval",
        type=int,
        default=defaults.get(
            "function_visibility_interval",
            DEFAULT_FUNCTION_VISIBILITY_INTERVAL_SECONDS,
        ),
        help="Seconds between saved-function /function/use visibility checks.",
    )
    parser.add_argument(
        "--skip-running-check",
        action="store_true",
        default=defaults.get("skip_running_check", False),
        help="Do not poll for the expected initial Topics running count after queueing.",
    )
    parser.add_argument(
        "--running-check-timeout",
        type=int,
        default=defaults.get("running_check_timeout", DEFAULT_RUNNING_CHECK_TIMEOUT_SECONDS),
        help="Seconds to wait for the expected Topics running count.",
    )
    parser.add_argument(
        "--running-check-interval",
        type=int,
        default=defaults.get("running_check_interval", DEFAULT_RUNNING_CHECK_INTERVAL_SECONDS),
        help="Seconds between Topics running-count checks.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(load_configured_defaults())
    args = parser.parse_args(argv)
    command = args.command or "create"
    try:
        if command == "status":
            return run_status(args)
        return run_create(args)
    except SmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
