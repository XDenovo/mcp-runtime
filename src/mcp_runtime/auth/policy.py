"""Strict policy for already verified internal JWT Claims."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from mcp_runtime.auth.principal import Principal

Clock = Callable[[], int | float]


class ClaimValidationError(ValueError):
    """A safely classified rejection from the Runtime Claim Policy."""

    def __init__(self, reason: str) -> None:
        super().__init__("internal credential claims are invalid")
        self.reason = reason


class ClaimPolicy:
    """Validate the canonical Platform Claims wire shape and time rules."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        clock: Clock = time.time,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self._clock = clock

    def validate(self, claims: Mapping[str, Any]) -> Principal:
        """Map verified Claims to the narrow service-facing Principal."""
        issuer = self._required_string(claims, "iss")
        if issuer != self.issuer:
            raise ClaimValidationError("issuer_mismatch")

        audience = self._required_string(claims, "aud")
        if audience != self.audience:
            raise ClaimValidationError("audience_mismatch")

        subject = self._required_string(claims, "sub")
        scope = self._required_string(claims, "scope")
        scopes = scope.split(" ")
        if (
            scope != scope.strip(" ")
            or any(not value for value in scopes)
            or any(any(character.isspace() for character in value) for value in scopes)
        ):
            raise ClaimValidationError("scope_format")
        if len(scopes) != len(set(scopes)):
            raise ClaimValidationError("scope_duplicate")
        if "mcp:invoke" not in scopes:
            raise ClaimValidationError("required_scope_missing")

        issued_at = self._required_numeric_date(claims, "iat")
        expires_at = self._required_numeric_date(claims, "exp")
        lifetime = expires_at - issued_at
        if lifetime <= 0 or lifetime > 300:
            raise ClaimValidationError("invalid_lifetime")

        now = self._clock()
        if issued_at > now + 30:
            raise ClaimValidationError("iat_in_future")
        if expires_at <= now:
            raise ClaimValidationError("expired")

        if "nbf" in claims:
            not_before = self._required_numeric_date(claims, "nbf")
            if not_before >= expires_at:
                raise ClaimValidationError("nbf_not_before_exp")
            if not_before > now + 30:
                raise ClaimValidationError("nbf_in_future")

        return Principal(
            subject=subject,
            scopes=frozenset(scopes),
        )

    @staticmethod
    def _required_string(claims: Mapping[str, Any], name: str) -> str:
        if name not in claims:
            raise ClaimValidationError(f"{name}_missing")
        value = claims[name]
        if not isinstance(value, str):
            raise ClaimValidationError(f"{name}_not_string")
        if not value.strip():
            raise ClaimValidationError(f"{name}_empty")
        return value

    @staticmethod
    def _required_numeric_date(claims: Mapping[str, Any], name: str) -> int:
        if name not in claims:
            raise ClaimValidationError(f"{name}_missing")
        value = claims[name]
        if type(value) is not int:
            raise ClaimValidationError(f"{name}_not_integer")
        return value
