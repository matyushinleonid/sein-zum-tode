import pytest
from aiogram.types import Update

from sein_zum_tode.ingress.routing import AiogramUpdateUserResolver
from tests.support import TelegramUpdates

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("update", "expected"),
    [
        (
            TelegramUpdates.callback(
                update_id=791,
                user_id=65_537,
                chat_id=-940_031,
            ),
            65_537,
        ),
        (TelegramUpdates.poll_answer(update_id=809, user_id=71_903), 71_903),
        (TelegramUpdates.anonymous_poll(update_id=823), None),
        (Update(update_id=827), None),
    ],
)
def test_resolves_user_from_every_supported_event_shape(
    update: Update,
    expected: int | None,
) -> None:
    actual = AiogramUpdateUserResolver().resolve(update)

    assert actual == expected, "resolver chose a user outside the Telegram event contract"
