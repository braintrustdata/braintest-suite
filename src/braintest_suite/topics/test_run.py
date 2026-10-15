import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from click.testing import CliRunner

import braintest_suite
from braintest_suite.topics import run_module as topics_smoke


class TopicsSmokeTests(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "count": 105,
            "allow_below_threshold": False,
            "idle_seconds": 10,
            "facet_preflight_timeout": 30,
            "function_visibility_timeout": 60,
            "function_visibility_interval": 2,
            "compaction_timeout": 300,
            "compaction_interval": 3,
            "automation_execution_timeout": 30,
            "running_check_timeout": 600,
            "running_check_interval": 3,
            "classification_timeout": 900,
            "classification_interval": 5,
        }
        values.update(overrides)
        return mock.Mock(**values)

    def make_automation(self, **overrides):
        automation = {
            "id": "automation_1",
            "name": topics_smoke.AUTOMATION_NAME,
            "config": {
                "facet_functions": [{"type": "global", "name": "Task", "function_type": "facet"}],
            },
        }
        automation.update(overrides)
        return automation

    def test_count_guardrail_rejects_below_threshold(self):
        args = self.make_args(count=99, allow_below_threshold=False)
        with self.assertRaises(topics_smoke.SmokeError):
            topics_smoke.validate_args(args)

    def test_count_guardrail_can_be_overridden(self):
        args = self.make_args(count=99, allow_below_threshold=True)
        topics_smoke.validate_args(args)

    def test_running_check_interval_guardrail(self):
        args = self.make_args(running_check_interval=0)
        with self.assertRaises(topics_smoke.SmokeError):
            topics_smoke.validate_args(args)

    def test_timestamped_project_name_uses_prefix_and_timestamp(self):
        self.assertEqual(
            topics_smoke.timestamped_project_name("Topics Smoke!", "20260515-120102"),
            "topics-smoke-20260515-120102",
        )

    def test_app_project_topics_url_encodes_path_pieces(self):
        self.assertEqual(
            topics_smoke.app_project_topics_url("Acme / Test", "project/name"),
            "https://www.braintrust.dev/app/Acme%20%2F%20Test/p/project%2Fname/topics",
        )

    def test_build_args_maps_configured_durations(self):
        args = topics_smoke.build_args({"topics": {"count": 110, "topic_window": "2h", "generation_cadence": "30m"}})
        self.assertEqual(args.count, 110)
        self.assertEqual(args.topic_window_seconds, 7200)
        self.assertEqual(args.generation_cadence_seconds, 1800)

    def test_suite_run_uses_configuration(self):
        with mock.patch.object(topics_smoke, "run_create", return_value=0) as run_create:
            self.assertTrue(topics_smoke.run({"topics": {"count": 110}}))
        self.assertEqual(run_create.call_args.args[0].count, 110)

    def test_cli_dispatches_topics_smoke_test(self):
        with mock.patch.object(topics_smoke, "run_create", return_value=0), redirect_stdout(StringIO()):
            status = braintest_suite._run_suite("topics", {"topics": {"count": 110}})
        self.assertEqual(status, "SUCCESS")

    def invoke_cli(self, args, config=None):
        with (
            mock.patch.dict(os.environ),
            mock.patch.object(braintest_suite, "_load_config", return_value=config or {"topics": {}}),
        ):
            return CliRunner().invoke(braintest_suite.cli, args)

    def test_cli_topics_uses_configuration(self):
        config = {
            "braintrust": {"api_url": "https://configured.example"},
            "topics": {"count": 120, "topic_window": "2h", "skip_facet_preflight": True},
        }
        with mock.patch.object(topics_smoke, "run_create", return_value=0) as create:
            result = self.invoke_cli(["run", "topics"], config)
        self.assertEqual(result.exit_code, 0, result.output)
        args = create.call_args.args[0]
        self.assertEqual(args.count, 120)
        self.assertEqual(args.topic_window_seconds, 7200)
        self.assertTrue(args.skip_facet_preflight)
        self.assertEqual(args.api_url, "https://configured.example")

    def test_cli_dry_run_does_not_create_resources(self):
        with (
            mock.patch.object(
                topics_smoke,
                "preview_auth",
                return_value={
                    "org": "test",
                    "api_url": "https://example.com",
                    "note": "test",
                },
            ),
            mock.patch.object(topics_smoke, "api_post") as post,
            mock.patch.object(topics_smoke, "discover_auth") as auth,
        ):
            result = self.invoke_cli(["run", "topics"], {"topics": {"dry_run": True}})
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('"dry_run": true', result.output)
        post.assert_not_called()
        auth.assert_not_called()

    def test_dry_run_without_credentials_or_optional_config(self):
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(StringIO()) as output:
            self.assertTrue(topics_smoke.run({"topics": {"dry_run": True}}))
        self.assertIn('"dry_run": true', output.getvalue())

    def test_cli_status_uses_positional_project_and_configuration(self):
        with mock.patch.object(topics_smoke, "run_status", return_value=0) as status:
            result = self.invoke_cli(
                ["status", "topics", "example"],
                {
                    "braintrust": {"api_url": "https://example.com"},
                    "topics": {"org": "configured", "timeout": 12},
                },
            )
        self.assertEqual(result.exit_code, 0, result.output)
        args = status.call_args.args[0]
        self.assertEqual(args.project, "example")
        self.assertEqual(args.org, "configured")
        self.assertEqual(args.timeout, 12)
        self.assertEqual(args.api_url, "https://example.com")

    def test_cli_rejects_topics_flags(self):
        for command in (["run", "topics"], ["run", "all"], ["run", "functional"], ["status", "topics"]):
            for flag in ("--dry-run", "--count", "--api-url", "--project", "--org"):
                with self.subTest(command=command, flag=flag):
                    result = self.invoke_cli([*command, flag])
                    self.assertEqual(result.exit_code, 2, result.output)
                    self.assertIn("No such option", result.output)

    def test_cli_all_runs_every_suite(self):
        with mock.patch.object(braintest_suite, "_run_suite", return_value="SUCCESS") as run:
            result = self.invoke_cli(["run", "all"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([call.args[0] for call in run.call_args_list], list(braintest_suite.AVAILABLE_SUITES))

    def test_yaml_and_environment_settings(self):
        import tempfile
        from pathlib import Path

        from braintest_suite.config import load_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            source = Path(__file__).resolve().parents[3] / "braintest.yaml"
            path.write_text(source.read_text().replace("dry_run: False", "dry_run: True"))
            with mock.patch.dict(os.environ, {"BRAINTEST_CONFIG_FILE": str(path)}, clear=True):
                self.assertTrue(load_config()["topics"]["dry_run"])
                with mock.patch.dict(
                    os.environ,
                    {
                        "TOPICS__DRY_RUN": "false",
                        "TOPICS__COUNT": "120",
                        "BRAINTRUST__API_URL": "https://override.example",
                    },
                ):
                    args = topics_smoke.build_args(load_config())
                self.assertFalse(args.dry_run)
                self.assertEqual(args.count, 120)
                self.assertEqual(args.api_url, "https://override.example")

    def test_cli_reports_invalid_config_and_missing_status_project(self):
        result = self.invoke_cli(["run", "topics"], {"topics": {"topic_window": "invalid"}})
        self.assertNotEqual(result.exit_code, 0)
        with mock.patch.object(topics_smoke, "run_status") as status:
            result = self.invoke_cli(["status", "topics"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Missing argument", result.output)
        status.assert_not_called()

    def test_status_exposes_stalled_facet_processing(self):
        args = topics_smoke.build_args({})
        args.project = "example"
        ctx = topics_smoke.AuthContext(api_key="key", org_id="org", org_name="test", api_url="https://example.com")
        cursor = {"pending_segments": 1, "last_executed_xact_id": None, "last_error": None}
        counts = {"matched": 0, "processed": 0, "running": 0, "errors": 0, "completed": 0}
        with (
            mock.patch.object(topics_smoke, "discover_auth", return_value=ctx),
            mock.patch.object(topics_smoke, "get_project_by_name", return_value=topics_smoke.Project("pid", "example")),
            mock.patch.object(topics_smoke, "list_topic_automations", return_value=[self.make_automation(id="aid")]),
            mock.patch.object(topics_smoke, "get_topic_facet_status_counts", return_value=counts),
            mock.patch.object(
                topics_smoke,
                "api_post",
                side_effect=[
                    {"topic_runtime": {"state": "waiting_for_facets"}},
                    cursor,
                ],
            ),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(topics_smoke.run_status(args), 0)
        automation = json.loads(output.getvalue())["automations"][0]
        self.assertEqual(automation["facet_counts"], counts)
        self.assertEqual(automation["segment_cursor"], cursor)

    def test_build_trace_events_count_and_shape(self):
        events = topics_smoke.build_trace_events(
            105,
            project_name="topics-smoke-20260515-120102",
            run_id="20260515-120102",
        )
        self.assertEqual(len(events), 105)
        first = events[0]
        self.assertEqual(first["span_id"], first["root_span_id"])
        self.assertEqual(first["span_attributes"]["type"], "llm")
        self.assertEqual(first["input"][0]["role"], "user")
        self.assertEqual(first["output"][0]["role"], "assistant")
        self.assertTrue(first["metadata"]["synthetic"])

    def test_select_org_single_org(self):
        org = topics_smoke.select_org(
            [{"id": "org_1", "name": "acme", "api_url": "https://api.acme"}],
            None,
        )
        self.assertEqual(org["name"], "acme")

    def test_select_org_multiple_requires_requested_org(self):
        with self.assertRaises(topics_smoke.SmokeError):
            topics_smoke.select_org(
                [
                    {"id": "org_1", "name": "acme", "api_url": "https://api.acme"},
                    {"id": "org_2", "name": "other", "api_url": "https://api.other"},
                ],
                None,
            )

    def test_select_org_uses_requested_org(self):
        org = topics_smoke.select_org(
            [
                {"id": "org_1", "name": "acme", "api_url": "https://api.acme"},
                {"id": "org_2", "name": "other", "api_url": "https://api.other"},
            ],
            "other",
        )
        self.assertEqual(org["api_url"], "https://api.other")

    def test_discover_auth_uses_forced_api_url_with_discovered_org(self):
        args = mock.Mock(
            api_key="key",
            org=None,
            api_url="https://forced.example",
            timeout=1,
        )
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                topics_smoke,
                "json_request",
                return_value={
                    "org_info": [
                        {
                            "id": "org_1",
                            "name": "acme",
                            "api_url": "https://discovered.example",
                        }
                    ]
                },
            ),
        ):
            ctx = topics_smoke.discover_auth(args)
        self.assertEqual(ctx.org_name, "acme")
        self.assertEqual(ctx.api_url, "https://forced.example")

    def test_preview_auth_without_key_uses_explicit_values(self):
        args = mock.Mock(
            api_key=None,
            org="acme",
            api_url="https://forced.example",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            preview = topics_smoke.preview_auth(args)
        self.assertEqual(preview["org"], "acme")
        self.assertEqual(preview["api_url"], "https://forced.example")
        self.assertIn("No network calls", preview["note"])

    def test_preview_auth_with_key_discovers_values(self):
        args = mock.Mock(api_key="key", org=None, api_url=None)
        with mock.patch.object(
            topics_smoke,
            "discover_auth",
            return_value=topics_smoke.AuthContext(
                api_key="key",
                org_id="org_1",
                org_name="acme",
                api_url="https://api.acme",
            ),
        ):
            preview = topics_smoke.preview_auth(args)
        self.assertEqual(preview["org"], "acme")
        self.assertEqual(preview["api_url"], "https://api.acme")
        self.assertIn("No project", preview["note"])

    def test_duration_roundtrip(self):
        self.assertEqual(topics_smoke.parse_duration_seconds("1h"), 3600)
        self.assertEqual(topics_smoke.format_duration_seconds(3600), "1h")
        self.assertEqual(topics_smoke.format_duration_seconds(90), "90s")

    def test_api_helpers_send_org_header(self):
        ctx = topics_smoke.AuthContext(
            api_key="key",
            org_id="org_1",
            org_name="acme",
            api_url="https://api.acme",
        )
        with mock.patch.object(topics_smoke, "json_request", return_value={}) as request:
            topics_smoke.api_get(ctx, "/v1/project")
            topics_smoke.api_post(ctx, "/btql", {"query": "select 1"})

        self.assertEqual(request.call_args_list[0].kwargs["org_name"], "acme")
        self.assertEqual(request.call_args_list[1].kwargs["org_name"], "acme")

    def test_list_topic_automations_uses_current_control_plane_route(self):
        rows = [
            {"id": "topic_1", "config": {"event_type": "topic"}},
            {"id": "other_1", "config": {"event_type": "log"}},
        ]
        with mock.patch.object(topics_smoke, "api_post", return_value=rows) as request:
            result = topics_smoke.list_topic_automations(mock.Mock(), "project_1")
        self.assertEqual(result, [rows[0]])
        request.assert_called_once_with(
            mock.ANY,
            "/api/project_automation/get",
            {"project_id": "project_1"},
        )

    def test_inclusive_start_xact_id_matches_cli_formula_shape(self):
        self.assertEqual(
            topics_smoke.inclusive_start_xact_id_from_epoch_ms(0),
            str((0x0DE1 << 48) - 1),
        )

    def test_btql_path_quoting_handles_function_keys(self):
        self.assertEqual(topics_smoke.quote_btql_path_piece("Task"), "Task")
        self.assertEqual(
            topics_smoke.quote_btql_path_piece("global:facet:Task"),
            '"global:facet:Task"',
        )
        self.assertEqual(topics_smoke.quote_btql_path_piece(""), '""')

    def test_read_count_accepts_numeric_shapes(self):
        self.assertEqual(topics_smoke.read_count({"count": 3}, "count"), 3)
        self.assertEqual(topics_smoke.read_count({"count": 3.0}, "count"), 3)
        self.assertEqual(topics_smoke.read_count({"count": "3"}, "count"), 3)
        self.assertEqual(topics_smoke.read_count({"count": "nope"}, "count"), 0)

    def test_verify_expected_running_waits_until_expected_count_is_processed(self):
        args = self.make_args(count=105)
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        with (
            mock.patch.object(
                topics_smoke,
                "get_topic_facet_status_counts",
                side_effect=[
                    {
                        "matched": 105,
                        "processed": 0,
                        "running": 105,
                        "errors": 0,
                        "completed": 0,
                    },
                    {
                        "matched": 105,
                        "processed": 105,
                        "running": 0,
                        "errors": 0,
                        "completed": 105,
                    },
                ],
            ) as counts,
            mock.patch.object(topics_smoke, "execute_topic_automation"),
            mock.patch.object(topics_smoke.time, "sleep"),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                self.make_automation(),
                args,
            )
        self.assertEqual(counts.call_count, 2)
        counts.assert_called_with(
            mock.ANY,
            "project_1",
            "automation_1",
            "Task",
            "global:facet:Task",
        )

    def test_verify_expected_running_keeps_polling_through_transient_errors(self):
        args = self.make_args(count=105)
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        with (
            mock.patch.object(
                topics_smoke,
                "get_topic_facet_status_counts",
                side_effect=[
                    {
                        "matched": 0,
                        "processed": 0,
                        "running": 0,
                        "errors": 0,
                        "completed": 0,
                    },
                    {
                        "matched": 0,
                        "processed": 105,
                        "running": 0,
                        "errors": 0,
                        "completed": 0,
                    },
                ],
            ) as counts,
            mock.patch.object(topics_smoke, "execute_topic_automation"),
            mock.patch.object(topics_smoke.time, "sleep"),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                self.make_automation(),
                args,
            )
        self.assertEqual(counts.call_count, 2)

    def test_verify_expected_running_stops_when_all_expected_rows_error(self):
        args = self.make_args(count=105, running_check_timeout=90)
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        with (
            mock.patch.object(
                topics_smoke,
                "get_topic_facet_status_counts",
                return_value={
                    "matched": 0,
                    "processed": 0,
                    "running": 0,
                    "errors": 105,
                    "completed": 0,
                },
            ) as counts,
            self.assertRaisesRegex(topics_smoke.SmokeError, "reported 105 error"),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                self.make_automation(),
                args,
            )
        counts.assert_called_once()

    def test_status_count_query_treats_finished_attempts_as_errors(self):
        posted_bodies = []

        def fake_api_post(_ctx, path, body):
            posted_bodies.append((path, body))
            if path == "/brainstore/automation/get-cursors":
                return {"pending_min_executed_xact_id": None}
            if path == "/btql":
                return {"data": [{"matched": 0, "processed": 0, "inflight": 105, "errors": 105}]}
            raise AssertionError(path)

        with mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post):
            counts = topics_smoke.get_topic_facet_status_counts(
                mock.Mock(),
                "project_1",
                "automation_1",
                "Task",
            )

        self.assertEqual(counts["running"], 0)
        self.assertEqual(counts["errors"], 105)
        btql_body = posted_bodies[1][1]
        self.assertIn("attempts > 0", btql_body["query"])

    def test_saved_function_ref_key_handles_local_and_global_refs(self):
        self.assertEqual(
            topics_smoke.saved_function_ref_key({"type": "function", "id": "facet_1"}),
            "function_id:facet_1",
        )
        self.assertEqual(
            topics_smoke.saved_function_ref_key({"type": "global", "function_type": "facet", "name": "Task"}),
            "global:facet:Task",
        )

    def test_saved_function_ref_to_use_body_converts_local_and_global_refs(self):
        self.assertEqual(
            topics_smoke.saved_function_ref_to_use_body({"type": "function", "id": "function_1", "version": "123"}),
            {"function_id": "function_1", "version": "123"},
        )
        self.assertEqual(
            topics_smoke.saved_function_ref_to_use_body({"type": "global", "function_type": "facet", "name": "Task"}),
            {"global_function": "Task", "function_type": "facet"},
        )

    def test_verify_function_refs_resolve_calls_function_use_with_project_header(self):
        calls = []

        def fake_api_post(_ctx, path, body, **kwargs):
            calls.append((path, body, kwargs))
            if body["function_id"] == "facet_function_1":
                return {"function_data": {"type": "facet"}}
            if body["function_id"] == "topic_map_function_1":
                return {"function_data": {"type": "topic_map"}}
            raise AssertionError(body)

        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_function_refs_resolve(
                mock.Mock(),
                "project_1",
                {"type": "function", "id": "facet_function_1", "version": "10"},
                {"function": {"type": "function", "id": "topic_map_function_1"}},
                timeout_seconds=0,
                interval_seconds=1,
            )

        self.assertEqual([call[0] for call in calls], ["/function/use", "/function/use"])
        self.assertEqual(calls[0][1], {"function_id": "facet_function_1", "version": "10"})
        self.assertEqual(calls[0][2]["extra_headers"], {"x-bt-project-id": "project_1"})

    def test_verify_function_refs_resolve_waits_through_transient_lookup_failure(self):
        responses = [
            topics_smoke.SmokeError("not found yet"),
            {"function_data": {"type": "facet"}},
            {"function_data": {"type": "topic_map"}},
        ]

        def fake_api_post(_ctx, _path, _body, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post),
            mock.patch.object(topics_smoke.time, "sleep") as sleep,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_function_refs_resolve(
                mock.Mock(),
                "project_1",
                {"type": "function", "id": "facet_function_1"},
                {"function": {"type": "function", "id": "topic_map_function_1"}},
                timeout_seconds=30,
                interval_seconds=1,
            )

        sleep.assert_called_once_with(1)

    def test_create_topic_function_refs_use_builtin_facet_and_create_topic_map(self):
        posted_bodies = []

        def fake_api_post(_ctx, path, body):
            posted_bodies.append((path, body))
            self.assertEqual(path, "/insert-functions")
            return {"functions": [{"id": "topic_map_function_1"}]}

        with mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post):
            facet_ref, topic_map_ref = topics_smoke.create_topic_function_refs(
                mock.Mock(),
                "project_1",
            )

        self.assertEqual(
            facet_ref,
            {"type": "global", "name": "Task", "function_type": "facet"},
        )
        self.assertEqual(
            topic_map_ref,
            {"function": {"type": "function", "id": "topic_map_function_1"}},
        )
        body = posted_bodies[0][1]
        function = body["functions"][0]
        self.assertEqual(function["function_type"], "classifier")
        self.assertEqual(function["slug"], "task-topic-map")
        self.assertEqual(function["function_data"]["source_facet"], "Task")
        self.assertEqual(
            function["function_data"]["source_facet_function"],
            {"type": "global", "name": "Task", "function_type": "facet"},
        )
        self.assertEqual(
            function["function_data"]["embedding_model"],
            topics_smoke.TOPIC_MAP_EMBEDDING_MODEL,
        )

    def test_preflight_topics_pipeline_invokes_async_batch_gateway_path(self):
        args = self.make_args()
        event = {"root_span_id": "root_1"}
        calls = []

        def fake_api_post(_ctx, path, body, **kwargs):
            calls.append((path, body, kwargs))
            if path == "/function/invoke" and body.get("global_function") == "Task":
                return "User wants to test topics"
            if path == "/function/invoke-async-batch":
                return {"status": "success", "succeeded": 1, "failed": 0, "total": 1}
            raise AssertionError(path)

        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.preflight_topics_pipeline(
                mock.Mock(),
                topics_smoke.Project(id="project_1", name="project"),
                event,
                args,
                {"type": "global", "name": "Task", "function_type": "facet"},
            )

        async_call = calls[-1]
        self.assertEqual(async_call[0], "/function/invoke-async-batch")
        self.assertEqual(async_call[1][0]["request"]["global_function"], "Task")
        self.assertEqual(async_call[1][0]["request"]["function_type"], "facet")
        self.assertEqual(async_call[2]["extra_headers"], {"x-bt-use-gateway": "true"})

    def test_seed_topic_cursor_resets_before_upsert(self):
        calls = []

        def fake_api_post(_ctx, path, body, **_kwargs):
            calls.append((path, body))
            return {"success": True}

        with mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post):
            topics_smoke.seed_topic_automation_cursors(
                mock.Mock(),
                "project_1",
                {"id": "automation_1", "config": {}},
                3600,
            )

        self.assertEqual(
            [path for path, _body in calls],
            [
                "/brainstore/automation/reset-cursors",
                "/brainstore/automation/upsert-object-cursor",
            ],
        )

    def test_classification_backfill_rewinds_and_requeues_original_automation(self):
        calls = []

        def fake_api_post(_ctx, path, body, **_kwargs):
            calls.append((path, body))
            return {"success": True}

        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        automation = {"id": "automation_1", "config": {}}
        with mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post):
            topics_smoke.start_topic_classification_backfill(
                mock.Mock(),
                project,
                automation,
                "backfill_start_1",
            )

        self.assertEqual(
            calls,
            [
                (
                    "/brainstore/automation/reset-cursors",
                    {
                        "automation_id": "automation_1",
                        "object_id": "project_logs:project_1",
                        "start_xact_id": "backfill_start_1",
                    },
                ),
                (
                    "/brainstore/automation/upsert-object-cursor",
                    {"automation_id": "automation_1", "object_id": "project_logs:project_1"},
                ),
            ],
        )

    def test_classification_backfill_tolerates_transient_requeue_failure(self):
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        automation = {"id": "automation_1", "config": {}}
        responses = [
            {"success": True},
            topics_smoke.SmokeError("POST upsert-object-cursor failed with HTTP 500"),
        ]

        def fake_api_post(_ctx, _path, _body, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post),
            redirect_stdout(StringIO()) as output,
        ):
            topics_smoke.start_topic_classification_backfill(
                mock.Mock(),
                project,
                automation,
                "backfill_start_1",
            )

        self.assertIn("requeue will be retried", output.getvalue())

    def test_execute_topic_automation_runs_two_passes(self):
        responses = [
            {"successful": 1, "failed": 0, "rows_matched": 105},
            {"successful": 1, "failed": 0, "rows_matched": 0},
        ]
        with mock.patch.object(topics_smoke, "api_post", side_effect=responses) as request:
            result = topics_smoke.execute_topic_automation(
                mock.Mock(),
                "project_1",
                {"id": "automation_1"},
            )

        self.assertEqual(result, {"successful": 2, "failed": 0, "rows_matched": 105})
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.args[1], "/brainstore/automation/execute")
            self.assertEqual(
                call.args[2],
                {
                    "automation_id": "automation_1",
                    "project_id": "project_1",
                    "max_concurrency": 10,
                },
            )
            self.assertEqual(call.kwargs["timeout"], 30)

    def test_execute_topic_automation_treats_gateway_timeout_as_in_progress(self):
        with (
            mock.patch.object(
                topics_smoke,
                "api_post",
                side_effect=topics_smoke.SmokeError("POST execute failed with HTTP 504"),
            ) as request,
            redirect_stdout(StringIO()),
        ):
            result = topics_smoke.execute_topic_automation(
                mock.Mock(),
                "project_1",
                {"id": "automation_1"},
            )

        self.assertEqual(result, {"successful": 0, "failed": 0, "rows_matched": 0})
        request.assert_called_once()

    def test_execute_topic_automation_rejects_failed_work(self):
        responses = [
            {"successful": 0, "failed": 1, "rows_matched": 105},
            {"successful": 0, "failed": 0, "rows_matched": 0},
        ]
        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=responses),
            self.assertRaisesRegex(topics_smoke.SmokeError, "reported failures"),
        ):
            topics_smoke.execute_topic_automation(
                mock.Mock(),
                "project_1",
                {"id": "automation_1"},
            )

    def test_classification_count_is_scoped_to_the_original_automation(self):
        with mock.patch.object(
            topics_smoke,
            "api_post",
            return_value={"data": [{"count": 105}]},
        ) as post:
            count = topics_smoke.get_topic_classification_count(
                mock.Mock(),
                "project_1",
                "Task",
                "Topics smoke",
            )

        self.assertEqual(count, 105)
        query = post.call_args.args[2]["query"]
        self.assertIn("count(classifications.Task)", query)
        self.assertIn("classifications.Task is not null", query)
        self.assertIn("span_attributes.type = 'automation'", query)
        self.assertIn("name = 'Topics smoke'", query)

    def test_classification_wait_checks_results_before_executing_again(self):
        args = self.make_args(count=105)
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        with (
            mock.patch.object(topics_smoke, "get_topic_classification_count", return_value=105),
            mock.patch.object(topics_smoke, "execute_topic_automation") as execute,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.wait_for_topic_classifications(
                mock.Mock(),
                project,
                {"id": "automation_1", "name": "Topics smoke"},
                "Task",
                args,
            )

        execute.assert_not_called()

    def test_topic_map_wait_checks_runtime_before_executing_again(self):
        args = self.make_args()
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        cursor = {
            "topic_runtime": {
                "state": "backfilling_topic_classifications",
                "active_topic_map_versions": {"function_1": "version_1"},
                "topic_classification_backfill_start_xact_id": "start_1",
            }
        }
        with (
            mock.patch.object(topics_smoke, "api_post", return_value=cursor),
            mock.patch.object(topics_smoke, "execute_topic_automation") as execute,
            redirect_stdout(StringIO()),
        ):
            result = topics_smoke.wait_for_generated_topic_map(
                mock.Mock(),
                project,
                {"id": "automation_1", "config": {}},
                "function_1",
                args,
            )

        self.assertEqual(result, ("version_1", "start_1"))
        execute.assert_not_called()

    def test_wait_for_trace_idle_includes_clock_granularity_buffer(self):
        with (
            mock.patch.object(topics_smoke.time, "monotonic", return_value=105),
            mock.patch.object(topics_smoke.time, "sleep") as sleep,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.wait_for_trace_idle(inserted_at=100, idle_seconds=10)
        sleep.assert_called_once_with(6)

    def test_wait_for_compacted_traces_uses_non_realtime_data(self):
        responses = [
            {"data": [{"count": 1}]},
            {"data": [{"count": 105}]},
        ]
        project = topics_smoke.Project(id="project_1", name="project")
        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=responses) as request,
            mock.patch.object(topics_smoke.time, "monotonic", side_effect=[0, 1]),
            mock.patch.object(topics_smoke.time, "sleep") as sleep,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.wait_for_compacted_traces(
                mock.Mock(),
                project,
                "run_1",
                105,
                timeout_seconds=300,
                interval_seconds=3,
            )

        self.assertEqual(request.call_count, 2)
        body = request.call_args_list[0].args[2]
        self.assertFalse(body["brainstore_realtime"])
        self.assertFalse(body["brainstore_ephemeral_wal"])
        self.assertIn("metadata.run_id = 'run_1'", body["query"])
        sleep.assert_called_once_with(3)

    def test_wait_for_compacted_facets_uses_non_realtime_data(self):
        responses = [
            {"data": [{"count": 75}]},
            {"data": [{"count": 100}]},
        ]
        project = topics_smoke.Project(id="project_1", name="project")
        with (
            mock.patch.object(topics_smoke, "api_post", side_effect=responses) as request,
            mock.patch.object(topics_smoke.time, "monotonic", side_effect=[0, 1]),
            mock.patch.object(topics_smoke.time, "sleep") as sleep,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.wait_for_compacted_facet_outputs(
                mock.Mock(),
                project,
                "Topics smoke",
                "Task",
                100,
                timeout_seconds=300,
                interval_seconds=5,
            )

        self.assertEqual(request.call_count, 2)
        body = request.call_args_list[0].args[2]
        self.assertFalse(body["brainstore_realtime"])
        self.assertFalse(body["brainstore_ephemeral_wal"])
        self.assertIn("count(facets.Task)", body["query"])
        self.assertIn("name = 'Topics smoke'", body["query"])
        sleep.assert_called_once_with(5)

    def test_wait_for_compacted_traces_times_out(self):
        project = topics_smoke.Project(id="project_1", name="project")
        with (
            mock.patch.object(topics_smoke, "api_post", return_value={"data": [{"count": 2}]}),
            mock.patch.object(topics_smoke.time, "monotonic", side_effect=[0, 10]),
            self.assertRaisesRegex(topics_smoke.SmokeError, "2/105"),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.wait_for_compacted_traces(
                mock.Mock(),
                project,
                "run_1",
                105,
                timeout_seconds=10,
                interval_seconds=1,
            )


if __name__ == "__main__":
    unittest.main()
