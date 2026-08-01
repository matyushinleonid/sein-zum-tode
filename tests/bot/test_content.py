from pathlib import Path

import pytest
from pydantic import ValidationError

from sein_zum_tode.bot.content import (
    BotContent,
    LocalizationContent,
    LocalizedBotContent,
    NotificationSettingsContent,
    PredictionContent,
    QuestionContent,
    QuestionnaireContent,
    YamlBotContentLoader,
)
from sein_zum_tode.bot.errors import ContentConfigurationError

pytestmark = pytest.mark.fast


def localized_content(notification: str = "Days left: {days_left}") -> LocalizedBotContent:
    return LocalizedBotContent(
        help="Navigate",
        about="About",
        unsupported="Unsupported",
        group_unsupported="Groups unsupported",
        scream_denied="Scream denied",
        notification=notification,
        localization=LocalizationContent(
            prompt="Choose your language",
            russian="🇷🇺 RU",
            english="🇺🇸 EN",
            updated="Language changed",
        ),
        notification_settings=NotificationSettingsContent(
            prompt="Frequency?",
            daily="Daily",
            weekly="Weekly",
            monthly="Monthly",
            never="Never",
            updated="Notifications: {frequency}",
        ),
        prediction=PredictionContent(
            limit_exhausted="Limit exhausted",
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
locales:
  en:
    help: Navigate by the constellations
    about: About the constellations
    unsupported: Unsupported
    group_unsupported: Groups unsupported
    scream_denied: Scream denied
    notification: "Days left: {days_left}"
    localization:
      prompt: Choose your language
      russian: "🇷🇺 RU"
      english: "🇺🇸 EN"
      updated: Language changed
    notification_settings:
      prompt: Frequency?
      daily: Daily
      weekly: Weekly
      monthly: Monthly
      never: Never
      updated: "Notifications: {frequency}"
    prediction:
      limit_exhausted: Limit exhausted
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
        actual.default().notification_text(17),
        actual.default().questionnaire.questions,
    ) == (
        "stellar-v7",
        "Navigate by the constellations",
        "Days left: 17",
        (QuestionContent(id="star", text="Which star?"),),
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
        localized_content(notification)


def test_rejects_invalid_notification_settings_and_mock_templates() -> None:
    with pytest.raises(ValidationError):
        NotificationSettingsContent(
            prompt="Frequency?",
            daily="Daily",
            weekly="Weekly",
            monthly="Monthly",
            never="Never",
            updated="No placeholder",
        )
    with pytest.raises(ValidationError):
        PredictionContent(
            limit_exhausted="Limit",
            failed="Failed",
            mock="{answers} {locale}",
        )


def test_falls_back_to_default_content_for_an_unknown_locale() -> None:
    content = BotContent(
        version="stellar-v13",
        default_locale="en",
        locales={"en": localized_content()},
    )

    assert content.localized("unknown") is content.default(), (
        "unknown Mortal locale did not use configured default content"
    )
