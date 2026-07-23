# mcp-runtime 技术栈

本文记录 `mcp-runtime` 仓库级技术选择、依赖边界和仍需完成的技术决策。平台级选择和
跨仓库兼容基线由
[`XDenovo/platform` 技术栈](https://github.com/XDenovo/platform/blob/main/docs/techstack.md)
负责；模块职责和公开 API 由 [`design.md`](./design.md) 负责。

本文不是依赖清单或实施状态报告。直接依赖范围、实际解析版本和已实现行为分别以
`pyproject.toml`、`uv.lock`、源码和行为测试为准。

## 1. 决策状态与总览

- **已批准**：当前设计采用该技术方向；不表示实现和集成验证已经完成。
- **暂缓**：当前版本不采用，并记录重新评估条件。
- **开放**：仍需在实现或生产部署前确定。

| 领域 | 选择 | 状态 |
|---|---|---|
| Python Runtime | Python 3.13 | 已批准 |
| Packaging | `uv`、`uv_build` | 已批准 |
| MCP Server | FastMCP 3.x、`fastmcp[apps]` | 已批准 |
| Configuration | Pydantic Settings 2 | 已批准 |
| Internal Authentication | FastMCP JWT Verifier、Runtime 严格 Claim Wrapper、`httpx` | 已批准 |
| Persistence | SQLAlchemy 2.x、Psycopg 3 | 已批准 |
| Migrations | Alembic，由 Compute MCP Service 拥有 | 已批准 |
| Durable Workflow | Temporal Python SDK | 已批准 |
| Artifact Client | `boto3` 同步 Core、Presigned URL、有界异步线程卸载 | 已批准 |
| Native Async Artifact Client | `aioboto3` | 暂缓 |
| Telemetry | OpenTelemetry、W3C Trace Context、OTLP | 已批准 |
| Structured Logging | `structlog`、stdout JSON | 已批准 |
| Quality | Ruff、ty、pytest、pytest-asyncio、prek | 已批准 |

Python 的支持范围限定为 `>=3.13,<3.14`。扩展到新的 Python Minor 之前必须完成
Runtime、SDK、原生扩展、生成模板和容器镜像的独立验证。

## 2. MCP Server 与 Apps

### 2.1 FastMCP

Runtime 使用 FastMCP 3.x 组装私网 Streamable HTTP Server，并为 Compute MCP Service
提供认证、生命周期、健康检查、日志和遥测基线。服务自己的 Tool、Resource、Prompt
和科学计算依赖不进入 Runtime。

`fastmcp[apps]` 是默认 Runtime 能力。Prefab UI、Custom HTML、3D 结构查看器和其他
业务 UI 由各 Compute MCP Service 定义，Runtime 不提供跨服务的业务组件库。

### 2.2 公开 Apps 的前置条件

启用 `fastmcp[apps]` 不等于公网 Gateway 已具备端到端 MCP Apps 能力。Gateway 必须
实现 Apps-aware Protocol Routing，并通过 TypeScript Gateway 与 Python FastMCP 的
跨语言集成测试。至少必须保持：

- `io.modelcontextprotocol/ui` Capability；
- Tool、Resource、Call Request 和 Call Result 的完整 Metadata 与未知 `_meta`；
- `structuredContent`、`ui://` Resource、MIME、CSP 和 Resource URI；
- 不出现在普通 Discovery 中的 app-only backend Tool 身份和授权；
- Tool/Resource 重命名后的所有关联引用。

FastMCP TypeScript 的原生 Remote Proxy 或只根据 `tools/list` 注册 Wrapper Tool
不能作为满足该契约的依据。普通 MCP Client 不支持 Apps 时，model-visible Tool
仍必须返回有意义的文本或结构化降级结果。

## 3. 配置与内部身份

### 3.1 Pydantic Settings

Runtime 使用 Pydantic Settings 2 加载和校验环境配置。服务名驱动 Database Schema、
Artifact Namespace、Temporal Namespace 和 Task Queue 的安全默认值；Secret 字段使用
秘密类型并在 repr、日志和校验错误中脱敏。

Server 与 Worker 是否拆分顶层配置模型属于公开 API 设计，但不得让 Worker 获得不需要
的 HTTP/JWKS 配置，也不得让 Server 获得不需要的 Worker 或 Compute 凭据。

### 3.2 FastMCP JWT Verification

Runtime 组合 FastMCP 的 JWT Verifier 和访问令牌上下文，而不维护平行的
PyJWT/PyJWKClient 认证管线。Runtime Wrapper 负责强制 Gateway 内部令牌契约并向服务
暴露稳定的 `Principal`，至少验证签名、算法、`iss`、`aud`、`sub`、`exp`、`iat`、
`nbf` 和 Scope 格式。

JWKS 请求使用共享的 `httpx.AsyncClient`，由 Server 生命周期管理连接池、超时、TLS、
缓存刷新和关闭。具体签名算法、密钥保管与轮换仍由 Platform 的 Secrets and Signing
Keys 决策负责。

## 4. Persistence 与 Workflow

### 4.1 SQLAlchemy 与 Psycopg

Runtime 使用 SQLAlchemy 2.x 和 Psycopg 3。Psycopg 同时支持同步与异步 Engine，避免
为 FastMCP Server 和 Worker 维护两套 PostgreSQL Driver。

`mcp-runtime` 作为 Library 依赖 `psycopg` 接口；最终 Compute MCP Service 镜像根据
构建和安全策略选择 `psycopg[c]` 或 `psycopg[binary]` 实现。连接池、事务和
`search_path` 必须保持服务 Schema 隔离。

Alembic 不作为 Runtime 的 Migration Owner。Runtime 可以提供共享 SQLAlchemy 类型和
Engine 构造，但 Migration Environment、Revision 和升级顺序由各 Compute MCP Service
维护。

### 4.2 Temporal

Runtime 使用 Temporal Python SDK，并只封装服务隔离、连接生命周期、幂等启动和安全
默认值，不复制 SDK 的完整功能面。Workflow、Activity、Retry Policy 和业务 Search
Attributes 留在服务仓库。

MCP Server 只提交 Workflow；长时间计算、同步文件传输和第三方程序执行位于独立
Worker Activity。Workflow 代码遵守 Temporal 确定性和版本兼容要求。

## 5. Artifact Client

### 5.1 boto3 基线

Runtime 使用 `boto3` 作为 S3-compatible Artifact Client：

- 同步 `ArtifactStore` 是存储操作的 Core；
- FastMCP 异步请求路径在进入线程池前通过 Semaphore 限制并发，再使用
  `asyncio.to_thread()` 执行短 S3 操作；
- Botocore 连接池上限与 Runtime Semaphore、Executor 上限保持一致；
- GPU Worker 和同步 Temporal Activity 使用 boto3 managed multipart transfer；
- Client 上传和下载大文件时使用 Presigned URL，不通过 MCP JSON 或 Gateway 代理
  Artifact 字节；
- 所有 `StreamingBody` 必须完整消费或显式关闭；
- 超时或取消不能被误认为底层线程或 multipart 已经停止，未完成的 multipart 必须显式
  Abort，并由对象存储 Lifecycle Rule 兜底。

`generate_presigned_url()` 等纯本地短操作不需要为了形式统一强制进入线程池。

### 5.2 暂缓 aioboto3

v0.1 不采用 `aioboto3`。它能在大量并发网络等待和长时间流式代理时减少线程占用，
但不会提高由磁盘、网络或对象存储吞吐决定的单次大文件传输速度。当前架构通过
Presigned URL 和 Worker managed transfer 避开了它最有价值的长流代理场景。

`aioboto3` 还通过 `aiobotocore` 约束可用的 `boto3`/`botocore` 版本范围，因此会让
共享 Runtime 的 AWS SDK 升级节奏依赖额外的兼容链。

以下条件是重新评估触发器，不是 SDK 性能保证：

- 单个 Runtime 实例持续超过 100 个并发 S3 小请求；
- 为满足延迟目标需要超过 32 个 S3 Executor 线程；
- Artifact Semaphore 等待时间 p95 持续超过 25 ms，或超过 Tool 总延迟的 10%；
- 单实例必须同时代理超过 20 条长时间对象流；
- 实际压测在相同连接数与资源下显示原生异步方案至少改善 20% 的 p95 或吞吐；
- `aioboto3` 不再迫使 Runtime 使用明显落后的 `boto3`/`botocore` 范围。

重新评估必须同时覆盖取消、multipart Abort、背压、连接释放、OpenTelemetry 和真实
MinIO/S3 集成测试。

## 6. 可观测性

### 6.1 OpenTelemetry

Runtime 采用 OpenTelemetry 作为 Traces 和 Metrics 的统一 API 与 SDK，使用 W3C
Trace Context 在 Gateway、Compute MCP Service、Temporal Workflow 和 Worker 之间
传播上下文，并通过 OTLP 向平台可观测性基础设施导出遥测。

该决策确定遥测标准和跨进程兼容边界，不选择具体 Telemetry Backend。Collector
部署、存储、查询、Dashboard、采样、保留策略和告警链路仍由 Platform 层决定。
没有配置 Exporter 时，本地开发必须能够在不连接外部遥测基础设施的情况下运行。

Runtime 负责统一初始化 SDK、Resource Attributes、Exporter 和 Instrumentation，
避免每个 Compute Service 各自建立一套遥测管线。集成至少覆盖：

- FastMCP Server 和 Client 的 MCP Span 与 Trace Context；
- JWKS 等出站 HTTP 请求；
- SQLAlchemy 同步与异步 Engine；
- Temporal Client、Workflow 和 Activity；
- Botocore 以及 boto3 managed transfer 使用的线程。

首阶段通过 OpenTelemetry 导出 Traces 和 Metrics。应用日志继续写入 stdout JSON，
并附带当前 `trace_id` 和 `span_id` 以支持关联查询；暂不通过 OpenTelemetry Logs
重复导出同一批日志。

遥测数据必须遵守以下安全和基数约束：

- 不记录访问令牌、内部凭证、数据库密码、对象存储密钥、Presigned URL 或 SQL 参数；
- 未经明确隐私设计，不把原始用户身份写入 Span Attribute；
- `job_id`、`request_id` 等高基数字段可以用于 Trace 和 Log，但不得作为 Metric
  Attribute；
- Gateway 不直接信任外部调用方提供的 Trace Context，而是建立或净化平台内部上下文。

### 6.2 structlog

Runtime 使用 `structlog` 作为 Compute MCP Service 和 Worker 的结构化日志接口。日志
写入容器 stdout，使用 JSON 格式，由部署层收集；Runtime 不在进程内选择或直连集中式
日志产品。

`structlog.contextvars` 提供请求、Principal、Job 和 Activity 作用域内的上下文绑定。
`ProcessorFormatter` 将 FastMCP、SQLAlchemy、Temporal、HTTP 和 Botocore 产生的
stdlib `logging` 记录接入同一条 JSON 管线。

Runtime 统一管理日志初始化、字段命名、级别、异常格式、敏感信息清理以及
OpenTelemetry Trace/Span 关联。Compute MCP Service 使用
`mcp_runtime.observability` 公开接口，不单独配置第二套 root logger 或 Processor。

## 7. 工程工具与权威来源

| 信息 | 权威来源 |
|---|---|
| Python 支持范围和直接依赖范围 | `pyproject.toml` |
| 某次可复现安装的具体版本 | `uv.lock` |
| 开发、测试和构建命令 | `AGENTS.md`、CI Workflow |
| Runtime 公开 API 与行为 | `docs/design.md`、源码和行为测试 |
| 生产 Runtime、Collector 和 Backend | `platform-deploy` 配置与 Runbook |

精确工具版本由 Manifest、Lockfile、Template 和 CI 管理，不在本文复制。Runtime 使用
Ruff 进行 Lint/Format、ty 进行类型检查、pytest/pytest-asyncio 进行行为测试，并通过
prek 管理本地 Hooks。

## 8. 开放决策

以下事项尚未确定：

- OpenTelemetry SDK、OTLP Exporter 和各 Instrumentation 包的具体依赖范围；
- OTLP 使用 HTTP/protobuf 还是 gRPC 作为默认传输；
- Temporal 采用稳定 Tracing Interceptor 还是新的 OpenTelemetry Plugin；
- Collector 拓扑、Telemetry Backend、采样、保留策略、Dashboard 和告警；
- 集中式日志的采集、存储和查询实现；
- Metrics 的业务指标集合、单位、Bucket 和低基数 Attribute 规范；
- Server 与 Worker 配置模型的最终公开 API；
- PostgreSQL、S3-compatible API 和 Temporal 的生产 TLS、Timeout 与 Pool 默认值。

这些开放项不得改变已经批准的服务隔离、MCP Apps、Psycopg 3、boto3 Core、W3C
Trace Context、OTLP、stdout JSON 和单一日志管线边界。
