from types import ModuleType

import pytest

import sein_zum_tode.bot.worker as worker_module
import sein_zum_tode.main as ingress_module
from tests.assembly import (
    EntrypointAssembly,
    IngressAssembly,
    WorkerAssembly,
    explicit_settings,
)

pytestmark = pytest.mark.fast


async def test_assembles_and_closes_the_ingress_process(monkeypatch) -> None:
    assembly = IngressAssembly()
    assembly.install(monkeypatch, ingress_module)

    await ingress_module.run(explicit_settings())

    assert assembly.events == [
        ("signals", False),
        ("bot", "181:irregular-token"),
        (
            "redis",
            {
                "host": "redis-pulsar.internal",
                "port": 1861,
                "db": 13,
                "password": "redis-irregular-1867",
            },
        ),
        (
            "temporal",
            "temporal-nebula.internal:1831",
            {"namespace": "galactic-1837", "tls": True},
        ),
        ("source", 43, 59),
        ("redis_client", True),
        ("resolver",),
        ("store", 1871, 1823),
        ("starter", 1871, "telegram-quasars-1847", 1853),
        ("handoff", True),
        ("waiter", 0.73, 18.29),
        ("poller", ("source", "store", "handoff", "retry_waiter")),
        ("poller.run", False),
        ("bot.close",),
        ("redis.close",),
    ], "ingress composition root wired wrong settings or leaked a client"


async def test_assembles_and_closes_the_temporal_worker(monkeypatch) -> None:
    assembly = WorkerAssembly()
    assembly.install(monkeypatch, worker_module)

    await worker_module.run(explicit_settings())

    assert assembly.events == [
        ("signals", False),
        ("bot", "181:irregular-token"),
        (
            "redis",
            {
                "host": "redis-pulsar.internal",
                "port": 1861,
                "db": 13,
                "password": "redis-irregular-1867",
            },
        ),
        (
            "temporal",
            "temporal-nebula.internal:1831",
            {"namespace": "galactic-1837", "tls": True},
        ),
        ("payloads", True),
        ("sender", True),
        ("inspect", True),
        ("prepare", 1823),
        ("delivery", True, True),
        ("cleanup", True),
        (
            "worker",
            True,
            "telegram-quasars-1847",
            (
                "activity:inspect",
                "activity:prepare_echo",
                "activity:prepare_help",
                "activity:prepare_unsupported",
                "activity:prepare_group_unsupported",
                "activity:deliver",
                "activity:cleanup",
            ),
        ),
        ("worker.enter",),
        ("worker.exit", None),
        ("bot.close",),
        ("redis.close",),
    ], "worker composition root wired wrong Activities or leaked a client"


@pytest.mark.parametrize("module", [ingress_module, worker_module])
def test_configures_and_runs_each_process_entrypoint(
    monkeypatch,
    module: ModuleType,
) -> None:
    assembly = EntrypointAssembly(explicit_settings())
    assembly.install(monkeypatch, module)

    module.main()

    assert assembly.events == [
        ("settings",),
        ("logging", "WARNING", "json", "telegram-cosmos-1811"),
        ("run", True),
    ], "process entrypoint skipped settings, logging, or its async application"
