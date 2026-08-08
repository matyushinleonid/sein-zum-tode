from enum import StrEnum
from pathlib import Path
from string import Formatter
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError

from sein_zum_tode.bot.errors import ContentConfigurationError
from sein_zum_tode.notifications.omens import OMEN_COUNTERS
from sein_zum_tode.unsupported.models import UnsupportedUpdateContent

TELEGRAM_TEXT_LIMIT = 4096
CustomEmojiId = Annotated[str, Field(pattern=r"^\d+$")]


class NotificationTextStyle(StrEnum):
    PLAIN = "plain"
    WITCH_HOUSE = "witch_house"


class NotificationNumberStyle(StrEnum):
    DIGITS = "digits"
    WORDS = "words"


class NotificationTier(StrEnum):
    LUCKY = "lucky"
    RARE = "rare"
    OMEN = "omen"
    EPIC = "epic"
    MYTHIC = "mythic"


class NotificationMediaKind(StrEnum):
    AUDIO = "audio"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"


class NotificationMedia(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: NotificationMediaKind
    url: str = Field(pattern=r"^https://", min_length=9, max_length=2048)


class NotificationTextForms(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    zero: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    one: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    two: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    few: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    many: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    other: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)

    @model_validator(mode="after")
    def validate_templates(self) -> Self:
        templates = (self.zero, self.one, self.two, self.few, self.many, self.other)
        if any(self._fields(template) != {"days_left"} for template in templates if template):
            raise ValueError(
                "notification text forms must contain only the {days_left} placeholder"
            )
        return self

    def render(self, days_left: int | str, plural_form: str) -> str:
        template = getattr(self, plural_form, None) or self.other
        return template.format(days_left=days_left)

    @staticmethod
    def _fields(template: str) -> set[str]:
        return {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name is not None
        }


class NotificationTextVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: NotificationTextForms
    style: NotificationTextStyle = NotificationTextStyle.PLAIN
    number_style: NotificationNumberStyle = NotificationNumberStyle.DIGITS


class NotificationMythicVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: NotificationTextForms | None = None
    style: NotificationTextStyle = NotificationTextStyle.PLAIN
    number_style: NotificationNumberStyle = NotificationNumberStyle.DIGITS
    media: NotificationMedia | None = None

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if self.text is None and self.media is None:
            raise ValueError("mythic notification variant must contain text or media")
        return self


class NotificationOmenForms(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    zero: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    one: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    two: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    few: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    many: str | None = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    other: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)

    @model_validator(mode="after")
    def validate_templates(self) -> Self:
        templates = (self.zero, self.one, self.two, self.few, self.many, self.other)
        if any(self._fields(template) != {"count"} for template in templates if template):
            raise ValueError("omen text forms must contain only the {count} placeholder")
        return self

    def render(self, count: int | str, plural_form: str) -> str:
        template = getattr(self, plural_form, None) or self.other
        return template.format(count=count)

    @staticmethod
    def _fields(template: str) -> set[str]:
        return {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name is not None
        }


class NotificationOmen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: NotificationOmenForms

    @model_validator(mode="after")
    def validate_known_counter(self) -> Self:
        if self.id not in OMEN_COUNTERS:
            raise ValueError(f"unknown omen {self.id!r}")
        return self


class NotificationContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default: NotificationTextForms
    natural: NotificationTextForms
    epic: tuple[NotificationTextVariant, ...] = Field(min_length=1)
    mythic: tuple[NotificationMythicVariant, ...] = Field(min_length=1)
    omens: tuple[NotificationOmen, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_omen_ids(self) -> Self:
        ids = tuple(omen.id for omen in self.omens)
        if len(ids) != len(set(ids)):
            raise ValueError("omen IDs must be unique")
        return self

    @model_validator(mode="after")
    def validate_epic_variants(self) -> Self:
        ids = tuple(variant.id for variant in self.epic + self.mythic)
        if len(ids) != len(set(ids)):
            raise ValueError("notification reward variant IDs must be unique")
        return self


class NotificationEmojiPool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probability: float = Field(gt=0, le=1)
    prelude: str = Field(min_length=1, max_length=64)
    rtl_walk_ids: tuple[CustomEmojiId, ...] = Field(min_length=1)
    ltr_walk_ids: tuple[CustomEmojiId, ...] = Field(min_length=1)
    rtl_arrow_ids: tuple[CustomEmojiId, ...] = Field(min_length=1)
    ltr_arrow_ids: tuple[CustomEmojiId, ...] = Field(min_length=1)
    dead_ids: tuple[CustomEmojiId, ...] = Field(min_length=1)
    rtl_walk_emoji: tuple[str, ...] = ()
    ltr_walk_emoji: tuple[str, ...] = ()
    rtl_arrow_emoji: tuple[str, ...] = ()
    ltr_arrow_emoji: tuple[str, ...] = ()
    dead_emoji: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_unique_emoji(self) -> Self:
        custom = (
            self.rtl_walk_ids
            + self.ltr_walk_ids
            + self.rtl_arrow_ids
            + self.ltr_arrow_ids
            + self.dead_ids
        )
        regular = (
            self.rtl_walk_emoji
            + self.ltr_walk_emoji
            + self.rtl_arrow_emoji
            + self.ltr_arrow_emoji
            + self.dead_emoji
        )
        if len(custom) != len(set(custom)) or len(regular) != len(set(regular)):
            raise ValueError("notification emoji must be unique within a tier")
        return self


class NotificationEpicPool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probability: float = Field(gt=0, le=1)
    prelude: str = Field(min_length=1, max_length=64)


class NotificationMythicPool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probability: float = Field(gt=0, le=1)
    prelude: str = Field(min_length=1, max_length=64)


class NotificationOmenPool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probability: float = Field(gt=0, le=1)
    prelude: str = Field(min_length=1, max_length=64)
    mini_witch_house_characters: int = Field(default=3, ge=1, le=64)


class NotificationRewards(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lucky: NotificationEmojiPool
    rare: NotificationEmojiPool
    omen: NotificationOmenPool
    epic: NotificationEpicPool
    mythic: NotificationMythicPool

    @model_validator(mode="after")
    def validate_probabilities(self) -> Self:
        if self.lucky.probability + self.rare.probability > 1:
            raise ValueError("notification emoji tier probabilities must not exceed one")
        if self.epic.probability + self.mythic.probability + self.omen.probability > 1:
            raise ValueError("notification message tier probabilities must not exceed one")
        return self


class QuestionContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)


class QuestionnaireContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    privacy_notice: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    started: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    completed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    deleted: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    cleanup_failed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    questions: tuple[QuestionContent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_question_ids(self) -> Self:
        ids = tuple(question.id for question in self.questions)
        if len(ids) != len(set(ids)):
            raise ValueError("questionnaire question IDs must be unique")
        return self


class NotificationSettingsContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    daily: str = Field(min_length=1, max_length=64)
    weekly: str = Field(min_length=1, max_length=64)
    monthly: str = Field(min_length=1, max_length=64)
    never: str = Field(min_length=1, max_length=64)
    custom: str = Field(min_length=1, max_length=64)
    custom_prompt: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_mock: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_invalid: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_too_frequent: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_failed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_interpretation: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_schedule: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_cron: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_description: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_timezone: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_next_notifications: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_disabled: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_description_unavailable: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_next_notifications_unavailable: str = Field(
        min_length=1,
        max_length=TELEGRAM_TEXT_LIMIT,
    )
    custom_unchanged: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    custom_change_hint: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    updated: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)

    @model_validator(mode="after")
    def validate_templates(self) -> Self:
        prompt_fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.prompt)
            if field_name is not None
        }
        updated_fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.updated)
            if field_name is not None
        }
        if prompt_fields != {"timezone"}:
            raise ValueError("notification settings prompt must contain {timezone}")
        if updated_fields != {"frequency"}:
            raise ValueError("notification settings updated must contain {frequency}")
        return self

    def prompt_text(self, timezone: str) -> str:
        return self.prompt.format(timezone=timezone)

    def updated_text(self, frequency: str) -> str:
        return self.updated.format(frequency=frequency)


class LocalizationContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    russian: str = Field(min_length=1, max_length=64)
    english: str = Field(min_length=1, max_length=64)
    updated: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)


class PredictionContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    failed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    mock: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)

    @model_validator(mode="after")
    def validate_mock_template(self) -> Self:
        fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.mock)
            if field_name is not None
        }
        if fields != {"answers"}:
            raise ValueError("prediction mock must contain only the {answers} placeholder")
        return self

    def mock_text(self, answers: str) -> str:
        return self.mock.format(answers=answers)


class LLMContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_exhausted: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)


class LocalizedBotContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    help: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    about: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    text_unsupported: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    payload_expired: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    group_unsupported: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    scream_denied: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    notification: NotificationContent
    localization: LocalizationContent
    notification_settings: NotificationSettingsContent
    llm: LLMContent
    prediction: PredictionContent
    questionnaire: QuestionnaireContent


class BotContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=128)
    default_locale: str = Field(min_length=2, max_length=16)
    unsupported_updates: UnsupportedUpdateContent
    notification_rewards: NotificationRewards
    locales: dict[str, LocalizedBotContent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_default_locale(self) -> Self:
        if self.default_locale not in self.locales:
            raise ValueError("default_locale must exist in locales")
        return self

    def default(self) -> LocalizedBotContent:
        return self.locales[self.default_locale]

    def localized(self, locale: str | None) -> LocalizedBotContent:
        if locale is None:
            return self.default()
        return self.locales.get(locale, self.default())


class YamlBotContentLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> BotContent:
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            return BotContent.model_validate(payload)
        except (OSError, YAMLError, ValidationError) as error:
            raise ContentConfigurationError(
                f"Failed to load bot content from {self._path}"
            ) from error
