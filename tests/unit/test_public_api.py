from __future__ import annotations

import mcp_runtime


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
