from __future__ import annotations

import re
from importlib.metadata import requires

import mcp_runtime
import mcp_runtime.testing


def test_top_level_public_api_is_the_first_slice_contract() -> None:
    expected = {
        "RuntimeSettings",
        "ServerSettings",
        "InternalAuthSettings",
        "Principal",
        "get_principal",
        "create_server",
        "run_server",
    }
    exported: dict[str, object] = {}

    exec("from mcp_runtime import *", {}, exported)

    assert set(mcp_runtime.__all__) == expected
    assert set(exported) == expected


def test_testing_submodule_is_public_without_top_level_re_exports() -> None:
    expected = {
        "InternalCredentialFactory",
        "assert_authentication_rejected",
        "streamable_http_client",
    }
    exported: dict[str, object] = {}

    exec("from mcp_runtime.testing import *", {}, exported)

    assert set(mcp_runtime.testing.__all__) == expected
    assert set(exported) == expected
    assert expected.isdisjoint(mcp_runtime.__all__)


def test_distribution_does_not_declare_mcp_sdk_directly() -> None:
    requirement_names = {
        re.split(r"[\[<>=!~; @]", requirement, maxsplit=1)[0].lower()
        for requirement in requires("mcp-runtime") or ()
    }

    assert "mcp" not in requirement_names
