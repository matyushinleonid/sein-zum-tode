import ssl
from pathlib import Path
from typing import Literal

from temporalio.client import TLSConfig

PostgresTlsMode = Literal["disable", "require", "verify-ca", "verify-full"]


def create_postgres_ssl_context(
    *,
    mode: PostgresTlsMode,
    ca_file: Path | None,
    certificate_file: Path | None,
    private_key_file: Path | None,
) -> ssl.SSLContext | None:
    if mode not in {"disable", "require", "verify-ca", "verify-full"}:
        raise ValueError(f"Unsupported PostgreSQL TLS mode: {mode}")
    if mode == "disable":
        return None
    if mode == "require":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        context.check_hostname = mode == "verify-full"
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if certificate_file is not None and private_key_file is not None:
        context.load_cert_chain(
            certfile=str(certificate_file),
            keyfile=str(private_key_file),
        )
    return context


def create_temporal_tls_config(
    *,
    enabled: bool,
    server_name: str | None,
    ca_file: Path | None,
    certificate_file: Path | None,
    private_key_file: Path | None,
) -> bool | TLSConfig:
    if not enabled:
        return False
    return TLSConfig(
        server_root_ca_cert=_read(ca_file),
        domain=server_name,
        client_cert=_read(certificate_file),
        client_private_key=_read(private_key_file),
    )


def _read(path: Path | None) -> bytes | None:
    return path.read_bytes() if path is not None else None
