import ssl
from pathlib import Path
from typing import Any

import pytest
from temporalio.client import TLSConfig

from sein_zum_tode.infrastructure.tls import (
    PostgresTlsMode,
    create_postgres_ssl_context,
    create_temporal_tls_config,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("mode", "expected_context", "expected_hostname", "expected_verification"),
    [
        ("disable", False, None, None),
        ("require", True, False, ssl.CERT_NONE),
        ("verify-ca", True, False, ssl.CERT_REQUIRED),
        ("verify-full", True, True, ssl.CERT_REQUIRED),
    ],
)
def test_builds_each_supported_postgres_tls_mode(
    mode: PostgresTlsMode,
    expected_context: bool,
    expected_hostname: bool | None,
    expected_verification: ssl.VerifyMode | None,
) -> None:
    context = create_postgres_ssl_context(
        mode=mode,
        ca_file=None,
        certificate_file=None,
        private_key_file=None,
    )

    assert (
        context is not None,
        context.check_hostname if context else None,
        context.verify_mode if context else None,
        context.minimum_version if context else None,
    ) == (
        expected_context,
        expected_hostname,
        expected_verification,
        ssl.TLSVersion.TLSv1_2 if context else None,
    ), f"PostgreSQL TLS mode {mode} received different verification semantics"


def test_loads_a_postgres_client_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []
    context = ssl.create_default_context()
    monkeypatch.setattr(
        "sein_zum_tode.infrastructure.tls.ssl.create_default_context",
        lambda **_: context,
    )
    monkeypatch.setattr(
        context,
        "load_cert_chain",
        lambda certfile, keyfile: events.append((certfile, keyfile)),
    )

    actual = create_postgres_ssl_context(
        mode="verify-full",
        ca_file=Path("/certificates/postgres-ca-2141.pem"),
        certificate_file=Path("/certificates/mortal-2143.pem"),
        private_key_file=Path("/certificates/mortal-2153.key"),
    )

    assert (actual is context, events) == (
        True,
        [("/certificates/mortal-2143.pem", "/certificates/mortal-2153.key")],
    ), "PostgreSQL TLS context did not install the client identity"


def test_rejects_an_unknown_postgres_tls_mode() -> None:
    invalid_mode: Any = "opportunistic"

    with pytest.raises(ValueError, match="Unsupported PostgreSQL TLS mode"):
        create_postgres_ssl_context(
            mode=invalid_mode,
            ca_file=None,
            certificate_file=None,
            private_key_file=None,
        )


def test_disables_temporal_tls_without_reading_files() -> None:
    actual = create_temporal_tls_config(
        enabled=False,
        server_name="unused-temporal.internal",
        ca_file=Path("/missing/ca.pem"),
        certificate_file=Path("/missing/client.pem"),
        private_key_file=Path("/missing/client.key"),
    )

    assert actual is False, "disabled Temporal TLS still attempted configuration"


def test_builds_temporal_mtls_from_mounted_files(tmp_path: Path) -> None:
    ca = tmp_path / "ca.pem"
    certificate = tmp_path / "client.pem"
    private_key = tmp_path / "client.key"
    ca.write_bytes(b"ca-2161")
    certificate.write_bytes(b"certificate-2179")
    private_key.write_bytes(b"private-key-2203")

    actual = create_temporal_tls_config(
        enabled=True,
        server_name="temporal-orbit.internal",
        ca_file=ca,
        certificate_file=certificate,
        private_key_file=private_key,
    )

    assert actual == TLSConfig(
        server_root_ca_cert=b"ca-2161",
        domain="temporal-orbit.internal",
        client_cert=b"certificate-2179",
        client_private_key=b"private-key-2203",
    ), "Temporal TLS lost its trust roots, server identity, or client identity"


def test_builds_temporal_tls_with_system_roots_only() -> None:
    actual = create_temporal_tls_config(
        enabled=True,
        server_name=None,
        ca_file=None,
        certificate_file=None,
        private_key_file=None,
    )

    assert actual == TLSConfig(), "Temporal TLS required optional custom material"
