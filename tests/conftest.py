from collections.abc import Callable

import pytest
from aiogram.types import Update


@pytest.fixture
def make_update() -> Callable[[int, str], Update]:
    def factory(update_id: int, text: str) -> Update:
        return Update.model_validate(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id * 10,
                    "date": 1_700_000_000,
                    "chat": {"id": 30, "type": "private"},
                    "from": {
                        "id": 40,
                        "is_bot": False,
                        "first_name": "Ada",
                    },
                    "text": text,
                },
            }
        )

    return factory
