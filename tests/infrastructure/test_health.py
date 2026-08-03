import asyncio
from io import BytesIO
from typing import Any

import pytest

import sein_zum_tode.infrastructure.health as health_module
from sein_zum_tode.infrastructure.health import (
    CallableHealthCheck,
    HealthEndpoint,
    HealthHttpServer,
    HealthMonitor,
    HealthState,
    IngressHealth,
    health_handler,
)
from sein_zum_tode.ports.metrics import NoopApplicationMetrics

pytestmark = pytest.mark.fast


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class HealthMetrics(NoopApplicationMetrics):
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def health_dependency(self, *, name: str, healthy: bool) -> None:
        self.events.append((name, healthy))


class Probe:
    def __init__(self, result: object) -> None:
        self.result = result

    async def __call__(self) -> object:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def state(clock: Clock) -> HealthState:
    return HealthState(
        dependencies=("redis", "temporal"),
        freshness_limits={"telegram_polling": 70},
        liveness_timeout_seconds=30,
        success_threshold=2,
        failure_threshold=2,
        clock=clock,
    )


def test_exposes_distinct_startup_liveness_and_dependency_readiness() -> None:
    clock = Clock()
    subject = state(clock)
    ingress = IngressHealth(subject)

    ingress.polling_started()
    ingress.polling_succeeded()
    for dependency in ("redis", "temporal"):
        subject.observe(dependency, healthy=True)
        subject.observe(dependency, healthy=True)

    assert (
        subject.started().healthy,
        subject.live().healthy,
        subject.ready().healthy,
        subject.ready().checks,
    ) == (
        True,
        True,
        True,
        {
            "redis": True,
            "temporal": True,
            "telegram_polling": True,
            "startup": True,
            "event_loop": True,
        },
    ), "health state conflated startup, event-loop liveness, and useful readiness"


def test_applies_hysteresis_and_freshness_without_restarting_for_one_failure() -> None:
    clock = Clock()
    subject = state(clock)
    subject.startup_completed()
    subject.signal("telegram_polling")
    for dependency in ("redis", "temporal"):
        subject.observe(dependency, healthy=True)
        subject.observe(dependency, healthy=True)
    subject.observe("redis", healthy=False)
    before_threshold = subject.ready().healthy
    subject.observe("redis", healthy=False)
    after_threshold = subject.ready().healthy
    subject.observe("redis", healthy=True)
    subject.observe("redis", healthy=True)
    clock.now += 71

    assert (
        before_threshold,
        after_threshold,
        subject.ready().healthy,
        subject.ready().checks["telegram_polling"],
    ) == (True, False, False, False), (
        "readiness ignored hysteresis or treated stale Telegram polling as healthy"
    )


def test_detects_a_stalled_event_loop_and_graceful_shutdown() -> None:
    clock = Clock()
    subject = state(clock)
    subject.startup_completed()
    clock.now += 31
    stalled = subject.live()
    subject.heartbeat()
    recovered = subject.live()
    subject.stopping()

    assert (
        stalled.healthy,
        recovered.healthy,
        subject.live().healthy,
        subject.started().healthy,
    ) == (False, True, False, False), "liveness failed to distinguish a stall from shutdown"


def test_rejects_an_unknown_freshness_signal() -> None:
    with pytest.raises(ValueError, match="Unknown freshness signal"):
        state(Clock()).signal("postgres")


async def test_monitor_records_success_false_and_exception_outcomes() -> None:
    clock = Clock()
    current = HealthState(
        dependencies=("redis", "temporal", "postgres"),
        liveness_timeout_seconds=30,
        success_threshold=1,
        failure_threshold=1,
        clock=clock,
    )
    metrics = HealthMetrics()
    monitor = HealthMonitor(
        state=current,
        checks=(
            CallableHealthCheck(name="redis", probe=Probe(True)),
            CallableHealthCheck(name="temporal", probe=Probe(False)),
            CallableHealthCheck(name="postgres", probe=Probe(RuntimeError("offline"))),
        ),
        interval_seconds=1,
        timeout_seconds=1,
        metrics=metrics,
    )

    await monitor.check()

    assert (
        current.ready().checks,
        metrics.events,
    ) == (
        {
            "redis": True,
            "temporal": False,
            "postgres": False,
            "startup": False,
            "event_loop": True,
        },
        [("redis", True), ("temporal", False), ("postgres", False)],
    ), "dependency monitor hid a failed or exceptional health check"


async def test_monitor_runs_until_the_stop_event_interrupts_its_wait() -> None:
    current = HealthState(
        dependencies=("redis",),
        liveness_timeout_seconds=30,
        success_threshold=1,
        failure_threshold=1,
    )
    stop = asyncio.Event()
    monitor = HealthMonitor(
        state=current,
        checks=(CallableHealthCheck(name="redis", probe=Probe(True)),),
        interval_seconds=0.001,
        timeout_seconds=1,
    )
    task = asyncio.create_task(monitor.run(stop))
    await asyncio.sleep(0.003)
    stop.set()

    await task

    assert (current.live().healthy, current.ready().checks["redis"]) == (
        True,
        True,
    ), "health monitor stopped refreshing its heartbeat or default metrics broke checks"


def test_routes_each_health_endpoint_and_rejects_unknown_paths() -> None:
    clock = Clock()
    current = state(clock)
    endpoint = HealthEndpoint(current)
    live = endpoint.response("/health/live")
    startup = endpoint.response("/health/startup")
    ready = endpoint.response("/health/ready")
    missing = endpoint.response("/robots.txt")

    assert (
        live[0],
        startup[0],
        ready[0],
        missing,
        b'"status": "ok"' in live[1],
    ) == (
        200,
        503,
        503,
        (404, b'{"status":"not_found"}'),
        True,
    ), "health HTTP routing returned the wrong status or body"


def test_http_handler_writes_the_endpoint_response_without_access_logs() -> None:
    current = state(Clock())
    handler_type = health_handler(HealthEndpoint(current))
    handler: Any = handler_type.__new__(handler_type)
    handler.path = "/health/live"
    handler.wfile = BytesIO()
    events: list[tuple[object, ...]] = []
    handler.send_response = lambda status: events.append(("status", status))
    handler.send_header = lambda name, value: events.append(("header", name, value))
    handler.end_headers = lambda: events.append(("end",))

    handler.do_GET()
    handler.log_message("ignored %s", "request")

    assert (
        events[0],
        events[-1],
        b'"status": "ok"' in handler.wfile.getvalue(),
    ) == (
        ("status", 200),
        ("end",),
        True,
    ), "health request handler changed status, headers, body, or logging behavior"


class HttpServerDouble:
    def __init__(self, address: tuple[str, int], handler: object) -> None:
        self.address = address
        self.handler = handler
        self.events: list[tuple[object, ...]] = []

    def serve_forever(self) -> None:
        self.events.append(("serve",))

    def shutdown(self) -> None:
        self.events.append(("shutdown",))

    def server_close(self) -> None:
        self.events.append(("server_close",))


class ThreadDouble:
    def __init__(self, *, target: object, daemon: bool) -> None:
        self.target = target
        self.daemon = daemon
        self.events: list[tuple[object, ...]] = []

    def start(self) -> None:
        self.events.append(("start",))

    def join(self, timeout: float | None = None) -> None:
        self.events.append(("join", timeout))


def test_starts_and_closes_the_health_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def create_server(address: tuple[str, int], handler: object) -> HttpServerDouble:
        server = HttpServerDouble(address, handler)
        captured["server"] = server
        return server

    def create_thread(*, target: object, daemon: bool) -> ThreadDouble:
        thread = ThreadDouble(target=target, daemon=daemon)
        captured["thread"] = thread
        return thread

    monkeypatch.setattr(health_module, "ThreadingHTTPServer", create_server)
    monkeypatch.setattr(health_module, "Thread", create_thread)

    listener = HealthHttpServer.start(
        host="127.0.0.29",
        port=8029,
        state=state(Clock()),
    )
    listener.close()

    server = captured["server"]
    thread = captured["thread"]
    assert (
        server.address,
        server.events,
        thread.daemon,
        thread.events,
    ) == (
        ("127.0.0.29", 8029),
        [("shutdown",), ("server_close",)],
        True,
        [("start",), ("join", 5)],
    ), "health listener did not bind, start, or close deterministically"
