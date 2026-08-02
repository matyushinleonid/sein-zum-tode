from hashlib import sha256
from html import escape
from typing import Protocol

from babel import Locale

from sein_zum_tode.bot.content import (
    BotContent,
    NotificationNumberStyle,
    NotificationTextStyle,
    NotificationTextVariant,
)
from sein_zum_tode.notifications.models import RenderedNotification
from sein_zum_tode.notifications.ports import NumberSpeller

WITCH_HOUSE_CHARACTERS: dict[str, str | int | None] = {
    "A": "Λ",
    "a": "λ",
    "D": "Δ",
    "d": "δ",
    "E": "Ξ",
    "e": "ξ",
    "O": "Ω",
    "o": "ω",
    "S": "ϟ",
    "s": "ϟ",
    "T": "Ŧ",
    "t": "ŧ",
    "А": "Λ",
    "а": "λ",
    "Д": "Δ",
    "д": "δ",
    "Е": "Ξ",
    "е": "ξ",
    "О": "Ω",
    "о": "ω",
    "С": "Ͼ",
    "с": "ϲ",
    "Т": "Ŧ",
    "т": "ŧ",
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
    ) -> RenderedNotification:
        locale_name = locale if locale in self._content.locales else self._content.default_locale
        notification = self._content.localized(locale).notification
        variant = self._variant(notification.variants, seed)
        displayed_days: int | str = days_left
        if variant is not None and variant.number_style == NotificationNumberStyle.WORDS:
            displayed_days = self._number_speller.spell(days_left, locale_name)
        text = (variant.text if variant is not None else notification.default).render(
            displayed_days,
            str(Locale.parse(locale_name).plural_form(days_left)),
        )
        if variant is not None and variant.style == NotificationTextStyle.WITCH_HOUSE:
            text = self._witch_house(text)
        if not self._selected(
            seed,
            "decoration",
            self._content.notification_decoration.probability,
        ):
            return RenderedNotification(
                text=text,
                parse_mode=None,
                fallback_text=None,
                variant_id=variant.id if variant is not None else None,
                decorated=False,
            )
        rich_prefix, fallback_prefix = self._decoration(seed)
        return RenderedNotification(
            text=f"{rich_prefix}\n{escape(text)}",
            parse_mode="HTML",
            fallback_text=f"{fallback_prefix}\n{text}",
            variant_id=variant.id if variant is not None else None,
            decorated=True,
        )

    def _variant(
        self,
        variants: tuple[NotificationTextVariant, ...],
        seed: str,
    ) -> NotificationTextVariant | None:
        value = self._randomizer.value(seed, "text_variant")
        boundary = 0.0
        for variant in variants:
            boundary += variant.probability
            if value < boundary:
                return variant
        return None

    def _decoration(self, seed: str) -> tuple[str, str]:
        decoration = self._content.notification_decoration
        if self._randomizer.value(seed, "direction") < 0.5:
            entries = (
                (
                    decoration.ltr_walk_ids[
                        self._randomizer.index(seed, "ltr_walk", len(decoration.ltr_walk_ids))
                    ],
                    "🚶",
                ),
                (
                    decoration.ltr_arrow_ids[
                        self._randomizer.index(seed, "ltr_arrow", len(decoration.ltr_arrow_ids))
                    ],
                    "➡️",
                ),
                (
                    decoration.dead_ids[
                        self._randomizer.index(seed, "ltr_dead", len(decoration.dead_ids))
                    ],
                    "💀",
                ),
            )
        else:
            entries = (
                (
                    decoration.dead_ids[
                        self._randomizer.index(seed, "rtl_dead", len(decoration.dead_ids))
                    ],
                    "💀",
                ),
                (
                    decoration.rtl_arrow_ids[
                        self._randomizer.index(seed, "rtl_arrow", len(decoration.rtl_arrow_ids))
                    ],
                    "⬅️",
                ),
                (
                    decoration.rtl_walk_ids[
                        self._randomizer.index(seed, "rtl_walk", len(decoration.rtl_walk_ids))
                    ],
                    "🚶",
                ),
            )
        rich = "".join(
            f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
            for emoji_id, fallback in entries
        )
        return rich, "".join(fallback for _, fallback in entries)

    def _selected(self, seed: str, decision: str, probability: float) -> bool:
        return self._randomizer.value(seed, decision) < probability

    @staticmethod
    def _witch_house(value: str) -> str:
        return value.translate(str.maketrans(WITCH_HOUSE_CHARACTERS))
