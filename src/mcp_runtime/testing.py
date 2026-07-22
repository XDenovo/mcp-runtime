from __future__ import annotations

from typing import Any

from mcp_runtime.auth import InternalTokenVerifier, Principal


def fake_principal(**overrides: Any) -> Principal:
    """Build a Principal for use in a service's own test suite, without a real JWT."""
    raise NotImplementedError


class InMemoryVerifier(InternalTokenVerifier):
    """Accepts any token and returns a fixed Principal; never calls the network.

    Intended for a service's own tests -- do not use outside test code.
    """

    def __init__(self, principal: Principal | None = None) -> None:
        raise NotImplementedError

    def verify(self, token: str) -> Principal:
        raise NotImplementedError
