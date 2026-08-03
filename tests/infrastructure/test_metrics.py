from typing import Any

import pytest
from prometheus_client import generate_latest

import sein_zum_tode.infrastructure.metrics as metrics_module
from sein_zum_tode.infrastructure.metrics import (
    PrometheusHttpServer,
    PrometheusMetrics,
)

pytestmark = pytest.mark.fast


def test_exports_every_application_metric_with_bounded_dimensions() -> None:
    metrics, registry = PrometheusMetrics.create(component="worker-317")

    metrics.poll(stage="prepare", outcome="failed")
    metrics.poll(stage="receive", outcome="success")
    metrics.updates(stage="received", outcome="success", count=19)
    metrics.inspected(kind="begin")
    metrics.payload_expired(kind="telegram_update")
    metrics.response_prepared(kind="help")
    metrics.delivery(
        kind="response",
        outcome="success",
        error_kind="none",
        elapsed_seconds=0.37,
    )
    metrics.cleanup(kind="questionnaire", outcome="success")
    metrics.mortal(event="registered")
    metrics.questionnaire(event="started", locale="ru")
    metrics.questionnaire(
        event="question",
        locale="ru",
        question_index=7,
    )
    metrics.llm_request(
        use_case="death_prediction",
        provider="alice",
        outcome="success",
        elapsed_seconds=1.71,
    )
    metrics.prediction(provider="alice", outcome="accepted")
    metrics.notification_schedule(kind="custom", outcome="applied", locale="ru")
    metrics.notification(outcome="prepared", locale="ru")
    metrics.broadcast(outcome="delivered", locale="ru", count=23)
    metrics.health_dependency(name="postgres", healthy=False)

    exposition = generate_latest(registry).decode()

    assert (
        'sein_zum_tode_application_info{component="worker-317"} 1.0' in exposition
        and 'sein_zum_tode_telegram_updates_total{outcome="success",stage="received"} 19.0'
        in exposition
        and 'sein_zum_tode_questionnaire_answers_total{locale="ru",question_index="7"} 1.0'
        in exposition
        and 'sein_zum_tode_payload_expired_total{kind="telegram_update"} 1.0' in exposition
        and 'sein_zum_tode_broadcast_deliveries_total{locale="ru",outcome="delivered"} 23.0'
        in exposition
        and 'sein_zum_tode_dependency_up{dependency="postgres"} 0.0' in exposition
        and "user_id" not in exposition
    ), "metrics exposition omitted a business signal or exposed a high-cardinality user label"


class HttpServerDouble:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self._events = events

    def shutdown(self) -> None:
        self._events.append(("shutdown",))

    def server_close(self) -> None:
        self._events.append(("server_close",))


class ThreadDouble:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self._events = events

    def join(self, timeout: float | None = None) -> None:
        self._events.append(("join", timeout))


def test_starts_and_closes_the_metrics_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    http_server = HttpServerDouble(events)
    thread = ThreadDouble(events)

    def start_http_server(**options: object) -> tuple[Any, Any]:
        events.append(("start", options["addr"], options["port"]))
        return http_server, thread

    monkeypatch.setattr(metrics_module, "start_http_server", start_http_server)
    _, registry = PrometheusMetrics.create(component="ingress-331")

    server = PrometheusHttpServer.start(
        host="127.0.0.17",
        port=8331,
        registry=registry,
    )
    server.close()

    assert events == [
        ("start", "127.0.0.17", 8331),
        ("shutdown",),
        ("server_close",),
        ("join", 5),
    ], "metrics endpoint did not release its HTTP listener deterministically"
