import queue
import threading
import time
from urllib.parse import urlparse

import gevent
from gevent.event import Event as GeventEvent
from requests.adapters import HTTPAdapter


def _metric_path(path: str) -> str:
    if not path:
        return "/"
    return path if path.startswith("/") else f"/{path}"


class BraintrustMetricsEmitter:
    """Bridges adapter threads to Locust's gevent event loop."""

    def __init__(self, environment, flush_interval_s: float = 0.1):
        self.environment = environment
        self.flush_interval_s = flush_interval_s
        self._queue = queue.Queue()
        self._stop_event = GeventEvent()
        self._greenlet = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._greenlet is not None:
                return
            self._stop_event.clear()
            self._greenlet = gevent.spawn(self._run)

    def stop(self, timeout_s: float = 5.0) -> None:
        with self._lock:
            if self._greenlet is None:
                return
            self._stop_event.set()
            self._greenlet.join(timeout=timeout_s)
            if not self._greenlet.dead:
                self._greenlet.kill(block=False)
            self._greenlet = None

    def record(
        self,
        *,
        request_type: str,
        name: str,
        response_time: float,
        response_length: int,
        exception: Exception | None,
        context: dict,
    ) -> None:
        self._queue.put(
            {
                "request_type": request_type,
                "name": name,
                "response_time": response_time,
                "response_length": response_length,
                "exception": exception,
                "context": context,
            }
        )

    def _drain(self) -> None:
        while True:
            try:
                metric = self._queue.get_nowait()
            except queue.Empty:
                return
            self.environment.events.request.fire(**metric)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._drain()
            gevent.sleep(self.flush_interval_s)
        self._drain()


class BraintrustMetricsAdapter(HTTPAdapter):
    def __init__(self, emitter: BraintrustMetricsEmitter, known_braintrust_hosts: set[str], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.emitter = emitter
        self.known_braintrust_hosts = {h.lower() for h in known_braintrust_hosts if h}

    def _metric_name(self, method: str, host: str, path: str) -> str:
        if host in self.known_braintrust_hosts or "braintrust" in host:
            return f"bt {method} {path}"
        return f"bt_external {method} /logs3_overflow_upload"

    @staticmethod
    def _header_content_length(headers) -> int:
        value = headers.get("Content-Length", "")
        return int(value) if value.isdigit() else 0

    @staticmethod
    def _as_http_error(response) -> Exception | None:
        if response.status_code < 400:
            return None
        body = response.text or ""
        return RuntimeError(f"HTTP {response.status_code} {response.reason}: {body}")

    @classmethod
    def _request_size_bytes(cls, request) -> int:
        size_from_header = cls._header_content_length(request.headers or {})
        if size_from_header > 0:
            return size_from_header

        body = request.body
        if body is None:
            return 0
        if isinstance(body, (bytes, bytearray)):
            return len(body)
        if isinstance(body, str):
            return len(body.encode("utf-8"))
        if hasattr(body, "__len__"):
            try:
                return len(body)
            except Exception:
                return 0
        return 0

    def send(self, request, *args, **kwargs):
        start = time.perf_counter()
        parsed = urlparse(request.url or "")
        host = (parsed.netloc or "").lower()
        method = (request.method or "UNKNOWN").upper()
        path = _metric_path(parsed.path or "/")
        name = self._metric_name(method, host, path)

        response = None
        exception = None
        request_size = self._request_size_bytes(request)
        status_code = None

        try:
            response = super().send(request, *args, **kwargs)
            status_code = response.status_code
            exception = self._as_http_error(response)
            return response
        except Exception as e:
            exception = e
            raise
        finally:
            self.emitter.record(
                request_type=method,
                name=name,
                response_time=(time.perf_counter() - start) * 1000,
                response_length=request_size,
                exception=exception,
                context={"host": host, "path": path, "status_code": status_code},
            )
