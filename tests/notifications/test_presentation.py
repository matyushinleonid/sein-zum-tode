import pytest

from sein_zum_tode.bot.content import (
    BotContent,
    NotificationContent,
    NotificationEmojiPool,
    NotificationMedia,
    NotificationMediaKind,
    NotificationMythicVariant,
    NotificationNumberStyle,
    NotificationTextForms,
    NotificationTextStyle,
    NotificationTextVariant,
    NotificationTier,
)
from sein_zum_tode.bot.models import TelegramAttachment, TelegramAttachmentKind
from sein_zum_tode.notifications.models import RenderedNotification
from sein_zum_tode.notifications.presentation import (
    NotificationMessagePresenter,
    StableNotificationRandomizer,
)
from tests.support import BotContents, NumberSpellerMemory, notification_rewards

pytestmark = pytest.mark.fast


class RandomizerMemory:
    def __init__(
        self,
        *,
        values: dict[str, float] | None = None,
        indexes: dict[str, int] | None = None,
    ) -> None:
        self.values = values or {}
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
    return NotificationContent(
        default=NotificationTextForms(other="Осталось дней: {days_left}"),
        natural=natural,
        epic=(
            NotificationTextVariant(
                id="haunting",
                text=NotificationTextForms(
                    other="Осталось {days_left} дней. Игнорировать всё сложнее"
                ),
            ),
            NotificationTextVariant(
                id="witch_house",
                text=natural,
                style=NotificationTextStyle.WITCH_HOUSE,
            ),
            NotificationTextVariant(
                id="words",
                text=natural,
                number_style=NotificationNumberStyle.WORDS,
            ),
            NotificationTextVariant(
                id="witch_house_words",
                text=natural,
                style=NotificationTextStyle.WITCH_HOUSE,
                number_style=NotificationNumberStyle.WORDS,
            ),
        ),
        mythic=(
            NotificationMythicVariant(
                id="stupa",
                media=NotificationMedia(
                    kind=NotificationMediaKind.AUDIO,
                    url="https://example.com/stupa.mp3",
                ),
            ),
            NotificationMythicVariant(
                id="mythic_words",
                text=natural,
                style=NotificationTextStyle.WITCH_HOUSE,
                number_style=NotificationNumberStyle.WORDS,
            ),
        ),
    )


def content() -> BotContent:
    original = BotContents.debug()
    russian = original.localized("ru").model_copy(update={"notification": notification_content()})
    rewards = notification_rewards()
    return original.model_copy(
        update={
            "notification_rewards": rewards.model_copy(
                update={
                    "lucky": NotificationEmojiPool(
                        probability=0.1,
                        prelude="🍀 Lucky!",
                        rtl_walk_ids=("11",),
                        ltr_walk_ids=("17",),
                        rtl_arrow_ids=("23",),
                        ltr_arrow_ids=("31",),
                        dead_ids=("41",),
                        rtl_walk_emoji=("🏃",),
                        ltr_walk_emoji=("🚀",),
                        rtl_arrow_emoji=("👈",),
                        ltr_arrow_emoji=("➡️",),
                        dead_emoji=("☠️",),
                    ),
                    "rare": NotificationEmojiPool(
                        probability=0.05,
                        prelude="✨ Rare!",
                        rtl_walk_ids=("13",),
                        ltr_walk_ids=("19",),
                        rtl_arrow_ids=("29",),
                        ltr_arrow_ids=("37",),
                        dead_ids=("43",),
                    ),
                }
            ),
            "locales": {"en": original.localized("en"), "ru": russian},
        }
    )


def presenter(randomizer: RandomizerMemory) -> NotificationMessagePresenter:
    return NotificationMessagePresenter(
        content=content(),
        number_speller=NumberSpellerMemory(words={(120, "ru"): "сто двадцать"}),
        randomizer=randomizer,
    )


@pytest.mark.parametrize(
    ("message_draw", "emoji_draw", "expected_tier", "expected_prelude"),
    [
        (0.0, 0.99, NotificationTier.MYTHIC, "👑 Mythic!"),
        (0.01, 0.99, NotificationTier.EPIC, "🌟 Epic!"),
        (0.9, 0.01, NotificationTier.RARE, "✨ Rare!"),
        (0.9, 0.1, NotificationTier.LUCKY, "🍀 Lucky!"),
        (0.9, 0.9, None, None),
    ],
)
def test_selects_mutually_exclusive_reward_tiers(
    message_draw: float,
    emoji_draw: float,
    expected_tier: NotificationTier | None,
    expected_prelude: str | None,
) -> None:
    randomizer = RandomizerMemory(
        values={
            "message_tier": message_draw,
            "emoji_tier": emoji_draw,
            "rare_direction": 0.25,
            "lucky_direction": 0.25,
        },
        indexes={
            "base_text": 0,
            "epic_variant": 0,
            "mythic_variant": 0,
            "rare_ltr_walk": 0,
            "rare_ltr_arrow": 0,
            "rare_ltr_dead": 0,
            "lucky_ltr_walk": 0,
            "lucky_ltr_arrow": 0,
            "lucky_ltr_dead": 0,
        },
    )

    actual = presenter(randomizer).render(locale="ru", days_left=120, seed="reward-120")

    assert (actual.tier, actual.prelude_text) == (
        expected_tier,
        expected_prelude,
    ), "notification reward probabilities did not produce the configured exclusive tier"


@pytest.mark.parametrize(
    ("base_index", "expected_variant", "expected_text"),
    [
        (0, "default", "Осталось дней: 120"),
        (1, "natural", "Осталось 120 дней"),
    ],
)
def test_selects_default_and_natural_text_with_equal_index_space(
    base_index: int,
    expected_variant: str,
    expected_text: str,
) -> None:
    actual = presenter(
        RandomizerMemory(
            values={"message_tier": 0.99, "emoji_tier": 0.99},
            indexes={"base_text": base_index},
        )
    ).render(
        locale="ru",
        days_left=120,
        seed="base-120",
        sample=None,
    )

    assert (actual.variant_id, actual.text) == (
        expected_variant,
        expected_text,
    ), "base notification did not select default and natural text from equal slots"


@pytest.mark.parametrize(
    ("variant_index", "expected_variant", "expected_text"),
    [
        (0, "haunting", "Осталось 120 дней. Игнорировать всё сложнее"),
        (1, "witch_house", "Ωϲŧλлωϲь 120 δнξй"),
        (2, "words", "Осталось сто двадцать дней"),
        (3, "witch_house_words", "Ωϲŧλлωϲь ϲŧω δвλδцλŧь δнξй"),
    ],
)
def test_selects_each_epic_text_with_equal_index_space(
    variant_index: int,
    expected_variant: str,
    expected_text: str,
) -> None:
    randomizer = RandomizerMemory(
        values={"rare_direction": 0.25},
        indexes={
            "epic_variant": variant_index,
            "rare_ltr_walk": 0,
            "rare_ltr_arrow": 0,
            "rare_ltr_dead": 0,
        },
    )

    actual = presenter(randomizer).render(
        locale="ru",
        days_left=120,
        seed="epic-120",
        sample=NotificationTier.EPIC,
    )

    assert (actual.variant_id, actual.fallback_text) == (
        expected_variant,
        f"🚶➡️💀\n{expected_text}",
    ), "epic pool did not select its text variants uniformly or force Rare emoji"


def test_renders_a_mythic_s3_attachment_with_base_text_and_rare_emoji() -> None:
    randomizer = RandomizerMemory(
        values={"rare_direction": 0.25},
        indexes={
            "mythic_variant": 0,
            "base_text": 1,
            "rare_ltr_walk": 0,
            "rare_ltr_arrow": 0,
            "rare_ltr_dead": 0,
        },
    )

    actual = presenter(randomizer).render(
        locale="ru",
        days_left=120,
        seed="mythic-120",
        sample=NotificationTier.MYTHIC,
    )

    assert actual == RenderedNotification(
        text=(
            '<tg-emoji emoji-id="19">🚶</tg-emoji>'
            '<tg-emoji emoji-id="37">➡️</tg-emoji>'
            '<tg-emoji emoji-id="43">💀</tg-emoji>\nОсталось 120 дней'
        ),
        parse_mode="HTML",
        fallback_text="🚶➡️💀\nОсталось 120 дней",
        prelude_text="👑 Mythic!",
        attachment=TelegramAttachment(
            kind=TelegramAttachmentKind.AUDIO,
            url="https://example.com/stupa.mp3",
        ),
        variant_id="stupa",
        tier=NotificationTier.MYTHIC,
    ), "Mythic reward lost its S3 media, separate prelude, base text, or forced Rare emoji"


def test_supports_a_text_only_mythic_variant() -> None:
    randomizer = RandomizerMemory(
        values={"rare_direction": 0.75},
        indexes={
            "mythic_variant": 1,
            "rare_rtl_dead": 0,
            "rare_rtl_arrow": 0,
            "rare_rtl_walk": 0,
        },
    )

    actual = presenter(randomizer).render(
        locale="ru",
        days_left=120,
        seed="mythic-words-120",
        sample=NotificationTier.MYTHIC,
    )

    assert (
        actual.variant_id,
        actual.fallback_text,
        actual.attachment,
    ) == (
        "mythic_words",
        "💀⬅️🚶\nΩϲŧλлωϲь ϲŧω δвλδцλŧь δнξй",
        None,
    ), "Mythic pool could not represent an Epic-like text-only reward"


@pytest.mark.parametrize(
    ("tier", "direction", "expected_rich", "expected_fallback"),
    [
        (
            NotificationTier.LUCKY,
            0.25,
            "🚀➡️☠️",
            "🚀➡️☠️",
        ),
        (
            NotificationTier.LUCKY,
            0.75,
            "☠️👈🏃",
            "☠️👈🏃",
        ),
        (
            NotificationTier.RARE,
            0.25,
            (
                '<tg-emoji emoji-id="19">🚶</tg-emoji>'
                '<tg-emoji emoji-id="37">➡️</tg-emoji>'
                '<tg-emoji emoji-id="43">💀</tg-emoji>'
            ),
            "🚶➡️💀",
        ),
    ],
)
def test_draws_custom_and_regular_emoji_in_both_directions(
    tier: NotificationTier,
    direction: float,
    expected_rich: str,
    expected_fallback: str,
) -> None:
    prefix = tier.value
    direction_name = "ltr" if direction < 0.5 else "rtl"
    indexes = {
        "base_text": 0,
        f"{prefix}_{direction_name}_walk": 1 if tier == NotificationTier.LUCKY else 0,
        f"{prefix}_{direction_name}_arrow": 1 if tier == NotificationTier.LUCKY else 0,
        f"{prefix}_{direction_name}_dead": 1 if tier == NotificationTier.LUCKY else 0,
    }
    randomizer = RandomizerMemory(
        values={f"{prefix}_direction": direction},
        indexes=indexes,
    )

    actual = presenter(randomizer).render(
        locale="ru",
        days_left=7,
        seed=f"{prefix}-7",
        sample=tier,
    )

    assert (actual.text, actual.fallback_text) == (
        f"{expected_rich}\nОсталось дней: 7",
        f"{expected_fallback}\nОсталось дней: 7",
    ), "emoji reward changed direction, custom/plain selection, or plain fallback"


def test_uses_default_locale_plural_rules_for_an_unknown_locale() -> None:
    subject = NotificationMessagePresenter(
        content=BotContents.debug(),
        number_speller=NumberSpellerMemory(words={}),
        randomizer=RandomizerMemory(
            values={"message_tier": 0.99, "emoji_tier": 0.99},
            indexes={"base_text": 0},
        ),
    )

    actual = subject.render(
        locale="unknown",
        days_left=1,
        seed="unknown-1",
        sample=None,
    )

    assert actual.text == "mock notification: 1", (
        "unknown locale bypassed the configured default plural rules"
    )


def test_derives_repeatable_independent_values_from_a_notification_seed() -> None:
    subject = StableNotificationRandomizer()

    actual = (
        subject.value("response-47", "message_tier"),
        subject.value("response-47", "emoji_tier"),
        subject.index("response-47", "walk", 29),
    )

    assert actual == (
        subject.value("response-47", "message_tier"),
        subject.value("response-47", "emoji_tier"),
        subject.index("response-47", "walk", 29),
    ), "notification retry produced different pseudo-random choices for the same seed"
