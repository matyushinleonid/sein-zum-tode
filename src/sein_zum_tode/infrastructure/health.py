import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock, Thread
from time import monotonic
from typing import Protocol

from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class HealthCheck(Protocol):
    @property
    def name(self) -> str: ...

    def check(self) -> Awaitable[bool | None]: ...


@dataclass(frozen=True, slots=True)
class CallableHealthCheck:
    name: str
    probe: Callable[[], Awaitable[object]]

    async def check(self) -> bool | None:
        outcome = await self.probe()
        if outcome is False:
            return False
        return True


@dataclass(slots=True)
class DependencyStatus:
    healthy: bool = False
    consecutive_successes: int = 0
    consecutive_failures: int = 0


@dataclass(frozen=True, slots=True)
class HealthReport:
    healthy: bool
    checks: Mapping[str, bool]

    def body(self) -> bytes:
        return json.dumps(
            {
                "status": "ok" if self.healthy else "unavailable",
                "checks": self.checks,
            },
            sort_keys=True,
        ).encode()


class HealthState:
    def __init__(
        self,
        *,
        dependencies: tuple[str, ...],
        freshness_limits: Mapping[str, float] | None = None,
        liveness_timeout_seconds: float,
        success_threshold: int,
        failure_threshold: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._clock = clock
        self._liveness_timeout_seconds = liveness_timeout_seconds
        self._success_threshold = success_threshold
        self._failure_threshold = failure_threshold
        self._dependencies = {name: DependencyStatus() for name in dependencies}
        self._freshness_limits = dict(freshness_limits or {})
        self._freshness: dict[str, float] = {}
        self._startup_complete = False
        self._stopping = False
        self._last_heartbeat = clock()
        self._lock = RLock()

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = self._clock()

    def startup_completed(self) -> None:
        with self._lock:
            self._startup_complete = True

    def stopping(self) -> None:
        with self._lock:
            self._stopping = True

    def signal(self, name: str) -> None:
        with self._lock:
            if name not in self._freshness_limits:
                raise ValueError(f"Unknown freshness signal: {name}")
            self._freshness[name] = self._clock()

    def observe(self, name: str, *, healthy: bool) -> None:
        with self._lock:
            status = self._dependencies[name]
            if healthy:
                status.consecutive_successes += 1
                status.consecutive_failures = 0
                if status.consecutive_successes >= self._success_threshold:
                    status.healthy = True
            else:
                status.consecutive_failures += 1
                status.consecutive_successes = 0
                if status.consecutive_failures >= self._failure_threshold:
                    status.healthy = False

    def live(self) -> HealthReport:
        with self._lock:
            loop_healthy = (
                not self._stopping
                and self._clock() - self._last_heartbeat <= self._liveness_timeout_seconds
            )
            return HealthReport(healthy=loop_healthy, checks={"event_loop": loop_healthy})

    def started(self) -> HealthReport:
        with self._lock:
            started = self._startup_complete and not self._stopping
            return HealthReport(healthy=started, checks={"startup": started})

    def ready(self) -> HealthReport:
        with self._lock:
            checks = {name: status.healthy for name, status in self._dependencies.items()}
            now = self._clock()
            checks.update(
                {
                    name: (name in self._freshness and now - self._freshness[name] <= maximum_age)
                    for name, maximum_age in self._freshness_limits.items()
                }
            )
            checks["startup"] = self._startup_complete and not self._stopping
            event_loop = (
                not self._stopping and now - self._last_heartbeat <= self._liveness_timeout_seconds
            )
            checks["event_loop"] = event_loop
            return HealthReport(healthy=all(checks.values()), checks=checks)


class HealthMonitor:
    def __init__(
        self,
        *,
        state: HealthState,
        checks: tuple[HealthCheck, ...],
        interval_seconds: float,
        timeout_seconds: float,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._state = state
        self._checks = checks
        self._interval_seconds = interval_seconds
        self._timeout_seconds = timeout_seconds
        self._metrics = metrics or NoopApplicationMetrics()

    async def check(self) -> None:
        self._state.heartbeat()
        outcomes = await asyncio.gather(*(self._check(item) for item in self._checks))
        for item, healthy in zip(self._checks, outcomes, strict=True):
            self._state.observe(item.name, healthy=healthy)
            self._metrics.health_dependency(name=item.name, healthy=healthy)

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await self.check()
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue

    async def _check(self, item: HealthCheck) -> bool:
        try:
            outcome = await asyncio.wait_for(
                item.check(),
                timeout=self._timeout_seconds,
            )
        except Exception:
            return False
        return outcome is not False


class IngressHealth:
    def __init__(self, state: HealthState) -> None:
        self._state = state

    def polling_started(self) -> None:
        self._state.startup_completed()

    def polling_succeeded(self) -> None:
        self._state.signal("telegram_polling")


class HealthEndpoint:
    def __init__(self, state: HealthState) -> None:
        self._state = state

    def response(self, path: str) -> tuple[int, bytes]:
        reports = {
            "/health/live": self._state.live,
            "/health/startup": self._state.started,
            "/health/ready": self._state.ready,
        }
        report_factory = reports.get(path)
        if report_factory is None:
            return 404, b'{"status":"not_found"}'
        report = report_factory()
        return (200 if report.healthy else 503), report.body()


def health_handler(endpoint: HealthEndpoint) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, body = endpoint.response(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return None

    return Handler


class HealthHttpServer:
    def __init__(self, *, server: ThreadingHTTPServer, thread: Thread) -> None:
        self._server = server
        self._thread = thread

    @classmethod
    def start(
        cls,
        *,
        host: str,
        port: int,
        state: HealthState,
    ) -> HealthHttpServer:
        server = ThreadingHTTPServer((host, port), health_handler(HealthEndpoint(state)))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return cls(server=server, thread=thread)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
