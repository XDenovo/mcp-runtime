from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastmcp import FastMCP


@dataclass(frozen=True, slots=True)
class Principal:
    """Verified identity extracted from a Gateway-issued internal JWT."""

    subject: str
    audience: str
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    claims: Mapping[str, Any]

    def has_scope(self, scope: str) -> bool:
        raise NotImplementedError


class TokenVerificationError(Exception):
    """Raised when an internal JWT fails signature, audience, issuer, or expiry checks."""


class InternalTokenVerifier:
    """Verifies internal JWTs issued by the Gateway, using its published JWKS.

    Wraps ``jwt.PyJWKClient`` with caching and key refresh. Construct one per
    service process from ``RuntimeConfig.gateway_jwks_url`` /
    ``internal_jwt_audience`` / ``internal_jwt_issuer``.
    """

    def __init__(
        self,
        jwks_url: str,
        audience: str,
        issuer: str,
        *,
        leeway_seconds: int = 30,
    ) -> None:
        raise NotImplementedError

    def verify(self, token: str) -> Principal:
        """Validate ``token`` and return the resulting Principal.

        Raises:
            TokenVerificationError: if signature, audience, issuer, or expiry
                checks fail.
        """
        raise NotImplementedError


_current_principal: ContextVar[Principal] = ContextVar("mcp_runtime_current_principal")


def install_auth(app: FastMCP, verifier: InternalTokenVerifier) -> None:
    """Wire request-scoped Principal extraction into ``app`` as FastMCP middleware.

    Every inbound MCP request has its Authorization header verified via
    ``verifier`` before reaching a tool handler; verification failures are
    mapped to a standard MCP auth error, not surfaced as a bare exception.
    """
    raise NotImplementedError


def current_principal() -> Principal:
    """Return the Principal verified for the in-flight request.

    Only valid inside a tool handler invoked after ``install_auth`` has run
    on the owning app.
    """
    raise NotImplementedError
