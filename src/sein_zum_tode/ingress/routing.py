from aiogram.types import Update, User

from sein_zum_tode.ingress.ports import UpdateUserResolver


class AiogramUpdateUserResolver(UpdateUserResolver):
    def resolve(self, update: Update) -> int | None:
        try:
            event = update.event
        except LookupError:
            return None
        user = getattr(event, "from_user", None)
        if not isinstance(user, User):
            user = getattr(event, "user", None)
        return user.id if isinstance(user, User) else None
