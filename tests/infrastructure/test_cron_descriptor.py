import pytest

from sein_zum_tode.infrastructure.cron_descriptor import CronDescriptor

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("en_US", "At 09:00 AM"),
        ("ru_RU", "В 09:00"),
    ],
)
def test_describes_cron_with_the_requested_library_locale(
    locale: str,
    expected: str,
) -> None:
    actual = CronDescriptor().describe("0 9 * * *", locale)

    assert actual == expected, "cron-descriptor locale or output was changed by the adapter"
