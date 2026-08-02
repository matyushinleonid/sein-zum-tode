from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

PREPARE_UNSUPPORTED_ACTIVITY_NAME = "prepare_unsupported_response"
VISUALLY_EMPTY_TELEGRAM_MESSAGE = "\u00a0"


class UnsupportedUpdateContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_silence_count: int = Field(ge=0)
    stanzas: tuple[tuple[str, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stanzas(self) -> UnsupportedUpdateContent:
        if any(not stanza for stanza in self.stanzas):
            raise ValueError("unsupported update poem stanzas must not be empty")
        if any(not line for stanza in self.stanzas for line in stanza):
            raise ValueError("unsupported update poem lines must not be empty")
        return self

    def messages(self) -> tuple[str, ...]:
        return tuple(
            message
            for stanza in self.stanzas
            for message in (*stanza, VISUALLY_EMPTY_TELEGRAM_MESSAGE)
        )


@dataclass(frozen=True, slots=True)
class UnsupportedResponsePreparation:
    response_prepared: bool


class UnsupportedUpdateSession(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ignored_updates: int = Field(default=0, ge=0)
    next_message_index: int = Field(default=0, ge=0)
    last_update_key: str | None = None
    last_response_text: str | None = None

    def advance(
        self,
        *,
        update_key: str,
        content: UnsupportedUpdateContent,
    ) -> tuple[UnsupportedUpdateSession, str | None]:
        if update_key == self.last_update_key:
            return self, self.last_response_text
        if self.ignored_updates < content.initial_silence_count:
            return (
                self.model_copy(
                    update={
                        "ignored_updates": self.ignored_updates + 1,
                        "last_update_key": update_key,
                        "last_response_text": None,
                    }
                ),
                None,
            )
        messages = content.messages()
        text = messages[self.next_message_index % len(messages)]
        return (
            self.model_copy(
                update={
                    "next_message_index": (self.next_message_index + 1) % len(messages),
                    "last_update_key": update_key,
                    "last_response_text": text,
                }
            ),
            text,
        )
