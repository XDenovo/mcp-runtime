"""Validate a built wheel from an isolated consumer environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

CONSUMER_SOURCE = textwrap.dedent(
    """
    from __future__ import annotations

    import asyncio
    from importlib.resources import files

    from mcp_runtime import InternalAuthSettings, RuntimeSettings, create_server
    from mcp_runtime.testing import InternalCredentialFactory, streamable_http_client

    settings = RuntimeSettings(
        service_id="distribution-smoke",
        auth=InternalAuthSettings(
            issuer="https://api.xdenovoai.com/",
            jwks_url="http://gateway.internal/.well-known/jwks.json",
        ),
    )
    credentials = InternalCredentialFactory(settings)
    server = create_server(
        settings,
        jwks_transport=credentials.jwks_transport,
    )


    @server.tool(name="contract_probe")
    async def contract_probe() -> str:
        return "ok"


    async def verify_installed_contract() -> None:
        credential: str = credentials.issue(
            subject="subject",
            scopes=("example:read",),
        )
        async with streamable_http_client(
            server,
            credential=credential,
        ) as client:
            tool_names: list[str] = [
                tool.name for tool in await client.list_tools()
            ]

        assert tool_names == ["contract_probe"]


    if __name__ == "__main__":
        assert files("mcp_runtime").joinpath("py.typed").is_file()
        asyncio.run(verify_installed_contract())
    """
).lstrip()


def _venv_python(venv_dir: Path) -> Path:
    executable = "python.exe" if sys.platform == "win32" else "bin/python"
    return venv_dir / executable


def _type_checker() -> Path:
    executable = "ty.exe" if sys.platform == "win32" else "ty"
    return Path(sys.executable).with_name(executable)


def _run(*command: str, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _validate_wheel(wheel: Path) -> None:
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise ValueError(f"expected a built wheel, got {wheel}")

    with tempfile.TemporaryDirectory(prefix="mcp-runtime-dist-") as temp_directory:
        consumer_root = Path(temp_directory)
        venv_dir = consumer_root / ".venv"
        python = _venv_python(venv_dir)
        consumer_file = consumer_root / "consumer.py"
        consumer_file.write_text(CONSUMER_SOURCE, encoding="utf-8")
        (consumer_root / "pyproject.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "mcp-runtime-distribution-smoke"
                version = "0.0.0"
                requires-python = ">=3.13"

                [tool.ty.environment]
                python-version = "3.13"
                """
            ).lstrip(),
            encoding="utf-8",
        )

        _run("uv", "venv", "--python", "3.13", str(venv_dir))
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(wheel),
        )
        _run(str(python), "-I", str(consumer_file), cwd=consumer_root)
        _run(
            str(_type_checker()),
            "check",
            "--project",
            str(consumer_root),
            "--python",
            str(venv_dir),
            str(consumer_file),
            cwd=consumer_root,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "wheel",
        type=Path,
        help="Path to the built wheel consumed by downstream services.",
    )
    args = parser.parse_args()
    wheel = args.wheel.resolve()

    _validate_wheel(wheel)
    print(f"validated installed runtime and typed consumer against {wheel.name}")


if __name__ == "__main__":
    main()
