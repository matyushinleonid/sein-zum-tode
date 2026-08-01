from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdatePayloadKeys:
    update: str

    @classmethod
    def received(
        cls,
        *,
        bot_id: int,
        update_id: int,
        prefix: str = "telegram:updates",
    ) -> UpdatePayloadKeys:
        return cls(update=f"{prefix}:{bot_id}:{update_id}")

    def response(self) -> str:
        return f"{self.update}:response"

    def scream_report(self) -> str:
        return f"{self.update}:scream-report"

    def notification_schedule_proposal(self) -> str:
        return f"{self.update}:notification-schedule"


@dataclass(frozen=True, slots=True)
class QuestionnairePayloadKeys:
    questionnaire: str

    def prediction(self) -> str:
        return f"{self.questionnaire}:prediction"

    def prediction_response(self) -> str:
        return f"{self.questionnaire}:prediction-response"

    def privacy_response(self) -> str:
        return f"{self.questionnaire}:privacy"


@dataclass(frozen=True, slots=True)
class MortalNotificationPayloadKeys:
    mortal_id: int
    run_id: str

    def response(self) -> str:
        return f"telegram:notification:{self.mortal_id}:{self.run_id}:response"
