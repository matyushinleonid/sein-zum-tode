from enum import StrEnum

CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME = "configure_mortal_localization"


class SupportedLocale(StrEnum):
    RUSSIAN = "ru"
    ENGLISH = "en"

    def callback_data(self) -> str:
        return f"localization:{self.value}"

    @classmethod
    def from_callback_data(cls, value: str | None) -> SupportedLocale | None:
        if value is None or not value.startswith("localization:"):
            return None
        try:
            return cls(value.removeprefix("localization:"))
        except ValueError:
            return None
