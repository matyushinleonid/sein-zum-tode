from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredUpdate:
    update_id: int
    key: str
    ttl_seconds: int
    user_id: int | None
