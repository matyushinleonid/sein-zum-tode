from aiogram.types import Update

from sein_zum_tode.ingress.routing import AiogramUpdateUserResolver


def test_resolver_uses_event_from_user() -> None:
    update = Update.model_validate(
        {
            "update_id": 1,
            "callback_query": {
                "id": "callback",
                "from": {
                    "id": 40,
                    "is_bot": False,
                    "first_name": "Ada",
                },
                "chat_instance": "instance",
            },
        }
    )

    assert AiogramUpdateUserResolver().resolve(update) == 40


def test_resolver_uses_event_user() -> None:
    update = Update.model_validate(
        {
            "update_id": 1,
            "poll_answer": {
                "poll_id": "poll",
                "option_ids": [0],
                "option_persistent_ids": [],
                "user": {
                    "id": 40,
                    "is_bot": False,
                    "first_name": "Ada",
                },
            },
        }
    )

    assert AiogramUpdateUserResolver().resolve(update) == 40


def test_resolver_returns_none_for_event_without_user() -> None:
    update = Update.model_validate(
        {
            "update_id": 1,
            "poll": {
                "id": "poll",
                "question": "Question",
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

    assert AiogramUpdateUserResolver().resolve(update) is None


def test_resolver_returns_none_for_unknown_event() -> None:
    assert AiogramUpdateUserResolver().resolve(Update(update_id=1)) is None
