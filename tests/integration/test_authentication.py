from __future__ import annotations

import asyncio
import time
from typing import Any

import anyio
import httpx
import pytest
from structlog.testing import capture_logs
from tests.support.asgi import (
    streamable_http_app,
    streamable_http_client,
    streamable_http_client_for_app,
)
from tests.support.jwt import SigningKey

from mcp_runtime import (
    InternalAuthSettings,
    RuntimeSettings,
    create_server,
    get_principal,
)


def _single_http_status_error(error: BaseException) -> httpx.HTTPStatusError:
    def leaf_exceptions(current: BaseException) -> list[BaseException]:
        if isinstance(current, BaseExceptionGroup):
            return [
                leaf for child in current.exceptions for leaf in leaf_exceptions(child)
            ]
        return [current]

    leaves = leaf_exceptions(error)
    assert len(leaves) == 1
    status_error = leaves[0]
    assert isinstance(status_error, httpx.HTTPStatusError)
    return status_error


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        service_id="graphpep-mcp",
        auth=InternalAuthSettings(
            issuer="https://api.xdenovoai.com/",
            jwks_url="http://gateway.internal/jwks",
        ),
    )


def _canonical_claims(
    settings: RuntimeSettings,
    *,
    now: int,
) -> dict[str, Any]:
    return {
        "iss": settings.auth.issuer,
        "aud": settings.audience,
        "sub": "sensitive-subject",
        "iat": now - 10,
        "exp": now + 290,
        "scope": "mcp:invoke example:read",
    }


async def test_valid_gateway_credential_reaches_tool_as_principal() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    settings = _settings()
    server = create_server(
        settings,
        jwks_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"keys": [signing_key.as_jwk()]},
            )
        ),
    )

    @server.tool
    async def whoami() -> dict[str, object]:
        principal = get_principal()
        return {
            "subject": principal.subject,
            "scopes": sorted(principal.scopes),
        }

    token = signing_key.issue(
        {
            "iss": settings.auth.issuer,
            "aud": settings.audience,
            "sub": "user_01J2ABCDEF",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke example:read",
            "unknown_claim": "must-not-enter-principal",
        }
    )

    async with streamable_http_client(server, token=token) as client:
        result = await client.call_tool("whoami")

    assert result.data == {
        "subject": "user_01J2ABCDEF",
        "scopes": ["example:read", "mcp:invoke"],
    }


async def test_concurrent_requests_keep_principals_isolated() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    settings = _settings()
    server = create_server(
        settings,
        jwks_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"keys": [signing_key.as_jwk()]},
            )
        ),
    )

    @server.tool
    async def observe_principal(delay: float) -> dict[str, object]:
        before = get_principal()
        await anyio.sleep(delay)
        after = get_principal()
        return {
            "before": before.subject,
            "after": after.subject,
            "scopes": sorted(after.scopes),
        }

    def token_for(subject: str, scope: str) -> str:
        return signing_key.issue(
            {
                **_canonical_claims(settings, now=now),
                "sub": subject,
                "scope": f"mcp:invoke {scope}",
            }
        )

    async with (
        streamable_http_app(server) as app,
        streamable_http_client_for_app(
            app,
            token=token_for("principal-a", "a:read"),
        ) as client_a,
        streamable_http_client_for_app(
            app,
            token=token_for("principal-b", "b:read"),
        ) as client_b,
    ):
        result_a, result_b = await asyncio.gather(
            client_a.call_tool("observe_principal", {"delay": 0.02}),
            client_b.call_tool("observe_principal", {"delay": 0.0}),
        )

    assert result_a.data == {
        "before": "principal-a",
        "after": "principal-a",
        "scopes": ["a:read", "mcp:invoke"],
    }
    assert result_b.data == {
        "before": "principal-b",
        "after": "principal-b",
        "scopes": ["b:read", "mcp:invoke"],
    }


async def test_session_id_cannot_be_reused_by_another_principal() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    settings = _settings()
    server = create_server(
        settings,
        jwks_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"keys": [signing_key.as_jwk()]},
            )
        ),
    )

    def token_for(subject: str) -> str:
        return signing_key.issue(
            {
                **_canonical_claims(settings, now=now),
                "sub": subject,
            }
        )

    token_a = token_for("principal-a")
    token_b = token_for("principal-b")
    async with (
        streamable_http_app(server) as app,
        streamable_http_client_for_app(app, token=token_a) as client_a,
    ):
        session_id = client_a.transport.get_session_id()
        assert session_id is not None

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client_b:
            response = await client_b.post(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {token_b}",
                    "Accept": "application/json, text/event-stream",
                    "Mcp-Session-Id": session_id,
                },
                json={"jsonrpc": "2.0", "id": 99, "method": "tools/list"},
            )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Session not found"


async def test_jwks_redirect_is_not_followed_and_request_fails_closed() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    settings = _settings()
    requests: list[httpx.Request] = []

    def redirect_jwks(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "http://untrusted.internal/redirected-jwks"},
        )

    tool_calls = 0
    server = create_server(
        settings,
        jwks_transport=httpx.MockTransport(redirect_jwks),
    )

    @server.tool
    async def protected() -> str:
        nonlocal tool_calls
        tool_calls += 1
        return "unexpected"

    token = signing_key.issue(_canonical_claims(settings, now=now))
    with pytest.raises(ExceptionGroup) as captured:
        async with streamable_http_client(server, token=token):
            pass

    assert _single_http_status_error(captured.value).response.status_code == 401
    assert [str(request.url) for request in requests] == [settings.auth.jwks_url]
    assert tool_calls == 0


async def test_public_auth_error_and_structured_event_exclude_rejected_values() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    settings = _settings()
    server = create_server(
        settings,
        jwks_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"keys": [signing_key.as_jwk()]},
            )
        ),
    )
    rejected_issuer = "https://rejected.example/sensitive"
    token = signing_key.issue(
        {
            **_canonical_claims(settings, now=now),
            "iss": rejected_issuer,
        }
    )

    with capture_logs() as logs:
        async with streamable_http_app(server) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/mcp",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )

    assert response.status_code == 401
    rendered = repr((response.headers, response.text, logs))
    assert token not in rendered
    assert "sensitive-subject" not in rendered
    assert rejected_issuer not in rendered
    assert settings.auth.jwks_url not in rendered


@pytest.mark.parametrize(
    "authorization_header",
    [None, "Basic opaque", "Bearer", "Bearer not-a-jwt"],
)
async def test_missing_or_malformed_bearer_never_reaches_tool(
    authorization_header: str | None,
) -> None:
    tool_calls = 0
    server = create_server(
        _settings(),
        jwks_transport=httpx.MockTransport(
            lambda request: pytest.fail("malformed credentials must not fetch JWKS")
        ),
    )

    @server.tool
    async def protected() -> str:
        nonlocal tool_calls
        tool_calls += 1
        return "unexpected"

    with pytest.raises(ExceptionGroup) as captured:
        async with streamable_http_client(
            server,
            authorization_header=authorization_header,
        ):
            pass

    status_error = _single_http_status_error(captured.value)
    assert status_error.response.status_code == 401
    assert tool_calls == 0


@pytest.mark.parametrize(
    "case",
    [
        "missing_kid",
        "invalid_kid_type",
        "empty_kid",
        "wrong_algorithm",
        "wrong_signature",
        "wrong_issuer",
        "wrong_audience",
        "audience_array",
        "missing_scope",
        "scope_array",
        "duplicate_scope",
        "iat_boolean",
        "exp_float",
        "nbf_string",
        "expired",
        "overlong_lifetime",
        "unknown_kid",
    ],
)
async def test_invalid_gateway_credentials_fail_closed_before_tool(
    case: str,
) -> None:
    now = int(time.time())
    settings = _settings()
    trusted_key = SigningKey.generate()
    other_key = SigningKey.generate(kid="gateway-other")
    claims = _canonical_claims(settings, now=now)

    if case == "wrong_issuer":
        claims["iss"] = "https://rejected.example/"
    elif case == "wrong_audience":
        claims["aud"] = "urn:xdenovo:mcp-service:other"
    elif case == "audience_array":
        claims["aud"] = [settings.audience]
    elif case == "missing_scope":
        claims["scope"] = "example:read"
    elif case == "scope_array":
        claims["scope"] = ["mcp:invoke"]
    elif case == "duplicate_scope":
        claims["scope"] = "mcp:invoke mcp:invoke"
    elif case == "iat_boolean":
        claims["iat"] = True
    elif case == "exp_float":
        claims["exp"] = float(now + 290)
    elif case == "nbf_string":
        claims["nbf"] = str(now)
    elif case == "expired":
        claims["iat"] = now - 10
        claims["exp"] = now
    elif case == "overlong_lifetime":
        claims["iat"] = now - 11
        claims["exp"] = now + 290

    if case == "missing_kid":
        token = trusted_key.issue(claims, include_kid=False)
    elif case == "invalid_kid_type":
        token = trusted_key.issue_with_headers(claims, {"kid": 7})
    elif case == "empty_kid":
        token = trusted_key.issue(claims, kid=" ")
    elif case == "wrong_algorithm":
        token = trusted_key.issue_with_headers(
            claims,
            {"alg": "HS256", "kid": trusted_key.kid},
        )
    elif case == "wrong_signature":
        token = other_key.issue(claims, kid=trusted_key.kid)
    elif case == "unknown_kid":
        token = trusted_key.issue(claims, kid="gateway-unknown")
    else:
        token = trusted_key.issue(claims)

    tool_calls = 0
    server = create_server(
        settings,
        jwks_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"keys": [trusted_key.as_jwk()]},
            )
        ),
    )

    @server.tool
    async def protected() -> str:
        nonlocal tool_calls
        tool_calls += 1
        return "unexpected"

    with pytest.raises(ExceptionGroup) as captured:
        async with streamable_http_client(server, token=token):
            pass

    status_error = _single_http_status_error(captured.value)
    response = status_error.response
    assert response.status_code == 401
    public_error = repr((status_error, response.headers))
    assert token not in public_error
    assert "sensitive-subject" not in public_error
    assert settings.auth.jwks_url not in public_error
    assert tool_calls == 0
