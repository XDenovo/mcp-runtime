"""FastMCP JWT verifier adapter for the Platform internal credential contract."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
import structlog
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.utilities.auth import decode_jwt_header

from mcp_runtime.auth.policy import ClaimPolicy, ClaimValidationError, Clock

_SAFE_KID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_EVENT_LOGGER = structlog.get_logger(__name__)


class InternalJWTVerifier(JWTVerifier):
    """Apply Runtime policy after FastMCP verifies an RS256 JWT."""

    def __init__(
        self,
        *,
        service_id: str,
        issuer: str,
        audience: str,
        jwks_url: str,
        http_client: httpx.AsyncClient | None,
        clock: Clock,
    ) -> None:
        super().__init__(
            jwks_uri=jwks_url,
            issuer=issuer,
            audience=audience,
            algorithm="RS256",
            http_client=http_client,
        )
        self._service_id = service_id
        self._jwks_url = jwks_url
        self._runtime_http_client = http_client
        self._policy = ClaimPolicy(
            issuer=issuer,
            audience=audience,
            clock=clock,
        )

        # FastMCP's verifier messages can interpolate rejected Claims. Runtime
        # emits its own safe structured events instead.
        silent_logger = logging.Logger(
            "mcp_runtime.auth.suppressed_fastmcp_verifier",
            level=logging.CRITICAL + 1,
        )
        silent_logger.disabled = True
        self.logger = silent_logger

    def bind_http_client(self, client: httpx.AsyncClient) -> None:
        """Bind the shared client owned by the active server lifespan."""
        if self._runtime_http_client is not None:
            raise RuntimeError("Runtime JWKS client is already bound")
        self._runtime_http_client = client

    def unbind_http_client(self, client: httpx.AsyncClient) -> None:
        """Remove the client after the owning server lifespan exits."""
        if self._runtime_http_client is not client:
            raise RuntimeError("Runtime JWKS client binding does not match")
        self._runtime_http_client = None

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify the token and return a policy-constrained FastMCP token."""
        try:
            header = decode_jwt_header(token)
        except Exception:
            self._log_rejection(stage="kid", reason="malformed_header")
            return None

        if "kid" not in header:
            self._log_rejection(stage="kid", reason="kid_missing")
            return None
        kid = header["kid"]
        if not isinstance(kid, str):
            self._log_rejection(stage="kid", reason="kid_not_string")
            return None
        if not kid.strip():
            self._log_rejection(stage="kid", reason="kid_empty")
            return None
        safe_kid = kid if _SAFE_KID.fullmatch(kid) else "<redacted>"

        access_token = await super().verify_token(token)
        if access_token is None:
            self._log_rejection(
                stage="verification",
                reason="verification_failed",
                kid=safe_kid,
            )
            return None

        try:
            principal = self._policy.validate(access_token.claims)
        except ClaimValidationError as error:
            self._log_rejection(
                stage="claims",
                reason=error.reason,
                kid=safe_kid,
            )
            return None

        return AccessToken(
            token=access_token.token,
            client_id=principal.subject,
            subject=principal.subject,
            scopes=sorted(principal.scopes),
            expires_at=access_token.expires_at,
            resource=access_token.resource,
            claims=access_token.claims,
        )

    async def _fetch_jwks(self) -> dict[str, Any]:
        """Fetch JWKS at the Runtime-owned HTTP boundary without unsafe logs."""
        client = self._runtime_http_client
        if client is None:
            self._log_jwks_failure(reason="client_unavailable", retryable=True)
            raise ValueError("Runtime JWKS client is unavailable")

        try:
            response = await client.get(self._jwks_url)
        except httpx.TimeoutException:
            self._log_jwks_failure(reason="timeout", retryable=True)
            raise ValueError("Runtime JWKS fetch failed") from None
        except httpx.HTTPError:
            self._log_jwks_failure(reason="network_error", retryable=True)
            raise ValueError("Runtime JWKS fetch failed") from None

        if not response.is_success:
            self._log_jwks_failure(
                reason="http_status",
                retryable=response.status_code == 429 or response.status_code >= 500,
                status_code=response.status_code,
            )
            raise ValueError("Runtime JWKS fetch failed")

        try:
            jwks = response.json()
        except (ValueError, UnicodeDecodeError):
            self._log_jwks_failure(reason="invalid_json", retryable=False)
            raise ValueError("Runtime JWKS response is invalid") from None

        if (
            not isinstance(jwks, dict)
            or not isinstance(jwks.get("keys"), list)
            or not all(isinstance(key, dict) for key in jwks["keys"])
        ):
            self._log_jwks_failure(reason="invalid_shape", retryable=False)
            raise ValueError("Runtime JWKS response is invalid")
        return jwks

    def _log_rejection(
        self,
        *,
        stage: str,
        reason: str,
        kid: str | None = None,
    ) -> None:
        event = {
            "service_id": self._service_id,
            "validation_stage": stage,
            "reason": reason,
            "retryable": False,
        }
        if kid is not None:
            event["kid"] = kid
        _EVENT_LOGGER.warning("internal_auth_failed", **event)

    def _log_jwks_failure(
        self,
        *,
        reason: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        event = {
            "service_id": self._service_id,
            "validation_stage": "jwks",
            "reason": reason,
            "retryable": retryable,
        }
        if status_code is not None:
            event["status_code"] = status_code
        _EVENT_LOGGER.warning("jwks_fetch_failed", **event)
