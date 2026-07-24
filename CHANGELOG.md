# Changelog

## [0.2.0](https://github.com/XDenovo/mcp-runtime/compare/v0.1.0...v0.2.0) (2026-07-24)


### Features

* add authenticated private MCP runtime ([#4](https://github.com/XDenovo/mcp-runtime/issues/4)) ([5af0cb3](https://github.com/XDenovo/mcp-runtime/commit/5af0cb3a6cee13183c785abbe145b4c9a73da815)), closes [#2](https://github.com/XDenovo/mcp-runtime/issues/2)

## 0.1.0 (2026-07-24)


### Features

* add authenticated private MCP runtime ([#4](https://github.com/XDenovo/mcp-runtime/issues/4)) ([5af0cb3](https://github.com/XDenovo/mcp-runtime/commit/5af0cb3a6cee13183c785abbe145b4c9a73da815)), closes [#2](https://github.com/XDenovo/mcp-runtime/issues/2)

### Compatibility

`mcp-runtime` follows SemVer. While the project remains below `1.0.0`, a MINOR release may contain
breaking API changes. Consumers should pin an exact Git tag and commit through their `uv.lock`,
review Release Notes before upgrading, and update that lock intentionally.

### Known limitations

This first slice provides Runtime/Server/Internal Auth settings, Gateway-issued RS256 JWT and JWKS
verification, immutable request `Principal` mapping, and stateful Streamable HTTP server assembly.
It does not include the Gateway signer or JWKS route, database or Job/Artifact foundations, S3,
Temporal Workflow/Activity support, health probes, multi-replica Session coordination, business
authorization helpers, or a public testing package.
