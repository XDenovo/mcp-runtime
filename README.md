# XDeNovo MCP Runtime

`mcp-runtime` 是 XDeNovo Compute MCP Service 共用的 Python 运行时库，不是独立部署的
服务。当前提供经过验证的配置、Gateway 内部 JWT 鉴权、请求级 `Principal`，
具有固定安全策略的 FastMCP stateful Streamable HTTP Server，以及下游服务可复用的
内部鉴权契约测试工具。

详细的凭证契约、失败语义和测试设计见
[`docs/authentication.md`](docs/authentication.md)。平台边界以
[Internal Credential Contract](https://github.com/XDenovo/platform/blob/main/docs/internal-credential-contract.md)
为准。

## 公共 API

顶层包当前只导出：

```python
from mcp_runtime import (
    InternalAuthSettings,
    Principal,
    RuntimeSettings,
    ServerSettings,
    create_server,
    get_principal,
    run_server,
)
```

`Principal` 只含不可变的 `subject` 和 `scopes`。服务仍须根据它执行业务授权、资源归属
检查；Runtime 鉴权本身不代表调用者有权访问任意业务对象。

测试工具位于独立子模块，不会扩大顶层 `mcp_runtime` 的导出：

```python
from mcp_runtime.testing import (
    InternalCredentialFactory,
    assert_authentication_rejected,
    streamable_http_client,
)
```

## 下游鉴权契约测试

`InternalCredentialFactory` 为一组测试生成独立的临时 RSA key、内存 JWKS transport 和
符合 Platform 契约的 300 秒 RS256 Credential。它只允许调用方提供非空 subject、
业务 scope，以及用于 audience 隔离测试的目标 `service_id`；不能构造任意 Header、
Claim 或算法，也不公开私钥。

```python
from mcp_runtime import RuntimeSettings, create_server
from mcp_runtime.testing import (
    InternalCredentialFactory,
    assert_authentication_rejected,
    streamable_http_client,
)

settings = RuntimeSettings()
credentials = InternalCredentialFactory(settings)
server = create_server(
    settings,
    jwks_transport=credentials.jwks_transport,
)


@server.tool
async def contract_probe() -> str:
    return "ok"


async def test_authenticated_service_contract() -> None:
    credential = credentials.issue(
        subject="user_01J2ABCDEF",
        scopes=("example:read",),
    )
    async with streamable_http_client(
        server,
        credential=credential,
    ) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["contract_probe"]

    await assert_authentication_rejected(streamable_http_client(server))
    await assert_authentication_rejected(
        streamable_http_client(
            server,
            credential=credentials.issue(
                subject="user_01J2ABCDEF",
                target_service_id="other-mcp",
            ),
        )
    )
```

这个 Client 经由进程内 ASGI 应用穿过真实 Bearer middleware 和 stateful Streamable
HTTP Session，不使用会绕过 HTTP 鉴权的 FastMCP in-memory Server transport。
`assert_authentication_rejected()` 不依赖 pytest，并把 SDK/AnyIO 的嵌套异常稳定为
“预期 HTTP 401”这一断言语义。

这些 API 虽随普通发行包提供，但只允许用于 Compute MCP Service 的契约测试；生产
代码和 Gateway 实现不得调用它们，也不得把 Factory 用作生产 signer 或运行时凭证
链路的一部分。Runtime 私有的畸形 Token、key rotation 和敏感日志测试仍保留在本仓库
`tests/support` 边界内。

## 配置

Runtime 默认只读取显式构造参数和具有 `MCP_RUNTIME_` 前缀的进程环境变量，嵌套字段用
双下划线分隔：

```bash
export MCP_RUNTIME_SERVICE_ID=graphpep-mcp
export MCP_RUNTIME_AUTH__ISSUER=https://api.xdenovoai.com/
export MCP_RUNTIME_AUTH__JWKS_URL=http://gateway.internal/.well-known/jwks.json
```

Server 默认绑定 `127.0.0.1:8000`。非 loopback 绑定必须显式列出允许的 Host，且不能用
通配符：

```bash
export MCP_RUNTIME_SERVER__HOST=0.0.0.0
export MCP_RUNTIME_SERVER__PORT=8000
export MCP_RUNTIME_SERVER__ALLOWED_HOSTS='["graphpep.internal"]'
```

Runtime 不会自动查找 `.env`、YAML 或 JSON。仅本地开发需要时，可由调用方明确选择：

```python
settings = RuntimeSettings(_env_file=".env")
```

`audience` 始终由 `service_id` 派生为
`urn:xdenovo:mcp-service:{service_id}`；RS256 和 `mcp:invoke` 是固定策略，不能通过
配置降级。

## 最小服务

```python
from mcp_runtime import RuntimeSettings, create_server, get_principal, run_server

settings = RuntimeSettings()
server = create_server(settings)


@server.tool
async def whoami() -> dict[str, object]:
    principal = get_principal()
    return {
        "subject": principal.subject,
        "scopes": sorted(principal.scopes),
    }


if __name__ == "__main__":
    run_server(server, settings)
```

`run_server()` 固定运行 `/mcp` 上的 stateful Streamable HTTP，启用严格 Host/Origin
保护并屏蔽 Tool 错误细节。Gateway 的服务间请求不需要浏览器 `Origin` Header。

JWKS 在首次鉴权时懒加载；一个 Server lifespan 内共用同一个不跟随重定向的
`httpx.AsyncClient`，退出时可靠关闭。正常 key overlap 期间，FastMCP 会在遇到未知
`kid` 时刷新 JWKS。JWT/JWKS 错误会 fail closed，并只产生不含 Token、`sub` 或内部
URL 的安全结构化事件。

## 开发验证

```bash
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
uv run --no-sync pytest
uv build
```

完整 CI 覆盖率门禁命令见 [`AGENTS.md`](AGENTS.md)。本切片的测试使用真实 RSA/JWKS
wire data，以及通过进程内 streaming ASGI transport 的真实 FastMCP HTTP 鉴权和会话
路径。

当前不包括 Gateway 签名端、数据库、Job/Artifact、Temporal Workflow/Activity、
对象存储、健康探针、多副本 Session 协调、Event Store、业务授权装饰器或公开的
生产签名 API。
