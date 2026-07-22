from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from mcp_runtime.config import RuntimeConfig
from mcp_runtime.observability import bind_context, configure_logging, get_logger


def _make_config(**overrides: Any) -> RuntimeConfig:
    defaults: dict[str, Any] = {
        "service_name": "testsvc",
        "environment": "development",
        "http_port": 8000,
        "gateway_jwks_url": "https://gateway.internal/.well-known/jwks.json",
        "internal_jwt_audience": "testsvc",
        "internal_jwt_issuer": "gateway",
        "postgres_dsn": "postgresql://localhost/test",
        "s3_endpoint_url": "https://minio.internal",
        "s3_access_key": "ak",
        "s3_secret_key": "sk",
        "s3_bucket": "artifacts",
        "temporal_address": "temporal.internal:7233",
        "log_level": "INFO",
    }
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Any:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)


def _last_json_line(output: str) -> dict[str, Any]:
    return json.loads(output.strip().splitlines()[-1])


def test_get_logger_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(_make_config())

    log = get_logger("test_get_logger_emits_json")
    log.info("hello", foo="bar")

    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "hello"
    assert line["foo"] == "bar"
    assert line["level"] == "info"
    assert line["logger"] == "test_get_logger_emits_json"


def test_bind_context_fields_appear_only_inside_scope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(_make_config())

    log = get_logger("test_bind_context_fields_appear_only_inside_scope")
    with bind_context(job_id="job-123"):
        log.info("inside")
    log.info("outside")

    out_lines = capsys.readouterr().out.strip().splitlines()
    inside, outside = (json.loads(line) for line in out_lines)
    assert inside["job_id"] == "job-123"
    assert "job_id" not in outside


def test_stdlib_logging_is_captured_in_the_same_json_format(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(_make_config())

    logging.getLogger("some.third.party.lib").warning("from stdlib")

    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "from stdlib"
    assert line["level"] == "warning"


def test_configure_logging_honors_log_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(_make_config(log_level="WARNING"))

    logging.getLogger("some.third.party.lib").info("should be suppressed")
    logging.getLogger("some.third.party.lib").warning("should appear")

    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "should appear"
