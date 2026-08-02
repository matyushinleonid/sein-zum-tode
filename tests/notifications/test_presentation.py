import pytest

from sein_zum_tode.bot.content import (
    BotContent,
    NotificationContent,
    NotificationDecorationContent,
    NotificationNumberStyle,
    NotificationTextForms,
    NotificationTextStyle,
    NotificationTextVariant,
)
from sein_zum_tode.notifications.models import RenderedNotification
from sein_zum_tode.notifications.presentation import (
    NotificationMessagePresenter,
    StableNotificationRandomizer,
)
from tests.support import BotContents, NumberSpellerMemory

pytestmark = pytest.mark.fast


class RandomizerMemory:
    def __init__(
        self,
        *,
        values: dict[str, float],
        indexes: dict[str, int] | None = None,
    ) -> None:
        self.values = values
        self.indexes = indexes or {}
        self.events: list[tuple[object, ...]] = []

    def value(self, seed: str, decision: str) -> float:
        self.events.append(("value", seed, decision))
        return self.values[decision]

    def index(self, seed: str, decision: str, size: int) -> int:
        self.events.append(("index", seed, decision, size))
        return self.indexes[decision]


def notification_content() -> NotificationContent:
    natural = NotificationTextForms(
        one="Остался {days_left} день",
        few="Осталось {days_left} дня",
        many="Осталось {days_left} дней",
        other="Осталось {days_left} дня",
    )
    haunting = NotificationTextForms(
        one="Остался {days_left} день. Игнорировать всё сложнее",
        few="Осталось {days_left} дня. Игнорировать всё сложнее",
        many="Осталось {days_left} дней. Игнорировать всё сложнее",
        other="Осталось {days_left} дня. Игнорировать всё сложнее",
    )
    return NotificationContent(
        default=NotificationTextForms(other="Осталось дней: {days_left}"),
        variants=(
            NotificationTextVariant(id="natural", probability=0.5, text=natural),
            NotificationTextVariant(id="haunting", probability=0.01, text=haunting),
            NotificationTextVariant(
                id="witch_house",
                probability=0.01,
                text=natural,
                style=NotificationTextStyle.WITCH_HOUSE,
            ),
            NotificationTextVariant(
                id="words",
                probability=0.01,
                text=natural,
                number_style=NotificationNumberStyle.WORDS,
            ),
            NotificationTextVariant(
                id="witch_house_words",
                probability=0.01,
                text=natural,
                style=NotificationTextStyle.WITCH_HOUSE,
                number_style=NotificationNumberStyle.WORDS,
            ),
        ),
    )


def content(
    *,
    decoration_probability: float,
    notification: NotificationContent | None = None,
) -> BotContent:
    original = BotContents.debug()
    russian = original.localized("ru").model_copy(
        update={"notification": notification or notification_content()}
    )
    return original.model_copy(
        update={
            "notification_decoration": NotificationDecorationContent(
                probability=decoration_probability,
                rtl_walk_ids=("11", "13"),
                ltr_walk_ids=("17", "19"),
                rtl_arrow_ids=("23", "29"),
                ltr_arrow_ids=("31", "37"),
                dead_ids=("41", "43"),
            ),
            "locales": {"en": original.localized("en"), "ru": russian},
        }
    )


@pytest.mark.parametrize(
    ("draw", "expected_variant", "expected_text"),
    [
        (0.1, "natural", "Осталось 120 дней"),
        (0.505, "haunting", "Осталось 120 дней. Игнорировать всё сложнее"),
        (0.515, "witch_house", "Ωϲŧλлωϲь 120 δнξй"),
        (0.525, "words", "Осталось сто двадцать дней"),
        (0.535, "witch_house_words", "Ωϲŧλлωϲь ϲŧω δвλδцλŧь δнξй"),
        (0.9, None, "Осталось дней: 120"),
    ],
)
def test_selects_one_configured_text_variant_or_the_default(
    draw: float,
    expected_variant: str | None,
    expected_text: str,
) -> None:
    speller = NumberSpellerMemory(words={(120, "ru"): "сто двадцать"})
    subject = NotificationMessagePresenter(
        content=content(decoration_probability=0),
        number_speller=speller,
        randomizer=RandomizerMemory(
            values={"text_variant": draw, "decoration": 0.99},
        ),
    )

    actual = subject.render(locale="ru", days_left=120, seed="response-120")

    assert actual == RenderedNotification(
        text=expected_text,
        parse_mode=None,
        fallback_text=None,
        variant_id=expected_variant,
        decorated=False,
    ), "notification text selection did not respect its configured probability interval"


@pytest.mark.parametrize(
    ("direction", "expected_text", "expected_fallback", "expected_index_events"),
    [
        (
            0.25,
            '<tg-emoji emoji-id="19">🚶</tg-emoji>'
            '<tg-emoji emoji-id="31">➡️</tg-emoji>'
            '<tg-emoji emoji-id="43">💀</tg-emoji>\nDays &lt; 7 &amp; counting',
            "🚶➡️💀\nDays < 7 & counting",
            (
                ("index", "response-7", "ltr_walk", 2),
                ("index", "response-7", "ltr_arrow", 2),
                ("index", "response-7", "ltr_dead", 2),
            ),
        ),
        (
            0.75,
            '<tg-emoji emoji-id="43">💀</tg-emoji>'
            '<tg-emoji emoji-id="29">⬅️</tg-emoji>'
            '<tg-emoji emoji-id="11">🚶</tg-emoji>\nDays &lt; 7 &amp; counting',
            "💀⬅️🚶\nDays < 7 & counting",
            (
                ("index", "response-7", "rtl_dead", 2),
                ("index", "response-7", "rtl_arrow", 2),
                ("index", "response-7", "rtl_walk", 2),
            ),
        ),
    ],
)
def test_decorates_in_either_direction_and_keeps_a_plain_fallback(
    direction: float,
    expected_text: str,
    expected_fallback: str,
    expected_index_events: tuple[tuple[object, ...], ...],
) -> None:
    randomizer = RandomizerMemory(
        values={"text_variant": 0.99, "decoration": 0.05, "direction": direction},
        indexes={
            "ltr_walk": 1,
            "ltr_arrow": 0,
            "ltr_dead": 1,
            "rtl_dead": 1,
            "rtl_arrow": 1,
            "rtl_walk": 0,
        },
    )
    notification = NotificationContent(
        default=NotificationTextForms(other="Days < {days_left} & counting"),
    )
    subject = NotificationMessagePresenter(
        content=content(
            decoration_probability=0.1,
            notification=notification,
        ),
        number_speller=NumberSpellerMemory(words={}),
        randomizer=randomizer,
    )

    actual = subject.render(locale="ru", days_left=7, seed="response-7")

    assert (
        actual,
        tuple(event for event in randomizer.events if event[0] == "index"),
    ) == (
        RenderedNotification(
            text=expected_text,
            parse_mode="HTML",
            fallback_text=expected_fallback,
            variant_id=None,
            decorated=True,
        ),
        expected_index_events,
    ), "custom emoji direction, IDs, HTML escaping, or fallback text changed"


def test_uses_default_locale_plural_rules_for_an_unknown_locale() -> None:
    original = BotContents.debug()
    english = original.localized("en").model_copy(
        update={
            "notification": NotificationContent(
                default=NotificationTextForms(
                    one="{days_left} day",
                    other="{days_left} days",
                )
            )
        }
    )
    configured = original.model_copy(update={"locales": {"en": english}})
    subject = NotificationMessagePresenter(
        content=configured,
        number_speller=NumberSpellerMemory(words={}),
        randomizer=RandomizerMemory(
            values={"text_variant": 0.99, "decoration": 0.99},
        ),
    )

    actual = subject.render(locale="unknown", days_left=1, seed="response-1")

    assert actual.text == "1 day", "unknown locale bypassed the configured default plural rules"


def test_derives_repeatable_independent_values_from_a_notification_seed() -> None:
    subject = StableNotificationRandomizer()

    actual = (
        subject.value("response-47", "decoration"),
        subject.value("response-47", "direction"),
        subject.index("response-47", "walk", 29),
    )

    assert actual == (
        subject.value("response-47", "decoration"),
        subject.value("response-47", "direction"),
        subject.index("response-47", "walk", 29),
    ), "notification retry produced different pseudo-random choices for the same seed"
