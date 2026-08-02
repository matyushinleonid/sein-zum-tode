from pathlib import Path

import pytest
from pydantic import ValidationError

from sein_zum_tode.bot.content import (
    BotContent,
    LLMContent,
    LocalizationContent,
    LocalizedBotContent,
    NotificationContent,
    NotificationDecorationContent,
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


def notification_decoration() -> NotificationDecorationContent:
    return NotificationDecorationContent(
        probability=0.1,
        rtl_walk_ids=("127",),
        ltr_walk_ids=("131",),
        rtl_arrow_ids=("137",),
        ltr_arrow_ids=("139",),
        dead_ids=("149",),
    )


def localized_content(
    notification: NotificationContent | None = None,
) -> LocalizedBotContent:
    return LocalizedBotContent(
        help="Navigate",
        about="About",
        group_unsupported="Groups unsupported",
        scream_denied="Scream denied",
        notification=notification
        or NotificationContent(
            default=NotificationTextForms(other="Days left: {days_left}"),
        ),
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
            updated="Notifications: {frequency}",
        ),
        llm=LLMContent(limit_exhausted="Limit exhausted"),
        prediction=PredictionContent(
            failed="Failed",
            mock="Mock: {answers}",
        ),
        questionnaire=QuestionnaireContent(
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
notification_decoration:
  probability: 0.1
  rtl_walk_ids: ["127"]
  ltr_walk_ids: ["131"]
  rtl_arrow_ids: ["137"]
  ltr_arrow_ids: ["139"]
  dead_ids: ["149"]
locales:
  en:
    help: Navigate by the constellations
    about: About the constellations
    group_unsupported: Groups unsupported
    scream_denied: Scream denied
    notification:
      default:
        other: "Days left: {days_left}"
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
      updated: "Notifications: {frequency}"
    llm:
      limit_exhausted: Limit exhausted
    prediction:
      failed: Failed
      mock: "Mock: {answers}"
    questionnaire:
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
            notification_decoration=notification_decoration(),
            locales={"en": localized},
        )


def test_rejects_duplicate_question_ids() -> None:
    with pytest.raises(ValidationError):
        QuestionnaireContent(
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
        localized_content(
            NotificationContent(
                default=NotificationTextForms(other=notification),
            )
        )


@pytest.mark.parametrize(
    "variants",
    [
        (
            NotificationTextVariant(
                id="duplicate",
                probability=0.2,
                text=NotificationTextForms(other="First {days_left}"),
            ),
            NotificationTextVariant(
                id="duplicate",
                probability=0.3,
                text=NotificationTextForms(other="Second {days_left}"),
            ),
        ),
        (
            NotificationTextVariant(
                id="first",
                probability=0.7,
                text=NotificationTextForms(other="First {days_left}"),
            ),
            NotificationTextVariant(
                id="second",
                probability=0.4,
                text=NotificationTextForms(other="Second {days_left}"),
            ),
        ),
    ],
)
def test_rejects_ambiguous_notification_variant_configuration(
    variants: tuple[NotificationTextVariant, ...],
) -> None:
    with pytest.raises(ValidationError):
        NotificationContent(
            default=NotificationTextForms(other="Default {days_left}"),
            variants=variants,
        )


def test_rejects_a_non_numeric_custom_emoji_identifier() -> None:
    with pytest.raises(ValidationError):
        NotificationDecorationContent(
            probability=0.1,
            rtl_walk_ids=("not-an-id",),
            ltr_walk_ids=("131",),
            rtl_arrow_ids=("137",),
            ltr_arrow_ids=("139",),
            dead_ids=("149",),
        )


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
        notification_decoration=notification_decoration(),
        locales={"en": localized_content()},
    )

    assert content.localized("unknown") is content.default(), (
        "unknown Mortal locale did not use configured default content"
    )
