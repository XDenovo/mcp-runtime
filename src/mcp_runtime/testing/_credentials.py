"""Narrow internal-credential factory for downstream contract tests."""

from __future__ import annotations

import base64
import re
import secrets
import time
from collections.abc import Iterable

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from mcp_runtime.settings import RuntimeSettings

_SERVICE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _base64url_uint(value: int) -> str:
    size = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()


class InternalCredentialFactory:
    """Create isolated canonical Gateway credentials for one Runtime config."""

    __slots__ = ("__private_key", "_jwk", "_settings", "_transport")

    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self.__private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        kid = f"test-{secrets.token_urlsafe(18)}"
        numbers = self.__private_key.public_key().public_numbers()
        self._jwk = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": kid,
            "n": _base64url_uint(numbers.n),
            "e": _base64url_uint(numbers.e),
        }
        self._transport = httpx.MockTransport(self._serve_jwks)

    @property
    def jwks_transport(self) -> httpx.AsyncBaseTransport:
        """Return the in-memory JWKS transport accepted by ``create_server``."""
        return self._transport

    def issue(
        self,
        *,
        subject: str,
        scopes: Iterable[str] = (),
        target_service_id: str | None = None,
    ) -> str:
        """Issue a canonical credential for this factory's Runtime settings."""
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("subject must be a non-empty string")
        if isinstance(scopes, str):
            raise ValueError("scopes must be an iterable of scope values")
        caller_scopes = tuple(scopes)
        if any(
            not isinstance(scope, str)
            or not scope
            or any(character.isspace() for character in scope)
            for scope in caller_scopes
        ):
            raise ValueError("scope values must be non-empty and contain no whitespace")
        if (
            len(caller_scopes) != len(set(caller_scopes))
            or "mcp:invoke" in caller_scopes
        ):
            raise ValueError("caller scope values must not contain duplicates")
        if (
            target_service_id is not None
            and _SERVICE_ID.fullmatch(target_service_id) is None
        ):
            raise ValueError("target_service_id must be a lowercase DNS label")

        now = int(time.time())
        audience = (
            self._settings.audience
            if target_service_id is None
            else f"urn:xdenovo:mcp-service:{target_service_id}"
        )
        return jwt.encode(
            {
                "iss": self._settings.auth.issuer,
                "aud": audience,
                "sub": subject,
                "iat": now,
                "exp": now + 300,
                "scope": " ".join(("mcp:invoke", *caller_scopes)),
            },
            self.__private_key,
            algorithm="RS256",
            headers={"kid": self._jwk["kid"]},
        )

    def _serve_jwks(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [self._jwk]})
