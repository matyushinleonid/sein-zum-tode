import pytest
from pydantic import ValidationError

from sein_zum_tode.unsupported.models import (
    UnsupportedTurn,
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
    first, first_turn = UnsupportedUpdateSession().advance(
        update_key="telegram:unsupported:239",
        content=content(),
    )
    second, second_turn = first.advance(
        update_key="telegram:unsupported:241",
        content=content(),
    )

    assert (
        first.ignored_updates,
        first_turn,
        second.ignored_updates,
        second_turn,
    ) == (
        1,
        UnsupportedTurn(text=None, poem_gap=False),
        2,
        UnsupportedTurn(text=None, poem_gap=False),
    ), "unsupported session did not keep the initial updates silent"


def test_emits_poem_lines_and_silent_gaps_in_a_repeating_cycle() -> None:
    session = UnsupportedUpdateSession(ignored_updates=2)
    actual: list[UnsupportedTurn] = []

    for update_id in range(251, 257):
        session, turn = session.advance(
            update_key=f"telegram:unsupported:{update_id}",
            content=content(),
        )
        actual.append(turn)

    assert actual == [
        UnsupportedTurn(text="First"),
        UnsupportedTurn(text="Second"),
        UnsupportedTurn(text=None, poem_gap=True),
        UnsupportedTurn(text="Third"),
        UnsupportedTurn(text=None, poem_gap=True),
        UnsupportedTurn(text="First"),
    ], "poem did not preserve silent stanza boundaries or restart after its final gap"


def test_replaying_the_same_update_does_not_advance_the_poem() -> None:
    session = UnsupportedUpdateSession(ignored_updates=2)
    advanced, first_turn = session.advance(
        update_key="telegram:unsupported:263",
        content=content(),
    )
    replayed, replayed_turn = advanced.advance(
        update_key="telegram:unsupported:263",
        content=content(),
    )
    following, following_turn = replayed.advance(
        update_key="telegram:unsupported:269",
        content=content(),
    )

    assert (
        first_turn,
        replayed_turn,
        replayed,
        following_turn,
        following.next_message_index,
    ) == (
        UnsupportedTurn(text="First"),
        UnsupportedTurn(text="First"),
        advanced,
        UnsupportedTurn(text="Second"),
        2,
    ), "Activity replay consumed an extra poem line"


def test_replaying_a_stanza_gap_stays_silent_instead_of_repeating_a_line() -> None:
    session = UnsupportedUpdateSession(ignored_updates=2, next_message_index=2)
    gap, gap_turn = session.advance(
        update_key="telegram:unsupported:271",
        content=content(),
    )
    replayed, replayed_turn = gap.advance(
        update_key="telegram:unsupported:271",
        content=content(),
    )

    assert (gap_turn, replayed_turn, replayed) == (
        UnsupportedTurn(text=None, poem_gap=True),
        UnsupportedTurn(text=None, poem_gap=True),
        gap,
    ), "replayed stanza gap lost its silence and fell back to a spoken response"


@pytest.mark.parametrize("stanzas", [((),), (("",),)])
def test_rejects_empty_stanzas_and_lines(stanzas: tuple[tuple[str, ...], ...]) -> None:
    with pytest.raises(ValidationError):
        UnsupportedUpdateContent(
            initial_silence_count=10,
            stanzas=stanzas,
        )
