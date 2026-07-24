from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
import pytest
from fastmcp import FastMCP

from mcp_runtime import InternalAuthSettings, RuntimeSettings, create_server
from mcp_runtime.server import run_server


class TrackingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.close_count = 0
        self.requests: list[httpx.Request] = []

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"keys": []})

    async def aclose(self) -> None:
        self.close_count += 1


class YieldingCloseTransport(TrackingTransport):
    async def aclose(self) -> None:
        await anyio.sleep(0)
        self.close_count += 1


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        service_id="graphpep-mcp",
        auth=InternalAuthSettings(
            issuer="https://api.xdenovoai.com/",
            jwks_url="http://gateway.internal/jwks",
        ),
    )


def test_run_server_fixes_private_stateful_http_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    server = create_server(settings)
    calls: list[tuple[str | None, bool | None, dict[str, object]]] = []

    def record_run(
        transport: str | None = None,
        show_banner: bool | None = None,
        **transport_kwargs: object,
    ) -> None:
        calls.append((transport, show_banner, transport_kwargs))

    monkeypatch.setattr(server, "run", record_run)

    run_server(server, settings)

    assert calls == [
        (
            "streamable-http",
            None,
            {
                "host": "127.0.0.1",
                "port": 8000,
                "path": "/mcp",
                "stateless_http": False,
                "json_response": False,
                "host_origin_protection": True,
                "allowed_hosts": ["127.0.0.1"],
                "allowed_origins": None,
            },
        )
    ]


def test_run_server_uses_explicit_non_loopback_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = RuntimeSettings(
        service_id="graphpep-mcp",
        server={
            "host": "0.0.0.0",
            "port": 9000,
            "allowed_hosts": ("graphpep.internal", "graphpep.internal:9000"),
        },
        auth={
            "issuer": "https://api.xdenovoai.com/",
            "jwks_url": "http://gateway.internal/jwks",
        },
    )
    server = create_server(settings)
    captured: dict[str, object] = {}

    def record_run(
        transport: str | None = None,
        show_banner: bool | None = None,
        **transport_kwargs: object,
    ) -> None:
        captured.update(transport_kwargs)

    monkeypatch.setattr(server, "run", record_run)

    run_server(server, settings)

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9000
    assert captured["allowed_hosts"] == [
        "graphpep.internal",
        "graphpep.internal:9000",
    ]


def test_run_server_rejects_server_that_does_not_carry_runtime_auth() -> None:
    settings = _settings()

    with pytest.raises(ValueError, match="create_server"):
        run_server(FastMCP("graphpep-mcp"), settings)


def test_run_server_rejects_settings_for_another_service() -> None:
    settings = _settings()
    server = create_server(settings)
    other_settings = RuntimeSettings(
        service_id="other-mcp",
        auth={
            "issuer": settings.auth.issuer,
            "jwks_url": settings.auth.jwks_url,
        },
    )

    with pytest.raises(ValueError, match="same service"):
        run_server(server, other_settings)


def test_run_server_rejects_mismatched_auth_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    server = create_server(settings)
    mismatched_settings = RuntimeSettings(
        service_id=settings.service_id,
        auth={
            "issuer": "https://different.example/",
            "jwks_url": settings.auth.jwks_url,
        },
    )
    monkeypatch.setattr(
        server,
        "run",
        lambda *args, **kwargs: pytest.fail("mismatched settings must not run"),
    )

    with pytest.raises(ValueError, match="same service"):
        run_server(server, mismatched_settings)


async def test_server_lifespan_is_reentrant_and_jwks_fetch_is_lazy() -> None:
    transport = TrackingTransport()
    server = create_server(_settings(), jwks_transport=transport)
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
    )

    async with app.router.lifespan_context(app):
        pass
    async with app.router.lifespan_context(app):
        pass

    assert transport.requests == []
    assert transport.close_count == 2


async def test_jwks_client_closes_when_service_lifespan_fails() -> None:
    transport = TrackingTransport()

    @asynccontextmanager
    async def failing_lifespan(
        server: FastMCP[Any],
    ) -> AsyncIterator[dict[str, object]]:
        raise RuntimeError("service startup failed")
        yield {}

    server = create_server(
        _settings(),
        lifespan=failing_lifespan,
        jwks_transport=transport,
    )
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
    )

    with pytest.raises(RuntimeError, match="service startup failed"):
        async with app.router.lifespan_context(app):
            pass

    assert transport.close_count == 1


async def test_service_lifespan_is_composed_inside_runtime_resources() -> None:
    transport = TrackingTransport()
    events: list[str] = []

    @asynccontextmanager
    async def service_lifespan(
        server: FastMCP[Any],
    ) -> AsyncIterator[None]:
        events.append(f"enter:{server.name}")
        yield
        events.append("exit")

    server = create_server(
        _settings(),
        lifespan=service_lifespan,
        jwks_transport=transport,
    )
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
    )

    async with app.router.lifespan_context(app):
        assert events == ["enter:graphpep-mcp"]
        assert transport.close_count == 0

    assert events == ["enter:graphpep-mcp", "exit"]
    assert transport.close_count == 1


async def test_jwks_client_cleanup_is_shielded_from_cancellation() -> None:
    transport = YieldingCloseTransport()
    entered = anyio.Event()

    @asynccontextmanager
    async def waiting_lifespan(
        server: FastMCP[Any],
    ) -> AsyncIterator[dict[str, object]]:
        entered.set()
        yield {}

    server = create_server(
        _settings(),
        lifespan=waiting_lifespan,
        jwks_transport=transport,
    )
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
    )

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            await anyio.sleep_forever()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_lifespan)
        await entered.wait()
        task_group.cancel_scope.cancel()

    assert transport.close_count == 1


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({"Host": "unexpected.internal"}, 421),
        (
            {
                "Host": "graphpep.internal",
                "Origin": "https://unexpected.example",
            },
            403,
        ),
    ],
)
async def test_strict_http_guard_rejects_unexpected_host_or_origin(
    headers: dict[str, str],
    expected_status: int,
) -> None:
    server = create_server(_settings())
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["graphpep.internal"],
        allowed_origins=None,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://graphpep.internal",
    ) as client:
        response = await client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )

    assert response.status_code == expected_status
