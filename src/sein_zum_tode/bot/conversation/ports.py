from typing import Protocol

from sein_zum_tode.bot.conversation.models import ConversationState


class ConversationStateRepository(Protocol):
    async def load_conversation(self, key: str) -> ConversationState | None: ...

    async def store_conversation(
        self,
        key: str,
        state: ConversationState,
        ttl_seconds: int,
    ) -> None: ...
