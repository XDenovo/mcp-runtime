"""Validated configuration for an XDenovo Compute MCP Service."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Annotated, Any, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ServiceId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    ),
]


def _validate_absolute_url(value: str, *, schemes: frozenset[str]) -> str:
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError("URL must not contain surrounding whitespace or controls")

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise ValueError("URL is malformed") from error

    if parsed.scheme not in schemes or not parsed.netloc or parsed.hostname is None:
        raise ValueError(f"URL must be absolute and use {sorted(schemes)}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain userinfo")
    if parsed.fragment:
        raise ValueError("URL must not contain a fragment")
    return value


class ServerSettings(BaseModel):
    """Process bind settings for the private Streamable HTTP server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_hosts: tuple[str, ...] | None = None

    @field_validator("port", mode="before")
    @classmethod
    def _reject_boolean_port(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("port must be an integer")
        return value

    @model_validator(mode="after")
    def _validate_bind_policy(self) -> Self:
        if (
            not self.host
            or self.host != self.host.strip()
            or any(ord(character) < 32 for character in self.host)
        ):
            raise ValueError("host must be a non-empty value without whitespace")

        if self.allowed_hosts is not None:
            if not self.allowed_hosts:
                raise ValueError("allowed_hosts must not be empty when configured")
            if any(
                not allowed_host
                or allowed_host != allowed_host.strip()
                or "*" in allowed_host
                or any(ord(character) < 32 for character in allowed_host)
                for allowed_host in self.allowed_hosts
            ):
                raise ValueError("allowed_hosts must contain explicit host names")

        normalized_host = self.host.strip().strip("[]").lower()
        is_loopback = normalized_host == "localhost"
        if not is_loopback:
            try:
                is_loopback = ip_address(normalized_host).is_loopback
            except ValueError:
                is_loopback = False

        if not is_loopback and self.allowed_hosts is None:
            raise ValueError("a non-loopback bind requires explicit allowed_hosts")
        return self


class InternalAuthSettings(BaseModel):
    """Trusted Gateway issuer and JWKS retrieval settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str
    jwks_url: str

    @field_validator("issuer")
    @classmethod
    def _validate_issuer(cls, value: str) -> str:
        return _validate_absolute_url(value, schemes=frozenset({"https"}))

    @field_validator("jwks_url")
    @classmethod
    def _validate_jwks_url(cls, value: str) -> str:
        return _validate_absolute_url(value, schemes=frozenset({"http", "https"}))


class RuntimeSettings(BaseSettings):
    """Environment-aware settings bound to one stable Compute MCP Service."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_RUNTIME_",
        env_nested_delimiter="__",
        env_file=None,
        extra="forbid",
        frozen=True,
    )

    service_id: ServiceId
    server: ServerSettings = ServerSettings()
    auth: InternalAuthSettings

    @property
    def audience(self) -> str:
        """Return the only internal credential audience valid for this service."""
        return f"urn:xdenovo:mcp-service:{self.service_id}"
