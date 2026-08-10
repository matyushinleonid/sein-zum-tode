import json
import ssl
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from sein_zum_tode.infrastructure.kubernetes_leases import KubernetesPollingLeaseStore
from sein_zum_tode.ingress.errors import PollingLeaseError
from sein_zum_tode.ingress.ports import PollingLease

pytestmark = pytest.mark.fast


NOW = datetime(2057, 3, 11, 13, 17, 19, tzinfo=UTC)
RESOURCE_PATH = "/apis/coordination.k8s.io/v1/namespaces/mortals-2111/leases/telegram-poll-2113"
COLLECTION_PATH = "/apis/coordination.k8s.io/v1/namespaces/mortals-2111/leases"


def lease_payload(
    *,
    holder: str | None,
    resource_version: str,
    renewed: str | None = "2057-03-11T13:17:19Z",
    duration: int | None = 61,
    transitions: int = 0,
) -> dict[str, object]:
    spec: dict[str, object] = {
        "holderIdentity": holder,
        "leaseTransitions": transitions,
    }
    if renewed is not None:
        spec["renewTime"] = renewed
        spec["acquireTime"] = renewed
    if duration is not None:
        spec["leaseDurationSeconds"] = duration
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": {
            "name": "telegram-poll-2113",
            "namespace": "mortals-2111",
            "resourceVersion": resource_version,
        },
        "spec": spec,
    }


class KubernetesApiMemory:
    def __init__(self, responses: Sequence[tuple[int, object]]) -> None:
        self.responses = list(responses)
        self.events: list[tuple[str, str, object | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.events.append((request.method, request.url.path, body))
        status, payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload, request=request)


def lease_store(api: KubernetesApiMemory) -> KubernetesPollingLeaseStore:
    return KubernetesPollingLeaseStore(
        client=httpx.AsyncClient(
            base_url="https://kubernetes.invalid",
            transport=httpx.MockTransport(api),
        ),
        namespace="mortals-2111",
        lease_name="telegram-poll-2113",
        clock=lambda: NOW,
    )


async def acquired_lease(store: KubernetesPollingLeaseStore) -> PollingLease:
    lease = await store.acquire(
        holder_identity="ingress-new-2129",
        duration_seconds=61,
    )
    return cast(PollingLease, lease)


async def test_creates_and_gracefully_releases_a_missing_kubernetes_lease() -> None:
    acquired = lease_payload(holder="ingress-new-2129", resource_version="2131")
    released = lease_payload(holder=None, resource_version="2137")
    api = KubernetesApiMemory(
        responses=[
            (404, {"kind": "Status"}),
            (201, acquired),
            (200, released),
        ]
    )
    store = lease_store(api)

    lease = await acquired_lease(store)
    await lease.release()
    await store.close()

    assert api.events == [
        ("GET", RESOURCE_PATH, None),
        (
            "POST",
            COLLECTION_PATH,
            {
                "apiVersion": "coordination.k8s.io/v1",
                "kind": "Lease",
                "metadata": {
                    "name": "telegram-poll-2113",
                    "namespace": "mortals-2111",
                },
                "spec": {
                    "holderIdentity": "ingress-new-2129",
                    "leaseDurationSeconds": 61,
                    "acquireTime": "2057-03-11T13:17:19Z",
                    "renewTime": "2057-03-11T13:17:19Z",
                    "leaseTransitions": 0,
                },
            },
        ),
        (
            "PUT",
            RESOURCE_PATH,
            {
                "apiVersion": "coordination.k8s.io/v1",
                "kind": "Lease",
                "metadata": {
                    "name": "telegram-poll-2113",
                    "namespace": "mortals-2111",
                    "resourceVersion": "2131",
                },
                "spec": {
                    "leaseDurationSeconds": 61,
                    "acquireTime": "2057-03-11T13:17:19Z",
                    "renewTime": "2057-03-11T13:17:19Z",
                    "leaseTransitions": 0,
                },
            },
        ),
    ], "Kubernetes Lease store did not acquire and release through resource-version CAS"


@pytest.mark.parametrize(
    "current",
    [
        lease_payload(
            holder="ingress-old-2141",
            resource_version="2143",
            renewed="2057-03-11T13:17:18Z",
        ),
        lease_payload(
            holder="ingress-old-2141",
            resource_version="2143",
            renewed=None,
        ),
    ],
)
async def test_refuses_a_polling_turn_held_by_a_live_or_unverifiable_pod(
    current: dict[str, object],
) -> None:
    api = KubernetesApiMemory(responses=[(200, current)])
    store = lease_store(api)

    actual = await store.acquire(
        holder_identity="ingress-new-2149",
        duration_seconds=61,
    )
    await store.close()

    assert (actual, api.events) == (
        None,
        [("GET", RESOURCE_PATH, None)],
    ), "ingress stole an unexpired or unverifiable polling Lease"


async def test_replaces_an_expired_lease_and_records_the_transition() -> None:
    expired = lease_payload(
        holder="ingress-old-2153",
        resource_version="2161",
        renewed="2057-03-11T13:15:00Z",
        transitions=7,
    )
    acquired = lease_payload(
        holder="ingress-new-2167",
        resource_version="2179",
        transitions=8,
    )
    api = KubernetesApiMemory(responses=[(200, expired), (200, acquired)])
    store = lease_store(api)

    actual = await store.acquire(
        holder_identity="ingress-new-2167",
        duration_seconds=61,
    )
    await store.close()

    assert (actual is not None, api.events[-1]) == (
        True,
        (
            "PUT",
            RESOURCE_PATH,
            {
                "apiVersion": "coordination.k8s.io/v1",
                "kind": "Lease",
                "metadata": {
                    "name": "telegram-poll-2113",
                    "namespace": "mortals-2111",
                    "resourceVersion": "2161",
                },
                "spec": {
                    "holderIdentity": "ingress-new-2167",
                    "leaseDurationSeconds": 61,
                    "acquireTime": "2057-03-11T13:17:19Z",
                    "renewTime": "2057-03-11T13:17:19Z",
                    "leaseTransitions": 8,
                },
            },
        ),
    ), "expired polling Lease was not transferred with an incremented transition"


@pytest.mark.parametrize("conflict_status", [404, 409])
async def test_loses_a_concurrent_lease_write_without_claiming_the_turn(
    conflict_status: int,
) -> None:
    api = KubernetesApiMemory(
        responses=[
            (404, {"kind": "Status"}),
            (conflict_status, {"kind": "Status"}),
        ]
    )
    store = lease_store(api)

    actual = await store.acquire(
        holder_identity="ingress-racing-2203",
        duration_seconds=61,
    )
    await store.close()

    assert actual is None, "a failed Kubernetes CAS was mistaken for Lease ownership"


async def test_surfaces_kubernetes_api_failures_as_polling_coordination_errors() -> None:
    api = KubernetesApiMemory(responses=[(503, {"kind": "Status"})])
    store = lease_store(api)

    with pytest.raises(PollingLeaseError):
        await store.acquire(
            holder_identity="ingress-unavailable-2213",
            duration_seconds=61,
        )

    await store.close()


async def test_surfaces_a_failed_graceful_release_for_ttl_fallback() -> None:
    acquired = lease_payload(holder="ingress-new-2221", resource_version="2237")
    api = KubernetesApiMemory(
        responses=[
            (404, {"kind": "Status"}),
            (201, acquired),
            (500, {"kind": "Status"}),
        ]
    )
    store = lease_store(api)
    lease = await acquired_lease(store)

    with pytest.raises(PollingLeaseError):
        await lease.release()

    await store.close()


async def test_renews_a_lease_already_held_by_the_same_pod() -> None:
    current = lease_payload(
        holder="ingress-new-2243",
        resource_version="2251",
        renewed="2057-03-11T13:16:00Z",
        transitions=3,
    )
    renewed = lease_payload(
        holder="ingress-new-2243",
        resource_version="2267",
        transitions=3,
    )
    api = KubernetesApiMemory(responses=[(200, current), (200, renewed)])
    store = lease_store(api)

    actual = await store.acquire(
        holder_identity="ingress-new-2243",
        duration_seconds=61,
    )
    await store.close()

    request = cast(dict[str, object], api.events[-1][2])
    spec = cast(dict[str, object], request["spec"])
    assert (actual is not None, spec["acquireTime"], spec["leaseTransitions"]) == (
        True,
        "2057-03-11T13:16:00Z",
        3,
    ), "same pod reacquisition incorrectly recorded a leadership transition"


async def test_timestamps_a_new_lease_with_the_system_clock() -> None:
    acquired = lease_payload(holder="ingress-clock-2269", resource_version="2273")
    api = KubernetesApiMemory(
        responses=[
            (404, {"kind": "Status"}),
            (201, acquired),
        ]
    )
    store = KubernetesPollingLeaseStore(
        client=httpx.AsyncClient(
            base_url="https://kubernetes.invalid",
            transport=httpx.MockTransport(api),
        ),
        namespace="mortals-2111",
        lease_name="telegram-poll-2113",
    )

    actual = await store.acquire(
        holder_identity="ingress-clock-2269",
        duration_seconds=61,
    )
    await store.close()

    payload = cast(dict[str, object], api.events[-1][2])
    spec = cast(dict[str, object], payload["spec"])
    timestamp = datetime.fromisoformat(cast(str, spec["renewTime"]).replace("Z", "+00:00"))
    assert (actual is not None, timestamp.tzinfo) == (
        True,
        UTC,
    ), "default Kubernetes Lease clock did not produce an aware UTC timestamp"


async def test_builds_an_authenticated_client_from_a_projected_service_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_path = tmp_path / "token"
    ca_path = tmp_path / "ca.crt"
    token_path.write_text("  token-2273\n", encoding="utf-8")
    ca_path.write_text("ca-2279", encoding="utf-8")
    events: list[tuple[object, ...]] = []
    client = SimpleNamespace(aclose=lambda: None)

    def create_tls(*, cafile: str) -> object:
        events.append(("tls", cafile))
        return "tls-context"

    def create_client(**options: object) -> object:
        events.append(("client", options))
        return client

    monkeypatch.setattr(ssl, "create_default_context", create_tls)
    monkeypatch.setattr(httpx, "AsyncClient", create_client)

    actual = KubernetesPollingLeaseStore.from_service_account(
        api_url="https://kubernetes-2281.invalid",
        namespace="mortals-2287",
        lease_name="polling-2293",
        token_path=token_path,
        ca_path=ca_path,
        request_timeout_seconds=2.9,
    )

    assert (isinstance(actual, KubernetesPollingLeaseStore), events) == (
        True,
        [
            ("tls", str(ca_path)),
            (
                "client",
                {
                    "base_url": "https://kubernetes-2281.invalid",
                    "headers": {"Authorization": "Bearer token-2273"},
                    "timeout": 2.9,
                    "verify": "tls-context",
                },
            ),
        ],
    ), "projected ServiceAccount credentials were not bound to the Kubernetes client"
