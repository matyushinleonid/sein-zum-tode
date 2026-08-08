from collections.abc import Callable, Mapping
from datetime import date, timedelta

type OmenCounter = Callable[[date, date], int]

SECONDS_PER_DAY = 86_400
JULIAN_YEAR_DAYS = 365.25


def _span(today: date, death: date) -> int:
    return max((death - today).days, 0)


def _weekday(weekday: int) -> OmenCounter:
    def count(today: date, death: date) -> int:
        span = _span(today, death)
        if span == 0:
            return 0
        first = today + timedelta(days=1)
        offset = (weekday - first.weekday()) % 7
        if offset >= span:
            return 0
        return (span - offset - 1) // 7 + 1

    return count


def _month_days(day: int, month: int | None = None) -> OmenCounter:
    def count(today: date, death: date) -> int:
        if death <= today:
            return 0
        found = 0
        year, index = today.year, today.month
        while date(year, index, 1) <= death:
            if month is None or index == month:
                try:
                    candidate = date(year, index, day)
                except ValueError:
                    candidate = None
                if candidate is not None and today < candidate <= death:
                    found += 1
            index += 1
            if index == 13:
                year, index = year + 1, 1
        return found

    return count


def _cycle_days(period_days: float) -> OmenCounter:
    def count(today: date, death: date) -> int:
        return int(_span(today, death) // period_days)

    return count


def _cycle_seconds(period_seconds: float) -> OmenCounter:
    def count(today: date, death: date) -> int:
        return int(_span(today, death) * SECONDS_PER_DAY // period_seconds)

    return count


def _occurrences(*iso_dates: str) -> OmenCounter:
    moments = tuple(date.fromisoformat(value) for value in iso_dates)

    def count(today: date, death: date) -> int:
        return sum(1 for moment in moments if today < moment <= death)

    return count


OMEN_COUNTERS: Mapping[str, OmenCounter] = {
    "crab_pulsar_rotations": _cycle_seconds(0.0337),
    "sundays": _weekday(6),
    "wednesdays": _weekday(2),
    "full_moons": _cycle_days(29.530588),
    "new_years": _month_days(day=1, month=1),
    "winters": _month_days(day=21, month=12),
    "jupiter_oppositions": _cycle_days(398.9),
    "encke_returns": _cycle_days(3.30 * JULIAN_YEAR_DAYS),
    "leap_days": _month_days(day=29, month=2),
    "proxima_light_crossings": _cycle_days(4.2465 * JULIAN_YEAR_DAYS),
    "mercury_transits": _occurrences(
        "2032-11-13",
        "2039-11-07",
        "2049-05-07",
        "2052-11-09",
        "2062-05-11",
        "2065-11-11",
        "2078-11-14",
        "2085-11-07",
        "2095-05-08",
        "2098-11-10",
    ),
    "sirius_light_crossings": _cycle_days(8.611 * JULIAN_YEAR_DAYS),
    "saros_cycles": _cycle_days(6585.3213),
    "metonic_cycles": _cycle_days(6939.69),
    "great_conjunctions": _occurrences(
        "2040-10-31",
        "2060-04-07",
        "2080-03-15",
        "2100-09-18",
    ),
    "saturn_returns": _cycle_days(29.4571 * JULIAN_YEAR_DAYS),
    "tempel_tuttle_returns": _occurrences("2031-05-20", "2064-06-01", "2097-06-10"),
    "pons_brooks_returns": _occurrences("2095-04-19"),
    "halleys_comet_returns": _occurrences("2061-07-28", "2134-03-27"),
    "venus_transits": _occurrences("2117-12-11", "2125-12-08"),
    "swift_tuttle_returns": _occurrences("2126-07-12"),
    "great_years": _cycle_days(25_772 * JULIAN_YEAR_DAYS),
    "galactic_years": _cycle_days(230_000_000 * JULIAN_YEAR_DAYS),
}
