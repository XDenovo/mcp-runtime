from __future__ import annotations

import pytest
from fastmcp.server.auth import AccessToken
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from starlette.requests import Request

from mcp_runtime import get_principal
from mcp_runtime.auth import principal as principal_module


def test_get_principal_fails_clearly_outside_authenticated_request() -> None:
    with pytest.raises(RuntimeError, match="authenticated MCP request"):
        get_principal()


def test_get_principal_rejects_request_without_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(principal_module, "get_http_request", lambda: request)

    with pytest.raises(RuntimeError, match="authenticated MCP request"):
        get_principal()


@pytest.mark.parametrize("subject", [None, ""])
def test_get_principal_rejects_authenticated_token_without_subject(
    monkeypatch: pytest.MonkeyPatch,
    subject: str | None,
) -> None:
    access_token = AccessToken(
        token="opaque",
        client_id="gateway",
        subject=subject,
        scopes=["mcp:invoke"],
        claims={},
    )
    request = Request(
        {
            "type": "http",
            "headers": [],
            "user": AuthenticatedUser(access_token),
        }
    )
    monkeypatch.setattr(principal_module, "get_http_request", lambda: request)

    with pytest.raises(RuntimeError, match="authenticated MCP request"):
        get_principal()
