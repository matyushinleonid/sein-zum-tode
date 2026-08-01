import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.broadcasts.activities import (
    DeliverScreamActivity,
    ListScreamRecipientsActivity,
    PrepareScreamReportActivity,
)
from sein_zum_tode.broadcasts.models import (
    DeliverScreamInput,
    ListScreamRecipientsInput,
    PrepareScreamReportInput,
    ScreamRecipients,
    ScreamRequest,
)
from tests.support import MortalMemory, SilentLogger, TelegramMemory, mortal, result_or_raise

pytestmark = pytest.mark.fast


class ScreamCopierDouble:
    def __init__(self, outcome: object = None) -> None:
        self.outcome = outcome
        self.events: list[tuple[object, ...]] = []

    async def copy(self, request: ScreamRequest, recipient_id: int) -> None:
        self.events.append(("copy", request, recipient_id))
        result_or_raise(self.outcome)


def request() -> ScreamRequest:
    return ScreamRequest(
        locale="en",
        source_chat_id=181_081,
        source_message_id=181_087,
    )


async def test_selects_one_stable_page_of_matching_mortals() -> None:
    mortals = MortalMemory(
        {
            181_091: mortal(id=181_091, locale="en"),
            181_093: mortal(id=181_093, locale="ru"),
            181_099: mortal(id=181_099, locale="en"),
        }
    )
    subject = ListScreamRecipientsActivity(mortals=mortals, logger=SilentLogger())

    actual = await subject.list(
        ListScreamRecipientsInput(
            locale="en",
            after_mortal_id=181_091,
            limit=17,
            admin_user_id=162573173,
            update_key="telegram:scream:1811",
        )
    )

    assert (
        actual,
        mortals.events,
    ) == (
        ScreamRecipients(mortal_ids=(181_099,)),
        [("list_ids", "en", 181_091, 17)],
    ), "recipient selection ignored locale, cursor, or page limit"


async def test_copies_the_source_message_to_one_recipient() -> None:
    copier = ScreamCopierDouble()
    subject = DeliverScreamActivity(copier=copier, logger=SilentLogger())
    input = DeliverScreamInput(
        request=request(),
        recipient_id=181_123,
        admin_user_id=162573173,
        update_key="telegram:scream:1813",
    )

    await subject.deliver(input)

    assert copier.events == [("copy", request(), 181_123)], (
        "delivery rebuilt or redirected the replied Telegram message"
    )


@pytest.mark.parametrize(
    ("failure", "expected_type"),
    [
        (
            TelegramRecipientUnavailableError("blocked 1817"),
            "TelegramRecipientUnavailable",
        ),
        (
            PermanentTelegramDeliveryError("rejected 1819"),
            "PermanentTelegramDeliveryError",
        ),
    ],
)
async def test_marks_permanent_copy_failures_as_non_retryable(
    failure: BaseException,
    expected_type: str,
) -> None:
    subject = DeliverScreamActivity(
        copier=ScreamCopierDouble(failure),
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError) as captured:
        await subject.deliver(
            DeliverScreamInput(
                request=request(),
                recipient_id=181_127,
                admin_user_id=162573173,
                update_key="telegram:scream:1817",
            )
        )

    assert (captured.value.type, captured.value.non_retryable) == (
        expected_type,
        True,
    ), "permanent Telegram failure was retried or lost its recipient classification"


async def test_stores_the_admin_report_with_the_response_ttl() -> None:
    memory = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = PrepareScreamReportActivity(
        responses=memory.response_documents,
        ttl_seconds=1823,
        logger=SilentLogger(),
    )
    input = PrepareScreamReportInput(
        response_key="telegram:scream:1823:report",
        admin_chat_id=162573173,
        admin_user_id=162573173,
        update_key="telegram:scream:1823",
        delivered=11,
        failed=2,
    )

    await subject.prepare(input)

    assert memory.events == [
        (
            "store_response",
            "telegram:scream:1823:report",
            TelegramResponse(
                chat_id=162573173,
                text="Scream completed: 11 delivered, 2 failed.",
            ),
            1823,
        )
    ], "report preparation changed its recipient, totals, or Redis TTL"
