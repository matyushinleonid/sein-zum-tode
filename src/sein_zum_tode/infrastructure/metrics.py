from __future__ import annotations

from threading import Thread
from typing import Protocol, cast

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    start_http_server,
)


class StoppableHttpServer(Protocol):
    def shutdown(self) -> None: ...

    def server_close(self) -> None: ...


class PrometheusMetrics:
    def __init__(self, *, component: str, registry: CollectorRegistry) -> None:
        self._poll = Counter(
            "sein_zum_tode_telegram_poll_operations",
            "Telegram polling operations by stage and outcome.",
            ("stage", "outcome"),
            registry=registry,
        )
        self._poll_last_success = Gauge(
            "sein_zum_tode_telegram_poll_last_success_timestamp_seconds",
            "Unix timestamp of the last successful Telegram poll operation.",
            registry=registry,
        )
        self._updates = Counter(
            "sein_zum_tode_telegram_updates",
            "Telegram updates by processing stage and outcome.",
            ("stage", "outcome"),
            registry=registry,
        )
        self._inspected = Counter(
            "sein_zum_tode_telegram_update_kinds",
            "Inspected Telegram updates by bounded application kind.",
            ("kind",),
            registry=registry,
        )
        self._payload_expired = Counter(
            "sein_zum_tode_payload_expired",
            "Ephemeral payloads that expired before application processing.",
            ("kind",),
            registry=registry,
        )
        self._responses = Counter(
            "sein_zum_tode_telegram_responses_prepared",
            "Prepared Telegram responses by bounded kind.",
            ("kind",),
            registry=registry,
        )
        self._deliveries = Counter(
            "sein_zum_tode_telegram_deliveries",
            "Telegram delivery attempts by kind, outcome, and normalized error.",
            ("kind", "outcome", "error_kind"),
            registry=registry,
        )
        self._delivery_seconds = Histogram(
            "sein_zum_tode_telegram_delivery_seconds",
            "Telegram delivery duration in seconds.",
            ("kind", "outcome"),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=registry,
        )
        self._cleanups = Counter(
            "sein_zum_tode_payload_cleanups",
            "Ephemeral payload cleanup attempts by kind and outcome.",
            ("kind", "outcome"),
            registry=registry,
        )
        self._mortals = Counter(
            "sein_zum_tode_mortal_events",
            "Mortal lifecycle events.",
            ("event",),
            registry=registry,
        )
        self._questionnaires = Counter(
            "sein_zum_tode_questionnaires",
            "Questionnaire lifecycle events by locale.",
            ("event", "locale"),
            registry=registry,
        )
        self._questionnaire_answers = Counter(
            "sein_zum_tode_questionnaire_answers",
            "Recorded questionnaire answers by locale and question index.",
            ("locale", "question_index"),
            registry=registry,
        )
        self._llm_requests = Counter(
            "sein_zum_tode_llm_requests",
            "LLM requests by use case, provider, and outcome.",
            ("use_case", "provider", "outcome"),
            registry=registry,
        )
        self._llm_seconds = Histogram(
            "sein_zum_tode_llm_request_seconds",
            "LLM request duration in seconds.",
            ("use_case", "provider", "outcome"),
            buckets=(0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 180),
            registry=registry,
        )
        self._predictions = Counter(
            "sein_zum_tode_death_predictions",
            "Death prediction application outcomes by provider.",
            ("provider", "outcome"),
            registry=registry,
        )
        self._notification_schedules = Counter(
            "sein_zum_tode_notification_schedules",
            "Notification schedule configuration outcomes.",
            ("kind", "outcome", "locale"),
            registry=registry,
        )
        self._notifications = Counter(
            "sein_zum_tode_mortal_notifications",
            "Mortal notification lifecycle outcomes by locale.",
            ("outcome", "locale"),
            registry=registry,
        )
        self._broadcasts = Counter(
            "sein_zum_tode_broadcast_deliveries",
            "Broadcast recipient delivery outcomes by locale.",
            ("outcome", "locale"),
            registry=registry,
        )
        self._health_dependencies = Gauge(
            "sein_zum_tode_dependency_up",
            "Current health of a bounded external dependency.",
            ("dependency",),
            registry=registry,
        )
        info = Gauge(
            "sein_zum_tode_application_info",
            "Static application process information.",
            ("component",),
            registry=registry,
        )
        info.labels(component=component).set(1)

    @classmethod
    def create(cls, *, component: str) -> tuple[PrometheusMetrics, CollectorRegistry]:
        registry = CollectorRegistry()
        ProcessCollector(registry=registry)
        PlatformCollector(registry=registry)
        GCCollector(registry=registry)
        return cls(component=component, registry=registry), registry

    def poll(self, *, stage: str, outcome: str) -> None:
        self._poll.labels(stage=stage, outcome=outcome).inc()
        if outcome == "success":
            self._poll_last_success.set_to_current_time()

    def updates(self, *, stage: str, outcome: str, count: int = 1) -> None:
        self._updates.labels(stage=stage, outcome=outcome).inc(count)

    def inspected(self, *, kind: str) -> None:
        self._inspected.labels(kind=kind).inc()

    def payload_expired(self, *, kind: str) -> None:
        self._payload_expired.labels(kind=kind).inc()

    def response_prepared(self, *, kind: str) -> None:
        self._responses.labels(kind=kind).inc()

    def delivery(
        self,
        *,
        kind: str,
        outcome: str,
        error_kind: str,
        elapsed_seconds: float,
    ) -> None:
        self._deliveries.labels(
            kind=kind,
            outcome=outcome,
            error_kind=error_kind,
        ).inc()
        self._delivery_seconds.labels(kind=kind, outcome=outcome).observe(elapsed_seconds)

    def cleanup(self, *, kind: str, outcome: str) -> None:
        self._cleanups.labels(kind=kind, outcome=outcome).inc()

    def mortal(self, *, event: str) -> None:
        self._mortals.labels(event=event).inc()

    def questionnaire(
        self,
        *,
        event: str,
        locale: str,
        question_index: int | None = None,
    ) -> None:
        self._questionnaires.labels(event=event, locale=locale).inc()
        if question_index is not None:
            self._questionnaire_answers.labels(
                locale=locale,
                question_index=str(question_index),
            ).inc()

    def llm_request(
        self,
        *,
        use_case: str,
        provider: str,
        outcome: str,
        elapsed_seconds: float,
    ) -> None:
        labels = {
            "use_case": use_case,
            "provider": provider,
            "outcome": outcome,
        }
        self._llm_requests.labels(**labels).inc()
        self._llm_seconds.labels(**labels).observe(elapsed_seconds)

    def prediction(self, *, provider: str, outcome: str) -> None:
        self._predictions.labels(provider=provider, outcome=outcome).inc()

    def notification_schedule(self, *, kind: str, outcome: str, locale: str) -> None:
        self._notification_schedules.labels(
            kind=kind,
            outcome=outcome,
            locale=locale,
        ).inc()

    def notification(self, *, outcome: str, locale: str) -> None:
        self._notifications.labels(outcome=outcome, locale=locale).inc()

    def broadcast(self, *, outcome: str, locale: str, count: int = 1) -> None:
        self._broadcasts.labels(outcome=outcome, locale=locale).inc(count)

    def health_dependency(self, *, name: str, healthy: bool) -> None:
        self._health_dependencies.labels(dependency=name).set(1 if healthy else 0)


class PrometheusHttpServer:
    def __init__(self, *, server: StoppableHttpServer, thread: Thread) -> None:
        self._server = server
        self._thread = thread

    @classmethod
    def start(
        cls,
        *,
        host: str,
        port: int,
        registry: CollectorRegistry,
    ) -> PrometheusHttpServer:
        server, thread = start_http_server(port=port, addr=host, registry=registry)
        return cls(
            server=cast(StoppableHttpServer, server),
            thread=thread,
        )

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
