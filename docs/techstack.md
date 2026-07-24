# mcp-runtime 技术栈

本文是 `mcp-runtime` 已批准的仓库级技术选择及其边界的参考。未确定的方案、实施进度和
临时计划不进入本文；平台级选择和跨仓库兼容基线由
[`XDenovo/platform` 技术栈](https://github.com/XDenovo/platform/blob/main/docs/techstack.md)
负责。模块职责和公开 API 必须在实现前形成独立设计；不以占位源码、导入成功或类型
骨架作为已经批准的接口契约。

直接依赖范围、实际解析版本和已实现行为分别以 `pyproject.toml`、`uv.lock`、源码和
行为测试为准。

## 技术栈总览

| 领域 | 选择 |
|---|---|
| Python Runtime | Python 3.13 |
| Packaging | `uv`、`uv_build` |
| MCP Server | FastMCP 3.x、`fastmcp[apps]` |
| Configuration | Pydantic Settings 2 |
| Internal Authentication | FastMCP JWT Verifier、Runtime Claim Policy、`Principal` 映射、`httpx` |
| Auth Contract Testing | FastMCP Client、PyJWT、Cryptography、AnyIO、streaming ASGI transport |
| Persistence | SQLAlchemy 2.x、Psycopg 3 |
| Migrations | Alembic，由 Compute MCP Service 拥有 |
| Durable Workflow | Temporal Python SDK |
| Artifact Client | `boto3` 同步 Core、Presigned URL、有界异步线程卸载 |
| Telemetry | OpenTelemetry、W3C Trace Context、OTLP |
| Structured Logging | `structlog`、stdout JSON |
| Quality | Ruff、ty、pytest、pytest-asyncio、pytest-cov、Coverage.py、prek |

Python 3.13 是 Runtime、生成模板和容器镜像的共同基线。精确支持范围由项目 Manifest
声明；扩展到新的 Python Minor 前必须独立验证 Runtime、SDK、原生扩展、生成模板和
容器镜像。

## 工程质量与包基线

Runtime 使用 `uv_build` 的标准 `src` layout。生产包必须包含 `py.typed`，以声明内联
类型可供消费方类型检查器使用。公开 API 只在设计和行为完成后从
`mcp_runtime.__init__` 导出；空壳函数、`NotImplementedError` 和仅为导入成功而存在的
符号不构成可发布能力。

Ruff 同时负责 lint 和 format，目标语言版本与项目的 Python 3.13 基线一致。ty 检查
`src` 和 `tests`，第三方类型解析使用 uv 管理的项目环境，不维护第二套类型检查环境
或依赖声明。

pytest 使用原生 TOML 严格配置；pytest-asyncio 使用自动模式，并让异步 Fixture 和
Test 默认获得 function 级事件循环隔离。测试必须验证真实行为、失败路径和资源清理，
不编写只用于证明配置文件存在或包能够导入的占位测试。

pytest-cov 集成 Coverage.py，并以 `mcp_runtime` 为唯一生产源码范围：

- 同时采集语句和分支覆盖率，并使用相对路径保存结果，保证本地与 CI 报告可比较；
- 终端报告显示缺失行，CI 可输出 `coverage.xml`，本地按需生成 `htmlcov`；
- 普通和聚焦 pytest 调用不在全局 `addopts` 中强制 coverage，完整 CI 测试显式启用；
- 完整 CI 测试强制 `mcp_runtime` statement/branch 综合覆盖率至少 90%，普通和聚焦测试
  不强制启用 coverage；
- 覆盖率数字不能替代身份验证、服务隔离、幂等、取消、并发和资源清理的行为断言。

## MCP Server、配置与内部身份

### FastMCP 与 Apps

Runtime 使用 FastMCP 3.x 组装私网 Streamable HTTP Server，并为 Compute MCP Service
提供认证、生命周期、健康检查、日志和遥测基线。服务自己的 Tool、Resource、Prompt
和科学计算依赖不进入 Runtime。

`fastmcp[apps]` 是默认 Runtime 能力。Prefab UI、Custom HTML、3D 结构查看器和其他
业务 UI 由各 Compute MCP Service 定义，Runtime 不提供跨服务的业务组件库。

公开 Apps 的协议路由和跨语言兼容属于 Gateway 与 Platform 契约。启用
`fastmcp[apps]` 本身不代表公网 Gateway 已具备端到端 Apps 能力。

### Pydantic Settings

Runtime 使用 Pydantic Settings 2 加载和校验环境配置。服务名驱动 Database Schema、
Artifact Namespace、Temporal Namespace 和 Task Queue 的安全默认值；Secret 字段使用
秘密类型并在 repr、日志和校验错误中脱敏。Server 与 Worker 只接收各自需要的配置和
凭据。

### FastMCP JWT Verification

Runtime 将 FastMCP `JWTVerifier` 直接配置为 Server Auth Provider。FastMCP 负责
Bearer Token 提取、RS256 签名验证、JWKS 获取与缓存、`iss`、`aud`、`exp` 和请求级
`AccessToken` 上下文；`mcp-runtime` 不直接依赖或调用 PyJWT，也不对同一令牌执行
第二次解码或验签。

Runtime Claim Policy 在已验签的 `AccessToken.claims` 上强制
[`XDenovo/platform` Internal JWT 基线](https://github.com/XDenovo/platform/blob/main/docs/techstack.md)：
`iss`、`aud`、`sub`、`iat`、`exp` 和空格分隔的 `scope` 为必需字段，
`exp - iat` 不超过 5 分钟；`nbf` 可选但出现时必须验证，`iat`/`nbf` 最多允许 30 秒
时钟偏差，`exp` 严格过期。Runtime 将该上下文映射为稳定的 `Principal`，服务不直接
依赖 FastMCP 的 Token 类型。

实现细节、环境变量、失败语义和可执行示例见
[`authentication.md`](authentication.md)。生产 verifier 不调用 PyJWT 或接收私钥；
公开的 `mcp_runtime.testing` 契约测试 Factory 使用 PyJWT 和 Cryptography 生成临时
RSA/JWT/JWKS wire data。因为该子模块随普通发行包提供，PyJWT、Cryptography 和 AnyIO
都是明确的 Runtime 直接依赖，不使用 testing extra。

公开测试 Client 通过 FastMCP 的 `httpx_client_factory` 扩展点接入私有 streaming ASGI
transport，穿过真实 Bearer middleware 与 stateful Streamable HTTP Session。Runtime
不直接依赖、导入或 patch MCP SDK，并负责 Client、stream、并发、取消和失败清理；
下游测试也不解析 `ExceptionGroup`。临时 signing identity 仅属于契约测试，不改变
Gateway 独占生产私钥和 JWKS 发布的信任边界。

JWKS 请求复用由 Server 生命周期管理的共享 `httpx.AsyncClient`。Runtime 固定使用
平台批准的 RS256，不把 JWT Header 中的算法作为配置来源；私钥保管、轮换、JWKS
发布和故障恢复属于 Platform 的 Signing-Key Operations。

## Persistence 与 Workflow

### SQLAlchemy 与 Psycopg

Runtime 使用 SQLAlchemy 2.x 和 Psycopg 3。Psycopg 同时支持同步与异步 Engine，避免
为 FastMCP Server 和 Worker 维护两套 PostgreSQL Driver。

`mcp-runtime` 依赖 `psycopg` 接口；Compute MCP Service 镜像根据构建和安全策略选择
`psycopg[c]` 或 `psycopg[binary]` 实现。连接池、事务和 `search_path` 必须保持服务
Schema 隔离。

Alembic 不属于 Runtime。Runtime 提供共享 SQLAlchemy 类型和 Engine 构造；Migration
Environment、Revision 和升级顺序由拥有 Schema 的 Compute MCP Service 维护。

### Temporal

Runtime 使用 Temporal Python SDK，并只封装服务隔离、连接生命周期、幂等启动和安全
默认值。Workflow、Activity、Retry Policy 和业务 Search Attributes 留在服务仓库。

MCP Server 只提交 Workflow；长时间计算、同步文件传输和第三方程序执行位于独立
Worker Activity。Workflow 代码遵守 Temporal 确定性和版本兼容要求。

## Artifact Client

Runtime 使用 `boto3` 作为 S3-compatible Artifact Client：

- 同步 `ArtifactStore` 是存储操作的 Core；
- FastMCP 异步请求路径通过有界线程卸载执行短 S3 操作；
- GPU Worker 和同步 Temporal Activity 使用 boto3 managed multipart transfer；
- Client 使用 Presigned URL 传输大文件，不通过 MCP JSON 或 Gateway 代理字节；
- 连接池、线程并发、流关闭和 multipart 失败清理必须具有一致的资源边界。

Runtime 不采用 `aioboto3`：Presigned URL 和 Worker managed transfer 已避免长时间
对象流代理，而 `aiobotocore` 还会约束 `boto3` 和 `botocore` 的升级范围。只有真实
负载证明有界线程卸载是明确瓶颈时，才重新评估原生异步 Client。

## 可观测性

### OpenTelemetry

Runtime 使用 OpenTelemetry 统一 Traces 和 Metrics，通过 W3C Trace Context 在
Gateway、Compute MCP Service、Temporal Workflow 和 Worker 之间传播上下文，并通过
OTLP 导出遥测。

Runtime 统一初始化 SDK、Resource Attributes、Exporter 和 Instrumentation。覆盖范围
包括 FastMCP、出站 HTTP、SQLAlchemy、Temporal 和 Botocore。未配置 Exporter 时，
本地开发不依赖外部遥测基础设施。

Collector、Telemetry Backend、采样、保留策略、Dashboard 和告警由 Platform 层选择。
应用日志继续写入 stdout JSON，并通过 `trace_id` 和 `span_id` 与 Trace 关联，不通过
OpenTelemetry Logs 重复导出。

遥测不得包含访问令牌、内部凭证、数据库密码、对象存储密钥、Presigned URL 或未经
设计的原始用户身份。`job_id`、`request_id` 等高基数字段可以用于 Trace 和 Log，
不得作为 Metric Attribute。

### structlog

Runtime 使用 `structlog` 作为 Compute MCP Service 和 Worker 的结构化日志接口。日志
以 JSON 写入容器 stdout，由部署层收集；Runtime 不直连集中式日志产品。

`structlog.contextvars` 绑定请求、Principal、Job 和 Activity 上下文。
`ProcessorFormatter` 将 FastMCP、SQLAlchemy、Temporal、HTTP 和 Botocore 的 stdlib
`logging` 记录接入同一管线。Compute MCP Service 使用
`mcp_runtime.observability`，不配置第二套 root logger 或 Processor。
