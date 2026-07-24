from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.client.transports import http as fastmcp_http
from mcp.client.streamable_http import StreamableHTTPTransport

from mcp_runtime import (
    InternalAuthSettings,
    RuntimeSettings,
    create_server,
    get_principal,
)
from mcp_runtime.testing import (
    InternalCredentialFactory,
    assert_authentication_rejected,
    streamable_http_client,
)


class TrackingTransport(httpx.AsyncBaseTransport):
    def __init__(self, wrapped: httpx.AsyncBaseTransport) -> None:
        self._wrapped = wrapped
        self.close_count = 0

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        return await self._wrapped.handle_async_request(request)

    async def aclose(self) -> None:
        self.close_count += 1
        await self._wrapped.aclose()


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        service_id="graphpep-mcp",
        auth=InternalAuthSettings(
            issuer="https://api.xdenovoai.com/",
            jwks_url="http://gateway.internal/jwks",
        ),
    )


async def test_public_client_lists_and_calls_tools_through_real_auth_http() -> None:
    settings = _settings()
    credentials = InternalCredentialFactory(settings)
    server = create_server(
        settings,
        jwks_transport=credentials.jwks_transport,
    )

    @server.tool
    async def whoami() -> str:
        return get_principal().subject

    credential = credentials.issue(subject="user_01J2ABCDEF")
    async with streamable_http_client(
        server,
        credential=credential,
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool("whoami")

    assert [tool.name for tool in tools] == ["whoami"]
    assert result.data == "user_01J2ABCDEF"


@pytest.mark.parametrize("credential_kind", ["missing", "other-service"])
async def test_public_assertion_stabilizes_authentication_rejection(
    credential_kind: str,
) -> None:
    settings = _settings()
    credentials = InternalCredentialFactory(settings)
    server = create_server(
        settings,
        jwks_transport=credentials.jwks_transport,
    )
    tool_calls = 0

    @server.tool
    async def protected() -> str:
        nonlocal tool_calls
        tool_calls += 1
        return "unexpected"

    credential = (
        None
        if credential_kind == "missing"
        else credentials.issue(
            subject="sensitive-subject",
            target_service_id="other-mcp",
        )
    )

    await assert_authentication_rejected(
        streamable_http_client(server, credential=credential)
    )

    assert tool_calls == 0


async def test_concurrent_public_clients_restore_compatibility_patches() -> None:
    original_create_stream = anyio.create_memory_object_stream
    original_initialized_check = StreamableHTTPTransport._is_initialized_notification
    original_client_context = fastmcp_http.streamable_http_client
    first_entered = anyio.Event()
    second_entered = anyio.Event()
    release_first = anyio.Event()
    first_exited = anyio.Event()
    release_second = anyio.Event()

    def service(subject: str) -> tuple[FastMCP[Any], str]:
        settings = _settings()
        credentials = InternalCredentialFactory(settings)
        server = create_server(
            settings,
            jwks_transport=credentials.jwks_transport,
        )

        @server.tool(name="identity")
        async def identity() -> str:
            return get_principal().subject

        return server, credentials.issue(subject=subject)

    first_server, first_credential = service("principal-a")
    second_server, second_credential = service("principal-b")

    async def use_first() -> str:
        async with streamable_http_client(
            first_server,
            credential=first_credential,
        ) as client:
            result = await client.call_tool("identity")
            first_entered.set()
            await release_first.wait()
        first_exited.set()
        return result.data

    async def use_second() -> str:
        await first_entered.wait()
        async with streamable_http_client(
            second_server,
            credential=second_credential,
        ) as client:
            result = await client.call_tool("identity")
            second_entered.set()
            await release_second.wait()
        return result.data

    try:
        tasks = asyncio.gather(use_first(), use_second())
        await second_entered.wait()
        release_first.set()
        await first_exited.wait()
        release_second.set()
        results = await tasks
        patches_restored = (
            anyio.create_memory_object_stream is original_create_stream
            and StreamableHTTPTransport._is_initialized_notification
            is original_initialized_check
            and fastmcp_http.streamable_http_client is original_client_context
        )
    finally:
        anyio.create_memory_object_stream = original_create_stream
        StreamableHTTPTransport._is_initialized_notification = (
            original_initialized_check
        )
        fastmcp_http.streamable_http_client = original_client_context

    assert results == ["principal-a", "principal-b"]
    assert patches_restored


async def test_public_client_reenters_server_lifespan_without_leaking() -> None:
    settings = _settings()
    credentials = InternalCredentialFactory(settings)
    transport = TrackingTransport(credentials.jwks_transport)
    server = create_server(settings, jwks_transport=transport)

    for _ in range(2):
        async with streamable_http_client(
            server,
            credential=credentials.issue(subject="principal"),
        ) as client:
            assert await client.list_tools() == []

    assert transport.close_count == 2


async def test_public_client_cleans_up_after_cancellation() -> None:
    original_create_stream = anyio.create_memory_object_stream
    original_initialized_check = StreamableHTTPTransport._is_initialized_notification
    original_client_context = fastmcp_http.streamable_http_client
    settings = _settings()
    credentials = InternalCredentialFactory(settings)
    transport = TrackingTransport(credentials.jwks_transport)
    server = create_server(settings, jwks_transport=transport)
    entered = anyio.Event()

    async def run_client() -> None:
        async with streamable_http_client(
            server,
            credential=credentials.issue(subject="principal"),
        ):
            entered.set()
            await anyio.sleep_forever()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_client)
        await entered.wait()
        task_group.cancel_scope.cancel()

    assert transport.close_count == 1
    assert anyio.create_memory_object_stream is original_create_stream
    assert (
        StreamableHTTPTransport._is_initialized_notification
        is original_initialized_check
    )
    assert fastmcp_http.streamable_http_client is original_client_context


async def test_public_client_cleans_up_after_server_startup_failure() -> None:
    original_create_stream = anyio.create_memory_object_stream
    original_initialized_check = StreamableHTTPTransport._is_initialized_notification
    original_client_context = fastmcp_http.streamable_http_client
    settings = _settings()
    credentials = InternalCredentialFactory(settings)
    transport = TrackingTransport(credentials.jwks_transport)

    @asynccontextmanager
    async def failing_lifespan(
        server: FastMCP[Any],
    ) -> AsyncIterator[dict[str, object]]:
        raise RuntimeError("service startup failed")
        yield {}

    server = create_server(
        settings,
        lifespan=failing_lifespan,
        jwks_transport=transport,
    )

    with pytest.raises(RuntimeError, match="service startup failed"):
        async with streamable_http_client(
            server,
            credential=credentials.issue(subject="principal"),
        ):
            pass

    assert transport.close_count == 1
    assert anyio.create_memory_object_stream is original_create_stream
    assert (
        StreamableHTTPTransport._is_initialized_notification
        is original_initialized_check
    )
    assert fastmcp_http.streamable_http_client is original_client_context
