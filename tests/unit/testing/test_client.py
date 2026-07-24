from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest

from mcp_runtime.testing import assert_authentication_rejected


class _ProcessControl(BaseException):
    pass


@asynccontextmanager
async def _accepted_client() -> AsyncIterator[object]:
    yield object()


@asynccontextmanager
async def _unexpected_failure() -> AsyncIterator[object]:
    raise RuntimeError("sensitive-token sensitive-subject")
    yield object()


@asynccontextmanager
async def _nested_unauthorized() -> AsyncIterator[object]:
    request = httpx.Request("POST", "http://testserver/mcp")
    response = httpx.Response(401, request=request)
    status_error = httpx.HTTPStatusError(
        "unsafe response details",
        request=request,
        response=response,
    )
    raise ExceptionGroup("SDK internals", [ExceptionGroup("tasks", [status_error])])
    yield object()


@asynccontextmanager
async def _process_control_failure() -> AsyncIterator[object]:
    raise _ProcessControl
    yield object()


async def test_rejection_assertion_accepts_nested_unauthorized_error() -> None:
    await assert_authentication_rejected(_nested_unauthorized())


async def test_rejection_assertion_preserves_process_control_exceptions() -> None:
    with pytest.raises(_ProcessControl):
        await assert_authentication_rejected(_process_control_failure())


@pytest.mark.parametrize("client_context", [_accepted_client, _unexpected_failure])
async def test_rejection_assertion_uses_stable_sensitive_free_failure(
    client_context: Callable[[], AbstractAsyncContextManager[object]],
) -> None:
    with pytest.raises(AssertionError) as captured:
        await assert_authentication_rejected(client_context())

    assert str(captured.value) == "expected authentication rejection with HTTP 401"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
