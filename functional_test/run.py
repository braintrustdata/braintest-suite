import os
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests
import yaml
from dotenv import load_dotenv

from util import http_client


@dataclass
class ApiCallRecord:
    call: str
    method: str
    endpoint: str
    status: str
    status_code: int | None
    details: str


class FunctionalTestRunner:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config if isinstance(config, dict) else {}
        self._records: list[ApiCallRecord] = []
        self._resource_ids: dict[str, str] = {}
        self._suffix = uuid.uuid4().hex[:8]

        braintrust_cfg = self._config.get("braintrust", {})
        if not isinstance(braintrust_cfg, dict):
            print("[functionaltest] 'braintrust' section is missing or invalid.")
            braintrust_cfg = {}

        functional_cfg = self._config.get("functionaltest", {})
        if not isinstance(functional_cfg, dict):
            print("[functionaltest] 'functionaltest' section is missing or invalid.")
            functional_cfg = {}

        api_url = braintrust_cfg.get("api_url")
        self._api_base_url = ""
        if isinstance(api_url, str):
            self._api_base_url = api_url.rstrip("/")
            if self._api_base_url.endswith("/v1"):
                self._api_base_url = self._api_base_url[:-3]
        else:
            print("[functionaltest] Missing required config 'braintrust.api_url'.")

        self._project_name_base = braintrust_cfg.get("project_name")
        if not self._project_name_base:
            self._project_name_base = "functional-test-project"
            print(
                "[functionaltest] Missing config 'braintrust.project_name'. "
                "Using default: functional-test-project"
            )

        self._name_prefix = functional_cfg.get("name_prefix")
        if not self._name_prefix:
            self._name_prefix = "functional-test"
            print(
                "[functionaltest] Missing config 'functionaltest.name_prefix'. "
                "Using default: functional-test"
            )

        api_key = os.getenv("BRAINTRUST_API_KEY")
        self._headers = {
            "Authorization": f"Bearer {api_key}" if api_key else "",
            "Content-Type": "application/json",
        }

    def run(self) -> bool:
        print(f"Running functional test against {self._api_base_url}...")

        if not self._api_base_url:
            self._record(
                call="Initialize functional test",
                method="N/A",
                endpoint="N/A",
                status="FAIL",
                status_code=None,
                details="Missing required config field braintrust.api_url",
            )
            self._print_summary()
            return False

        if not os.getenv("BRAINTRUST_API_KEY"):
            self._record(
                call="Initialize functional test",
                method="N/A",
                endpoint="N/A",
                status="FAIL",
                status_code=None,
                details="Missing required environment variable BRAINTRUST_API_KEY",
            )
            self._print_summary()
            return False

        try:
            self._run_core_sequence()
        finally:
            self._cleanup_resources()
            self._print_summary()

        return not any(record.status == "FAIL" for record in self._records)

    def _run_core_sequence(self) -> None:
        self._create_and_read_project()
        self._insert_and_fetch_project_logs()
        self._create_and_read_role()
        self._create_and_read_group()
        self._create_and_read_dataset()
        self._create_and_read_experiment()
        self._create_and_read_prompt()
        self._create_and_read_acl()
        self._create_and_read_project_automation()
        self._create_and_read_project_score()
        self._create_and_read_project_tag()
        self._create_and_read_function()
        self._create_and_read_view()
        self._create_and_read_api_key()
        self._create_and_read_env_var()
        self._create_and_read_environment()

    def _create_and_read_project(self) -> None:
        payload: dict[str, Any] = {
            "name": self._unique_name(f"{self._project_name_base}-functional"),
            "description": "Functional test project",
        }

        ok, body = self._call_api(
            call="Create project",
            method="POST",
            endpoint="/v1/project",
            payload=payload,
        )
        if not ok:
            return

        project_id = self._extract_id("project", body)
        if not project_id:
            return
        self._resource_ids["project_id"] = project_id
        self._call_api(
            call="Get project",
            method="GET",
            endpoint=f"/v1/project/{project_id}",
        )

    def _create_and_read_role(self) -> None:
        payload: dict[str, Any] = {
            "name": self._unique_name(f"{self._name_prefix}-role"),
            "description": "Functional test role",
        }

        ok, body = self._call_api(
            call="Create role",
            method="POST",
            endpoint="/v1/role",
            payload=payload,
        )
        if not ok:
            return

        role_id = self._extract_id("role", body)
        if not role_id:
            return
        self._resource_ids["role_id"] = role_id
        self._call_api(
            call="Get role",
            method="GET",
            endpoint=f"/v1/role/{role_id}",
        )

    def _create_and_read_group(self) -> None:
        payload: dict[str, Any] = {
            "name": self._unique_name(f"{self._name_prefix}-group"),
            "description": "Functional test group",
        }

        ok, body = self._call_api(
            call="Create group",
            method="POST",
            endpoint="/v1/group",
            payload=payload,
        )
        if not ok:
            return

        group_id = self._extract_id("group", body)
        if not group_id:
            return
        self._resource_ids["group_id"] = group_id
        self._call_api(
            call="Get group",
            method="GET",
            endpoint=f"/v1/group/{group_id}",
        )

    def _create_and_read_dataset(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip("Create dataset", "POST", "/v1/dataset", "Missing project_id")
            self._skip("Get dataset", "GET", "/v1/dataset/{dataset_id}", "Not created")
            return

        payload = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-dataset"),
            "description": "Functional test dataset",
        }
        ok, body = self._call_api(
            call="Create dataset",
            method="POST",
            endpoint="/v1/dataset",
            payload=payload,
        )
        if not ok:
            return

        dataset_id = self._extract_id("dataset", body)
        if not dataset_id:
            return
        self._resource_ids["dataset_id"] = dataset_id
        self._call_api(
            call="Get dataset",
            method="GET",
            endpoint=f"/v1/dataset/{dataset_id}",
        )

    def _create_and_read_experiment(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip(
                "Create experiment", "POST", "/v1/experiment", "Missing project_id"
            )
            self._skip(
                "Get experiment", "GET", "/v1/experiment/{experiment_id}", "Not created"
            )
            return

        payload: dict[str, Any] = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-experiment"),
            "description": "Functional test experiment",
            "metadata": {"suite": "functionaltest"},
        }
        dataset_id = self._resource_ids.get("dataset_id")
        if dataset_id:
            payload["dataset_id"] = dataset_id

        ok, body = self._call_api(
            call="Create experiment",
            method="POST",
            endpoint="/v1/experiment",
            payload=payload,
        )
        if not ok:
            return

        experiment_id = self._extract_id("experiment", body)
        if not experiment_id:
            return
        self._resource_ids["experiment_id"] = experiment_id
        self._call_api(
            call="Get experiment",
            method="GET",
            endpoint=f"/v1/experiment/{experiment_id}",
        )

    def _create_and_read_prompt(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip("Create prompt", "POST", "/v1/prompt", "Missing project_id")
            self._skip("Get prompt", "GET", "/v1/prompt/{prompt_id}", "Not created")
            return

        payload = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-prompt"),
            "slug": self._unique_slug(f"{self._name_prefix}-prompt"),
            "description": "Functional test prompt",
        }
        ok, body = self._call_api(
            call="Create prompt",
            method="POST",
            endpoint="/v1/prompt",
            payload=payload,
        )
        if not ok:
            return

        prompt_id = self._extract_id("prompt", body)
        if not prompt_id:
            return
        self._resource_ids["prompt_id"] = prompt_id
        self._call_api(
            call="Get prompt",
            method="GET",
            endpoint=f"/v1/prompt/{prompt_id}",
        )

    def _create_and_read_acl(self) -> None:
        project_id = self._resource_ids.get("project_id")
        group_id = self._resource_ids.get("group_id")

        if not project_id or not group_id:
            reason = "Missing project_id or group_id"
            self._skip("Create ACL", "POST", "/v1/acl", reason)
            self._skip("Get ACL", "GET", "/v1/acl/{acl_id}", "Not created")
            return

        payload = {
            "object_type": "project",
            "object_id": project_id,
            "group_id": group_id,
            "permission": "read",
        }
        ok, body = self._call_api(
            call="Create ACL",
            method="POST",
            endpoint="/v1/acl",
            payload=payload,
        )
        if not ok:
            return

        acl_id = self._extract_id("acl", body)
        if not acl_id:
            return
        self._resource_ids["acl_id"] = acl_id
        self._call_api(
            call="Get ACL",
            method="GET",
            endpoint=f"/v1/acl/{acl_id}",
        )

    def _insert_and_fetch_project_logs(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip(
                "Insert project logs events",
                "POST",
                "/v1/project_logs/{project_id}/insert",
                "Missing project_id",
            )
            self._skip(
                "Fetch project logs events",
                "GET",
                "/v1/project_logs/{project_id}/fetch",
                "Project logs were not inserted",
            )
            return

        payload = {
            "events": [
                {
                    "id": self._unique_name("functional-project-log"),
                    "input": {"message": "functional test input"},
                    "output": {"message": "functional test output"},
                    "metadata": {"suite": "functionaltest"},
                    "tags": ["functionaltest"],
                }
            ]
        }
        ok, _ = self._call_api(
            call="Insert project logs events",
            method="POST",
            endpoint=f"/v1/project_logs/{project_id}/insert",
            payload=payload,
        )
        if not ok:
            self._skip(
                "Fetch project logs events",
                "GET",
                "/v1/project_logs/{project_id}/fetch",
                "Project logs insert failed",
            )
            return

        self._call_api(
            call="Fetch project logs events",
            method="GET",
            endpoint=f"/v1/project_logs/{project_id}/fetch",
            query_params={"limit": 1},
        )

    def _create_and_read_project_automation(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip(
                "Create project automation",
                "POST",
                "/v1/project_automation",
                "Missing project_id",
            )
            self._skip(
                "Get project automation",
                "GET",
                "/v1/project_automation/{project_automation_id}",
                "Not created",
            )
            return

        payload = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-automation"),
            "description": "Functional test project automation",
            "config": {
                "event_type": "logs",
                "btql_filter": "TRUE",
                "interval_seconds": 60,
                "action": {
                    "type": "webhook",
                    "url": "https://example.com/braintrust-functional-test",
                },
            },
        }
        ok, body = self._call_api(
            call="Create project automation",
            method="POST",
            endpoint="/v1/project_automation",
            payload=payload,
        )
        if not ok:
            return

        automation_id = self._extract_id("project_automation", body)
        if not automation_id:
            return
        self._resource_ids["project_automation_id"] = automation_id
        self._call_api(
            call="Get project automation",
            method="GET",
            endpoint=f"/v1/project_automation/{automation_id}",
        )

    def _create_and_read_project_score(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip(
                "Create project score",
                "POST",
                "/v1/project_score",
                "Missing project_id",
            )
            self._skip(
                "Get project score",
                "GET",
                "/v1/project_score/{project_score_id}",
                "Not created",
            )
            return

        payload = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-score"),
            "description": "Functional test score",
            "score_type": "slider",
        }
        ok, body = self._call_api(
            call="Create project score",
            method="POST",
            endpoint="/v1/project_score",
            payload=payload,
        )
        if not ok:
            return

        score_id = self._extract_id("project_score", body)
        if not score_id:
            return
        self._resource_ids["project_score_id"] = score_id
        self._call_api(
            call="Get project score",
            method="GET",
            endpoint=f"/v1/project_score/{score_id}",
        )

    def _create_and_read_project_tag(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip(
                "Create project tag", "POST", "/v1/project_tag", "Missing project_id"
            )
            self._skip(
                "Get project tag",
                "GET",
                "/v1/project_tag/{project_tag_id}",
                "Not created",
            )
            return

        payload = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-tag"),
            "description": "Functional test project tag",
            "color": "#3B82F6",
        }
        ok, body = self._call_api(
            call="Create project tag",
            method="POST",
            endpoint="/v1/project_tag",
            payload=payload,
        )
        if not ok:
            return

        tag_id = self._extract_id("project_tag", body)
        if not tag_id:
            return
        self._resource_ids["project_tag_id"] = tag_id
        self._call_api(
            call="Get project tag",
            method="GET",
            endpoint=f"/v1/project_tag/{tag_id}",
        )

    def _create_and_read_function(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip("Create function", "POST", "/v1/function", "Missing project_id")
            self._skip(
                "Get function", "GET", "/v1/function/{function_id}", "Not created"
            )
            return

        payload = {
            "project_id": project_id,
            "name": self._unique_name(f"{self._name_prefix}-function"),
            "slug": self._unique_slug(f"{self._name_prefix}-function"),
            "description": "Functional test function",
            "function_data": {"type": "prompt"},
        }
        ok, body = self._call_api(
            call="Create function",
            method="POST",
            endpoint="/v1/function",
            payload=payload,
        )
        if not ok:
            return

        function_id = self._extract_id("function", body)
        if not function_id:
            return
        self._resource_ids["function_id"] = function_id
        self._call_api(
            call="Get function",
            method="GET",
            endpoint=f"/v1/function/{function_id}",
        )

    def _create_and_read_view(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip("Create view", "POST", "/v1/view", "Missing project_id")
            self._skip("Get view", "GET", "/v1/view/{view_id}", "Not created")
            return

        payload = {
            "object_type": "project",
            "object_id": project_id,
            "view_type": "logs",
            "name": self._unique_name(f"{self._name_prefix}-view"),
        }
        ok, body = self._call_api(
            call="Create view",
            method="POST",
            endpoint="/v1/view",
            payload=payload,
        )
        if not ok:
            self._skip("Get view", "GET", "/v1/view/{view_id}", "View not created")
            return

        view_id = self._extract_id("view", body)
        if not view_id:
            return
        self._resource_ids["view_id"] = view_id
        self._call_api(
            call="Get view",
            method="GET",
            endpoint=f"/v1/view/{view_id}",
            query_params={"object_type": "project", "object_id": project_id},
        )

    def _create_and_read_api_key(self) -> None:
        payload: dict[str, Any] = {
            "name": self._unique_name(f"{self._name_prefix}-api-key")
        }

        ok, body = self._call_api(
            call="Create API key",
            method="POST",
            endpoint="/v1/api_key",
            payload=payload,
        )
        if not ok:
            return

        api_key_id = self._extract_id("api_key", body)
        if not api_key_id:
            return
        self._resource_ids["api_key_id"] = api_key_id
        self._call_api(
            call="Get API key",
            method="GET",
            endpoint=f"/v1/api_key/{api_key_id}",
        )

    def _create_and_read_env_var(self) -> None:
        project_id = self._resource_ids.get("project_id")
        if not project_id:
            self._skip("Create env var", "POST", "/v1/env_var", "Missing project_id")
            self._skip("Get env var", "GET", "/v1/env_var/{env_var_id}", "Not created")
            return

        payload = {
            "object_type": "project",
            "object_id": project_id,
            "name": self._unique_env_var_name(f"{self._name_prefix}_ENV_VAR"),
            "value": "functional_test_value",
        }
        ok, body = self._call_api(
            call="Create env var",
            method="POST",
            endpoint="/v1/env_var",
            payload=payload,
        )
        if not ok:
            return

        env_var_id = self._extract_id("env_var", body)
        if not env_var_id:
            return
        self._resource_ids["env_var_id"] = env_var_id
        self._call_api(
            call="Get env var",
            method="GET",
            endpoint=f"/v1/env_var/{env_var_id}",
        )

    def _create_and_read_environment(self) -> None:
        payload = {
            "name": self._unique_name(f"{self._name_prefix}-environment"),
            "slug": self._unique_slug(f"{self._name_prefix}-environment"),
            "description": "Functional test environment",
        }
        ok, body = self._call_api(
            call="Create environment",
            method="POST",
            endpoint="/environment",
            payload=payload,
        )
        if not ok:
            return

        environment_id = self._extract_id("environment", body)
        if not environment_id:
            return

        self._resource_ids["environment_id"] = environment_id
        self._call_api(
            call="Get environment",
            method="GET",
            endpoint=f"/environment/{environment_id}",
        )

    def _cleanup_resources(self) -> None:
        if not self._resource_ids:
            print("No resources were created, cleanup skipped.")
            return

        print("Cleaning up created resources...")

        cleanup_steps = [
            ("env_var_id", "Delete env var", "/v1/env_var/{id}"),
            ("environment_id", "Delete environment", "/environment/{id}"),
            ("api_key_id", "Delete API key", "/v1/api_key/{id}"),
            ("view_id", "Delete view", "/v1/view/{id}"),
            ("function_id", "Delete function", "/v1/function/{id}"),
            ("project_tag_id", "Delete project tag", "/v1/project_tag/{id}"),
            ("project_score_id", "Delete project score", "/v1/project_score/{id}"),
            (
                "project_automation_id",
                "Delete project automation",
                "/v1/project_automation/{id}",
            ),
            ("acl_id", "Delete ACL", "/v1/acl/{id}"),
            ("prompt_id", "Delete prompt", "/v1/prompt/{id}"),
            ("experiment_id", "Delete experiment", "/v1/experiment/{id}"),
            ("dataset_id", "Delete dataset", "/v1/dataset/{id}"),
            ("group_id", "Delete group", "/v1/group/{id}"),
            ("role_id", "Delete role", "/v1/role/{id}"),
            ("project_id", "Delete project", "/v1/project/{id}"),
        ]

        for resource_key, call_name, endpoint_template in cleanup_steps:
            resource_id = self._resource_ids.get(resource_key)
            if not resource_id:
                self._skip(
                    call_name,
                    "DELETE",
                    endpoint_template,
                    f"{resource_key} not created",
                )
                continue

            endpoint = endpoint_template.format(id=resource_id)
            payload = None
            if resource_key == "view_id":
                project_id = self._resource_ids.get("project_id")
                if not project_id:
                    self._skip(
                        call_name,
                        "DELETE",
                        endpoint_template,
                        "project_id not available for view delete payload",
                    )
                    continue
                payload = {"object_type": "project", "object_id": project_id}

            self._call_api(
                call=call_name,
                method="DELETE",
                endpoint=endpoint,
                payload=payload,
            )

    def _call_api(
        self,
        call: str,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        query = query_params or {}
        filtered_query = {k: v for k, v in query.items() if v is not None}
        query_string = urlencode(filtered_query, doseq=True)
        full_endpoint = endpoint if not query_string else f"{endpoint}?{query_string}"
        url = f"{self._api_base_url}{endpoint}"
        if query_string:
            url = f"{url}?{query_string}"

        try:
            response = http_client(
                method=method,
                url=url,
                payload=payload,
                headers=self._headers,
            )
            body = self._parse_json(response)
            self._record(
                call=call,
                method=method,
                endpoint=full_endpoint,
                status="PASS",
                status_code=response.status_code,
                details="OK",
            )
            return True, body
        except requests.exceptions.RequestException as exc:
            status_code = (
                exc.response.status_code
                if getattr(exc, "response", None) is not None
                else None
            )
            self._record(
                call=call,
                method=method,
                endpoint=full_endpoint,
                status="FAIL",
                status_code=status_code,
                details=self._format_exception(exc),
            )
            return False, {}

    def _extract_id(self, resource_name: str, body: dict[str, Any]) -> str | None:
        resource_id = body.get("id") if isinstance(body, dict) else None
        if not resource_id:
            self._record(
                call=f"Capture {resource_name} ID",
                method="N/A",
                endpoint="N/A",
                status="FAIL",
                status_code=None,
                details=f"Create {resource_name} response did not include an id",
            )
            return None
        return str(resource_id)

    @staticmethod
    def _parse_json(response: requests.Response) -> dict[str, Any]:
        if not response.text:
            return {}
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else {"data": parsed}
        except ValueError:
            return {}

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        if isinstance(exc, requests.exceptions.RequestException):
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    data = response.json()
                    return str(data)[:200]
                except ValueError:
                    text = response.text or str(exc)
                    return text[:200]
        return str(exc)[:200]

    def _skip(self, call: str, method: str, endpoint: str, reason: str) -> None:
        self._record(
            call=call,
            method=method,
            endpoint=endpoint,
            status="SKIPPED",
            status_code=None,
            details=reason,
        )

    def _record(
        self,
        call: str,
        method: str,
        endpoint: str,
        status: str,
        status_code: int | None,
        details: str,
    ) -> None:
        self._records.append(
            ApiCallRecord(
                call=call,
                method=method,
                endpoint=endpoint,
                status=status,
                status_code=status_code,
                details=details,
            )
        )

    def _print_summary(self) -> None:
        print("\nFunctional Test API Call Results")

        headers = ["Call", "Method", "Endpoint", "Status", "Code", "Details"]
        rows = [
            [
                record.call,
                record.method,
                record.endpoint,
                record.status,
                str(record.status_code) if record.status_code is not None else "-",
                record.details,
            ]
            for record in self._records
        ]

        widths = []
        for index, header in enumerate(headers):
            content_width = max((len(row[index]) for row in rows), default=0)
            widths.append(max(len(header), content_width))

        def _format_row(values: list[str]) -> str:
            return " | ".join(
                value.ljust(widths[index]) for index, value in enumerate(values)
            )

        separator = "-+-".join("-" * width for width in widths)
        print(_format_row(headers))
        print(separator)
        for row in rows:
            print(_format_row(row))

        attempted = [
            record for record in self._records if record.status in {"PASS", "FAIL"}
        ]
        passed = [record for record in attempted if record.status == "PASS"]
        failed = [record for record in attempted if record.status == "FAIL"]
        skipped = [record for record in self._records if record.status == "SKIPPED"]

        pass_rate = (len(passed) / len(attempted) * 100) if attempted else 0.0
        print("\n-----Summary-----")
        print(f"Passed calls: {len(passed)}")
        print(f"Failed calls: {len(failed)}")
        print(f"Skipped calls: {len(skipped)}")
        print(f"Pass rate: {pass_rate:.2f}%")

    def _unique_name(self, prefix: str) -> str:
        return f"{prefix}-{self._suffix}"

    def _unique_slug(self, prefix: str) -> str:
        slug = self._unique_name(prefix).lower()
        slug = slug.replace("_", "-")
        return "".join(char if char.isalnum() or char == "-" else "-" for char in slug)

    def _unique_env_var_name(self, prefix: str) -> str:
        raw_name = self._unique_name(prefix).upper()
        return "".join(
            char if char.isalnum() or char == "_" else "_" for char in raw_name
        )


def load_config() -> dict[str, Any]:
    with open("./braintest.yaml", "r") as file_handle:
        loaded = yaml.safe_load(file_handle)
    if not isinstance(loaded, dict):
        print(
            "[functionaltest] braintest.yaml did not parse to an object. Using empty config."
        )
        return {}
    return loaded


def run() -> bool:
    load_dotenv()
    config = load_config()
    runner = FunctionalTestRunner(config=config)
    return runner.run()


if __name__ == "__main__":
    success = run()
    raise SystemExit(0 if success else 1)
