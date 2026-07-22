from __future__ import annotations

from dataclasses import dataclass

from fastmcp import FastMCP

from mcp_runtime.auth import InternalTokenVerifier
from mcp_runtime.config import RuntimeConfig


@dataclass
class ServerRuntime:
    """A FastMCP app pre-wired with auth, health checks, and structured logging."""

    app: FastMCP
    config: RuntimeConfig


def create_server(
    config: RuntimeConfig,
    *,
    verifier: InternalTokenVerifier | None = None,
) -> ServerRuntime:
    """Build a FastMCP app bound to Streamable HTTP with auth and logging wired in.

    Services attach their own ``@runtime.app.tool()``-decorated handlers after
    this call returns; ``create_server`` never registers business tools.

    Args:
        config: service-scoped runtime configuration.
        verifier: internal JWT verifier; defaults to one built from ``config``.
    """
    raise NotImplementedError


def run_server(runtime: ServerRuntime) -> None:
    """Blocking entrypoint used by a service's ``python -m <service>``."""
    raise NotImplementedError
