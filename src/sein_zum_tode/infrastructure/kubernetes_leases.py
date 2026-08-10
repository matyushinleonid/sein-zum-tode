import ssl
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sein_zum_tode.ingress.errors import PollingLeaseError


class KubernetesLeaseMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    namespace: str
    resource_version: str | None = Field(default=None, alias="resourceVersion")


class KubernetesLeaseSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    holder_identity: str | None = Field(default=None, alias="holderIdentity")
    lease_duration_seconds: int | None = Field(default=None, alias="leaseDurationSeconds")
    acquire_time: datetime | None = Field(default=None, alias="acquireTime")
    renew_time: datetime | None = Field(default=None, alias="renewTime")
    lease_transitions: int = Field(default=0, alias="leaseTransitions")


class KubernetesLeaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    api_version: str = Field(default="coordination.k8s.io/v1", alias="apiVersion")
    kind: str = "Lease"
    metadata: KubernetesLeaseMetadata
    spec: KubernetesLeaseSpec


def utc_now() -> datetime:
    return datetime.now(UTC)


class KubernetesPollingLease:
    def __init__(
        self,
        *,
        store: KubernetesPollingLeaseStore,
        document: KubernetesLeaseDocument,
    ) -> None:
        self._store = store
        self._document = document

    async def release(self) -> None:
        await self._store.release(self._document)


class KubernetesPollingLeaseStore:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        namespace: str,
        lease_name: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client
        self._namespace = namespace
        self._lease_name = lease_name
        self._clock = clock
        namespace_path = quote(namespace, safe="")
        lease_path = quote(lease_name, safe="")
        self._collection_path = f"/apis/coordination.k8s.io/v1/namespaces/{namespace_path}/leases"
        self._resource_path = f"{self._collection_path}/{lease_path}"

    @classmethod
    def from_service_account(
        cls,
        *,
        api_url: str,
        namespace: str,
        lease_name: str,
        token_path: Path,
        ca_path: Path,
        request_timeout_seconds: float,
    ) -> KubernetesPollingLeaseStore:
        token = token_path.read_text(encoding="utf-8").strip()
        tls = ssl.create_default_context(cafile=str(ca_path))
        client = httpx.AsyncClient(
            base_url=api_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=request_timeout_seconds,
            verify=tls,
        )
        return cls(
            client=client,
            namespace=namespace,
            lease_name=lease_name,
        )

    async def acquire(
        self,
        *,
        holder_identity: str,
        duration_seconds: int,
    ) -> KubernetesPollingLease | None:
        try:
            current = await self._read()
            if current is not None and not self._available(
                current,
                holder_identity=holder_identity,
            ):
                return None
            candidate = self._candidate(
                current,
                holder_identity=holder_identity,
                duration_seconds=duration_seconds,
            )
            acquired = await self._write(candidate, create=current is None)
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise PollingLeaseError("Kubernetes Lease acquisition failed") from error
        if acquired is None:
            return None
        return KubernetesPollingLease(store=self, document=acquired)

    async def release(self, document: KubernetesLeaseDocument) -> None:
        released = document.model_copy(
            update={
                "spec": document.spec.model_copy(
                    update={
                        "holder_identity": None,
                        "renew_time": self._clock(),
                    }
                )
            }
        )
        try:
            await self._write(released, create=False)
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise PollingLeaseError("Kubernetes Lease release failed") from error

    async def close(self) -> None:
        await self._client.aclose()

    async def _read(self) -> KubernetesLeaseDocument | None:
        response = await self._client.get(self._resource_path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return KubernetesLeaseDocument.model_validate(response.json())

    async def _write(
        self,
        document: KubernetesLeaseDocument,
        *,
        create: bool,
    ) -> KubernetesLeaseDocument | None:
        payload = document.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        if create:
            response = await self._client.post(self._collection_path, json=payload)
        else:
            response = await self._client.put(self._resource_path, json=payload)
        if response.status_code in {404, 409}:
            return None
        response.raise_for_status()
        return KubernetesLeaseDocument.model_validate(response.json())

    def _available(
        self,
        document: KubernetesLeaseDocument,
        *,
        holder_identity: str,
    ) -> bool:
        holder = document.spec.holder_identity
        if holder is None or holder == holder_identity:
            return True
        renewed = document.spec.renew_time or document.spec.acquire_time
        duration = document.spec.lease_duration_seconds
        if renewed is None or duration is None:
            return False
        return self._clock() >= renewed + timedelta(seconds=duration)

    def _candidate(
        self,
        current: KubernetesLeaseDocument | None,
        *,
        holder_identity: str,
        duration_seconds: int,
    ) -> KubernetesLeaseDocument:
        now = self._clock()
        acquire_time: datetime | None
        if current is None:
            metadata = KubernetesLeaseMetadata(
                name=self._lease_name,
                namespace=self._namespace,
            )
            previous_holder = None
            acquire_time = now
            transitions = 0
        else:
            metadata = current.metadata
            previous_holder = current.spec.holder_identity
            acquire_time = current.spec.acquire_time
            transitions = current.spec.lease_transitions
            if previous_holder != holder_identity:
                acquire_time = now
                transitions += 1
        return KubernetesLeaseDocument(
            metadata=metadata,
            spec=KubernetesLeaseSpec(
                holder_identity=holder_identity,
                lease_duration_seconds=duration_seconds,
                acquire_time=acquire_time,
                renew_time=now,
                lease_transitions=transitions,
            ),
        )
