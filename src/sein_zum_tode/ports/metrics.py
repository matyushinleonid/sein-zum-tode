from typing import Protocol


class ApplicationMetrics(Protocol):
    def poll(self, *, stage: str, outcome: str) -> None: ...

    def updates(self, *, stage: str, outcome: str, count: int = 1) -> None: ...

    def inspected(self, *, kind: str) -> None: ...

    def response_prepared(self, *, kind: str) -> None: ...

    def delivery(
        self,
        *,
        kind: str,
        outcome: str,
        error_kind: str,
        elapsed_seconds: float,
    ) -> None: ...

    def cleanup(self, *, kind: str, outcome: str) -> None: ...

    def mortal(self, *, event: str) -> None: ...

    def questionnaire(
        self,
        *,
        event: str,
        locale: str,
        question_index: int | None = None,
    ) -> None: ...

    def llm_request(
        self,
        *,
        use_case: str,
        provider: str,
        outcome: str,
        elapsed_seconds: float,
    ) -> None: ...

    def prediction(self, *, provider: str, outcome: str) -> None: ...

    def notification_schedule(self, *, kind: str, outcome: str, locale: str) -> None: ...

    def notification(self, *, outcome: str, locale: str) -> None: ...

    def broadcast(self, *, outcome: str, locale: str, count: int = 1) -> None: ...


class NoopApplicationMetrics:
    def poll(self, *, stage: str, outcome: str) -> None:
        return None

    def updates(self, *, stage: str, outcome: str, count: int = 1) -> None:
        return None

    def inspected(self, *, kind: str) -> None:
        return None

    def response_prepared(self, *, kind: str) -> None:
        return None

    def delivery(
        self,
        *,
        kind: str,
        outcome: str,
        error_kind: str,
        elapsed_seconds: float,
    ) -> None:
        return None

    def cleanup(self, *, kind: str, outcome: str) -> None:
        return None

    def mortal(self, *, event: str) -> None:
        return None

    def questionnaire(
        self,
        *,
        event: str,
        locale: str,
        question_index: int | None = None,
    ) -> None:
        return None

    def llm_request(
        self,
        *,
        use_case: str,
        provider: str,
        outcome: str,
        elapsed_seconds: float,
    ) -> None:
        return None

    def prediction(self, *, provider: str, outcome: str) -> None:
        return None

    def notification_schedule(self, *, kind: str, outcome: str, locale: str) -> None:
        return None

    def notification(self, *, outcome: str, locale: str) -> None:
        return None

    def broadcast(self, *, outcome: str, locale: str, count: int = 1) -> None:
        return None
