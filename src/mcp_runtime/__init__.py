"""Shared runtime foundation for XDenovo Compute MCP Services."""

from __future__ import annotations

from mcp_runtime.auth import Principal, get_principal
from mcp_runtime.server import create_server, run_server
from mcp_runtime.settings import (
    InternalAuthSettings,
    RuntimeSettings,
    ServerSettings,
)

__all__ = [
    "InternalAuthSettings",
    "Principal",
    "RuntimeSettings",
    "ServerSettings",
    "create_server",
    "get_principal",
    "run_server",
]
