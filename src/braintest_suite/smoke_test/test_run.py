import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

import braintest_suite
from braintest_suite.smoke_test import run_module as topics_smoke


class TopicsSmokeTests(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "count": 105,
            "allow_below_threshold": False,
            "idle_seconds": 10,
            "facet_preflight_timeout": 30,
            "function_visibility_timeout": 60,
            "function_visibility_interval": 2,
            "running_check_timeout": 90,
            "running_check_interval": 3,
        }
        values.update(overrides)
        return mock.Mock(**values)

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

    def test_terminal_hyperlink_includes_clickable_label_and_visible_url(self):
        link = topics_smoke.terminal_hyperlink("Topics results", "https://example.com/topics")
        self.assertIn("\033]8;;https://example.com/topics\aTopics results", link)
        self.assertTrue(link.endswith(" (https://example.com/topics)"))

    def test_parser_has_no_model_or_facet_override_flags(self):
        parser = topics_smoke.build_parser()
        with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
            parser.parse_args(["--dry-run", "--facet-model", "brain-facet-2"])
        with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
            parser.parse_args(["--dry-run", "--facet", "Task"])

    def test_configured_defaults_maps_durations(self):
        defaults = topics_smoke.configured_defaults(
            {
                "count": 110,
                "topic_window": "2h",
                "generation_cadence": "30m",
            }
        )
        self.assertEqual(defaults["count"], 110)
        self.assertEqual(defaults["topic_window_seconds"], 7200)
        self.assertEqual(defaults["generation_cadence_seconds"], 1800)

    def test_suite_run_uses_configuration(self):
        with mock.patch.object(topics_smoke, "run_create", return_value=0) as run_create:
            self.assertTrue(topics_smoke.run({"smoketest": {"count": 110}}))
        self.assertEqual(run_create.call_args.args[0].count, 110)

    def test_all_excludes_topics_smoke_test(self):
        self.assertIn("smoketest", braintest_suite.AVAILABLE_SUITES)
        self.assertNotIn("smoketest", braintest_suite.DEFAULT_SUITES)

    def test_cli_dispatches_topics_smoke_test(self):
        with mock.patch.object(topics_smoke, "run_create", return_value=0), redirect_stdout(StringIO()):
            status = braintest_suite._run_suite("smoketest", {"smoketest": {"count": 110}})
        self.assertEqual(status, "SUCCESS")

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

    def test_verify_expected_running_passes_when_expected_count_seen(self):
        args = self.make_args(count=105)
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        with (
            mock.patch.object(
                topics_smoke,
                "get_topic_facet_status_counts",
                return_value={
                    "matched": 0,
                    "processed": 0,
                    "running": 105,
                    "errors": 0,
                    "completed": 0,
                },
            ) as counts,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                {"id": "automation_1"},
                ["Task"],
                args,
            )
        counts.assert_called_once_with(
            mock.ANY,
            "project_1",
            "automation_1",
            "Task",
            ["global:facet:Task"],
        )

    def test_verify_expected_running_passes_when_expected_count_already_processed(self):
        args = self.make_args(count=105)
        project = topics_smoke.Project(id="project_1", name="topics-smoke-test")
        with (
            mock.patch.object(
                topics_smoke,
                "get_topic_facet_status_counts",
                return_value={
                    "matched": 105,
                    "processed": 105,
                    "running": 0,
                    "errors": 0,
                    "completed": 105,
                },
            ) as counts,
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                {"id": "automation_1"},
                ["Task"],
                args,
            )
        counts.assert_called_once()

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
                        "processed": 0,
                        "running": 105,
                        "errors": 0,
                        "completed": 0,
                    },
                ],
            ) as counts,
            mock.patch.object(topics_smoke.time, "sleep"),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                {"id": "automation_1"},
                ["Task"],
                args,
            )
        self.assertEqual(counts.call_count, 2)

    def test_verify_expected_running_fails_on_persistent_errors_at_timeout(self):
        args = self.make_args(count=105, running_check_timeout=0)
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
            ),
            self.assertRaises(topics_smoke.SmokeError),
            redirect_stdout(StringIO()),
        ):
            topics_smoke.verify_expected_running(
                mock.Mock(),
                project,
                {"id": "automation_1"},
                ["Task"],
                args,
            )

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
                {"id": "automation_1"},
                ["Task"],
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

    def test_saved_function_ref_from_inserted_function_keeps_version(self):
        self.assertEqual(
            topics_smoke.saved_function_ref_from_inserted_function(
                {"id": "function_1"},
                {"xact_id": "123"},
            ),
            {"type": "function", "id": "function_1", "version": "123"},
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
                [{"type": "function", "id": "facet_function_1", "version": "10"}],
                [{"function": {"type": "function", "id": "topic_map_function_1"}}],
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
                [{"type": "function", "id": "facet_function_1"}],
                [{"function": {"type": "function", "id": "topic_map_function_1"}}],
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
            facet_names, facet_refs, topic_map_refs = topics_smoke.create_topic_function_refs(
                mock.Mock(),
                "project_1",
            )

        self.assertEqual(facet_names, ["Task"])
        self.assertEqual(
            facet_refs,
            [{"type": "global", "name": "Task", "function_type": "facet"}],
        )
        self.assertEqual(
            topic_map_refs,
            [{"function": {"type": "function", "id": "topic_map_function_1"}}],
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

    def test_enable_topics_uses_builtin_facet_without_facet_model_override(self):
        posted_bodies = []

        def fake_api_post(_ctx, path, body):
            posted_bodies.append((path, body))
            if path == "/insert-functions":
                return {"functions": [{"id": "topic_map_function_1"}]}
            if path == "/api/project_automation/register":
                return {
                    "project_automation": {
                        "id": "automation_1",
                        "config": body["config"],
                    }
                }
            return {}

        args = self.make_args(
            generation_cadence_seconds=3600,
            topic_window_seconds=3600,
        )
        with (
            mock.patch.object(topics_smoke, "list_topic_automations", return_value=[]),
            mock.patch.object(topics_smoke, "api_post", side_effect=fake_api_post),
            mock.patch.object(topics_smoke, "seed_topic_automation_cursors"),
        ):
            topics_smoke.enable_topics(
                mock.Mock(),
                topics_smoke.Project(id="project_1", name="project"),
                args,
            )

        register_body = next(body for path, body in posted_bodies if path == "/api/project_automation/register")
        self.assertFalse(register_body["update"])
        self.assertNotIn("facet_model", register_body["config"])
        self.assertNotIn("relabel_overlap_seconds", register_body["config"])
        self.assertEqual(
            register_body["config"]["facet_functions"],
            [{"type": "global", "name": "Task", "function_type": "facet"}],
        )
        self.assertEqual(
            register_body["config"]["topic_map_functions"],
            [{"function": {"type": "function", "id": "topic_map_function_1"}}],
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
                ["Task"],
                [{"type": "global", "name": "Task", "function_type": "facet"}],
            )

        async_call = calls[-1]
        self.assertEqual(async_call[0], "/function/invoke-async-batch")
        self.assertEqual(async_call[1][0]["request"]["global_function"], "Task")
        self.assertEqual(async_call[1][0]["request"]["function_type"], "facet")
        self.assertEqual(async_call[2]["extra_headers"], {"x-bt-use-gateway": "true"})

    def test_seed_topic_cursor_upserts_before_reset(self):
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
                "/brainstore/automation/upsert-object-cursor",
                "/brainstore/automation/reset-cursors",
            ],
        )


if __name__ == "__main__":
    unittest.main()
