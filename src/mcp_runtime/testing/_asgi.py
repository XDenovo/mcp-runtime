"""Private full-duplex transport for exercising an ASGI app in-process.

Adapted from ``tests/interaction/transports/_bridge.py`` in the MCP Python SDK:

MIT License

Copyright (c) 2024 Anthropic, PBC

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Any, Self

import anyio
import anyio.abc
import httpx
from anyio.streams.memory import MemoryObjectReceiveStream

type _Message = dict[str, Any]
type _Receive = Callable[[], Awaitable[_Message]]
type _Send = Callable[[_Message], Awaitable[None]]
type _ASGIApp = Callable[[dict[str, Any], _Receive, _Send], Awaitable[None]]


class _StreamingResponseBody(httpx.AsyncByteStream):
    def __init__(
        self,
        chunks: MemoryObjectReceiveStream[bytes],
        client_disconnected: anyio.Event,
    ) -> None:
        self._chunks = chunks
        self._client_disconnected = client_disconnected

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self._client_disconnected.set()
        await self._chunks.aclose()


class _StreamingASGITransport(httpx.AsyncBaseTransport):
    """Drive a streaming ASGI application without sockets or global patches."""

    _task_group: anyio.abc.TaskGroup

    def __init__(self, app: _ASGIApp) -> None:
        self._app = app

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        self._task_group.cancel_scope.cancel()
        await self._task_group.__aexit__(exc_type, exc_value, traceback)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.AsyncByteStream):
            raise TypeError(
                "streaming ASGI transport requires an asynchronous request body"
            )
        request_body = b"".join([chunk async for chunk in request.stream])
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?", maxsplit=1)[0],
            "query_string": request.url.query,
            "root_path": "",
            "headers": [(name.lower(), value) for name, value in request.headers.raw],
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 1234),
        }

        request_delivered = False
        response_started = False
        client_disconnected = anyio.Event()
        response_available = anyio.Event()
        response_status = 0
        response_headers: list[tuple[bytes, bytes]] = []
        application_error: Exception | None = None
        chunk_writer, chunk_reader = anyio.create_memory_object_stream[bytes](math.inf)

        async def receive_request() -> _Message:
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {
                    "type": "http.request",
                    "body": request_body,
                    "more_body": False,
                }
            await client_disconnected.wait()
            return {"type": "http.disconnect"}

        async def send_response(message: _Message) -> None:
            nonlocal response_headers, response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
                response_available.set()
                return
            if message["type"] != "http.response.body":
                raise RuntimeError(f"unexpected ASGI message type: {message['type']}")
            body: bytes = message.get("body", b"")
            if body:
                await chunk_writer.send(body)
            if not message.get("more_body", False):
                await chunk_writer.aclose()

        async def run_application() -> None:
            nonlocal application_error
            try:
                await self._app(scope, receive_request, send_response)
            except Exception as error:
                application_error = error
            finally:
                response_available.set()
                await chunk_writer.aclose()

        self._task_group.start_soon(run_application)
        try:
            await response_available.wait()
            if application_error is not None and not response_started:
                raise application_error
        except BaseException:
            client_disconnected.set()
            await chunk_reader.aclose()
            raise

        return httpx.Response(
            status_code=response_status,
            headers=response_headers,
            stream=_StreamingResponseBody(chunk_reader, client_disconnected),
            request=request,
        )
