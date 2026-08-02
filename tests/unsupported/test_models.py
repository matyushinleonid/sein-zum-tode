import pytest
from pydantic import ValidationError

from sein_zum_tode.unsupported.models import (
    VISUALLY_EMPTY_TELEGRAM_MESSAGE,
    UnsupportedUpdateContent,
    UnsupportedUpdateSession,
)

pytestmark = pytest.mark.fast


def content() -> UnsupportedUpdateContent:
    return UnsupportedUpdateContent(
        initial_silence_count=2,
        stanzas=(("First", "Second"), ("Third",)),
    )


def test_ignores_the_configured_number_of_initial_updates() -> None:
    first, first_text = UnsupportedUpdateSession().advance(
        update_key="telegram:unsupported:239",
        content=content(),
    )
    second, second_text = first.advance(
        update_key="telegram:unsupported:241",
        content=content(),
    )

    assert (
        first.ignored_updates,
        first_text,
        second.ignored_updates,
        second_text,
    ) == (1, None, 2, None), "unsupported session did not keep the initial updates silent"


def test_emits_poem_lines_and_visual_separators_in_a_repeating_cycle() -> None:
    session = UnsupportedUpdateSession(ignored_updates=2)
    actual: list[str | None] = []

    for update_id in range(251, 257):
        session, text = session.advance(
            update_key=f"telegram:unsupported:{update_id}",
            content=content(),
        )
        actual.append(text)

    assert actual == [
        "First",
        "Second",
        VISUALLY_EMPTY_TELEGRAM_MESSAGE,
        "Third",
        VISUALLY_EMPTY_TELEGRAM_MESSAGE,
        "First",
    ], "poem did not preserve stanza boundaries or restart after its final separator"


def test_replaying_the_same_update_does_not_advance_the_poem() -> None:
    session = UnsupportedUpdateSession(ignored_updates=2)
    advanced, first_text = session.advance(
        update_key="telegram:unsupported:263",
        content=content(),
    )
    replayed, replayed_text = advanced.advance(
        update_key="telegram:unsupported:263",
        content=content(),
    )
    following, following_text = replayed.advance(
        update_key="telegram:unsupported:269",
        content=content(),
    )

    assert (
        first_text,
        replayed_text,
        replayed,
        following_text,
        following.next_message_index,
    ) == (
        "First",
        "First",
        advanced,
        "Second",
        2,
    ), "Activity replay consumed an extra poem line"


@pytest.mark.parametrize("stanzas", [((),), (("",),)])
def test_rejects_empty_stanzas_and_lines(stanzas: tuple[tuple[str, ...], ...]) -> None:
    with pytest.raises(ValidationError):
        UnsupportedUpdateContent(
            initial_silence_count=10,
            stanzas=stanzas,
        )
