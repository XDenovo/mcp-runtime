from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15


def _base64url_uint(value: int) -> str:
    size = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    @classmethod
    def generate(cls, kid: str = "gateway-current") -> SigningKey:
        return cls(
            kid=kid,
            private_key=rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            ),
        )

    def as_jwk(self) -> dict[str, str]:
        numbers = self.private_key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": _base64url_uint(numbers.n),
            "e": _base64url_uint(numbers.e),
        }

    def issue(
        self,
        claims: dict[str, Any],
        *,
        kid: str | None = None,
        include_kid: bool = True,
    ) -> str:
        headers = {"kid": self.kid if kid is None else kid} if include_kid else None
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers=headers,
        )

    def issue_with_headers(
        self,
        claims: dict[str, Any],
        headers: dict[str, Any],
    ) -> str:
        """Sign a compact JWT with deliberately noncanonical test headers."""
        header = {"alg": "RS256", "typ": "JWT", **headers}

        def encode_part(value: dict[str, Any]) -> bytes:
            serialized = json.dumps(
                value,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            return base64.urlsafe_b64encode(serialized).rstrip(b"=")

        signing_input = b".".join((encode_part(header), encode_part(claims)))
        signature = self.private_key.sign(
            signing_input,
            PKCS1v15(),
            hashes.SHA256(),
        )
        return (
            signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
        ).decode()
