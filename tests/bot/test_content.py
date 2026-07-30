from pathlib import Path

import pytest
from pydantic import ValidationError

from sein_zum_tode.bot.content import (
    BotContent,
    ConversationContent,
    LocalizedBotContent,
    QuestionContent,
    YamlBotContentLoader,
)
from sein_zum_tode.bot.errors import ContentConfigurationError

pytestmark = pytest.mark.fast


def test_loads_versioned_localized_bot_content_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "content.yaml"
    path.write_text(
        """
version: stellar-v7
default_locale: en
locales:
  en:
    help: Navigate by the constellations
    conversation:
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
        actual.default().conversation.questions,
    ) == (
        "stellar-v7",
        "Navigate by the constellations",
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
    localized = LocalizedBotContent(
        help="Navigate",
        conversation=ConversationContent(
            started="Started",
            completed="Completed",
            deleted="Deleted",
            questions=(QuestionContent(id="q1", text="Question?"),),
        ),
    )

    with pytest.raises(ValidationError):
        BotContent(
            version="stellar-v11",
            default_locale="ru",
            locales={"en": localized},
        )


def test_rejects_duplicate_question_ids() -> None:
    with pytest.raises(ValidationError):
        ConversationContent(
            started="Started",
            completed="Completed",
            deleted="Deleted",
            questions=(
                QuestionContent(id="duplicate", text="First?"),
                QuestionContent(id="duplicate", text="Second?"),
            ),
        )
