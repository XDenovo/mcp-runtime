from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from temporalio.client import WorkflowHandle
from temporalio.worker import Worker

from mcp_runtime.config import RuntimeConfig


class WorkflowClient:
    """Temporal client bound to a single service's Namespace and Task Queue.

    Every method that submits or targets work defaults to this service's own
    task queue -- there is no parameter that can address another service's
    Temporal Namespace or Task Queue through this API.
    """

    def __init__(self, address: str, namespace: str, task_queue: str) -> None:
        raise NotImplementedError

    @classmethod
    async def connect(cls, config: RuntimeConfig) -> WorkflowClient:
        """Connect using ``config.temporal_address`` / ``_namespace`` / ``_task_queue``."""
        raise NotImplementedError

    async def start(
        self,
        workflow: type | str,
        *args: Any,
        workflow_id: str,
        task_queue: str | None = None,
    ) -> WorkflowHandle:
        """Idempotently start ``workflow`` with id ``workflow_id``.

        Repeated calls with the same ``workflow_id`` must not start a second
        execution -- see architecture.md section 6.2 on idempotent Workflow
        submission. ``task_queue`` defaults to this service's own queue.
        """
        raise NotImplementedError

    async def result(self, workflow_id: str) -> Any:
        raise NotImplementedError

    async def cancel(self, workflow_id: str) -> None:
        raise NotImplementedError


def build_worker(
    client: WorkflowClient,
    *,
    workflows: Sequence[type],
    activities: Sequence[Callable[..., Any]],
) -> Worker:
    """Construct a Temporal Worker bound to this service's namespace/task queue.

    Used by the service's separate Worker process entrypoint, not the MCP
    Server process -- MCP Server processes submit workflows, they do not
    execute Activities in-process (architecture.md section 4.3).
    """
    raise NotImplementedError
