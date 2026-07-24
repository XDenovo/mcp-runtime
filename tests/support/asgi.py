from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import anyio
import httpx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp.client.streamable_http import StreamableHTTPTransport

_create_memory_object_stream = anyio.create_memory_object_stream


class _TrackedMemoryStreamFactory:
    def __init__(self, receive_streams: list[Any]) -> None:
        self._receive_streams = receive_streams

    def __getitem__(self, item: Any) -> _TrackedMemoryStreamFactory:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        send_stream, receive_stream = _create_memory_object_stream(*args, **kwargs)
        self._receive_streams.append(receive_stream)
        return send_stream, receive_stream


@asynccontextmanager
async def _closing_streamable_http_client(
    url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    terminate_on_close: bool = True,
) -> AsyncIterator[tuple[Any, Any, Callable[[], str | None]]]:
    """MCP 1.28.1 client context with both ends of memory streams closed."""
    if http_client is None:
        raise RuntimeError("ASGI test transport requires its configured HTTP client")

    read_writer, read = anyio.create_memory_object_stream[Any](0)
    write, write_reader = anyio.create_memory_object_stream[Any](0)
    transport = StreamableHTTPTransport(url)

    try:
        async with anyio.create_task_group() as task_group:

            def start_get_stream() -> None:
                task_group.start_soon(
                    transport.handle_get_stream,
                    http_client,
                    read_writer,
                )

            task_group.start_soon(
                transport.post_writer,
                http_client,
                write_reader,
                read_writer,
                write,
                start_get_stream,
                task_group,
            )
            try:
                yield read, write, transport.get_session_id
            finally:
                if transport.session_id and terminate_on_close:
                    await transport.terminate_session(http_client)
                task_group.cancel_scope.cancel()
    finally:
        await read_writer.aclose()
        await read.aclose()
        await write.aclose()
        await write_reader.aclose()


@asynccontextmanager
async def streamable_http_app(
    server: FastMCP,
) -> AsyncIterator[Any]:
    """Run a real stateful Streamable HTTP ASGI application for tests."""
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
    )
    receive_streams: list[Any] = []

    try:
        with (
            patch.object(
                anyio,
                "create_memory_object_stream",
                _TrackedMemoryStreamFactory(receive_streams),
            ),
            patch.object(
                StreamableHTTPTransport,
                "_is_initialized_notification",
                return_value=False,
            ),
            patch(
                "fastmcp.client.transports.http.streamable_http_client",
                _closing_streamable_http_client,
            ),
        ):
            async with app.router.lifespan_context(app):
                # ASGITransport cannot support the never-ending standalone GET
                # stream used for server notifications. Authentication assertions
                # exercise the same stateful POST/session path without that GET.
                yield app
    finally:
        # MCP SDK 1.28.1 leaves an internal receive-end open after stateful
        # ASGITransport tests. Close every test-created receive end explicitly.
        for receive_stream in receive_streams:
            await receive_stream.aclose()


@asynccontextmanager
async def streamable_http_client_for_app(
    app: Any,
    *,
    token: str | None = None,
    authorization_header: str | None = None,
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    """Connect a real FastMCP HTTP client to an active test ASGI app."""

    def client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        **kwargs: Any,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=bool(kwargs.get("follow_redirects", True)),
        )

    headers = (
        {"Authorization": authorization_header}
        if authorization_header is not None
        else None
    )
    transport = StreamableHttpTransport(
        "http://testserver/mcp",
        headers=headers,
        auth=token,
        httpx_client_factory=client_factory,
    )
    async with Client(transport) as client:
        yield client


@asynccontextmanager
async def streamable_http_client(
    server: FastMCP,
    *,
    token: str | None = None,
    authorization_header: str | None = None,
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    """Exercise the real HTTP auth middleware without opening a network port."""
    async with (
        streamable_http_app(server) as app,
        streamable_http_client_for_app(
            app,
            token=token,
            authorization_header=authorization_header,
        ) as client,
    ):
        yield client
