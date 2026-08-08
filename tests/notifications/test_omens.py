from datetime import date

import pytest

from sein_zum_tode.notifications.omens import OMEN_COUNTERS

pytestmark = pytest.mark.fast

TODAY = date(2026, 8, 8)
DEATH = date(2061, 3, 14)


@pytest.mark.parametrize(
    ("omen", "expected"),
    [
        ("crab_pulsar_rotations", 32_398_718_100),
        ("sundays", 1806),
        ("wednesdays", 1805),
        ("full_moons", 427),
        ("new_years", 35),
        ("winters", 35),
        ("jupiter_oppositions", 31),
        ("encke_returns", 10),
        ("leap_days", 9),
        ("proxima_light_crossings", 8),
        ("mercury_transits", 4),
        ("sirius_light_crossings", 4),
        ("saros_cycles", 1),
        ("metonic_cycles", 1),
        ("great_conjunctions", 2),
        ("saturn_returns", 1),
        ("tempel_tuttle_returns", 1),
        ("pons_brooks_returns", 0),
        ("halleys_comet_returns", 0),
        ("venus_transits", 0),
        ("swift_tuttle_returns", 0),
        ("great_years", 0),
        ("galactic_years", 0),
    ],
)
def test_counts_every_omen_between_today_and_the_death_date(omen: str, expected: int) -> None:
    assert OMEN_COUNTERS[omen](TODAY, DEATH) == expected, (
        f"omen {omen} counted the wrong number of remaining occurrences"
    )


@pytest.mark.parametrize("omen", sorted(OMEN_COUNTERS))
def test_counts_nothing_once_the_death_date_has_passed(omen: str) -> None:
    assert OMEN_COUNTERS[omen](DEATH, TODAY) == 0, (
        f"omen {omen} counted occurrences after the death date"
    )


def test_counts_a_weekday_that_has_not_come_round_yet_within_a_short_span() -> None:
    monday = date(2026, 8, 10)
    assert (
        OMEN_COUNTERS["sundays"](monday, date(2026, 8, 12)),
        OMEN_COUNTERS["sundays"](monday, date(2026, 8, 17)),
    ) == (0, 1), "a partial week counted the wrong number of Sundays"
