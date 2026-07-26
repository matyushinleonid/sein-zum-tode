from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredUpdate:
    update_id: int
    key: str
    ttl_seconds: int

    def next_offset(self) -> int:
        return self.update_id + 1
