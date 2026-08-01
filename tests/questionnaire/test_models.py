import pytest

from sein_zum_tode.questionnaire.models import (
    QuestionnaireState,
    QuestionnaireTurn,
    QuestionnaireTurnKind,
)
from tests.support import BotContents

pytestmark = pytest.mark.fast


def started_state() -> QuestionnaireState:
    content = BotContents.debug()
    return QuestionnaireState.begin(
        content=content,
        localized=content.default(),
        locale="en",
        user_id=201_107,
        chat_id=201_113,
    )


def test_snapshots_the_configured_questionnaire_for_one_user() -> None:
    actual = started_state()

    assert (
        actual.content_version,
        actual.locale,
        actual.user_id,
        actual.chat_id,
        actual.initial_messages(),
        tuple((question.id, question.text) for question in actual.questions),
    ) == (
        "debug-cosmos-v1",
        "en",
        201_107,
        201_113,
        ("mock questionnaire started", "q1?"),
        (("q1", "q1?"), ("q2", "q2?")),
    ), "questionnaire snapshot lost configured content or Telegram ownership"


def test_records_an_answer_and_selects_the_next_question() -> None:
    actual = started_state().apply_answer(
        update_key="telegram:answer:2017",
        text="Alpha Centauri",
    )

    assert (
        actual.completed,
        actual.response_text,
        actual.state.current_question_index,
        actual.state.questions[0].answer,
    ) == (
        False,
        "q2?",
        1,
        "Alpha Centauri",
    ), "accepted answer did not advance the questionnaire exactly once"


def test_replays_the_same_answer_idempotently() -> None:
    first = started_state().apply_answer(
        update_key="telegram:answer:2027",
        text="Betelgeuse",
    )

    actual = first.state.apply_answer(
        update_key="telegram:answer:2027",
        text="A different replayed payload",
    )

    assert actual == first, (
        "Activity retry changed an answer already associated with its update key"
    )


def test_completes_with_the_configured_completion_message() -> None:
    first = started_state().apply_answer(
        update_key="telegram:answer:2029",
        text="Rigel",
    )

    actual = first.state.apply_answer(
        update_key="telegram:answer:2039",
        text="/help",
    )

    assert (
        actual.completed,
        actual.state.current_question_index,
        actual.response_text,
    ) == (
        True,
        2,
        "thanks for your answers!",
    ), "final answer did not produce the configured completion message"


def test_keeps_a_completed_questionnaire_completed() -> None:
    state = started_state()
    state = state.apply_answer(update_key="telegram:answer:2053", text="Vega").state
    state = state.apply_answer(update_key="telegram:answer:2063", text="Sirius").state

    actual = state.apply_answer(
        update_key="telegram:late:2069",
        text="Late answer",
    )

    assert (
        actual.state,
        actual.completed,
        actual.response_text,
    ) == (
        state,
        True,
        state.completed_message,
    ), "completed state accepted an additional answer"


@pytest.mark.parametrize(
    ("kind", "accepted", "completed"),
    [
        (QuestionnaireTurnKind.QUESTION, True, False),
        (QuestionnaireTurnKind.COMPLETED, True, True),
        (QuestionnaireTurnKind.IGNORED, False, False),
        (QuestionnaireTurnKind.EXPIRED, False, False),
    ],
)
def test_describes_each_questionnaire_turn(
    kind: QuestionnaireTurnKind,
    accepted: bool,
    completed: bool,
) -> None:
    actual = QuestionnaireTurn(kind=kind)

    assert (actual.accepted(), actual.completed()) == (
        accepted,
        completed,
    ), "turn kind reported an inconsistent acceptance or completion state"
