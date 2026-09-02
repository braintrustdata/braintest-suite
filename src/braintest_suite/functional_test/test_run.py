import gzip
import json
import unittest
from unittest.mock import patch

import requests
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from braintest_suite.functional_test.run import FunctionalTestRunner
from braintest_suite.util import http_client


def _protobuf_span_name(payload: bytes) -> str:
    request = ExportTraceServiceRequest()
    request.ParseFromString(payload)
    return request.resource_spans[0].scope_spans[0].spans[0].name


class FakeResponse:
    def __init__(self, body=None, content=b"", status_code=200):
        self._body = body if body is not None else {}
        self.content = content
        self.status_code = status_code
        self.text = "" if not body else "response"

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(response=self)
            raise error


class FunctionalEndpointCoverageTest(unittest.TestCase):
    def setUp(self):
        self.runner = FunctionalTestRunner(
            {
                "braintrust": {
                    "api_url": "https://api.example.test/v1",
                    "project_name": "functional-project",
                },
                "functionaltest": {"name_prefix": "functional-test"},
            }
        )
        self.runner._headers["Authorization"] = "Bearer test-key"

    @patch("braintest_suite.functional_test.run.requests.request")
    @patch("braintest_suite.functional_test.run.http_client")
    def test_attachment_upload_status_and_download(self, http_client_mock, request_mock):
        self.runner._resource_ids.update({"org_id": "org-id", "project_id": "project-id"})
        attachment_data = b"functional test attachment\n"
        http_client_mock.side_effect = [
            FakeResponse({"signedUrl": "https://uploads.example.test/attachment", "headers": {}}),
            FakeResponse({}),
            FakeResponse(
                {
                    "status": {"upload_status": "done"},
                    "downloadUrl": "https://downloads.example.test/attachment",
                }
            ),
            FakeResponse({}),
            FakeResponse({}),
        ]
        request_mock.side_effect = [FakeResponse(), FakeResponse(content=attachment_data)]

        self.runner._upload_and_read_attachment()
        self.runner._insert_and_fetch_project_logs()

        self.assertIsNotNone(self.runner._attachment_reference)
        self.assertEqual(
            [call.kwargs["method"] for call in http_client_mock.call_args_list],
            ["POST", "POST", "GET", "POST", "GET"],
        )
        self.assertEqual(http_client_mock.call_args_list[0].kwargs["url"], "https://api.example.test/attachment")
        self.assertEqual(http_client_mock.call_args_list[1].kwargs["url"], "https://api.example.test/attachment/status")
        self.assertTrue(
            http_client_mock.call_args_list[2].kwargs["url"].startswith("https://api.example.test/attachment?key=")
        )
        self.assertEqual(
            http_client_mock.call_args_list[3].kwargs["payload"]["events"][0]["input"]["attachment"],
            self.runner._attachment_reference,
        )
        self.assertEqual(request_mock.call_args_list[0].kwargs["method"], "PUT")
        self.assertEqual(request_mock.call_args_list[0].kwargs["data"], attachment_data)
        self.assertEqual(request_mock.call_args_list[1].kwargs["method"], "GET")
        self.assertTrue(all(record.status == "PASS" for record in self.runner._records))

    @patch("braintest_suite.functional_test.run.http_client")
    def test_otel_trace_covers_json_and_protobuf_with_and_without_gzip(self, http_client_mock):
        self.runner._resource_ids["project_id"] = "project-id"
        http_client_mock.return_value = FakeResponse()

        self.runner._ingest_otel_trace()

        self.assertEqual(http_client_mock.call_count, 4)
        requests_by_name = {
            request.kwargs["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"]: request
            for request in http_client_mock.call_args_list
            if request.kwargs["payload"] is not None
        }
        json_request = requests_by_name["functional.otel.trace.json"]
        self.assertEqual(json_request.kwargs["method"], "POST")
        self.assertEqual(json_request.kwargs["url"], "https://api.example.test/otel/v1/traces")
        self.assertEqual(json_request.kwargs["headers"]["Content-Type"], "application/json")
        self.assertNotIn("Content-Encoding", json_request.kwargs["headers"])

        gzip_json_request = http_client_mock.call_args_list[1]
        self.assertEqual(gzip_json_request.kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(gzip_json_request.kwargs["headers"]["Content-Encoding"], "gzip")
        gzip_json_payload = json.loads(gzip.decompress(gzip_json_request.kwargs["data"]))
        self.assertEqual(
            gzip_json_payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"],
            "functional.otel.trace.json.gzip",
        )

        protobuf_request = http_client_mock.call_args_list[2]
        self.assertEqual(protobuf_request.kwargs["headers"]["Content-Type"], "application/x-protobuf")
        self.assertNotIn("Content-Encoding", protobuf_request.kwargs["headers"])
        self.assertEqual(_protobuf_span_name(protobuf_request.kwargs["data"]), "functional.otel.trace.protobuf")

        gzip_protobuf_request = http_client_mock.call_args_list[3]
        self.assertEqual(gzip_protobuf_request.kwargs["headers"]["Content-Type"], "application/x-protobuf")
        self.assertEqual(gzip_protobuf_request.kwargs["headers"]["Content-Encoding"], "gzip")
        self.assertEqual(
            _protobuf_span_name(gzip.decompress(gzip_protobuf_request.kwargs["data"])),
            "functional.otel.trace.protobuf.gzip",
        )

        for request in http_client_mock.call_args_list:
            self.assertEqual(request.kwargs["headers"]["x-bt-parent"], "project_id:project-id")
        self.assertTrue(all(record.status == "PASS" for record in self.runner._records))

    @patch("braintest_suite.functional_test.run.http_client")
    def test_otel_json_partial_success_is_failure(self, http_client_mock):
        self.runner._resource_ids["project_id"] = "project-id"
        http_client_mock.side_effect = [
            FakeResponse({"partialSuccess": {"rejectedSpans": 1, "errorMessage": "span dropped"}}),
            FakeResponse(),
            FakeResponse(),
            FakeResponse(),
        ]

        self.runner._ingest_otel_trace()

        json_record = self.runner._records[0]
        self.assertEqual(json_record.call, "Ingest OTEL trace (JSON)")
        self.assertEqual(json_record.status, "FAIL")
        self.assertEqual(json_record.status_code, 200)
        self.assertIn("rejected 1 span", json_record.details)
        self.assertIn("span dropped", json_record.details)
        self.assertTrue(all(record.status == "PASS" for record in self.runner._records[1:]))

    @patch("braintest_suite.functional_test.run.http_client")
    def test_otel_protobuf_partial_success_is_failure(self, http_client_mock):
        self.runner._resource_ids["project_id"] = "project-id"
        proto_response = ExportTraceServiceResponse()
        proto_response.partial_success.rejected_spans = 2
        proto_response.partial_success.error_message = "invalid parent"
        http_client_mock.side_effect = [
            FakeResponse(),
            FakeResponse(),
            FakeResponse(content=proto_response.SerializeToString()),
            FakeResponse(),
        ]

        self.runner._ingest_otel_trace()

        protobuf_record = self.runner._records[2]
        self.assertEqual(protobuf_record.call, "Ingest OTEL trace (protobuf)")
        self.assertEqual(protobuf_record.status, "FAIL")
        self.assertEqual(protobuf_record.status_code, 200)
        self.assertIn("rejected 2 span", protobuf_record.details)
        self.assertIn("invalid parent", protobuf_record.details)

    @patch("braintest_suite.util.requests.request")
    def test_http_client_sends_raw_otlp_payload_without_json_encoding(self, request_mock):
        request_mock.return_value = FakeResponse()

        http_client(
            method="POST",
            url="https://api.example.test/otel/v1/traces",
            data=b"otlp-protobuf",
            headers={"Content-Type": "application/x-protobuf"},
        )

        self.assertEqual(request_mock.call_args.kwargs["data"], b"otlp-protobuf")
        self.assertNotIn("json", request_mock.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
