import asyncio
import signal
from collections.abc import Callable

import pytest

import sein_zum_tode.runtime as runtime_module

pytestmark = pytest.mark.fast


class SignalLoop:
    def __init__(self) -> None:
        self.events: list[signal.Signals] = []

    def add_signal_handler(
        self,
        signum: signal.Signals,
        callback: Callable[[], None],
    ) -> None:
        self.events.append(signum)
        callback()


def test_converts_both_process_signals_into_an_async_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = SignalLoop()
    stop = asyncio.Event()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)

    runtime_module.install_signal_handlers(stop)

    assert (loop.events, stop.is_set()) == (
        [signal.SIGINT, signal.SIGTERM],
        True,
    ), "runtime failed to translate SIGINT and SIGTERM into graceful shutdown"
