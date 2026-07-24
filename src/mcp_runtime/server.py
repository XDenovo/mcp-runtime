"""Assembly and process adapters for the private FastMCP server."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
from fastmcp import FastMCP

from mcp_runtime.auth.verifier import InternalJWTVerifier
from mcp_runtime.settings import RuntimeSettings

ServiceLifespan = Callable[
    [FastMCP[Any]],
    AbstractAsyncContextManager[Any],
]

_JWKS_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=10.0,
    write=10.0,
    pool=5.0,
)


def create_server(
    settings: RuntimeSettings,
    *,
    lifespan: ServiceLifespan | None = None,
    jwks_transport: httpx.AsyncBaseTransport | None = None,
) -> FastMCP[Any]:
    """Build a native FastMCP server with fixed internal-auth policy."""
    verifier = InternalJWTVerifier(
        service_id=settings.service_id,
        issuer=settings.auth.issuer,
        audience=settings.audience,
        jwks_url=settings.auth.jwks_url,
        http_client=None,
        clock=time.time,
    )

    @asynccontextmanager
    async def runtime_lifespan(
        server: FastMCP[Any],
    ) -> AsyncIterator[Any]:
        async with httpx.AsyncClient(
            transport=jwks_transport,
            timeout=_JWKS_TIMEOUT,
            follow_redirects=False,
        ) as jwks_client:
            verifier.bind_http_client(jwks_client)
            try:
                if lifespan is None:
                    yield {}
                else:
                    async with lifespan(server) as service_context:
                        yield service_context if service_context is not None else {}
            finally:
                verifier.unbind_http_client(jwks_client)

    return FastMCP(
        settings.service_id,
        auth=verifier,
        lifespan=runtime_lifespan,
        mask_error_details=True,
        strict_input_validation=True,
        tasks=False,
    )


def run_server(server: FastMCP[Any], settings: RuntimeSettings) -> None:
    """Run the server with the fixed private Streamable HTTP policy."""
    if not isinstance(server.auth, InternalJWTVerifier):
        raise ValueError("run_server() requires a server returned by create_server()")
    if (
        server.name != settings.service_id
        or server.auth.issuer != settings.auth.issuer
        or server.auth.audience != settings.audience
        or server.auth.jwks_uri != settings.auth.jwks_url
    ):
        raise ValueError("run_server() requires settings for the same service")

    allowed_hosts = (
        list(settings.server.allowed_hosts)
        if settings.server.allowed_hosts is not None
        else [settings.server.host]
    )
    server.run(
        "streamable-http",
        host=settings.server.host,
        port=settings.server.port,
        path="/mcp",
        stateless_http=False,
        json_response=False,
        host_origin_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=None,
    )
