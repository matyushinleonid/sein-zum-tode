import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.broadcasts.workflow import TelegramScreamWorkflow
from sein_zum_tode.notifications.workflow import MortalNotificationWorkflow
from sein_zum_tode.questionnaire.workflow import TelegramQuestionnaireWorkflow

pytestmark = pytest.mark.replay

REPLAYED_WORKFLOWS = [
    TelegramUserWorkflow,
    TelegramQuestionnaireWorkflow,
    MortalNotificationWorkflow,
    TelegramScreamWorkflow,
]


@dataclass(frozen=True, slots=True)
class Divergence:
    workflow: str
    workflow_id: str
    reason: str


def replay_start() -> datetime:
    raw = os.environ.get("REPLAY_SINCE", "").strip()
    if not raw:
        pytest.fail("REPLAY_SINCE is not set; run this through `make replay SINCE=2026-08-01`")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        pytest.fail(f"REPLAY_SINCE={raw!r} is not an ISO 8601 date or datetime")
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def workflow_name(history: WorkflowHistory) -> str:
    started = history.events[0].workflow_execution_started_event_attributes
    return started.workflow_type.name or "unknown"


def summary(
    *,
    since: datetime,
    namespace: str,
    task_queue: str,
    replayed: Counter[str],
    divergences: list[Divergence],
) -> str:
    broken = Counter(divergence.workflow for divergence in divergences)
    lines = [
        "",
        "Replay summary",
        f"  since        {since.isoformat()}",
        f"  namespace    {namespace}",
        f"  task queue   {task_queue}",
        f"  executions   {sum(replayed.values())}",
    ]
    for name, total in sorted(replayed.items()):
        failures = broken[name]
        lines.append(f"    {name:<34} {total - failures:>4} ok   {failures:>4} diverged")
    if divergences:
        lines.append("  divergences")
        for divergence in divergences:
            lines.append(f"    {divergence.workflow} {divergence.workflow_id}")
            lines.append(f"      {divergence.reason}")
        lines.append("  verdict      DO NOT DEPLOY: running executions would break")
    else:
        lines.append("  verdict      every recorded history replays against the current code")
    return "\n".join(lines) + "\n"


async def test_recorded_histories_replay_against_the_current_workflow_code() -> None:
    since = replay_start()
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "sein-zum-tode")

    client = await Client.connect(address, namespace=namespace)
    query = f"TaskQueue = '{task_queue}' AND StartTime >= '{since.isoformat()}'"
    replayed: Counter[str] = Counter()
    divergences: list[Divergence] = []
    replayer = Replayer(workflows=REPLAYED_WORKFLOWS)
    async with replayer.workflow_replay_iterator(
        client.list_workflows(query).map_histories()
    ) as results:
        async for result in results:
            name = workflow_name(result.history)
            replayed[name] += 1
            if result.replay_failure is not None:
                divergences.append(
                    Divergence(
                        workflow=name,
                        workflow_id=result.history.workflow_id,
                        reason=str(result.replay_failure).splitlines()[0][:200],
                    )
                )

    print(
        summary(
            since=since,
            namespace=namespace,
            task_queue=task_queue,
            replayed=replayed,
            divergences=divergences,
        )
    )
    assert sum(replayed.values()) > 0, (
        f"no execution on {task_queue!r} started at or after {since.isoformat()}, "
        "so nothing was verified; choose an earlier SINCE"
    )
    assert not divergences, (
        f"{len(divergences)} recorded execution(s) diverge from the current workflow code; "
        "gate the change with workflow.patched() instead of editing the workflow in place"
    )
