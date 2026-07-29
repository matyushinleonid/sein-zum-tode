import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aiogram.types import Update

from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.ingress.models import StoredUpdate


class SilentLogger:
    def debug(self, *args: object, **kwargs: object) -> None:
        pass

    def info(self, *args: object, **kwargs: object) -> None:
        pass

    def warning(self, *args: object, **kwargs: object) -> None:
        pass

    def exception(self, *args: object, **kwargs: object) -> None:
        pass


class TelegramUpdates:
    @staticmethod
    def message(
        update_id: int,
        user_id: int,
        chat_id: int,
        text: str | None,
        chat_type: str,
    ) -> Update:
        message: dict[str, object] = {
            "message_id": update_id + 701,
            "date": 1_754_321_987,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Hypatia",
            },
        }
        if text is None:
            message["sticker"] = {
                "file_id": "AgACAgIAAxkBAAIBSphinx",
                "file_unique_id": "AQADSphinxQuartz",
                "type": "regular",
                "width": 317,
                "height": 509,
                "is_animated": False,
                "is_video": False,
            }
        else:
            message["text"] = text
        return Update.model_validate({"update_id": update_id, "message": message})

    @staticmethod
    def edited(update_id: int, user_id: int, chat_id: int, text: str) -> Update:
        return Update.model_validate(
            {
                "update_id": update_id,
                "edited_message": {
                    "message_id": update_id + 809,
                    "date": 1_754_321_987,
                    "edit_date": 1_754_322_123,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {
                        "id": user_id,
                        "is_bot": False,
                        "first_name": "Hypatia",
                    },
                    "text": text,
                },
            }
        )

    @staticmethod
    def callback(update_id: int, user_id: int, chat_id: int) -> Update:
        return Update.model_validate(
            {
                "update_id": update_id,
                "callback_query": {
                    "id": "callback-Sphinx-915",
                    "from": {
                        "id": user_id,
                        "is_bot": False,
                        "first_name": "Hypatia",
                    },
                    "chat_instance": "instance-quartz-823",
                    "message": {
                        "message_id": update_id + 907,
                        "date": 1_754_321_987,
                        "chat": {
                            "id": chat_id,
                            "type": "group",
                            "title": "Quartz Observatory",
                        },
                    },
                },
            }
        )

    @staticmethod
    def poll_answer(update_id: int, user_id: int) -> Update:
        return Update.model_validate(
            {
                "update_id": update_id,
                "poll_answer": {
                    "poll_id": "poll-galaxy-619",
                    "option_ids": [3],
                    "option_persistent_ids": [],
                    "user": {
                        "id": user_id,
                        "is_bot": False,
                        "first_name": "Hypatia",
                    },
                },
            }
        )

    @staticmethod
    def anonymous_poll(update_id: int) -> Update:
        return Update.model_validate(
            {
                "update_id": update_id,
                "poll": {
                    "id": "poll-anonymous-811",
                    "question": "Which nebula is brightest?",
                    "options": [],
                    "total_voter_count": 0,
                    "is_closed": False,
                    "is_anonymous": True,
                    "type": "regular",
                    "allows_multiple_answers": False,
                    "allows_revoting": False,
                    "members_only": False,
                },
            }
        )


def result_or_raise(result: Any) -> Any:
    if isinstance(result, BaseException):
        raise result
    return result


class RedisDouble:
    def __init__(
        self,
        get_result: object,
        set_result: object,
        delete_result: object,
    ) -> None:
        self.get_result = get_result
        self.set_result = set_result
        self.delete_result = delete_result
        self.events: list[tuple[object, ...]] = []

    async def get(self, key: str) -> object:
        self.events.append(("get", key))
        return result_or_raise(self.get_result)

    async def set(self, key: str, value: str, *, ex: int) -> object:
        self.events.append(("set", key, value, ex))
        return result_or_raise(self.set_result)

    async def delete(self, *keys: str) -> object:
        self.events.append(("delete", *keys))
        return result_or_raise(self.delete_result)


class TelegramBotDouble:
    def __init__(
        self,
        updates: Sequence[Update],
        delete_result: object,
        receive_result: object,
        send_result: object,
    ) -> None:
        self.updates = updates
        self.delete_result = delete_result
        self.receive_result = receive_result
        self.send_result = send_result
        self.events: list[tuple[str, object]] = []

    async def delete_webhook(self, *, drop_pending_updates: bool) -> None:
        self.events.append(("delete_webhook", drop_pending_updates))
        result_or_raise(self.delete_result)

    async def get_updates(self, **arguments: object) -> Sequence[Update]:
        self.events.append(("get_updates", arguments))
        result = result_or_raise(self.receive_result)
        return self.updates if result is None else result

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.events.append(("send_message", (chat_id, text)))
        result_or_raise(self.send_result)


class TelegramMemory:
    def __init__(
        self,
        update_result: object,
        response_result: object,
        store_result: object,
        send_result: object,
        delete_result: object,
    ) -> None:
        self.update_result = update_result
        self.response_result = response_result
        self.store_result = store_result
        self.send_result = send_result
        self.delete_result = delete_result
        self.events: list[tuple[object, ...]] = []
        self.responses: dict[str, TelegramResponse] = {}
        self.sent = asyncio.Event()

    async def load_update(self, key: str) -> Update | None:
        self.events.append(("load_update", key))
        return result_or_raise(self.update_result)

    async def store_response(
        self,
        key: str,
        response: TelegramResponse,
        ttl_seconds: int,
    ) -> None:
        self.events.append(("store_response", key, response, ttl_seconds))
        result_or_raise(self.store_result)
        self.responses[key] = response

    async def load_response(self, key: str) -> TelegramResponse | None:
        self.events.append(("load_response", key))
        result = result_or_raise(self.response_result)
        if result is None:
            return self.responses.get(key)
        return result

    async def delete(self, keys: tuple[str, ...]) -> None:
        self.events.append(("delete", keys))
        result_or_raise(self.delete_result)
        for key in keys:
            self.responses.pop(key, None)

    async def send_text(self, chat_id: int, text: str) -> None:
        self.events.append(("send_text", chat_id, text))
        result_or_raise(self.send_result)
        self.sent.set()


class UserResolverDouble:
    def __init__(self, user_id: int | None) -> None:
        self.user_id = user_id
        self.events: list[int] = []

    def resolve(self, update: Update) -> int | None:
        self.events.append(update.update_id)
        return self.user_id


class KeyValueDouble:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.events: list[tuple[str, str, int]] = []

    async def set(self, name: str, value: str, *, ex: int) -> object:
        self.events.append((name, value, ex))
        return result_or_raise(self.outcomes.pop(0))


class SourceDouble:
    def __init__(
        self,
        prepare_outcomes: list[object],
        receive_outcomes: list[object],
        stop_event: asyncio.Event,
    ) -> None:
        self.prepare_outcomes = prepare_outcomes
        self.receive_outcomes = receive_outcomes
        self.stop_event = stop_event
        self.events: list[tuple[str, object]] = []

    async def prepare(self) -> None:
        self.events.append(("prepare", len(self.prepare_outcomes)))
        result_or_raise(self.prepare_outcomes.pop(0))

    async def receive(self, offset: int | None) -> Sequence[Update]:
        self.events.append(("receive", offset))
        outcome = result_or_raise(self.receive_outcomes.pop(0))
        if not self.receive_outcomes:
            self.stop_event.set()
        return outcome


class StoreDouble:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.events: list[int] = []

    async def store(self, update: Update) -> StoredUpdate:
        self.events.append(update.update_id)
        return result_or_raise(self.outcomes.pop(0))


class HandoffDouble:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.events: list[StoredUpdate] = []

    async def handoff(self, update: StoredUpdate) -> None:
        self.events.append(update)
        result_or_raise(self.outcomes.pop(0))


class RetryWaiterDouble:
    def __init__(self, stop: bool) -> None:
        self.stop = stop
        self.events: list[int] = []

    async def wait(self, failure_count: int, stop_event: asyncio.Event) -> None:
        self.events.append(failure_count)
        if self.stop:
            stop_event.set()


class WorkflowStarterDouble:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.events: list[tuple[int, str]] = []

    async def signal_with_start(self, *, user_id: int, update_key: str) -> None:
        self.events.append((user_id, update_key))
        result_or_raise(self.outcome)


class TemporalClientDouble:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.events: list[tuple[object, ...]] = []

    async def start_workflow(self, *arguments: object, **options: object) -> object:
        self.events.append((*arguments, options))
        return result_or_raise(self.outcome)


@dataclass(frozen=True, slots=True)
class ActivityCase:
    update: Update
    expected_kind: object
    expected_chat_id: int
