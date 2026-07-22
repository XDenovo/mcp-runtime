from __future__ import annotations

from typing import Any, Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeConfig(BaseSettings):
    """Environment-driven configuration shared by every XDenovo compute MCP service.

    ``service_name`` is the only field a service must set explicitly. The
    other service-scoped identifiers (``db_schema``, ``s3_namespace``,
    ``temporal_namespace``, ``temporal_task_queue``) resolve to
    ``service_name`` when left unset, so a service can only address its own
    database schema, object storage namespace, and Temporal namespace/task
    queue unless it deliberately overrides a default. See
    mcp-runtime/docs/design.md section 2.1.
    """

    model_config = SettingsConfigDict(env_prefix="MCP_", extra="forbid")

    service_name: str
    environment: Literal["development", "staging", "production"]

    http_host: str = "0.0.0.0"
    http_port: int

    gateway_jwks_url: str
    internal_jwt_audience: str
    internal_jwt_issuer: str

    postgres_dsn: str
    db_schema: str | None = None

    s3_endpoint_url: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str
    s3_namespace: str | None = None

    temporal_address: str
    temporal_namespace: str | None = None
    temporal_task_queue: str | None = None

    log_level: str = "INFO"

    @classmethod
    def from_env(cls, **overrides: Any) -> RuntimeConfig:
        """Load configuration from the process environment, applying ``overrides`` last.

        The implementation must resolve ``db_schema``, ``s3_namespace``,
        ``temporal_namespace``, and ``temporal_task_queue`` to ``service_name``
        when unset -- callers must never see ``None`` for these fields.
        """
        raise NotImplementedError
