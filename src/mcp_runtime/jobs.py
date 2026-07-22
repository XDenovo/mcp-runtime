from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped

from mcp_runtime.config import RuntimeConfig


class JobStatus(str, Enum):
    """Status vocabulary shared by every service's Job metadata.

    ``SUBMITTING`` is the in-flight state between writing the initial Job row
    and confirming the Workflow has actually started -- see architecture.md
    section 6.2 on reconciling Job writes with Workflow submission.
    """

    PENDING = "pending"
    SUBMITTING = "submitting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobMixin:
    """Declarative mixin for the columns shared by every service's Job table.

    Deliberately NOT a ``DeclarativeBase`` subclass: every direct subclass of
    ``DeclarativeBase`` starts its own independent ORM registry, so a shared
    abstract base would conflict with each service's own ``Base``. Combine
    this mixin with the service's own declarative base instead::

        class Job(JobMixin, Base):
            __tablename__ = "job"
            # ...domain-specific columns...

    Only columns common to every compute service live here; mcp-runtime does
    not provide a generic repository or query layer.
    """

    id: Mapped[str]
    workflow_id: Mapped[str]
    status: Mapped[JobStatus]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ArtifactMixin:
    """Declarative mixin for the columns shared by every service's Artifact table.

    Combine with the service's own declarative base, the same way as
    ``JobMixin``.
    """

    id: Mapped[str]
    job_id: Mapped[str]
    storage_key: Mapped[str]
    created_at: Mapped[datetime]


def generate_job_id(service_name: str) -> str:
    """Generate an id usable as both a Job primary key and a Temporal workflow_id."""
    raise NotImplementedError


async def create_engine_async(config: RuntimeConfig) -> AsyncEngine:
    """Build an async SQLAlchemy engine scoped to ``config.db_schema``.

    Used by the MCP Server process's concurrent request path.
    """
    raise NotImplementedError


def create_engine_sync(config: RuntimeConfig) -> Engine:
    """Build a sync SQLAlchemy engine scoped to ``config.db_schema``.

    Used by the service's Worker process.
    """
    raise NotImplementedError
