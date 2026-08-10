from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from html import escape
from typing import Protocol

from babel import Locale

from sein_zum_tode.bot.content import (
    BotContent,
    NotificationContent,
    NotificationEmojiPool,
    NotificationMedia,
    NotificationNumberStyle,
    NotificationTextForms,
    NotificationTextStyle,
    NotificationTier,
)
from sein_zum_tode.bot.models import TelegramAttachment, TelegramAttachmentKind
from sein_zum_tode.notifications.models import RenderedNotification
from sein_zum_tode.notifications.omens import OMEN_COUNTERS
from sein_zum_tode.notifications.ports import NumberSpeller

WITCH_HOUSE_CHARACTERS: dict[str, str | int | None] = {
    "A": "Λ",
    "D": "Δ",
    "E": "Ξ",
    "O": "Ω",
    "S": "ϟ",
    "T": "Ŧ",
    "А": "Λ",
    "Д": "Δ",
    "Е": "Ξ",
    "О": "Ω",
    "С": "Ͼ",
    "Т": "Ŧ",
}


class NotificationRandomizer(Protocol):
    def value(self, seed: str, decision: str) -> float: ...

    def index(self, seed: str, decision: str, size: int) -> int: ...


class StableNotificationRandomizer:
    def value(self, seed: str, decision: str) -> float:
        return self._number(seed, decision) / (1 << 64)

    def index(self, seed: str, decision: str, size: int) -> int:
        return self._number(seed, decision) % size

    @staticmethod
    def _number(seed: str, decision: str) -> int:
        digest = sha256(f"{seed}\0{decision}".encode()).digest()
        return int.from_bytes(digest[:8])


@dataclass(frozen=True, slots=True)
class _TextSelection:
    forms: NotificationTextForms
    style: NotificationTextStyle
    number_style: NotificationNumberStyle
    variant_id: str
    media: NotificationMedia | None = None


class NotificationMessagePresenter:
    def __init__(
        self,
        *,
        content: BotContent,
        number_speller: NumberSpeller,
        randomizer: NotificationRandomizer | None = None,
    ) -> None:
        self._content = content
        self._number_speller = number_speller
        self._randomizer = randomizer or StableNotificationRandomizer()

    def render(
        self,
        *,
        locale: str | None,
        days_left: int,
        seed: str,
        today: date | None = None,
        death_date: date | None = None,
        sample: NotificationTier | None = None,
    ) -> RenderedNotification:
        locale_name = locale if locale in self._content.locales else self._content.default_locale
        notification = self._content.localized(locale_name).notification
        tier = sample or self._tier(seed)
        selected = self._text(notification, tier, seed)
        displayed_days: int | str = days_left
        if selected.number_style == NotificationNumberStyle.WORDS:
            displayed_days = self._number_speller.spell(days_left, locale_name)
        text = selected.forms.render(
            displayed_days,
            str(Locale.parse(locale_name).plural_form(days_left)),
        )
        if selected.style == NotificationTextStyle.WITCH_HOUSE:
            text = self._witch_house(text)
        if tier == NotificationTier.OMEN:
            text = self._omen(
                text,
                notification=notification,
                locale_name=locale_name,
                seed=seed,
                today=today,
                death_date=death_date,
            )
        emoji_tier = self._emoji_tier(tier)
        if emoji_tier is None:
            rich_text = text
            fallback_text = None
            parse_mode = None
        else:
            rich_prefix, fallback_prefix = self._decoration(seed, emoji_tier)
            rich_text = f"{rich_prefix}\n{escape(text)}"
            fallback_text = f"{fallback_prefix}\n{text}"
            parse_mode = "HTML"
        return RenderedNotification(
            text=rich_text,
            parse_mode=parse_mode,
            fallback_text=fallback_text,
            prelude_text=self._prelude(tier),
            attachment=self._attachment(selected.media),
            variant_id=selected.variant_id,
            tier=tier,
        )

    def _tier(self, seed: str) -> NotificationTier | None:
        rewards = self._content.notification_rewards
        message = self._randomizer.value(seed, "message_tier")
        if message < rewards.mythic.probability:
            return NotificationTier.MYTHIC
        if message < rewards.mythic.probability + rewards.epic.probability:
            return NotificationTier.EPIC
        if (
            message
            < rewards.mythic.probability + rewards.epic.probability + rewards.omen.probability
        ):
            return NotificationTier.OMEN
        emoji = self._randomizer.value(seed, "emoji_tier")
        if emoji < rewards.rare.probability:
            return NotificationTier.RARE
        if emoji < rewards.rare.probability + rewards.lucky.probability:
            return NotificationTier.LUCKY
        return None

    def _text(
        self,
        notification: NotificationContent,
        tier: NotificationTier | None,
        seed: str,
    ) -> _TextSelection:
        if tier == NotificationTier.EPIC:
            epic = notification.epic[
                self._randomizer.index(seed, "epic_variant", len(notification.epic))
            ]
            return _TextSelection(
                forms=epic.text,
                style=epic.style,
                number_style=epic.number_style,
                variant_id=epic.id,
            )
        if tier == NotificationTier.MYTHIC:
            mythic = notification.mythic[
                self._randomizer.index(seed, "mythic_variant", len(notification.mythic))
            ]
            if mythic.text is None:
                base = self._base_text(notification, seed)
                return _TextSelection(
                    forms=base.forms,
                    style=base.style,
                    number_style=base.number_style,
                    variant_id=mythic.id,
                    media=mythic.media,
                )
            return _TextSelection(
                forms=mythic.text,
                style=mythic.style,
                number_style=mythic.number_style,
                variant_id=mythic.id,
                media=mythic.media,
            )
        return self._base_text(notification, seed)

    def _base_text(self, notification: NotificationContent, seed: str) -> _TextSelection:
        if self._randomizer.index(seed, "base_text", 2) == 0:
            return _TextSelection(
                forms=notification.default,
                style=NotificationTextStyle.PLAIN,
                number_style=NotificationNumberStyle.DIGITS,
                variant_id="default",
            )
        return _TextSelection(
            forms=notification.natural,
            style=NotificationTextStyle.PLAIN,
            number_style=NotificationNumberStyle.DIGITS,
            variant_id="natural",
        )

    def _emoji_tier(self, tier: NotificationTier | None) -> NotificationTier | None:
        if tier in {NotificationTier.EPIC, NotificationTier.MYTHIC, NotificationTier.OMEN}:
            return None
        return tier

    def _decoration(self, seed: str, tier: NotificationTier) -> tuple[str, str]:
        pool = self._emoji_pool(tier)
        prefix = tier.value
        if self._randomizer.value(seed, f"{prefix}_direction") < 0.5:
            entries = (
                self._emoji(
                    seed,
                    f"{prefix}_ltr_walk",
                    pool.ltr_walk_ids,
                    pool.ltr_walk_emoji,
                    "🚶",
                ),
                self._emoji(
                    seed,
                    f"{prefix}_ltr_arrow",
                    pool.ltr_arrow_ids,
                    pool.ltr_arrow_emoji,
                    "➡️",
                ),
                self._emoji(
                    seed,
                    f"{prefix}_ltr_dead",
                    pool.dead_ids,
                    pool.dead_emoji,
                    "💀",
                ),
            )
        else:
            entries = (
                self._emoji(
                    seed,
                    f"{prefix}_rtl_dead",
                    pool.dead_ids,
                    pool.dead_emoji,
                    "💀",
                ),
                self._emoji(
                    seed,
                    f"{prefix}_rtl_arrow",
                    pool.rtl_arrow_ids,
                    pool.rtl_arrow_emoji,
                    "⬅️",
                ),
                self._emoji(
                    seed,
                    f"{prefix}_rtl_walk",
                    pool.rtl_walk_ids,
                    pool.rtl_walk_emoji,
                    "🚶",
                ),
            )
        return "".join(entry[0] for entry in entries), "".join(entry[1] for entry in entries)

    def _emoji(
        self,
        seed: str,
        decision: str,
        custom_ids: tuple[str, ...],
        regular: tuple[str, ...],
        fallback: str,
    ) -> tuple[str, str]:
        selected = self._randomizer.index(seed, decision, len(custom_ids) + len(regular))
        if selected < len(custom_ids):
            return (
                f'<tg-emoji emoji-id="{custom_ids[selected]}">{fallback}</tg-emoji>',
                fallback,
            )
        emoji = regular[selected - len(custom_ids)]
        return escape(emoji), emoji

    def _emoji_pool(self, tier: NotificationTier) -> NotificationEmojiPool:
        rewards = self._content.notification_rewards
        return rewards.rare if tier == NotificationTier.RARE else rewards.lucky

    def _prelude(self, tier: NotificationTier | None) -> str | None:
        rewards = self._content.notification_rewards
        if tier == NotificationTier.LUCKY:
            return rewards.lucky.prelude
        if tier == NotificationTier.RARE:
            return rewards.rare.prelude
        if tier == NotificationTier.EPIC:
            return rewards.epic.prelude
        if tier == NotificationTier.MYTHIC:
            return rewards.mythic.prelude
        if tier == NotificationTier.OMEN:
            return rewards.omen.prelude
        return None

    @staticmethod
    def _attachment(media: NotificationMedia | None) -> TelegramAttachment | None:
        if media is None:
            return None
        return TelegramAttachment(
            kind=TelegramAttachmentKind(media.kind.value),
            url=media.url,
        )

    def _omen(
        self,
        text: str,
        *,
        notification: NotificationContent,
        locale_name: str,
        seed: str,
        today: date | None,
        death_date: date | None,
    ) -> str:
        if self._randomizer.index(seed, "omen_kind", 2) == 0:
            return self._mini_witch_house(text, seed)
        if today is None or death_date is None:
            return text
        omen = notification.omens[
            self._randomizer.index(seed, "omen_variant", len(notification.omens))
        ]
        count = OMEN_COUNTERS[omen.id](today, death_date)
        line = omen.text.render(count, str(Locale.parse(locale_name).plural_form(count)))
        appended = f"{text}\n{line}"
        if self._randomizer.index(seed, "omen_mini_witch", 2) == 0:
            return self._mini_witch_house(appended, seed)
        return appended

    def _mini_witch_house(self, value: str, seed: str) -> str:
        positions = [
            index
            for index, character in enumerate(value)
            if character.upper() in WITCH_HOUSE_CHARACTERS
        ]
        wanted = self._content.notification_rewards.omen.mini_witch_house_characters
        characters = list(value)
        for step in range(min(wanted, len(positions))):
            chosen = positions.pop(
                self._randomizer.index(seed, f"mini_witch_{step}", len(positions))
            )
            characters[chosen] = str(WITCH_HOUSE_CHARACTERS[characters[chosen].upper()])
        return "".join(characters)

    @staticmethod
    def _witch_house(value: str) -> str:
        return value.upper().translate(str.maketrans(WITCH_HOUSE_CHARACTERS))
