import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol, cast

from aiogram.types import InlineKeyboardMarkup, Update
from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.bot.content import (
    BotContent,
    LLMContent,
    LocalizationContent,
    LocalizedBotContent,
    NotificationSettingsContent,
    PredictionContent,
    QuestionContent,
    QuestionnaireContent,
)
from sein_zum_tode.bot.models import (
    InspectionKind,
    TelegramResponse,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.infrastructure.redis import RedisClient
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.prediction.models import StoredDeathPrediction
from sein_zum_tode.questionnaire.models import QuestionnaireState

TEST_TIMEOUT_SECONDS = 30


def mortal(
    *,
    id: int,
    locale: str | None = None,
    timezone: str = "Europe/Moscow",
    notification_cron: str | None = "0 9 * * *",
    death_date: date | None = None,
    telegram_unreachable_at: datetime | None = None,
    llm_requests_remaining: int = 50,
) -> Mortal:
    return Mortal(
        id=id,
        locale=locale,
        timezone=timezone,
        notification_cron=notification_cron,
        death_date=death_date,
        telegram_unreachable_at=telegram_unreachable_at,
        llm_requests_remaining=llm_requests_remaining,
    )


class SilentLogger(logging.Logger):
    def __init__(self) -> None:
        super().__init__("silent-test-logger")
        self.disabled = True


class BotContents:
    @staticmethod
    def debug(
        *,
        first_question: str = "q1?",
        second_question: str = "q2?",
    ) -> BotContent:
        return BotContent(
            version="debug-cosmos-v1",
            default_locale="en",
            locales={
                "en": LocalizedBotContent(
                    help="Navigate by the constellations",
                    about=(
                        'About: <a href="https://github.com/matyushinleonid/'
                        'sein-zum-tode">github</a>'
                    ),
                    unsupported="Use /help to learn how to use the bot",
                    group_unsupported="Group chats are not supported.",
                    scream_denied="You can't scream 🤷‍♂️",
                    notification="mock notification: {days_left}",
                    localization=LocalizationContent(
                        prompt="Choose your language / Выберите язык",
                        russian="🇷🇺 RU",
                        english="🇺🇸 EN",
                        updated="Language changed to English.",
                    ),
                    notification_settings=NotificationSettingsContent(
                        prompt="Choose a notification frequency ({timezone})",
                        daily="Daily",
                        weekly="Weekly",
                        monthly="Monthly",
                        never="Never",
                        custom="✨ Custom schedule",
                        custom_prompt="Describe a custom notification schedule",
                        custom_mock="Custom notification schedule updated",
                        custom_invalid="Custom notification schedule is invalid",
                        custom_too_frequent="Notifications cannot be sent more than daily",
                        custom_failed="Custom notification schedule failed",
                        updated="Notifications: {frequency}",
                    ),
                    llm=LLMContent(limit_exhausted="LLM request limit exhausted"),
                    prediction=PredictionContent(
                        failed="Prediction failed",
                        mock="Mock prediction: {answers}",
                    ),
                    questionnaire=QuestionnaireContent(
                        started="mock questionnaire started",
                        completed="thanks for your answers!",
                        deleted="your answers were deleted from our system",
                        questions=(
                            QuestionContent(id="q1", text=first_question),
                            QuestionContent(id="q2", text=second_question),
                        ),
                    ),
                ),
                "ru": LocalizedBotContent(
                    help="Путь укажут созвездия",
                    about=(
                        'О боте: <a href="https://github.com/matyushinleonid/'
                        'sein-zum-tode">github</a>'
                    ),
                    unsupported="Нажмите /help, чтобы узнать, как пользоваться ботом",
                    group_unsupported="Групповые чаты не поддерживаются.",
                    scream_denied="Ты не можешь кричать 🤷‍♂️",
                    notification="Осталось дней: {days_left}",
                    localization=LocalizationContent(
                        prompt="Выберите язык.",
                        russian="🇷🇺 RU",
                        english="🇺🇸 EN",
                        updated="Язык изменён на русский.",
                    ),
                    notification_settings=NotificationSettingsContent(
                        prompt="Выберите частоту уведомлений ({timezone})",
                        daily="Ежедневно",
                        weekly="Еженедельно",
                        monthly="Ежемесячно",
                        never="Никогда",
                        custom="✨ Своё расписание",
                        custom_prompt="Опишите своё расписание уведомлений",
                        custom_mock="Расписание уведомлений обновлено",
                        custom_invalid="Расписание уведомлений некорректно",
                        custom_too_frequent="Уведомления нельзя присылать чаще раза в день",
                        custom_failed="Не удалось настроить расписание уведомлений",
                        updated="Уведомления: {frequency}",
                    ),
                    llm=LLMContent(limit_exhausted="Лимит LLM-запросов исчерпан"),
                    prediction=PredictionContent(
                        failed="Ошибка предсказания",
                        mock="Тестовое предсказание: {answers}",
                    ),
                    questionnaire=QuestionnaireContent(
                        started="Тестовая анкета начата",
                        completed="Спасибо за ваши ответы!",
                        deleted="Ваши ответы удалены из нашей системы",
                        questions=(
                            QuestionContent(id="q1", text="Первый вопрос?"),
                            QuestionContent(id="q2", text="Второй вопрос?"),
                        ),
                    ),
                ),
            },
        )


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
    def reply_command(
        *,
        update_id: int,
        user_id: int,
        text: str,
        replied_content: dict[str, object] | None,
        media_group_id: str | None = None,
    ) -> Update:
        chat = {"id": user_id, "type": "private", "first_name": "Hypatia"}
        message: dict[str, object] = {
            "message_id": update_id + 701,
            "date": 1_754_321_987,
            "chat": chat,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Hypatia",
            },
            "text": text,
        }
        if replied_content is not None:
            replied: dict[str, object] = {
                "message_id": update_id + 509,
                "date": 1_754_321_901,
                "chat": chat,
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Hypatia",
                },
                **replied_content,
            }
            if media_group_id is not None:
                replied["media_group_id"] = media_group_id
            message["reply_to_message"] = replied
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
    def callback(
        update_id: int,
        user_id: int,
        chat_id: int,
        *,
        chat_type: str = "group",
        data: str | None = None,
    ) -> Update:
        chat: dict[str, object] = {
            "id": chat_id,
            "type": chat_type,
        }
        if chat_type == "private":
            chat["first_name"] = "Hypatia"
        else:
            chat["title"] = "Quartz Observatory"
        callback: dict[str, object] = {
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
                "chat": chat,
            },
        }
        if data is not None:
            callback["data"] = data
        return Update.model_validate(
            {
                "update_id": update_id,
                "callback_query": callback,
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

    @staticmethod
    def membership(
        *,
        update_id: int,
        user_id: int,
        bot_id: int,
        old_status: str,
        new_status: str,
        chat_type: str = "private",
    ) -> Update:
        chat: dict[str, object] = {
            "id": user_id,
            "type": chat_type,
        }
        if chat_type == "private":
            chat["first_name"] = "Hypatia"
        else:
            chat["title"] = "Quartz Observatory"
        bot = {
            "id": bot_id,
            "is_bot": True,
            "first_name": "Memento",
        }
        old_chat_member: dict[str, object] = {
            "status": old_status,
            "user": bot,
        }
        new_chat_member: dict[str, object] = {
            "status": new_status,
            "user": bot,
        }
        if old_status == "kicked":
            old_chat_member["until_date"] = 0
        if new_status == "kicked":
            new_chat_member["until_date"] = 0
        if new_status == "creator":
            new_chat_member["is_anonymous"] = False
        return Update.model_validate(
            {
                "update_id": update_id,
                "my_chat_member": {
                    "chat": chat,
                    "from": {
                        "id": user_id,
                        "is_bot": False,
                        "first_name": "Hypatia",
                    },
                    "date": 1_754_321_987,
                    "old_chat_member": old_chat_member,
                    "new_chat_member": new_chat_member,
                },
            }
        )


def result_or_raise[T](result: T | BaseException) -> T:
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

    def client(self) -> RedisClient:
        return RedisClient(self)

    async def get(self, name: str) -> str | bytes | None:
        self.events.append(("get", name))
        return cast(str | bytes | None, result_or_raise(self.get_result))

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
    ) -> bool | str | bytes | None:
        self.events.append(("set", name, value, ex))
        return cast(bool | str | bytes | None, result_or_raise(self.set_result))

    async def delete(self, *names: str) -> int:
        self.events.append(("delete", *names))
        return cast(int, result_or_raise(self.delete_result))


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

    async def delete_webhook(
        self,
        drop_pending_updates: bool | None = None,
        request_timeout: int | None = None,
    ) -> object:
        self.events.append(("delete_webhook", drop_pending_updates))
        return result_or_raise(self.delete_result)

    async def get_updates(
        self,
        offset: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
        request_timeout: int | None = None,
    ) -> Sequence[Update]:
        arguments: dict[str, object] = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": allowed_updates,
            "request_timeout": request_timeout,
        }
        if limit is not None:
            arguments["limit"] = limit
        self.events.append(("get_updates", arguments))
        result = result_or_raise(self.receive_result)
        return self.updates if result is None else cast(Sequence[Update], result)

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object:
        self.events.append(("send_message", (chat_id, text, parse_mode, reply_markup)))
        return result_or_raise(self.send_result)

    async def answer_callback_query(self, callback_query_id: str) -> object:
        self.events.append(("answer_callback_query", callback_query_id))
        return result_or_raise(self.send_result)

    async def copy_message(
        self,
        *,
        chat_id: int,
        from_chat_id: int,
        message_id: int,
    ) -> object:
        self.events.append(("copy_message", (chat_id, from_chat_id, message_id)))
        return result_or_raise(self.send_result)


class UpdateMemoryBackend(Protocol):
    async def load_update(self, key: str) -> Update | None: ...


class ResponseMemoryBackend(Protocol):
    async def store_response(
        self,
        key: str,
        response: TelegramResponse,
        ttl_seconds: int,
    ) -> None: ...

    async def load_response(self, key: str) -> TelegramResponse | None: ...


class UpdateDocumentMemory:
    def __init__(self, backend: UpdateMemoryBackend) -> None:
        self._backend = backend

    async def load(self, key: str) -> Update | None:
        return await self._backend.load_update(key)


class ResponseDocumentMemory:
    def __init__(self, backend: ResponseMemoryBackend) -> None:
        self._backend = backend

    async def store(
        self,
        key: str,
        document: TelegramResponse,
        ttl_seconds: int,
    ) -> None:
        await self._backend.store_response(key, document, ttl_seconds)

    async def load(self, key: str) -> TelegramResponse | None:
        return await self._backend.load_response(key)


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
        self.update_documents = UpdateDocumentMemory(self)
        self.response_documents = ResponseDocumentMemory(self)

    async def load_update(self, key: str) -> Update | None:
        self.events.append(("load_update", key))
        return cast(Update | None, result_or_raise(self.update_result))

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
        return cast(TelegramResponse, result)

    async def delete(self, keys: tuple[str, ...]) -> None:
        self.events.append(("delete", keys))
        result_or_raise(self.delete_result)
        for key in keys:
            self.responses.pop(key, None)

    async def send(self, response: TelegramResponse) -> None:
        self.events.append(("send_text", response.chat_id, response.text))
        result_or_raise(self.send_result)
        self.sent.set()


class QuestionnaireStateMemory:
    def __init__(self, memory: QuestionnaireMemory) -> None:
        self._memory = memory

    async def load(self, key: str) -> QuestionnaireState | None:
        return await self._memory.load_questionnaire(key)

    async def store(
        self,
        key: str,
        document: QuestionnaireState,
        ttl_seconds: int,
    ) -> None:
        await self._memory.store_questionnaire(key, document, ttl_seconds)


class DeathPredictionMemory:
    def __init__(self, memory: QuestionnaireMemory) -> None:
        self._memory = memory

    async def load(self, key: str) -> StoredDeathPrediction | None:
        return await self._memory.load_prediction(key)

    async def store(
        self,
        key: str,
        document: StoredDeathPrediction,
        ttl_seconds: int,
    ) -> None:
        await self._memory.store_prediction(key, document, ttl_seconds)


class QuestionnaireMemory:
    def __init__(
        self,
        *,
        updates: dict[str, Update] | None = None,
        questionnaires: dict[str, QuestionnaireState] | None = None,
    ) -> None:
        self.updates = dict(updates or {})
        self.questionnaires = dict(questionnaires or {})
        self.responses: dict[str, TelegramResponse] = {}
        self.predictions: dict[str, StoredDeathPrediction] = {}
        self.events: list[tuple[object, ...]] = []
        self.messages: list[tuple[int, str]] = []
        self.changed = asyncio.Event()
        self.update_documents = UpdateDocumentMemory(self)
        self.response_documents = ResponseDocumentMemory(self)
        self.questionnaire_repository = QuestionnaireStateMemory(self)
        self.prediction_repository = DeathPredictionMemory(self)

    async def load_update(self, key: str) -> Update | None:
        self.events.append(("load_update", key))
        return self.updates.get(key)

    async def load_questionnaire(self, key: str) -> QuestionnaireState | None:
        self.events.append(("load_questionnaire", key))
        return self.questionnaires.get(key)

    async def store_questionnaire(
        self,
        key: str,
        state: QuestionnaireState,
        ttl_seconds: int,
    ) -> None:
        self.events.append(("store_questionnaire", key, state, ttl_seconds))
        self.questionnaires[key] = state

    async def store_response(
        self,
        key: str,
        response: TelegramResponse,
        ttl_seconds: int,
    ) -> None:
        self.events.append(("store_response", key, response, ttl_seconds))
        self.responses[key] = response

    async def load_response(self, key: str) -> TelegramResponse | None:
        self.events.append(("load_response", key))
        return self.responses.get(key)

    async def delete(self, keys: tuple[str, ...]) -> None:
        self.events.append(("delete", keys))
        for key in keys:
            self.updates.pop(key, None)
            self.questionnaires.pop(key, None)
            self.responses.pop(key, None)
            self.predictions.pop(key, None)
        self.changed.set()

    async def load_prediction(self, key: str) -> StoredDeathPrediction | None:
        self.events.append(("load_prediction", key))
        return self.predictions.get(key)

    async def store_prediction(
        self,
        key: str,
        prediction: StoredDeathPrediction,
        ttl_seconds: int,
    ) -> None:
        self.events.append(("store_prediction", key, prediction, ttl_seconds))
        self.predictions[key] = prediction

    async def send(self, response: TelegramResponse) -> None:
        self.events.append(("send_text", response.chat_id, response.text))
        self.messages.append((response.chat_id, response.text))
        self.changed.set()

    async def wait_for_messages(self, count: int) -> None:
        while len(self.messages) < count:
            self.changed.clear()
            await asyncio.wait_for(
                self.changed.wait(),
                timeout=TEST_TIMEOUT_SECONDS,
            )

    async def wait_until_absent(self, key: str) -> None:
        while key in self.updates or key in self.questionnaires or key in self.responses:
            self.changed.clear()
            await asyncio.wait_for(
                self.changed.wait(),
                timeout=TEST_TIMEOUT_SECONDS,
            )


class QuestionnaireRepositoryDouble:
    def __init__(
        self,
        *,
        load_result: object,
        store_result: object = None,
    ) -> None:
        self.load_result = load_result
        self.store_result = store_result
        self.events: list[tuple[object, ...]] = []

    async def load(self, key: str) -> QuestionnaireState | None:
        self.events.append(("load_questionnaire", key))
        return cast(QuestionnaireState | None, result_or_raise(self.load_result))

    async def store(
        self,
        key: str,
        document: QuestionnaireState,
        ttl_seconds: int,
    ) -> None:
        self.events.append(("store_questionnaire", key, document, ttl_seconds))
        result_or_raise(self.store_result)


class MortalMemory:
    def __init__(self, mortals: dict[int, Mortal] | None = None) -> None:
        self.mortals = dict(mortals or {})
        self.consumed_request_ids: set[str] = set()
        self.events: list[tuple[object, ...]] = []

    async def ensure(self, mortal_id: int) -> Mortal:
        self.events.append(("ensure", mortal_id))
        current = mortal(id=mortal_id)
        mortal_state = self.mortals.setdefault(mortal_id, current).model_copy(
            update={"telegram_unreachable_at": None}
        )
        self.mortals[mortal_id] = mortal_state
        return mortal_state

    async def get(self, mortal_id: int) -> Mortal | None:
        self.events.append(("get", mortal_id))
        return self.mortals.get(mortal_id)

    async def list_ids(
        self,
        *,
        locale: str,
        after_mortal_id: int | None,
        limit: int,
    ) -> tuple[int, ...]:
        self.events.append(("list_ids", locale, after_mortal_id, limit))
        return tuple(
            mortal.id
            for mortal in sorted(self.mortals.values(), key=lambda current: current.id)
            if mortal.locale == locale
            and mortal.telegram_unreachable_at is None
            and (after_mortal_id is None or mortal.id > after_mortal_id)
        )[:limit]

    async def set_death_date(self, mortal_id: int, death_date: date) -> Mortal:
        self.events.append(("set_death_date", mortal_id, death_date))
        mortal_state = self.mortals.get(mortal_id, mortal(id=mortal_id)).model_copy(
            update={"death_date": death_date}
        )
        self.mortals[mortal_id] = mortal_state
        return mortal_state

    async def set_notification_cron(
        self,
        mortal_id: int,
        cron: str | None,
    ) -> Mortal:
        self.events.append(("set_notification_cron", mortal_id, cron))
        mortal_state = self.mortals.get(mortal_id, mortal(id=mortal_id)).model_copy(
            update={"notification_cron": cron}
        )
        self.mortals[mortal_id] = mortal_state
        return mortal_state

    async def set_notification_settings(
        self,
        mortal_id: int,
        *,
        cron: str | None,
        timezone: str,
    ) -> Mortal:
        self.events.append(("set_notification_settings", mortal_id, cron, timezone))
        mortal_state = self.mortals.get(mortal_id, mortal(id=mortal_id)).model_copy(
            update={"notification_cron": cron, "timezone": timezone}
        )
        self.mortals[mortal_id] = mortal_state
        return mortal_state

    async def set_locale(self, mortal_id: int, locale: str) -> Mortal:
        self.events.append(("set_locale", mortal_id, locale))
        mortal_state = self.mortals.get(mortal_id, mortal(id=mortal_id)).model_copy(
            update={"locale": locale}
        )
        self.mortals[mortal_id] = mortal_state
        return mortal_state

    async def consume_llm_request(self, mortal_id: int, request_id: str) -> Mortal:
        self.events.append(("consume_llm_request", mortal_id, request_id))
        mortal = self.mortals[mortal_id]
        if request_id in self.consumed_request_ids:
            return mortal
        self.consumed_request_ids.add(request_id)
        updated = mortal.model_copy(
            update={
                "llm_requests_remaining": max(
                    0,
                    mortal.llm_requests_remaining - 1,
                )
            }
        )
        self.mortals[mortal_id] = updated
        return updated

    async def mark_unreachable(self, mortal_id: int) -> None:
        self.events.append(("mark_unreachable", mortal_id))
        mortal = self.mortals.get(mortal_id)
        if mortal is not None:
            self.mortals[mortal_id] = mortal.model_copy(
                update={"telegram_unreachable_at": datetime.now(UTC)}
            )


class MortalScheduleMemory:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    async def ensure(self, mortal: Mortal) -> None:
        self.events.append(("ensure", mortal))

    async def delete(self, mortal_id: int) -> None:
        self.events.append(("delete", mortal_id))


class UserResolverDouble:
    def __init__(self, user_id: int | None) -> None:
        self.user_id = user_id
        self.events: list[int] = []

    def resolve(self, update: Update) -> int | None:
        self.events.append(update.update_id)
        return self.user_id


class SourceDouble:
    def __init__(
        self,
        prepare_outcomes: Sequence[object],
        receive_outcomes: Sequence[object],
        stop_event: asyncio.Event,
    ) -> None:
        self.prepare_outcomes = list(prepare_outcomes)
        self.receive_outcomes = list(receive_outcomes)
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
        return cast(Sequence[Update], outcome)


class StoreDouble:
    def __init__(self, outcomes: Sequence[object]) -> None:
        self.outcomes = list(outcomes)
        self.events: list[int] = []

    async def store(self, update: Update) -> StoredUpdate:
        self.events.append(update.update_id)
        return cast(StoredUpdate, result_or_raise(self.outcomes.pop(0)))


class HandoffDouble:
    def __init__(self, outcomes: Sequence[object]) -> None:
        self.outcomes = list(outcomes)
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

    async def start_workflow(
        self,
        workflow: str,
        arg: UserWorkflowInput,
        *,
        id: str,
        task_queue: str,
        id_conflict_policy: WorkflowIDConflictPolicy,
        start_signal: str | None,
        start_signal_args: Sequence[TelegramUpdateSignal],
    ) -> object:
        self.events.append(
            (
                workflow,
                arg,
                {
                    "id": id,
                    "task_queue": task_queue,
                    "id_conflict_policy": id_conflict_policy,
                    "start_signal": start_signal,
                    "start_signal_args": start_signal_args,
                },
            )
        )
        return result_or_raise(self.outcome)


@dataclass(frozen=True, slots=True)
class ActivityCase:
    update: Update
    expected_kind: InspectionKind
    expected_chat_id: int
    expected_callback_query_id: str | None = None
