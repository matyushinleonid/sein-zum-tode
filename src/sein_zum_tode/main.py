"""Minimal process entrypoint.

The real bot and Temporal workers can be added later. For now the process
validates configuration, connects to every infrastructure dependency, and
stays alive until SIGINT or SIGTERM.
"""

import asyncio
import logging
import signal

from sein_zum_tode.clients import ApplicationClients
from sein_zum_tode.config import Settings

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)

    logger.info("Connecting to PostgreSQL, Redis, and Temporal")
    clients = await ApplicationClients.connect(settings)
    logger.info(
        "Infrastructure connections are ready (Temporal namespace=%s, task_queue=%s)",
        settings.temporal_namespace,
        settings.temporal_task_queue,
    )

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down")
        await clients.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
