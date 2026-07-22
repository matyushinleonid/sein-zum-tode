"""Temporal client."""

from temporalio.client import Client

from sein_zum_tode.config import Settings


class TemporalClient:
    """Thin owner around the Temporal SDK client."""

    def __init__(self, client: Client) -> None:
        self.client = client

    @classmethod
    async def connect(cls, settings: Settings) -> TemporalClient:
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            tls=settings.temporal_tls,
        )
        return cls(client)
