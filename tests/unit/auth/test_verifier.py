from __future__ import annotations

import time

import httpx
import pytest
from structlog.testing import capture_logs
from tests.support.jwt import SigningKey

from mcp_runtime.auth.verifier import InternalJWTVerifier


async def test_verifier_maps_fastmcp_verified_claims_to_access_token() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    requests: list[httpx.Request] = []

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": [signing_key.as_jwk()]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(serve_jwks),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        access_token = await verifier.verify_token(
            signing_key.issue(
                {
                    "iss": "https://api.xdenovoai.com/",
                    "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
                    "sub": "user_01J2ABCDEF",
                    "iat": now - 10,
                    "exp": now + 290,
                    "scope": "mcp:invoke example:read",
                    "extension": "ignored-by-principal",
                }
            )
        )

    assert access_token is not None
    assert access_token.client_id == "user_01J2ABCDEF"
    assert access_token.subject == "user_01J2ABCDEF"
    assert access_token.scopes == ["example:read", "mcp:invoke"]
    assert len(requests) == 1


async def test_jwks_network_failure_emits_only_safe_structured_context() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate(kid="gateway-sensitive-kid")
    token = signing_key.issue(
        {
            "iss": "https://api.xdenovoai.com/",
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "sensitive-subject",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke",
        }
    )

    def fail_jwks(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "secret failure at http://gateway.internal/jwks",
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(fail_jwks),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        with capture_logs() as logs:
            access_token = await verifier.verify_token(token)

    assert access_token is None
    assert any(
        event.get("event") == "jwks_fetch_failed"
        and event.get("reason") == "network_error"
        and event.get("retryable") is True
        for event in logs
    )
    rendered_logs = repr(logs)
    assert token not in rendered_logs
    assert "sensitive-subject" not in rendered_logs
    assert "http://gateway.internal/jwks" not in rendered_logs
    assert "secret failure" not in rendered_logs


async def test_jwks_timeout_is_retryable_and_runtime_created_only_fails_closed() -> (
    None
):
    now = int(time.time())
    signing_key = SigningKey.generate()
    token = signing_key.issue(
        {
            "iss": "https://api.xdenovoai.com/",
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "sensitive-subject",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke",
        }
    )

    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unsafe internal timeout details", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(time_out),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        with capture_logs() as timeout_logs:
            assert await verifier.verify_token(token) is None

    never_started_verifier = InternalJWTVerifier(
        service_id="graphpep-mcp",
        issuer="https://api.xdenovoai.com/",
        audience="urn:xdenovo:mcp-service:graphpep-mcp",
        jwks_url="http://gateway.internal/jwks",
        http_client=None,
        clock=lambda: now,
    )
    with capture_logs() as unavailable_logs:
        assert await never_started_verifier.verify_token(token) is None

    assert any(
        event.get("event") == "jwks_fetch_failed"
        and event.get("reason") == "timeout"
        and event.get("retryable") is True
        for event in timeout_logs
    )
    assert any(
        event.get("event") == "jwks_fetch_failed"
        and event.get("reason") == "client_unavailable"
        and event.get("retryable") is True
        for event in unavailable_logs
    )
    rendered_logs = repr((timeout_logs, unavailable_logs))
    assert token not in rendered_logs
    assert "sensitive-subject" not in rendered_logs
    assert "unsafe internal timeout details" not in rendered_logs
    assert "http://gateway.internal/jwks" not in rendered_logs


async def test_unknown_kid_refreshes_jwks_and_preserves_overlapping_key() -> None:
    now = int(time.time())
    old_key = SigningKey.generate(kid="gateway-old")
    new_key = SigningKey.generate(kid="gateway-new")
    responses = [
        {"keys": [old_key.as_jwk()]},
        {"keys": [old_key.as_jwk(), new_key.as_jwk()]},
    ]
    request_count = 0

    def serve_rotating_jwks(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        response = responses[min(request_count, len(responses) - 1)]
        request_count += 1
        return httpx.Response(200, json=response)

    claims = {
        "iss": "https://api.xdenovoai.com/",
        "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
        "sub": "user_01J2ABCDEF",
        "iat": now - 10,
        "exp": now + 290,
        "scope": "mcp:invoke",
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(serve_rotating_jwks),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )

        assert await verifier.verify_token(old_key.issue(claims)) is not None
        assert await verifier.verify_token(new_key.issue(claims)) is not None
        assert await verifier.verify_token(old_key.issue(claims)) is not None

    assert request_count == 2


@pytest.mark.parametrize(
    ("response", "reason", "retryable"),
    [
        (httpx.Response(429), "http_status", True),
        (httpx.Response(503), "http_status", True),
        (httpx.Response(404), "http_status", False),
        (
            httpx.Response(
                200,
                content=b"not-json",
                headers={"content-type": "application/json"},
            ),
            "invalid_json",
            False,
        ),
        (httpx.Response(200, json=[]), "invalid_shape", False),
    ],
)
async def test_jwks_response_failures_are_safely_classified(
    response: httpx.Response,
    reason: str,
    retryable: bool,
) -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    token = signing_key.issue(
        {
            "iss": "https://api.xdenovoai.com/",
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "sensitive-subject",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke",
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: response),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        with capture_logs() as logs:
            access_token = await verifier.verify_token(token)

    assert access_token is None
    assert any(
        event.get("event") == "jwks_fetch_failed"
        and event.get("reason") == reason
        and event.get("retryable") is retryable
        for event in logs
    )
    rendered_logs = repr(logs)
    assert token not in rendered_logs
    assert "sensitive-subject" not in rendered_logs
    assert "http://gateway.internal/jwks" not in rendered_logs


async def test_rejected_claim_and_hostile_kid_cannot_inject_log_fields() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate(kid="gateway-current")
    hostile_kid = "gateway-current\nsubject=sensitive-subject " + "x" * 100
    rejected_issuer = "https://internal.example/\nforged_event=accepted"
    token = signing_key.issue(
        {
            "iss": rejected_issuer,
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "sensitive-subject",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke secret:scope",
        },
        kid=hostile_kid,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "keys": [
                        {
                            **signing_key.as_jwk(),
                            "kid": hostile_kid,
                        }
                    ]
                },
            )
        ),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        with capture_logs() as logs:
            access_token = await verifier.verify_token(token)

    assert access_token is None
    assert logs[-1]["event"] == "internal_auth_failed"
    assert logs[-1]["kid"] == "<redacted>"
    rendered_logs = repr(logs)
    assert token not in rendered_logs
    assert hostile_kid not in rendered_logs
    assert rejected_issuer not in rendered_logs
    assert "sensitive-subject" not in rendered_logs
    assert "secret:scope" not in rendered_logs


async def test_malformed_jwk_fails_closed_without_unsafe_details() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    token = signing_key.issue(
        {
            "iss": "https://api.xdenovoai.com/",
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "sensitive-subject",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke",
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "keys": [
                        {
                            "kid": signing_key.kid,
                            "kty": "RSA",
                            "n": "unsafe malformed modulus",
                            "e": "AQAB",
                        }
                    ]
                },
            )
        ),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        with capture_logs() as logs:
            assert await verifier.verify_token(token) is None

    rendered_logs = repr(logs)
    assert logs[-1]["reason"] == "verification_failed"
    assert token not in rendered_logs
    assert "sensitive-subject" not in rendered_logs
    assert "unsafe malformed modulus" not in rendered_logs


async def test_invalid_jwks_keys_container_fails_closed() -> None:
    now = int(time.time())
    signing_key = SigningKey.generate()
    token = signing_key.issue(
        {
            "iss": "https://api.xdenovoai.com/",
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "sensitive-subject",
            "iat": now - 10,
            "exp": now + 290,
            "scope": "mcp:invoke",
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"keys": "not-a-list"},
            )
        ),
        follow_redirects=False,
    ) as client:
        verifier = InternalJWTVerifier(
            service_id="graphpep-mcp",
            issuer="https://api.xdenovoai.com/",
            audience="urn:xdenovo:mcp-service:graphpep-mcp",
            jwks_url="http://gateway.internal/jwks",
            http_client=client,
            clock=lambda: now,
        )
        with capture_logs() as logs:
            access_token = await verifier.verify_token(token)

    assert access_token is None
    assert any(
        event.get("event") == "jwks_fetch_failed"
        and event.get("reason") == "invalid_shape"
        for event in logs
    )
