import pytest

from sein_zum_tode.payload_keys import (
    MortalNotificationPayloadKeys,
    QuestionnairePayloadKeys,
    UpdatePayloadKeys,
)

pytestmark = pytest.mark.fast


def test_derives_every_ephemeral_payload_key_from_its_owner() -> None:
    update = UpdatePayloadKeys.received(
        bot_id=470_017,
        update_id=470_021,
        prefix="telegram:incoming",
    )
    questionnaire = QuestionnairePayloadKeys("telegram:questionnaire:47027")
    notification = MortalNotificationPayloadKeys(
        mortal_id=470_029,
        run_id="run-470031",
    )

    assert (
        update.update,
        update.response(),
        update.scream_report(),
        update.notification_schedule_proposal(),
        questionnaire.prediction(),
        questionnaire.prediction_response(),
        questionnaire.privacy_response(),
        notification.response(),
    ) == (
        "telegram:incoming:470017:470021",
        "telegram:incoming:470017:470021:response",
        "telegram:incoming:470017:470021:scream-report",
        "telegram:incoming:470017:470021:notification-schedule",
        "telegram:questionnaire:47027:prediction",
        "telegram:questionnaire:47027:prediction-response",
        "telegram:questionnaire:47027:privacy",
        "telegram:notification:470029:run-470031:response",
    )
