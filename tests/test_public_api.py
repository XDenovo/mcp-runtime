from __future__ import annotations

import dataclasses

import mcp_runtime


def test_public_api_symbols_are_exported() -> None:
    for name in mcp_runtime.__all__:
        assert hasattr(mcp_runtime, name)


def test_principal_is_a_frozen_dataclass() -> None:
    assert dataclasses.is_dataclass(mcp_runtime.Principal)
    assert dataclasses.fields(mcp_runtime.Principal)


def test_job_status_values() -> None:
    assert {status.value for status in mcp_runtime.JobStatus} == {
        "pending",
        "submitting",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }


def test_submodules_import_cleanly() -> None:
    import mcp_runtime.auth
    import mcp_runtime.config
    import mcp_runtime.jobs
    import mcp_runtime.observability
    import mcp_runtime.server
    import mcp_runtime.storage
    import mcp_runtime.testing
    import mcp_runtime.workflow

    assert mcp_runtime.auth
    assert mcp_runtime.config
    assert mcp_runtime.jobs
    assert mcp_runtime.observability
    assert mcp_runtime.server
    assert mcp_runtime.storage
    assert mcp_runtime.testing
    assert mcp_runtime.workflow
