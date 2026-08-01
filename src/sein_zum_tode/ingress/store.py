from aiogram.types import Update

from sein_zum_tode.infrastructure.redis_documents import DocumentStoreError
from sein_zum_tode.ingress.errors import UpdateStoreError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import UpdateUserResolver
from sein_zum_tode.payload_keys import UpdatePayloadKeys
from sein_zum_tode.ports.documents import DocumentWriter


class TelegramUpdateStore:
    def __init__(
        self,
        updates: DocumentWriter[Update],
        user_resolver: UpdateUserResolver,
        bot_id: int,
        ttl_seconds: int,
        key_prefix: str = "telegram:updates",
    ) -> None:
        self._updates = updates
        self._user_resolver = user_resolver
        self._bot_id = bot_id
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix

    async def store(self, update: Update) -> StoredUpdate:
        key = UpdatePayloadKeys.received(
            bot_id=self._bot_id,
            update_id=update.update_id,
            prefix=self._key_prefix,
        ).update
        try:
            await self._updates.store(key, update, self._ttl_seconds)
        except DocumentStoreError as error:
            raise UpdateStoreError(f"Failed to store Telegram update {update.update_id}") from error
        return StoredUpdate(
            update_id=update.update_id,
            key=key,
            ttl_seconds=self._ttl_seconds,
            user_id=self._user_resolver.resolve(update),
        )
