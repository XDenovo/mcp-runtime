"""Authenticated in-process Streamable HTTP contract-test client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    contextmanager,
)
from contextvars import ContextVar
from threading import RLock
from typing import Any

import anyio
import httpx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from mcp_runtime.testing._asgi import _StreamingASGITransport

_create_memory_object_stream = anyio.create_memory_object_stream
_receive_streams: ContextVar[list[Any] | None] = ContextVar(
    "mcp_runtime_testing_receive_streams",
    default=None,
)
_patch_lock = RLock()
_patch_users = 0


class _TrackedMemoryStreamFactory:
    def __getitem__(self, item: Any) -> _TrackedMemoryStreamFactory:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        send_stream, receive_stream = _create_memory_object_stream(*args, **kwargs)
        receive_streams = _receive_streams.get()
        if receive_streams is not None:
            receive_streams.append(receive_stream)
        return send_stream, receive_stream


_tracked_memory_stream_factory = _TrackedMemoryStreamFactory()


@contextmanager
def _track_memory_streams(receive_streams: list[Any]) -> Iterator[None]:
    global _patch_users

    token = _receive_streams.set(receive_streams)
    with _patch_lock:
        if _patch_users == 0:
            anyio.create_memory_object_stream = (  # ty: ignore[invalid-assignment]
                _tracked_memory_stream_factory
            )
        _patch_users += 1

    try:
        yield
    finally:
        _receive_streams.reset(token)
        with _patch_lock:
            _patch_users -= 1
            if _patch_users == 0:
                anyio.create_memory_object_stream = _create_memory_object_stream


@asynccontextmanager
async def _streamable_http_app(
    server: FastMCP[Any],
) -> AsyncIterator[Any]:
    app = server.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=False,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
    )
    receive_streams: list[Any] = []

    try:
        with _track_memory_streams(receive_streams):
            async with app.router.lifespan_context(app):
                yield app
    finally:
        for receive_stream in receive_streams:
            await receive_stream.aclose()


@asynccontextmanager
async def _streamable_http_client_for_app(
    app: Any,
    *,
    credential: str | None = None,
    authorization_header: str | None = None,
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    if credential is not None and authorization_header is not None:
        raise ValueError("configure either credential or authorization_header")

    def client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        **kwargs: Any,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=_StreamingASGITransport(app),
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
        auth=credential,
        httpx_client_factory=client_factory,
    )
    async with Client(transport) as client:
        yield client


@asynccontextmanager
async def streamable_http_client(
    server: FastMCP[Any],
    *,
    credential: str | None = None,
) -> AsyncIterator[Client[StreamableHttpTransport]]:
    """Connect through real Bearer middleware and stateful HTTP in-process."""
    async with (
        _streamable_http_app(server) as app,
        _streamable_http_client_for_app(app, credential=credential) as client,
    ):
        yield client


def _leaf_exceptions(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in _leaf_exceptions(child)]
    return [error]


async def assert_authentication_rejected(
    client_context: AbstractAsyncContextManager[object],
) -> None:
    """Assert that opening a test client is rejected with HTTP 401."""
    message = "expected authentication rejection with HTTP 401"
    try:
        async with client_context:
            pass
    except BaseException as error:
        leaves = _leaf_exceptions(error)
        if any(not isinstance(leaf, Exception) for leaf in leaves):
            raise
        if len(leaves) == 1:
            status_error = leaves[0]
            if (
                isinstance(status_error, httpx.HTTPStatusError)
                and status_error.response.status_code == 401
            ):
                return
    raise AssertionError(message)
