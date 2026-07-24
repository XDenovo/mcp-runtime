# XDeNovo MCP Runtime

## Repository Role

- `mcp-runtime` is the shared Python runtime library for XDeNovo Compute MCP Services. It is not
  an independently deployed service.
- It provides common configuration, internal authentication, FastMCP server assembly, Workflow
  integration, Job and Artifact foundations, object-storage access, observability, and test
  helpers.
- Service-specific Tools, scientific dependencies, domain models, repositories, migrations,
  Workflows, Activities, and Compute Job images stay in the owning service repository.
- This is an independent Git repository, not a package in a workspace monorepo.
- Use the canonical
  [Platform architecture](https://github.com/XDenovo/platform/blob/main/docs/architecture.md) and
  [approved technology stack](https://github.com/XDenovo/platform/blob/main/docs/techstack.md) as
  supplemental platform-wide context.
- Public module boundaries and APIs must be designed before implementation; placeholder source,
  import success, and typed skeletons are not interface contracts. `docs/releasing.md` owns
  versioning and release operations.

## Architecture and Security Guardrails

- Verify only the short-lived internal JWT issued by Gateway. External OAuth access tokens must
  never reach a Compute MCP Service or this runtime.
- Bind database Schema, object-storage namespace, Temporal Namespace, and Task Queue to the
  current service through `RuntimeConfig`.
- Shared APIs must not offer an unrestricted parameter that can target another service's Schema,
  Artifact namespace, Temporal Namespace, or Task Queue.
- Runtime authentication establishes the caller's `Principal`; each service remains responsible
  for business authorization and resource ownership checks.
- Each service owns its Job, JobStep, and Artifact metadata. Do not add a shared cross-service
  repository or query layer.
- MCP Server processes submit Workflows. They do not execute long-running computation or
  Workflow Activities inside an MCP request.
- Keep third-party scientific software and service-specific compute dependencies out of this
  package.
- Keep credentials, JWTs, database passwords, object-storage secrets, and presigned URLs out of
  logs and exception text.
- First-slice test support lives privately in `tests/support`; do not publish or re-export it
  through the production package API.

## Stack and Sources of Truth

- Python 3.13, pinned by `.python-version` and the project metadata.
- uv for dependency resolution and environment management; `uv_build` as the build backend.
- Ruff for linting and formatting, ty for type checking, pytest with automatic asyncio mode, and
  pytest-cov with branch coverage.
- `pyproject.toml` and `uv.lock` own exact dependency and environment state.
- `src/mcp_runtime/__init__.py` owns the production public export surface.
- `tests/` contains behavior and contract tests once implemented; do not add placeholder tests only
  to make an empty suite pass.

## Setup and Dependency Management

CI uses Python 3.13 and uv `0.11.30`; use the same versions when reproducing CI-specific behavior.

```bash
uv sync --locked
```

Use uv for dependency changes and commit both `pyproject.toml` and `uv.lock`:

```bash
uv add <package>
uv add --dev <package>
uv remove <package>
uv lock
```

Do not add a parallel pip, requirements-file, Poetry, or Conda dependency workflow.

### Pre-commit and Pre-push Hooks

`.pre-commit-config.yaml` defines local hooks run through `prek`, using the locked project
toolchain (plain `uv run`, so each invocation re-checks lock consistency before running).

Install once per clone:

```bash
uv run prek install --hook-type pre-commit --hook-type pre-push
```

Run manually without committing or pushing:

```bash
uv run prek run --all-files
uv run prek run --all-files --stage pre-push
```

- `pre-commit` stage: `ruff check --fix`, `ruff format`, `ty check`. A hook that modifies files
  aborts the commit once; re-stage and commit again.
- `pre-push` stage: `pytest` when a `tests/` directory exists.

## Development Workflow

This repository builds a library rather than starting a development server. After synchronizing
the environment, run project tools through the locked environment:

```bash
uv run --no-sync <command>
```

- Keep public interfaces typed and documented.
- Do not add a public export until its design, behavior, failure paths, and compatibility impact
  are documented and tested together.
- Preserve `from __future__ import annotations` and the existing modern type syntax.
- Keep service isolation structural: constructors and methods should derive service-owned
  resources from `RuntimeConfig` rather than accept arbitrary cross-service identifiers.
- Keep sync and async APIs explicit. Do not block the FastMCP event loop with synchronous
  database, storage, or Workflow operations.
- Give external clients, streams, engines, and workers an explicit lifecycle and cleanup path.
- Use the observability module for process logging and request or Job context instead of creating
  a second logging pipeline.
- A completed public implementation must have behavior and failure-path tests; removing
  `NotImplementedError` or making an import succeed is not sufficient.

## Testing and Validation

Run the same quality gate as CI:

```bash
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
uv build
```

Once behavior tests exist, also run:

```bash
uv run --no-sync pytest
```

The complete coverage-gated command used by CI is:

```bash
uv run --no-sync pytest \
  --cov=mcp_runtime \
  --cov-config=pyproject.toml \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-fail-under=90
```

Focused checks:

```bash
uv run --no-sync pytest tests/test_<module>.py
uv run --no-sync pytest -k "<expression>"
uv run --no-sync ruff check <changed-path>
uv run --no-sync ruff format --check <changed-path>
```

- Test files use `tests/test_*.py`; pytest runs async tests with `asyncio_mode = "auto"`.
- Prefer behavior assertions over import-only checks.
- Coverage measures `mcp_runtime` statements and branches. Focused tests do not enforce a global
  threshold; the complete CI suite enforces at least 90% and writes `coverage.xml`.
- Cover invalid configuration, identity and scope failures, service-boundary violations,
  idempotency, retries, cancellation, concurrent context isolation, and resource cleanup when the
  affected module is implemented.

Internal-auth integration tests use real RSA/JWT/JWKS wire data with `httpx.MockTransport`, and a
real FastMCP Streamable HTTP Client through `httpx.ASGITransport`; they do not require an external
JWKS process. TODO: When PostgreSQL, MinIO, and Temporal integration-test facilities land, document
their exact startup, selection, teardown, and CI commands.

## Build and Release

- `uv build` produces the wheel and source distribution checked by CI and attached to GitHub
  Releases.
- Releases use SemVer and tags named `vX.Y.Z`. During 0.x development, a breaking change produces
  a MINOR bump.
- release-please derives versions and release notes from Conventional Commits and maintains the
  release PR. Publishing remains an explicit human decision made by merging that PR.
- The project does not publish to a private package registry. Consumers pin a Git tag and the
  resolved commit in their own `uv.lock`.
- XDeNovo organization policy prevents the default `GITHUB_TOKEN` from creating release PRs.
  Preserve the narrowly scoped GitHub App token flow described in `docs/releasing.md`.
- Keep third-party GitHub Actions pinned to full commit SHAs.

TODO: When clean-wheel installation, `py.typed`, and external-consumer type checks enter CI,
document their exact validation commands here.

## Git and Pull Requests

- Treat the Issue as the implementation specification and the PR as the result report.
- Follow Conventional Commits because release-please uses them to calculate versions.
- Mark breaking changes with `!` or a `BREAKING CHANGE:` footer and explain consumer migration.
- Use the XDenovo organization-default Issue and PR templates.
- Preserve unrelated working-tree changes, and stage only the explicit paths intended for a
  commit.
- Public API changes must describe compatibility impact and update the design and tests in the
  same change.
