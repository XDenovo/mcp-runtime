"""Stable service-facing identity."""

from __future__ import annotations

from dataclasses import dataclass

from fastmcp.server.auth import AccessToken
from fastmcp.server.dependencies import get_http_request


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller identity exposed to Compute MCP Tools."""

    subject: str
    scopes: frozenset[str]


def get_principal() -> Principal:
    """Return the caller only during the current authenticated MCP request."""
    try:
        request = get_http_request()
    except RuntimeError:
        raise RuntimeError(
            "get_principal() requires an authenticated MCP request"
        ) from None

    access_token = getattr(request.scope.get("user"), "access_token", None)
    if (
        not isinstance(access_token, AccessToken)
        or not isinstance(access_token.subject, str)
        or not access_token.subject
    ):
        raise RuntimeError("get_principal() requires an authenticated MCP request")

    return Principal(
        subject=access_token.subject,
        scopes=frozenset(access_token.scopes),
    )
