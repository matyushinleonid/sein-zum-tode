import pytest

from sein_zum_tode.broadcasts.models import PrepareScreamReportInput, ScreamRecipients

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("recipients", "expected"),
    [
        (ScreamRecipients(mortal_ids=()), None),
        (ScreamRecipients(mortal_ids=(180_181, 180_187)), 180_187),
    ],
)
def test_exposes_the_cursor_after_the_last_selected_mortal(
    recipients: ScreamRecipients,
    expected: int | None,
) -> None:
    assert recipients.next_cursor() == expected, (
        "recipient pagination repeated a page or skipped its last Mortal"
    )


def test_formats_the_non_localized_admin_report() -> None:
    report = PrepareScreamReportInput(
        response_key="telegram:scream:report-1801",
        admin_chat_id=180_181,
        admin_user_id=180_181,
        update_key="telegram:scream:1801",
        delivered=37,
        failed=5,
    )

    assert report.text() == "Scream completed: 37 delivered, 5 failed.", (
        "admin report changed its fixed language or delivery totals"
    )
