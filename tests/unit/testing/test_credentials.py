from __future__ import annotations

import time

import httpx
import jwt
import pytest

from mcp_runtime import InternalAuthSettings, RuntimeSettings
from mcp_runtime.testing import InternalCredentialFactory


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        service_id="graphpep-mcp",
        auth=InternalAuthSettings(
            issuer="https://api.xdenovoai.com/",
            jwks_url="http://gateway.internal/jwks",
        ),
    )


async def test_factory_issues_canonical_credential_for_runtime_settings() -> None:
    before = int(time.time())
    settings = _settings()
    factory = InternalCredentialFactory(settings)

    credential = factory.issue(
        subject="user_01J2ABCDEF",
        scopes=("example:read",),
    )

    async with httpx.AsyncClient(transport=factory.jwks_transport) as client:
        response = await client.get(settings.auth.jwks_url)
    response.raise_for_status()
    jwk = response.json()["keys"][0]
    header = jwt.get_unverified_header(credential)
    claims = jwt.decode(
        credential,
        jwt.PyJWK.from_dict(jwk).key,
        algorithms=["RS256"],
        audience=settings.audience,
        issuer=settings.auth.issuer,
    )

    assert header == {
        "alg": "RS256",
        "kid": jwk["kid"],
        "typ": "JWT",
    }
    assert jwk.keys() == {"alg", "e", "kid", "kty", "n", "use"}
    assert claims["iss"] == settings.auth.issuer
    assert claims["aud"] == settings.audience
    assert claims["sub"] == "user_01J2ABCDEF"
    assert claims["scope"] == "mcp:invoke example:read"
    assert type(claims["iat"]) is int
    assert type(claims["exp"]) is int
    assert before <= claims["iat"] <= int(time.time())
    assert claims["exp"] - claims["iat"] == 300


async def test_target_service_override_changes_only_the_audience() -> None:
    settings = _settings()
    factory = InternalCredentialFactory(settings)

    credential = factory.issue(
        subject="user_01J2ABCDEF",
        scopes=("example:read",),
        target_service_id="pepmimic-mcp",
    )

    async with httpx.AsyncClient(transport=factory.jwks_transport) as client:
        jwk = (await client.get(settings.auth.jwks_url)).json()["keys"][0]
    claims = jwt.decode(
        credential,
        jwt.PyJWK.from_dict(jwk).key,
        algorithms=["RS256"],
        audience="urn:xdenovo:mcp-service:pepmimic-mcp",
        issuer=settings.auth.issuer,
    )

    assert claims["aud"] == "urn:xdenovo:mcp-service:pepmimic-mcp"
    assert claims["sub"] == "user_01J2ABCDEF"
    assert claims["scope"] == "mcp:invoke example:read"
    assert claims["exp"] - claims["iat"] == 300


async def test_factories_do_not_share_signing_identity_or_public_key() -> None:
    settings = _settings()
    first = InternalCredentialFactory(settings)
    second = InternalCredentialFactory(settings)

    async with (
        httpx.AsyncClient(transport=first.jwks_transport) as first_client,
        httpx.AsyncClient(transport=second.jwks_transport) as second_client,
    ):
        first_jwk = (await first_client.get(settings.auth.jwks_url)).json()["keys"][0]
        second_jwk = (await second_client.get(settings.auth.jwks_url)).json()["keys"][0]

    credential = first.issue(subject="principal-a")

    assert first_jwk["kid"] != second_jwk["kid"]
    assert first_jwk["n"] != second_jwk["n"]
    assert not hasattr(first, "private_key")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            credential,
            jwt.PyJWK.from_dict(second_jwk).key,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.auth.issuer,
        )


@pytest.mark.parametrize("subject", ["", "   "])
def test_factory_rejects_empty_subject(subject: str) -> None:
    factory = InternalCredentialFactory(_settings())

    with pytest.raises(ValueError, match="subject"):
        factory.issue(subject=subject)


@pytest.mark.parametrize(
    "scopes",
    [
        "",
        ("",),
        ("   ",),
        ("example:read extra",),
        ("example:read", "example:read"),
        ("mcp:invoke",),
    ],
)
def test_factory_rejects_invalid_or_duplicate_caller_scopes(
    scopes: object,
) -> None:
    factory = InternalCredentialFactory(_settings())

    with pytest.raises(ValueError, match="scope"):
        factory.issue(
            subject="user_01J2ABCDEF",
            scopes=scopes,  # ty: ignore[invalid-argument-type]
        )


@pytest.mark.parametrize(
    "service_id",
    ["", "GraphPep", "graphpep_mcp", "-graphpep", "graphpep-", "a" * 64],
)
def test_factory_rejects_invalid_target_service_id(service_id: str) -> None:
    factory = InternalCredentialFactory(_settings())

    with pytest.raises(ValueError, match="target_service_id"):
        factory.issue(
            subject="user_01J2ABCDEF",
            target_service_id=service_id,
        )
