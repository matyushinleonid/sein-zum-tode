from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogContext:
    component: str
    user_id: int | None = None
    update_key: str | None = None
    correlation_id: str | None = None
    session_id: str | None = None

    def event(self, name: str, **details: object) -> dict[str, object]:
        fields: dict[str, object] = {
            "event": name,
            "component": self.component,
            "user_id": self.user_id,
        }
        if self.update_key is not None:
            fields["update_key"] = self.update_key
        correlation_id = self.correlation_id or self.update_key
        if correlation_id is not None:
            fields["correlation_id"] = correlation_id
        if self.session_id is not None:
            fields["session_id"] = self.session_id
        fields.update(details)
        return fields
