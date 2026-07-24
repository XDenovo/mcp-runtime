from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mcp_runtime import InternalAuthSettings, RuntimeSettings, ServerSettings


def test_explicit_settings_derive_service_audience() -> None:
    settings = RuntimeSettings(
        service_id="graphpep-mcp",
        server=ServerSettings(),
        auth=InternalAuthSettings(
            issuer="https://api.xdenovoai.com/",
            jwks_url="http://gateway.internal/.well-known/jwks.json",
        ),
    )

    assert settings.service_id == "graphpep-mcp"
    assert settings.audience == "urn:xdenovo:mcp-service:graphpep-mcp"
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 8000


@pytest.mark.parametrize(
    "service_id",
    [
        "",
        "GraphPep",
        "graphpep_mcp",
        "-graphpep",
        "graphpep-",
        "a" * 64,
    ],
)
def test_service_id_rejects_values_outside_lowercase_dns_label(
    service_id: str,
) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(
            service_id=service_id,
            auth={
                "issuer": "https://api.xdenovoai.com/",
                "jwks_url": "https://gateway.internal/jwks",
            },
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer", "http://api.xdenovoai.com/"),
        ("issuer", "/relative/issuer"),
        ("issuer", " https://api.xdenovoai.com/"),
        ("issuer", "https://api.xdenovoai.com:invalid/"),
        ("issuer", "https://user@api.xdenovoai.com/"),
        ("issuer", "https://api.xdenovoai.com/#fragment"),
        ("jwks_url", "ftp://gateway.internal/jwks"),
        ("jwks_url", "gateway.internal/jwks"),
        ("jwks_url", "https://user@gateway.internal/jwks"),
        ("jwks_url", "https://gateway.internal/jwks#fragment"),
    ],
)
def test_auth_urls_reject_untrusted_shapes(field: str, value: str) -> None:
    values = {
        "issuer": "https://api.xdenovoai.com/",
        "jwks_url": "http://gateway.internal/jwks",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        InternalAuthSettings(**values)


@pytest.mark.parametrize(
    "server",
    [
        {"port": 0},
        {"port": 65536},
        {"port": True},
        {"host": " 127.0.0.1 "},
        {"host": "0.0.0.0"},
        {"host": "0.0.0.0", "allowed_hosts": []},
        {"host": "0.0.0.0", "allowed_hosts": ["*"]},
        {"host": "0.0.0.0", "allowed_hosts": ["*.internal"]},
        {"host": "0.0.0.0", "allowed_hosts": ["gateway.internal\n"]},
    ],
)
def test_server_settings_reject_unsafe_bind_configuration(
    server: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        ServerSettings(**server)


def test_non_loopback_bind_accepts_explicit_hosts() -> None:
    server = ServerSettings(
        host="0.0.0.0",
        allowed_hosts=("graphpep.internal", "gateway.internal"),
    )

    assert server.allowed_hosts == ("graphpep.internal", "gateway.internal")


def test_runtime_settings_load_nested_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_RUNTIME_SERVICE_ID", "graphpep-mcp")
    monkeypatch.setenv("MCP_RUNTIME_SERVER__PORT", "9000")
    monkeypatch.setenv(
        "MCP_RUNTIME_AUTH__ISSUER",
        "https://api.xdenovoai.com/",
    )
    monkeypatch.setenv(
        "MCP_RUNTIME_AUTH__JWKS_URL",
        "http://gateway.internal/jwks",
    )

    settings = RuntimeSettings()

    assert settings.service_id == "graphpep-mcp"
    assert settings.server.port == 9000
    assert settings.auth.jwks_url == "http://gateway.internal/jwks"


def test_explicit_values_override_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_RUNTIME_SERVICE_ID", "environment-mcp")
    monkeypatch.setenv(
        "MCP_RUNTIME_AUTH__ISSUER",
        "https://environment.example/",
    )
    monkeypatch.setenv(
        "MCP_RUNTIME_AUTH__JWKS_URL",
        "https://environment.example/jwks",
    )

    settings = RuntimeSettings(
        service_id="explicit-mcp",
        auth={
            "issuer": "https://explicit.example/",
            "jwks_url": "http://gateway.internal/jwks",
        },
    )

    assert settings.service_id == "explicit-mcp"
    assert settings.auth.issuer == "https://explicit.example/"


@pytest.mark.parametrize(
    "untrusted_option",
    ["audience", "algorithm", "required_scope"],
)
def test_security_policy_cannot_be_configured(
    untrusted_option: str,
) -> None:
    auth: dict[str, object] = {
        "issuer": "https://api.xdenovoai.com/",
        "jwks_url": "http://gateway.internal/jwks",
    }
    values: dict[str, object] = {
        "service_id": "graphpep-mcp",
        "auth": auth,
    }
    if untrusted_option == "audience":
        values[untrusted_option] = "unsafe"
    else:
        auth[untrusted_option] = "unsafe"

    with pytest.raises(ValidationError):
        RuntimeSettings(**values)


def test_dotenv_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MCP_RUNTIME_SERVICE_ID=graphpep-mcp",
                "MCP_RUNTIME_AUTH__ISSUER=https://api.xdenovoai.com/",
                "MCP_RUNTIME_AUTH__JWKS_URL=http://gateway.internal/jwks",
            ]
        )
    )
    monkeypatch.chdir(tmp_path)
    for name in (
        "MCP_RUNTIME_SERVICE_ID",
        "MCP_RUNTIME_AUTH__ISSUER",
        "MCP_RUNTIME_AUTH__JWKS_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        RuntimeSettings()

    settings = RuntimeSettings(_env_file=env_file)  # ty: ignore[unknown-argument]
    assert settings.service_id == "graphpep-mcp"
