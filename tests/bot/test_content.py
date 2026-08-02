from pathlib import Path

import pytest
from pydantic import ValidationError

from sein_zum_tode.bot.content import (
    BotContent,
    LLMContent,
    LocalizationContent,
    LocalizedBotContent,
    NotificationContent,
    NotificationEmojiPool,
    NotificationEpicPool,
    NotificationMedia,
    NotificationMediaKind,
    NotificationMythicPool,
    NotificationMythicVariant,
    NotificationRewards,
    NotificationSettingsContent,
    NotificationTextForms,
    NotificationTextVariant,
    PredictionContent,
    QuestionContent,
    QuestionnaireContent,
    YamlBotContentLoader,
)
from sein_zum_tode.bot.errors import ContentConfigurationError
from sein_zum_tode.unsupported.models import (
    VISUALLY_EMPTY_TELEGRAM_MESSAGE,
    UnsupportedUpdateContent,
)

pytestmark = pytest.mark.fast


def emoji_pool(*, probability: float, first_id: int, prelude: str) -> NotificationEmojiPool:
    return NotificationEmojiPool(
        probability=probability,
        prelude=prelude,
        rtl_walk_ids=(str(first_id),),
        ltr_walk_ids=(str(first_id + 1),),
        rtl_arrow_ids=(str(first_id + 2),),
        ltr_arrow_ids=(str(first_id + 3),),
        dead_ids=(str(first_id + 4),),
    )


def notification_rewards() -> NotificationRewards:
    return NotificationRewards(
        lucky=emoji_pool(probability=0.1, first_id=127, prelude="🍀 Lucky!"),
        rare=emoji_pool(probability=0.05, first_id=137, prelude="✨ Rare!"),
        epic=NotificationEpicPool(probability=1 / 60, prelude="🌟 Epic!"),
        mythic=NotificationMythicPool(probability=1 / 180, prelude="👑 Mythic!"),
    )


def notification_content(
    default: str = "Days left: {days_left}",
) -> NotificationContent:
    natural = NotificationTextForms(other="{days_left} days remain")
    return NotificationContent(
        default=NotificationTextForms(other=default),
        natural=natural,
        epic=(NotificationTextVariant(id="haunting", text=natural),),
        mythic=(
            NotificationMythicVariant(
                id="stupa",
                media=NotificationMedia(
                    kind=NotificationMediaKind.AUDIO,
                    url="https://example.com/stupa.mp3",
                ),
            ),
        ),
    )


def localized_content(
    notification: NotificationContent | None = None,
) -> LocalizedBotContent:
    return LocalizedBotContent(
        help="Navigate",
        about="About",
        text_unsupported="Use /help",
        group_unsupported="Groups unsupported",
        scream_denied="Scream denied",
        notification=notification or notification_content(),
        localization=LocalizationContent(
            prompt="Choose your language",
            russian="🇷🇺 RU",
            english="🇺🇸 EN",
            updated="Language changed",
        ),
        notification_settings=NotificationSettingsContent(
            prompt="Frequency in {timezone}?",
            daily="Daily",
            weekly="Weekly",
            monthly="Monthly",
            never="Never",
            custom="✨ Custom",
            custom_prompt="Describe the schedule",
            custom_mock="Schedule updated",
            custom_invalid="Invalid schedule",
            custom_too_frequent="Schedule too frequent",
            custom_failed="Schedule failed",
            custom_interpretation="Interpreted:",
            custom_schedule="Schedule:",
            custom_cron="Cron",
            custom_description="Description",
            custom_timezone="Timezone",
            custom_next_notifications="Next:",
            custom_disabled="Disabled",
            custom_description_unavailable="Description unavailable",
            custom_next_notifications_unavailable="Next unavailable",
            custom_unchanged="Unchanged",
            custom_change_hint="Change it",
            updated="Notifications: {frequency}",
        ),
        llm=LLMContent(limit_exhausted="Limit exhausted"),
        prediction=PredictionContent(
            failed="Failed",
            mock="Mock: {answers}",
        ),
        questionnaire=QuestionnaireContent(
            privacy_notice="Private",
            started="Started",
            completed="Completed",
            deleted="Deleted",
            questions=(QuestionContent(id="q1", text="Question?"),),
        ),
    )


def test_loads_versioned_localized_bot_content_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "content.yaml"
    path.write_text(
        """
version: stellar-v7
default_locale: en
unsupported_updates:
  initial_silence_count: 2
  stanzas:
    - ["First line", "Second line"]
notification_rewards:
  lucky:
    probability: 0.1
    prelude: "🍀 Lucky!"
    rtl_walk_ids: ["127"]
    ltr_walk_ids: ["131"]
    rtl_arrow_ids: ["137"]
    ltr_arrow_ids: ["139"]
    dead_ids: ["149"]
  rare:
    probability: 0.05
    prelude: "✨ Rare!"
    rtl_walk_ids: ["151"]
    ltr_walk_ids: ["157"]
    rtl_arrow_ids: ["163"]
    ltr_arrow_ids: ["167"]
    dead_ids: ["173"]
  epic:
    probability: 0.016666666666666666
    prelude: "🌟 Epic!"
  mythic:
    probability: 0.005555555555555556
    prelude: "👑 Mythic!"
locales:
  en:
    help: Navigate by the constellations
    about: About the constellations
    text_unsupported: Use /help
    group_unsupported: Groups unsupported
    scream_denied: Scream denied
    notification:
      default:
        other: "Days left: {days_left}"
      natural:
        other: "{days_left} days remain"
      epic:
        - id: haunting
          text:
            other: "Haunting {days_left} days"
      mythic:
        - id: stupa
          media:
            kind: audio
            url: https://example.com/stupa.mp3
    localization:
      prompt: Choose your language
      russian: "🇷🇺 RU"
      english: "🇺🇸 EN"
      updated: Language changed
    notification_settings:
      prompt: Frequency in {timezone}?
      daily: Daily
      weekly: Weekly
      monthly: Monthly
      never: Never
      custom: Custom
      custom_prompt: Describe the schedule
      custom_mock: Schedule updated
      custom_invalid: Invalid schedule
      custom_too_frequent: Schedule too frequent
      custom_failed: Schedule failed
      custom_interpretation: "Interpreted:"
      custom_schedule: "Schedule:"
      custom_cron: Cron
      custom_description: Description
      custom_timezone: Timezone
      custom_next_notifications: "Next:"
      custom_disabled: Disabled
      custom_description_unavailable: Description unavailable
      custom_next_notifications_unavailable: Next unavailable
      custom_unchanged: Unchanged
      custom_change_hint: Change it
      updated: "Notifications: {frequency}"
    llm:
      limit_exhausted: Limit exhausted
    prediction:
      failed: Failed
      mock: "Mock: {answers}"
    questionnaire:
      privacy_notice: Private answers
      started: The survey has started
      completed: Survey complete
      deleted: Private answers deleted
      questions:
        - id: star
          text: Which star?
""".strip(),
        encoding="utf-8",
    )

    actual = YamlBotContentLoader(path).load()

    assert (
        actual.version,
        actual.default().help,
        actual.default().notification.default.render(17, "other"),
        actual.default().questionnaire.questions,
        actual.unsupported_updates.messages(),
    ) == (
        "stellar-v7",
        "Navigate by the constellations",
        "Days left: 17",
        (QuestionContent(id="star", text="Which star?"),),
        ("First line", "Second line", VISUALLY_EMPTY_TELEGRAM_MESSAGE),
    ), "YAML loading changed the configured version, locale, or questions"


@pytest.mark.parametrize(
    "payload",
    [
        "locales: [",
        "version: incomplete",
    ],
)
def test_rejects_unreadable_or_invalid_yaml_content(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "invalid-content.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ContentConfigurationError):
        YamlBotContentLoader(path).load()


def test_rejects_a_missing_content_file(tmp_path: Path) -> None:
    with pytest.raises(ContentConfigurationError):
        YamlBotContentLoader(tmp_path / "missing.yaml").load()


def test_rejects_a_default_locale_without_content() -> None:
    localized = localized_content()

    with pytest.raises(ValidationError):
        BotContent(
            version="stellar-v11",
            default_locale="ru",
            unsupported_updates=UnsupportedUpdateContent(
                initial_silence_count=1,
                stanzas=(("Decay",),),
            ),
            notification_rewards=notification_rewards(),
            locales={"en": localized},
        )


def test_rejects_duplicate_question_ids() -> None:
    with pytest.raises(ValidationError):
        QuestionnaireContent(
            privacy_notice="Private",
            started="Started",
            completed="Completed",
            deleted="Deleted",
            questions=(
                QuestionContent(id="duplicate", text="First?"),
                QuestionContent(id="duplicate", text="Second?"),
            ),
        )


@pytest.mark.parametrize(
    "notification",
    [
        "No placeholder",
        "{days_left} {locale}",
    ],
)
def test_rejects_an_invalid_notification_template(notification: str) -> None:
    with pytest.raises(ValidationError):
        localized_content(notification_content(notification))


def test_rejects_duplicate_notification_variant_ids_across_reward_tiers() -> None:
    natural = NotificationTextForms(other="Natural {days_left}")
    with pytest.raises(ValidationError):
        NotificationContent(
            default=NotificationTextForms(other="Default {days_left}"),
            natural=natural,
            epic=(NotificationTextVariant(id="duplicate", text=natural),),
            mythic=(
                NotificationMythicVariant(
                    id="duplicate",
                    text=natural,
                ),
            ),
        )


def test_rejects_a_non_numeric_custom_emoji_identifier() -> None:
    with pytest.raises(ValidationError):
        NotificationEmojiPool(
            probability=0.1,
            prelude="🍀 Lucky!",
            rtl_walk_ids=("not-an-id",),
            ltr_walk_ids=("131",),
            rtl_arrow_ids=("137",),
            ltr_arrow_ids=("139",),
            dead_ids=("149",),
        )


def test_rejects_duplicate_emoji_within_one_reward_tier() -> None:
    with pytest.raises(ValidationError):
        NotificationEmojiPool(
            probability=0.1,
            prelude="🍀 Lucky!",
            rtl_walk_ids=("127",),
            ltr_walk_ids=("127",),
            rtl_arrow_ids=("137",),
            ltr_arrow_ids=("139",),
            dead_ids=("149",),
        )


def test_rejects_reward_probabilities_that_cannot_be_mutually_exclusive() -> None:
    rewards = notification_rewards()

    with pytest.raises(ValidationError):
        NotificationRewards(
            lucky=rewards.lucky.model_copy(update={"probability": 0.8}),
            rare=rewards.rare.model_copy(update={"probability": 0.3}),
            epic=rewards.epic,
            mythic=rewards.mythic,
        )
    with pytest.raises(ValidationError):
        NotificationRewards(
            lucky=rewards.lucky,
            rare=rewards.rare,
            epic=rewards.epic.model_copy(update={"probability": 0.8}),
            mythic=rewards.mythic.model_copy(update={"probability": 0.3}),
        )


def test_rejects_an_empty_mythic_reward_variant() -> None:
    with pytest.raises(ValidationError):
        NotificationMythicVariant(id="empty")


def test_rejects_invalid_notification_settings_and_mock_templates() -> None:
    with pytest.raises(ValidationError):
        NotificationSettingsContent(
            prompt="Frequency?",
            daily="Daily",
            weekly="Weekly",
            monthly="Monthly",
            never="Never",
            custom="✨ Custom",
            custom_prompt="Describe the schedule",
            custom_mock="Schedule updated",
            custom_invalid="Invalid schedule",
            custom_too_frequent="Schedule too frequent",
            custom_failed="Schedule failed",
            custom_interpretation="Interpreted",
            custom_schedule="Schedule",
            custom_cron="Cron",
            custom_description="Description",
            custom_timezone="Timezone",
            custom_next_notifications="Next",
            custom_disabled="Disabled",
            custom_description_unavailable="Description unavailable",
            custom_next_notifications_unavailable="Next unavailable",
            custom_unchanged="Unchanged",
            custom_change_hint="Change",
            updated="Notifications: {frequency}",
        )
    with pytest.raises(ValidationError):
        NotificationSettingsContent(
            prompt="Frequency in {timezone}?",
            daily="Daily",
            weekly="Weekly",
            monthly="Monthly",
            never="Never",
            custom="✨ Custom",
            custom_prompt="Describe the schedule",
            custom_mock="Schedule updated",
            custom_invalid="Invalid schedule",
            custom_too_frequent="Schedule too frequent",
            custom_failed="Schedule failed",
            custom_interpretation="Interpreted",
            custom_schedule="Schedule",
            custom_cron="Cron",
            custom_description="Description",
            custom_timezone="Timezone",
            custom_next_notifications="Next",
            custom_disabled="Disabled",
            custom_description_unavailable="Description unavailable",
            custom_next_notifications_unavailable="Next unavailable",
            custom_unchanged="Unchanged",
            custom_change_hint="Change",
            updated="No placeholder",
        )
    with pytest.raises(ValidationError):
        PredictionContent(
            failed="Failed",
            mock="{answers} {locale}",
        )


def test_falls_back_to_default_content_for_an_unknown_locale() -> None:
    content = BotContent(
        version="stellar-v13",
        default_locale="en",
        unsupported_updates=UnsupportedUpdateContent(
            initial_silence_count=1,
            stanzas=(("Decay",),),
        ),
        notification_rewards=notification_rewards(),
        locales={"en": localized_content()},
    )

    assert content.localized("unknown") is content.default(), (
        "unknown Mortal locale did not use configured default content"
    )
