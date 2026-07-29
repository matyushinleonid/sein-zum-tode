from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogContext:
    component: str
    user_id: int | None = None
    update_key: str | None = None

    def event(self, name: str, **details: object) -> dict[str, object]:
        fields: dict[str, object] = {
            "event": name,
            "component": self.component,
            "user_id": self.user_id,
        }
        if self.update_key is not None:
            fields["update_key"] = self.update_key
        fields.update(details)
        return fields
