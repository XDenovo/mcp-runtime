from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from mcp_runtime import Principal
from mcp_runtime.auth.policy import ClaimPolicy, ClaimValidationError


def _canonical_claims() -> dict[str, object]:
    return {
        "iss": "https://api.xdenovoai.com/",
        "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
        "sub": "user_01J2ABCDEF",
        "iat": 1_784_880_000,
        "exp": 1_784_880_300,
        "scope": "mcp:invoke example:read",
    }


def _policy() -> ClaimPolicy:
    return ClaimPolicy(
        issuer="https://api.xdenovoai.com/",
        audience="urn:xdenovo:mcp-service:graphpep-mcp",
        clock=lambda: 1_784_880_100,
    )


def test_valid_claims_map_only_subject_and_scopes_to_immutable_principal() -> None:
    policy = ClaimPolicy(
        issuer="https://api.xdenovoai.com/",
        audience="urn:xdenovo:mcp-service:graphpep-mcp",
        clock=lambda: 1_784_880_100,
    )

    principal = policy.validate(
        {
            "iss": "https://api.xdenovoai.com/",
            "aud": "urn:xdenovo:mcp-service:graphpep-mcp",
            "sub": "user_01J2ABCDEF",
            "iat": 1_784_880_000,
            "exp": 1_784_880_300,
            "nbf": 1_784_880_000,
            "scope": "mcp:invoke example:read",
            "example_extension": "opaque",
        }
    )

    assert principal == Principal(
        subject="user_01J2ABCDEF",
        scopes=frozenset({"mcp:invoke", "example:read"}),
    )
    assert [field.name for field in fields(principal)] == ["subject", "scopes"]
    with pytest.raises(FrozenInstanceError):
        principal.subject = "another-user"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("iss", None, "iss_not_string"),
        ("iss", "", "iss_empty"),
        ("iss", "   ", "iss_empty"),
        ("iss", "https://other.example/", "issuer_mismatch"),
        ("aud", ["urn:xdenovo:mcp-service:graphpep-mcp"], "aud_not_string"),
        ("aud", "", "aud_empty"),
        ("aud", "urn:xdenovo:mcp-service:other", "audience_mismatch"),
        ("sub", 7, "sub_not_string"),
        ("sub", "", "sub_empty"),
        ("sub", "\t", "sub_empty"),
        ("scope", ["mcp:invoke"], "scope_not_string"),
        ("scope", "", "scope_empty"),
        ("scope", "   ", "scope_empty"),
        ("scope", " mcp:invoke", "scope_format"),
        ("scope", "mcp:invoke ", "scope_format"),
        ("scope", "mcp:invoke  example:read", "scope_format"),
        ("scope", "mcp:invoke\texample:read", "scope_format"),
        ("scope", "mcp:invoke mcp:invoke", "scope_duplicate"),
        ("scope", "example:read", "required_scope_missing"),
    ],
)
def test_claim_policy_rejects_noncanonical_strings_and_scopes(
    field: str,
    value: object,
    reason: str,
) -> None:
    claims = _canonical_claims()
    claims[field] = value

    with pytest.raises(ClaimValidationError) as captured:
        _policy().validate(claims)

    assert captured.value.reason == reason


@pytest.mark.parametrize("field", ["iss", "aud", "sub", "scope", "iat", "exp"])
def test_claim_policy_rejects_missing_required_claim(field: str) -> None:
    claims = _canonical_claims()
    del claims[field]

    with pytest.raises(ClaimValidationError) as captured:
        _policy().validate(claims)

    assert captured.value.reason == f"{field}_missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iat", True),
        ("iat", 1_784_880_000.0),
        ("iat", "1784880000"),
        ("exp", False),
        ("exp", 1_784_880_300.0),
        ("exp", "1784880300"),
        ("nbf", True),
        ("nbf", 1_784_880_000.0),
        ("nbf", "1784880000"),
    ],
)
def test_claim_policy_requires_integer_numeric_dates(
    field: str,
    value: object,
) -> None:
    claims = _canonical_claims()
    claims[field] = value

    with pytest.raises(ClaimValidationError) as captured:
        _policy().validate(claims)

    assert captured.value.reason == f"{field}_not_integer"


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"iat": 1_784_880_100, "exp": 1_784_880_100}, "invalid_lifetime"),
        ({"iat": 1_784_880_101, "exp": 1_784_880_100}, "invalid_lifetime"),
        ({"iat": 1_784_879_999, "exp": 1_784_880_300}, "invalid_lifetime"),
        ({"iat": 1_784_880_131, "exp": 1_784_880_200}, "iat_in_future"),
        ({"exp": 1_784_880_100, "iat": 1_784_880_099}, "expired"),
        ({"nbf": 1_784_880_131, "exp": 1_784_880_200}, "nbf_in_future"),
        ({"nbf": 1_784_880_300}, "nbf_not_before_exp"),
    ],
)
def test_claim_policy_rejects_invalid_time_boundaries(
    updates: dict[str, int],
    reason: str,
) -> None:
    claims = _canonical_claims()
    claims.update(updates)

    with pytest.raises(ClaimValidationError) as captured:
        _policy().validate(claims)

    assert captured.value.reason == reason


@pytest.mark.parametrize(
    "updates",
    [
        {"iat": 1_784_880_130, "exp": 1_784_880_200},
        {"iat": 1_784_880_099, "exp": 1_784_880_101},
        {"nbf": 1_784_880_130, "exp": 1_784_880_200},
        {"iat": 1_784_880_000, "exp": 1_784_880_300},
    ],
)
def test_claim_policy_accepts_exact_time_boundaries(
    updates: dict[str, int],
) -> None:
    claims = _canonical_claims()
    claims.update(updates)

    assert _policy().validate(claims).subject == "user_01J2ABCDEF"
