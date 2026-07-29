from sein_zum_tode.observability import LogContext


def test_log_context_builds_event_fields() -> None:
    context = LogContext(component="worker", user_id=40, update_key="update-key")

    assert context.event("telegram_update_inspected", duration_ms=1.5) == {
        "event": "telegram_update_inspected",
        "component": "worker",
        "user_id": 40,
        "update_key": "update-key",
        "duration_ms": 1.5,
    }


def test_log_context_omits_unavailable_update_key() -> None:
    context = LogContext(component="ingress")

    assert context.event("telegram_update_unroutable") == {
        "event": "telegram_update_unroutable",
        "component": "ingress",
        "user_id": None,
    }
