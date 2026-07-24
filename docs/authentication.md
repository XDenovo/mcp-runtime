# Runtime 内部身份验证

本文描述 `mcp-runtime` 实现的配置、认证、请求身份、Server 生命周期和下游契约测试
边界。
规范来源是 Platform
[Internal Credential Contract](https://github.com/XDenovo/platform/blob/main/docs/internal-credential-contract.md)；
本文说明 Python Runtime 如何实现该契约，不另行定义 Gateway Token。

## 信任边界

Compute MCP Service 只接收 Gateway 签发的短时内部 JWT。外部 OAuth Access Token、
用户控制的 JWKS 地址和私钥不会进入 Runtime。认证建立调用者身份，业务 Tool 仍负责
scope、资源归属和其他领域授权。

Runtime 固定：

- JWT 算法为 RS256；
- 必需 scope 为 `mcp:invoke`；
- `aud` 为 `urn:xdenovo:mcp-service:{service_id}`；
- HTTP transport 为 `/mcp` 上的 stateful Streamable HTTP；
- 严格 Host/Origin 防护、masked Server error、禁用 FastMCP background tasks。

这些值不是环境变量，也不能通过 `create_server()` 或 `run_server()` 的任意参数覆盖。

## 设置模型

顶层配置为 `RuntimeSettings`：

| 环境变量 | 含义 | 默认值 |
|---|---|---|
| `MCP_RUNTIME_SERVICE_ID` | 稳定、lowercase DNS-label 服务 ID | 必填 |
| `MCP_RUNTIME_SERVER__HOST` | 进程绑定地址 | `127.0.0.1` |
| `MCP_RUNTIME_SERVER__PORT` | 进程端口，1–65535 | `8000` |
| `MCP_RUNTIME_SERVER__ALLOWED_HOSTS` | 严格 Host allowlist；复杂值使用 JSON 数组 | loopback 时为绑定 host |
| `MCP_RUNTIME_AUTH__ISSUER` | 必须精确匹配的稳定 HTTPS issuer | 必填 |
| `MCP_RUNTIME_AUTH__JWKS_URL` | Runtime 获取公钥的绝对 HTTP/HTTPS URL | 必填 |

`issuer` 与 `jwks_url` 是两个独立配置。它们拒绝相对 URL、userinfo 和 fragment；
Runtime 不从 issuer 推断 JWKS，也不接受请求提供的 URL。

构造参数优先于进程环境：

```python
from mcp_runtime import InternalAuthSettings, RuntimeSettings, ServerSettings

settings = RuntimeSettings(
    service_id="graphpep-mcp",
    server=ServerSettings(),
    auth=InternalAuthSettings(
        issuer="https://api.xdenovoai.com/",
        jwks_url="http://gateway.internal/.well-known/jwks.json",
    ),
)
```

默认配置不发现文件。调用方可以通过
`RuntimeSettings(_env_file="/explicit/path/.env")` 明确启用一个 `.env`；Runtime 不加载
YAML、JSON 或任意配置目录。

非 loopback 绑定必须提供无通配符的 `allowed_hosts`。`run_server()` 不接受任意
`**kwargs`，因此服务不能意外切换到 stateless HTTP、关闭 Host 防护或替换认证 Provider。
它还会拒绝并非由 `create_server()` 组装的 Server，或与构造时服务身份/认证设置不一致
的 `RuntimeSettings`。
服务间 Gateway 请求不发送浏览器 Origin 即可；若请求携带 Origin，它仍须通过严格
同源检查。

## Credential 验证

FastMCP `JWTVerifier` 负责 JWKS key 选择、RS256 验签以及 issuer、audience、expiry
检查，并生成已验证的 `AccessToken`。Runtime 不再次解码 payload 或重复验签，而是在
已验证 Claims 上应用更严格的 wire policy：

- `kid` 必须是非空字符串；
- `iss`、`aud`、`sub`、`scope` 必须是非空字符串；
- `iss` 和 `aud` 必须分别精确匹配配置值与派生值，不能使用 audience 数组；
- `scope` 必须是单空格分隔、无重复值的字符串，并包含 `mcp:invoke`；
- `iat`、`exp` 和可选 `nbf` 必须是整数 NumericDate；boolean、float、string 均拒绝；
- `0 < exp - iat <= 300`；
- `iat <= now + 30`，若有 `nbf` 则 `nbf <= now + 30` 且 `nbf < exp`；
- `exp > now`，正好到期即无效。

未知额外 Claim 可以存在，但不会进入服务 API。验证成功后，Runtime 只创建：

```python
Principal(subject: str, scopes: frozenset[str])
```

`Principal` 是 immutable。它不保留原始 JWT、FastMCP `AccessToken`、issuer、
audience、时间字段或任意 Claim。

## 请求上下文

Tool 在当前已认证 MCP HTTP 请求中同步调用 `get_principal()`：

```python
@server.tool
async def submit() -> str:
    principal = get_principal()
    return principal.subject
```

函数在请求外、未认证请求或缺少验证后 subject 时抛出清晰的 `RuntimeError`。它直接读取
FastMCP 当前 HTTP request 上的认证用户，不创建第二个 Runtime `ContextVar`，也不会从
FastMCP background-task snapshot 恢复身份。

Workflow、Activity、队列消息和服务自建后台任务必须显式复制所需的稳定业务字段，例如
`Principal.subject`；不要传播原始 Token 或假设请求上下文会继续存在。

不同并发请求的 FastMCP request context 相互隔离。Stateful HTTP Session 还绑定创建它
的认证身份；另一有效 Principal 使用捕获的 Session ID 时得到与不存在 Session 相同的
404，避免泄露 Session 是否存在。

## Server 与 JWKS 生命周期

典型服务可以组合自己的 lifespan：

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from mcp_runtime import RuntimeSettings, create_server, run_server


@asynccontextmanager
async def service_lifespan(
    server: FastMCP[Any],
) -> AsyncIterator[dict[str, object]]:
    resource = await open_service_resource()
    try:
        yield {"resource": resource}
    finally:
        await resource.aclose()


settings = RuntimeSettings()
server = create_server(settings, lifespan=service_lifespan)
run_server(server, settings)
```

Runtime 在每次 Server lifespan 进入时创建一个共享 `httpx.AsyncClient`，设置有限
timeout，并禁用 redirect。JWKS 不在构造或 startup 时预取，只在首次认证请求时加载。
FastMCP 缓存一个 JWKS 集合；缓存中不存在新 `kid` 时重新获取，因此正常 overlap
rotation 可在不重启服务的情况下同时接受新旧 key。该缓存行为不是紧急私钥撤销 SLA。

Runtime 先建立 JWKS Client，再进入服务 lifespan；退出顺序相反。正常关闭、服务
startup 失败和取消路径都会清理 Runtime 资源。同一 Server 的 lifespan 可在测试中
重复进入；仅构造但从未运行不会创建 HTTP Client。

`jwks_transport` 只是在单元/集成测试中注入 `httpx.AsyncBaseTransport` 的窄 seam。
公开的 `InternalCredentialFactory.jwks_transport` 实现这个 seam；Runtime 始终拥有
Client、timeout、redirect 和关闭策略，生产服务不应传入它。

## 失败和日志语义

任何 Bearer、header、签名、Claim 或 JWKS 问题都在 Tool 执行前 fail closed。FastMCP
的公共 verifier contract 会把一些 JWKS 故障与无效 Token 都表现为
`401 invalid_token`；调用者不应据此推断内部网络状态。

Runtime 控制的 JWKS HTTP 边界会发送 `jwks_fetch_failed` 结构化事件。认证拒绝发送
`internal_auth_failed`，包含服务 ID、验证阶段、低基数 reason、retryability 和经过
限制/脱敏的 `kid`。事件不会包含：

- 原始 Token 或 Authorization Header；
- `sub` 或拒绝的 Claim 值；
- 内部 JWKS URL；
- 未清理的异常文本。

Runtime 不全局配置 structlog、stdlib logging 或 tracing，也不默认记录成功
Principal。FastMCP verifier 实例中可能插入 Claim 值的日志被抑制，签名验证本身仍由
FastMCP 完成。

## 测试策略

### 下游支持的契约测试 API

`mcp_runtime.testing` 随普通 wheel/sdist 发布，不使用额外 dependency extra，也不在
顶层 `mcp_runtime` re-export。它公开三个 typed API：

- `InternalCredentialFactory(settings)`：每个实例生成独立临时 RSA key 和内存 JWKS
  transport；`issue()` 固定 RS256、issuer、300 秒整数时间、`mcp:invoke` 和单一目标
  audience，只接受 subject、无重复业务 scope 和可选目标 `service_id`；
- `streamable_http_client(server, credential=...)`：通过进程内 ASGI 应用进入真实
  Bearer middleware、stateful Streamable HTTP 初始化和 Session；
- `assert_authentication_rejected(client_context)`：pytest-independent 的 async 断言，
  只接受 HTTP 401，并隐藏 MCP SDK、AnyIO 和 `ExceptionGroup` 的嵌套形状与敏感错误
  上下文。

Factory 不公开私钥、任意 JWT Header/Claim、算法或通用 Token builder。目标 service
override 只改变 canonical audience，用于证明跨服务隔离。Client 管理应用 lifespan、
HTTP Client、任务、streams 和 Session；成功、401、startup 失败、重复进入、并发退出
和取消都执行显式清理。Client 仅通过 FastMCP 的公开
`httpx_client_factory` 扩展点接入私有 streaming ASGI transport，不直接导入或 patch
MCP SDK；当前 SDK 遗留的 AnyIO receive stream 由并发安全、作用域受限的兼容层跟踪
并关闭。

### Runtime 私有测试

Unit suite 覆盖配置、严格 Claims、时间边界、Principal、JWKS cache/rotation、失败分类、
日志安全、公开测试 Factory 和资源生命周期：

```bash
uv run --no-sync pytest tests/unit
```

Integration suite 使用公开 Factory，并保留 `tests/support` 私有 adversarial builder
来生成畸形 Header/Claim。二者都通过真实 RSA/JWT/JWKS wire data 和
`httpx.MockTransport` 提供 JWKS，以 FastMCP Streamable HTTP Client 经进程内
streaming ASGI transport 穿过真实 Bearer middleware。它不使用会绕过 HTTP 认证的
in-memory Server transport：

```bash
uv run --no-sync pytest tests/integration
```

完整 CI 命令同时采集 `mcp_runtime` statement/branch coverage，输出 terminal/XML，并要求
至少 90%：

```bash
uv run --no-sync pytest \
  --cov=mcp_runtime \
  --cov-config=pyproject.toml \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-fail-under=90
```

普通或聚焦 pytest 不被全局 coverage 参数包裹。

## 明确不包含

本 Runtime 不实现生产 Gateway signer/JWKS Route、外部 OAuth Token 接受、业务授权装饰器、
数据库、Job/JobStep/Artifact、S3、Temporal Workflow/Activity/Worker、健康探针、
Event Store、多副本 Session 协调或 key 运维 runbook。`mcp_runtime.testing` 只拥有
canonical 下游契约测试；任意畸形 Token、Header/Claim 和私钥操作仍保持在私有
`tests/support`。
