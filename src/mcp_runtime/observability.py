from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from structlog.contextvars import bound_contextvars, merge_contextvars
from structlog.stdlib import BoundLogger

from mcp_runtime.config import RuntimeConfig

# Shared by structlog's own pipeline and by the ProcessorFormatter's
# foreign_pre_chain, so stdlib-originated records (fastmcp, sqlalchemy,
# temporalio, and boto3 all log via `logging`) get the same level/timestamp
# treatment -- and the same contextvars merge -- as structlog-originated ones.
_SHARED_PROCESSORS: list[Any] = [
    merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def configure_logging(config: RuntimeConfig) -> None:
    """Configure process-wide structured (stdout JSON) logging.

    Every service process (MCP Server or Worker) calls this once at startup.
    Routes both structlog-emitted logs and stdlib ``logging``-emitted logs
    through the same JSON renderer, so container stdout is one consistent
    stream regardless of which library produced a given line -- matching the
    deployment model in architecture.md section 7.1 (containers write to
    stdout/journald; there is no in-process log shipping).
    """
    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(config.log_level)


def get_logger(name: str) -> BoundLogger:
    """Return a structlog bound logger for ``name``.

    Thin wrapper over ``structlog.get_logger`` so services depend on
    mcp_runtime's re-export rather than importing structlog directly.
    """
    return structlog.get_logger(name)


@contextmanager
def bind_context(**kv: Any) -> Iterator[None]:
    """Bind ``kv`` into the structlog context for the duration of this scope.

    Every log line emitted anywhere in the call stack while this context
    manager is active -- structlog or stdlib, e.g. principal subject, job_id
    -- includes these fields, because ``merge_contextvars`` runs as a
    processor on every log call. Thin wrapper over
    ``structlog.contextvars.bound_contextvars``.
    """
    with bound_contextvars(**kv):
        yield
