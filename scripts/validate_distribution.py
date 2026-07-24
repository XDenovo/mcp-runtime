"""Validate built distributions from an isolated consumer environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import zipfile
from pathlib import Path

PACKAGE_NAME = "mcp-runtime"
PACKAGE_PATH = "mcp_runtime"


def _single_artifact(dist_dir: Path, pattern: str, artifact_type: str) -> Path:
    artifacts = sorted(dist_dir.glob(pattern))
    if len(artifacts) != 1:
        raise RuntimeError(
            f"expected exactly one {artifact_type} in {dist_dir}, found {artifacts}"
        )
    return artifacts[0]


def _venv_python(venv_dir: Path) -> Path:
    executable = "python.exe" if sys.platform == "win32" else "bin/python"
    return venv_dir / executable


def _run(*command: str, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _project_version(repository_root: Path) -> str:
    with (repository_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    return str(pyproject["project"]["version"])


def _validate_archive_contents(wheel: Path, sdist: Path) -> None:
    with zipfile.ZipFile(wheel) as wheel_archive:
        wheel_files = set(wheel_archive.namelist())
    if f"{PACKAGE_PATH}/py.typed" not in wheel_files:
        raise RuntimeError("wheel does not contain mcp_runtime/py.typed")

    with tarfile.open(sdist, mode="r:gz") as sdist_archive:
        sdist_files = {
            member.name.removeprefix(f"{sdist.stem.removesuffix('.tar')}/")
            for member in sdist_archive.getmembers()
        }
    if f"src/{PACKAGE_PATH}/py.typed" not in sdist_files:
        raise RuntimeError("sdist does not contain src/mcp_runtime/py.typed")


def _validate_installed_wheel(
    *,
    repository_root: Path,
    wheel: Path,
    expected_version: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="mcp-runtime-dist-") as temp_directory:
        consumer_root = Path(temp_directory)
        venv_dir = consumer_root / ".venv"
        python = _venv_python(venv_dir)

        _run("uv", "venv", "--python", "3.13", str(venv_dir))
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(wheel),
        )

        runtime_smoke = textwrap.dedent(
            f"""
            from importlib.metadata import version
            from importlib.resources import files

            from mcp_runtime import (
                InternalAuthSettings,
                Principal,
                RuntimeSettings,
                ServerSettings,
                create_server,
                get_principal,
                run_server,
            )

            assert version({PACKAGE_NAME!r}) == {expected_version!r}
            assert files("mcp_runtime").joinpath("py.typed").is_file()

            settings = RuntimeSettings(
                service_id="distribution-smoke",
                server=ServerSettings(),
                auth=InternalAuthSettings(
                    issuer="https://api.xdenovoai.com/",
                    jwks_url="http://gateway.internal/.well-known/jwks.json",
                ),
            )
            assert settings.audience == (
                "urn:xdenovo:mcp-service:distribution-smoke"
            )
            assert create_server(settings).name == "distribution-smoke"
            assert Principal("subject", frozenset({{"mcp:invoke"}})).subject == "subject"
            assert callable(get_principal)
            assert callable(run_server)
            """
        )
        _run(str(python), "-I", "-c", runtime_smoke, cwd=consumer_root)

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
        consumer_file = consumer_root / "consumer.py"
        consumer_file.write_text(
            textwrap.dedent(
                """
                from mcp_runtime import (
                    InternalAuthSettings,
                    Principal,
                    RuntimeSettings,
                    ServerSettings,
                    create_server,
                )

                settings: RuntimeSettings = RuntimeSettings(
                    service_id="typed-consumer",
                    server=ServerSettings(),
                    auth=InternalAuthSettings(
                        issuer="https://api.xdenovoai.com/",
                        jwks_url="http://gateway.internal/.well-known/jwks.json",
                    ),
                )
                principal: Principal = Principal(
                    subject="subject",
                    scopes=frozenset({"mcp:invoke"}),
                )
                server = create_server(settings)
                identity: tuple[str, str] = (server.name, principal.subject)
                """
            ).lstrip(),
            encoding="utf-8",
        )
        _run(
            "uv",
            "run",
            "--no-sync",
            "ty",
            "check",
            "--project",
            str(consumer_root),
            "--python",
            str(venv_dir),
            str(consumer_file),
            cwd=repository_root,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dist_dir",
        type=Path,
        help="Directory containing one wheel and one source distribution.",
    )
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parent.parent
    dist_dir = args.dist_dir.resolve()
    wheel = _single_artifact(dist_dir, "*.whl", "wheel")
    sdist = _single_artifact(dist_dir, "*.tar.gz", "source distribution")
    expected_version = _project_version(repository_root)

    _validate_archive_contents(wheel, sdist)
    _validate_installed_wheel(
        repository_root=repository_root,
        wheel=wheel,
        expected_version=expected_version,
    )

    print(
        f"validated {wheel.name} and {sdist.name} for {PACKAGE_NAME} {expected_version}"
    )


if __name__ == "__main__":
    main()
