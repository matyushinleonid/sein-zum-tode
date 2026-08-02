import pytest
from aiogram.types import Update

from sein_zum_tode.bot.errors import InvalidStoredPayloadError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.ports.documents import DocumentReader, DocumentStore, DocumentWriter
from sein_zum_tode.questionnaire.activities import (
    RecordTelegramQuestionnaireAnswerActivity,
    StartTelegramQuestionnaireActivity,
)
from sein_zum_tode.questionnaire.models import (
    QuestionnaireState,
    QuestionnaireTurnKind,
    RecordQuestionnaireAnswerInput,
    StartQuestionnaireInput,
)
from tests.support import (
    BotContents,
    MortalMemory,
    QuestionnaireMemory,
    QuestionnaireRepositoryDouble,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
    mortal,
)

pytestmark = pytest.mark.fast


def questionnaire_state() -> QuestionnaireState:
    content = BotContents.debug()
    return QuestionnaireState.begin(
        content=content,
        localized=content.default(),
        locale="en",
        user_id=223_721,
        chat_id=223_727,
    )


def record_activity(
    *,
    updates: DocumentReader[Update],
    questionnaires: DocumentStore[QuestionnaireState],
    responses: DocumentWriter[TelegramResponse],
) -> RecordTelegramQuestionnaireAnswerActivity:
    return RecordTelegramQuestionnaireAnswerActivity(
        updates=updates,
        questionnaires=questionnaires,
        responses=responses,
        questionnaire_ttl_seconds=2237,
        response_ttl_seconds=2239,
        privacy_response_ttl_seconds=2243,
        logger=SilentLogger(),
    )


async def test_starts_with_a_redis_snapshot_and_three_prepared_messages() -> None:
    content = BotContents.debug()
    memory = QuestionnaireMemory()
    subject = StartTelegramQuestionnaireActivity(
        content=content,
        mortals=MortalMemory({226_973: mortal(id=226_973)}),
        questionnaires=memory.questionnaire_repository,
        responses=memory.response_documents,
        questionnaire_ttl_seconds=2243,
        response_ttl_seconds=2251,
        privacy_response_ttl_seconds=2267,
        logger=SilentLogger(),
    )

    actual = await subject.start(
        StartQuestionnaireInput(
            questionnaire_key="telegram:questionnaire:2269",
            user_id=226_973,
            chat_id=226_979,
        )
    )

    state = memory.questionnaires["telegram:questionnaire:2269"]
    assert (
        actual.response_keys,
        actual.privacy_response_key,
        state.content_version,
        memory.responses,
    ) == (
        (
            "telegram:questionnaire:2269:initial:0",
            "telegram:questionnaire:2269:initial:1",
            "telegram:questionnaire:2269:initial:2",
        ),
        "telegram:questionnaire:2269:privacy",
        "debug-cosmos-v1",
        {
            "telegram:questionnaire:2269:initial:0": TelegramResponse(
                chat_id=226_979,
                text="Private answers are temporary.",
            ),
            "telegram:questionnaire:2269:initial:1": TelegramResponse(
                chat_id=226_979,
                text="mock questionnaire started",
            ),
            "telegram:questionnaire:2269:initial:2": TelegramResponse(
                chat_id=226_979,
                text="q1?",
            ),
            "telegram:questionnaire:2269:privacy": TelegramResponse(
                chat_id=226_979,
                text="your answers were deleted from our system",
            ),
        },
    ), "questionnaire start failed to snapshot content or prepare its ordered messages"
    assert [
        event[-1]
        for event in memory.events
        if event[0] in {"store_questionnaire", "store_response"}
    ] == [
        2243,
        2251,
        2251,
        2251,
        2267,
    ], "questionnaire start assigned the wrong TTL to stored private data"


async def test_records_text_and_refreshes_only_questionnaire_privacy_data() -> None:
    update_key = "telegram:answer:2273"
    state = questionnaire_state()
    memory = QuestionnaireMemory(
        updates={
            update_key: TelegramUpdates.message(
                update_id=2273,
                user_id=state.user_id,
                chat_id=state.chat_id,
                text="Polaris",
                chat_type="private",
            )
        },
        questionnaires={"telegram:questionnaire:2273": state},
    )
    subject = record_activity(
        updates=memory.update_documents,
        questionnaires=memory.questionnaire_repository,
        responses=memory.response_documents,
    )

    actual = await subject.record(
        RecordQuestionnaireAnswerInput(
            questionnaire_key="telegram:questionnaire:2273",
            update_key=update_key,
            user_id=state.user_id,
        )
    )

    saved = memory.questionnaires["telegram:questionnaire:2273"]
    assert (
        actual.kind,
        actual.response_keys,
        saved.current_question_index,
        saved.questions[0].answer,
        memory.responses,
    ) == (
        QuestionnaireTurnKind.QUESTION,
        ("telegram:answer:2273:questionnaire-response:0",),
        1,
        "Polaris",
        {
            "telegram:answer:2273:questionnaire-response:0": TelegramResponse(
                chat_id=state.chat_id,
                text="q2?",
            ),
            "telegram:questionnaire:2273:privacy": TelegramResponse(
                chat_id=state.chat_id,
                text="your answers were deleted from our system",
            ),
        },
    ), "accepted text did not advance state or prepare the next question"
    assert [
        event[-1]
        for event in memory.events
        if event[0] in {"store_questionnaire", "store_response"}
    ] == [
        2237,
        2239,
        2243,
    ], "accepted text failed to restart inactivity and privacy response TTLs"


async def test_prepares_only_the_completion_message_after_the_last_answer() -> None:
    first = questionnaire_state().apply_answer(
        update_key="telegram:answer:2281",
        text="Deneb",
    )
    update_key = "telegram:answer:2287"
    memory = QuestionnaireMemory(
        updates={
            update_key: TelegramUpdates.message(
                update_id=2287,
                user_id=first.state.user_id,
                chat_id=first.state.chat_id,
                text="S" * 4096,
                chat_type="private",
            )
        },
        questionnaires={"telegram:questionnaire:2287": first.state},
    )
    subject = record_activity(
        updates=memory.update_documents,
        questionnaires=memory.questionnaire_repository,
        responses=memory.response_documents,
    )

    actual = await subject.record(
        RecordQuestionnaireAnswerInput(
            questionnaire_key="telegram:questionnaire:2287",
            update_key=update_key,
            user_id=first.state.user_id,
        )
    )

    response_parts = tuple(memory.responses[key].text for key in actual.response_keys)
    assert (
        actual.kind,
        "".join(response_parts),
    ) == (
        QuestionnaireTurnKind.COMPLETED,
        "thanks for your answers!",
    ), "completed questionnaire exposed answers instead of the completion message"


@pytest.mark.parametrize(
    "update_outcome",
    [
        None,
        InvalidStoredPayloadError("private update shattered 2293"),
        TelegramUpdates.message(
            update_id=2297,
            user_id=223_721,
            chat_id=223_727,
            text=None,
            chat_type="private",
        ),
        TelegramUpdates.message(
            update_id=2309,
            user_id=223_721,
            chat_id=-223_727,
            text="Group answer",
            chat_type="group",
        ),
    ],
)
async def test_ignores_input_that_is_not_a_private_text_message(
    update_outcome: object,
) -> None:
    state = questionnaire_state()
    questionnaires = QuestionnaireRepositoryDouble(load_result=state)
    updates = TelegramMemory(
        update_result=update_outcome,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    responses = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = record_activity(
        updates=updates.update_documents,
        questionnaires=questionnaires,
        responses=responses.response_documents,
    )

    actual = await subject.record(
        RecordQuestionnaireAnswerInput(
            questionnaire_key="telegram:questionnaire:2309",
            update_key="telegram:update:2311",
            user_id=state.user_id,
        )
    )

    assert (
        actual.kind,
        questionnaires.events,
        responses.events,
    ) == (
        QuestionnaireTurnKind.IGNORED,
        [("load_questionnaire", "telegram:questionnaire:2309")],
        [],
    ), "unsupported input advanced the question or refreshed questionnaire TTL"


@pytest.mark.parametrize(
    "questionnaire_outcome",
    [
        None,
        InvalidStoredPayloadError("questionnaire snapshot shattered 2333"),
    ],
)
async def test_reports_an_expired_or_invalid_questionnaire(
    questionnaire_outcome: object,
) -> None:
    questionnaires = QuestionnaireRepositoryDouble(load_result=questionnaire_outcome)
    updates = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    responses = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = record_activity(
        updates=updates.update_documents,
        questionnaires=questionnaires,
        responses=responses.response_documents,
    )

    actual = await subject.record(
        RecordQuestionnaireAnswerInput(
            questionnaire_key="telegram:questionnaire:2339",
            update_key="telegram:update:2341",
            user_id=234_149,
        )
    )

    assert (
        actual.kind,
        updates.events,
        responses.events,
    ) == (
        QuestionnaireTurnKind.EXPIRED,
        [],
        [],
    ), "expired questionnaire read or wrote Telegram update and response data"
