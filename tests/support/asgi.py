from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from mcp_runtime.testing._client import (
    _streamable_http_app,
    _streamable_http_client_for_app,
)


@asynccontextmanager
async def streamable_http_app(
    server: FastMCP[Any],
) -> AsyncIterator[Any]:
    """Run the Runtime-owned authenticated ASGI test application."""
    async with _streamable_http_app(server) as app:
        yield app


@asynccontextmanager
async def streamable_http_client_for_app(
    app: Any,
    *,
    token: str | None = None,
    authorization_header: str | None = None,
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    """Expose malformed-header control only to Runtime adversarial tests."""
    async with _streamable_http_client_for_app(
        app,
        credential=token,
        authorization_header=authorization_header,
    ) as client:
        yield client


@asynccontextmanager
async def streamable_http_client(
    server: FastMCP[Any],
    *,
    token: str | None = None,
    authorization_header: str | None = None,
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    """Exercise the shared HTTP mechanics with private adversarial controls."""
    async with (
        streamable_http_app(server) as app,
        streamable_http_client_for_app(
            app,
            token=token,
            authorization_header=authorization_header,
        ) as client,
    ):
        yield client
