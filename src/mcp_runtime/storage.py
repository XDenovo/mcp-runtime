from __future__ import annotations

from typing import BinaryIO

from mcp_runtime.config import RuntimeConfig


class ArtifactStore:
    """S3-compatible object storage client scoped to a single service namespace.

    Every ``key`` passed to these methods is a path relative to
    ``namespace``; the implementation must prefix every request with
    ``f"{namespace}/"`` so a service can never read or write another
    service's Artifacts through this client (architecture.md section 4.6 --
    "a path prefix alone, without an access policy, is not isolation").
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        namespace: str,
    ) -> None:
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> ArtifactStore:
        raise NotImplementedError

    def put(self, key: str, data: BinaryIO, *, content_type: str | None = None) -> str:
        raise NotImplementedError

    def get(self, key: str) -> BinaryIO:
        raise NotImplementedError

    def presign_get(self, key: str, *, expires_in: int = 3600) -> str:
        raise NotImplementedError

    def presign_put(self, key: str, *, expires_in: int = 3600) -> str:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError
