# mcp-runtime v0.1.0 发布前 TODO

本文跟踪 `mcp-runtime` 首个可用版本的发布工作。`v0.1.0` 的目标不是只提供可导入的
API 骨架，而是提供能够被计算型 MCP 服务实际使用、经过真实基础设施验证的共享运行时。

## 当前发布状态

**No-Go。** 在本文的“最终发布门禁”全部满足前，不合并 Release Please 创建的
`chore(main): release mcp-runtime 0.1.0` PR，也不创建或移动 `v0.1.0` Tag。

当前已知基线：

- `observability` 已有真实实现；
- `config`、`auth`、`server`、`workflow`、`jobs`、`storage` 和 `testing` 仍包含
  `NotImplementedError`；
- CI 可以通过，但现有测试主要验证导入、公开符号和日志行为，尚未验证核心运行能力；
- 当前仓库可构建 sdist/wheel，但产物中仍包含未实现的公开接口。

## 阶段 1：冻结 v0.1 API 契约

在开始大规模实现前先完成下列决策，避免实现完成后立刻发生破坏性修改。

### 配置

- [ ] 保证通过任何方式构造 `RuntimeConfig` 时，`db_schema`、`s3_namespace`、
  `temporal_namespace` 和 `temporal_task_queue` 都不会是 `None`。
- [ ] 为 `service_name`、Schema、Namespace、Task Queue、端口、URL、日志级别和超时增加校验。
- [ ] 决定同步和异步 PostgreSQL 连接使用两个 DSN，还是由配置生成不同 driver URL。
- [ ] 决定 Server 与 Worker 是否使用不同的配置模型，避免 Worker 获得不需要的 HTTP/JWKS 配置。
- [ ] 补齐 PostgreSQL、S3/MinIO 和 Temporal 的 TLS、认证及连接超时配置策略。
- [ ] 确保配置对象的 repr 和日志不会泄露 PostgreSQL、S3 或其他凭据。

### 身份验证

- [ ] 决定复用 FastMCP 的异步 `JWTVerifier`，还是维护自定义 `InternalTokenVerifier`。
- [ ] 与 Gateway 固化 JWT 契约：算法、`iss`、`aud`、`sub`、`exp`、`iat`、`nbf`、scope 格式和时钟偏差。
- [ ] 定义 JWKS 请求超时、缓存、密钥轮换、未知 `kid` 和 Gateway 暂时不可用时的行为。
- [ ] 定义认证失败的标准 MCP 错误，以及在 handler 外调用 `current_principal()` 的错误类型。
- [ ] 明确健康检查端点是否绕过认证，并确保其他路由默认拒绝匿名访问。

### Job 与数据库

- [ ] 用 `mapped_column` 定义可直接组合使用的主键、类型、时间戳和必要索引。
- [ ] 确认 `JobStatus` 在 PostgreSQL 中保存枚举值还是名称，并固定迁移兼容策略。
- [ ] 定义 UTC/timezone、`created_at`/`updated_at` 默认值和更新时间语义。
- [ ] 确认 Artifact 与 Job 的外键由 runtime mixin 还是各服务迁移负责。
- [ ] 定义 `generate_job_id()` 的格式、合法字符、长度、碰撞概率和可观测性要求。
- [ ] 安全设置 PostgreSQL `search_path`，禁止通过未校验 Schema 名称拼接 SQL。

### Temporal

- [ ] 将 workflow 参数类型与 Temporal SDK 对齐：workflow callable 或字符串，而不是模糊的 class 类型。
- [ ] 固化重复 `workflow_id` 的语义，包括运行中冲突、已完成 ID 复用和参数不一致。
- [ ] 明确使用 `WorkflowIDReusePolicy`、`WorkflowIDConflictPolicy` 和稳定 request ID 的策略。
- [ ] 决定 `start()` 需要暴露的超时、retry、memo、search attributes、priority 和版本参数。
- [ ] 移除无意义的 `task_queue` 参数，或确保调用方不能借此访问其他服务队列。
- [ ] 为同步 Activity 定义 executor，并确定 Worker 并发、优雅关闭、identity/build ID 和版本策略。
- [ ] 定义 Temporal TLS、认证、payload/data converter 和 RPC 超时配置。

### S3/MinIO

- [ ] 决定 `ArtifactStore` 提供同步、异步，还是显式区分两套 API；不得阻塞 FastMCP 事件循环。
- [ ] 定义相对 key 的合法格式，并拒绝空 key、绝对路径和不允许的 namespace 表达形式。
- [ ] 定义 presigned URL 的最大有效期、Content-Type、文件大小和覆盖行为。
- [ ] 定义 StreamingBody 的关闭责任，优先提供不易泄漏连接的上下文管理或下载 API。
- [ ] 为大文件确定 multipart、checksum、重试、超时、连接池和失败清理策略。
- [ ] 补齐 MinIO 所需的 region、signature version、path-style 和自定义 CA 配置。

**阶段完成条件：** `docs/design.md`、公开类型签名和 Gateway/服务模板中的约定一致，
且上述决策不再依赖实现者临时猜测。

## 阶段 2：实现核心运行时

- [ ] 实现 `RuntimeConfig` 的环境加载、默认值解析和完整校验。
- [ ] 实现 `Principal.has_scope()`、JWT 验证、请求身份绑定和 ContextVar 清理。
- [ ] 实现 FastMCP app 创建、Streamable HTTP 启动、结构化请求日志和健康检查。
- [ ] 实现可工作的 SQLAlchemy mixin、同步/异步 Engine 和 Schema 隔离。
- [ ] 实现 Temporal Client 连接、幂等启动、结果查询、取消和 Worker 构造。
- [ ] 实现 S3/MinIO 上传、下载、预签名和删除，并强制 namespace 边界。
- [ ] 实现 `fake_principal()` 和 `InMemoryVerifier`，且测试替身不会进入生产默认路径。
- [ ] 删除所有预期公开可用路径中的 `NotImplementedError`。
- [ ] 对所有外部客户端提供明确的关闭或生命周期管理方式。

**阶段完成条件：** 每个 `mcp_runtime.__all__` 导出的符号都具有真实行为或被明确移出
`v0.1` 公开 API。

## 阶段 3：补齐行为与安全测试

### 单元测试

- [ ] 配置默认值、环境覆盖、非法名称、非法 URL/端口和秘密字段脱敏。
- [ ] JWT 正常路径及错误签名、错误 issuer/audience、过期、未生效、缺失 claim、未知 `kid`。
- [ ] 并发请求之间 Principal 和日志 ContextVar 不串号，请求结束后上下文被清理。
- [ ] Job/Artifact mixin 能与服务自有 `DeclarativeBase` 组合并生成预期表结构。
- [ ] Temporal 同 ID 重试不会创建第二个执行，参数冲突不会被静默当作成功。
- [ ] Temporal result/cancel 对不存在、已完成、失败和已取消 Workflow 有稳定行为。
- [ ] S3 key 规范化、namespace 隔离、预签名参数、流关闭和 SDK 错误传播。
- [ ] `configure_logging()` 重复调用、第三方日志、异常日志和敏感字段行为。

### 测试质量门禁

- [ ] CI 对核心模块启用 coverage 检查，并结合行为断言；不能把执行 `raise` 或仅导入算作完成。
- [ ] CI 将未处理 warning、资源泄漏和异步任务泄漏视为失败。
- [ ] 增加公开 API 快照或契约测试，防止无意的破坏性变更。
- [ ] 对公开 API 运行类型检查消费样例。

**阶段完成条件：** 失败路径、并发隔离和资源清理均有自动化测试，不以单一覆盖率数字替代行为验证。

## 阶段 4：真实基础设施集成测试

- [ ] 使用真实 PostgreSQL 验证 async/sync Engine、连接池、事务、Schema `search_path` 和角色隔离。
- [ ] 使用真实 MinIO 验证 put/get/delete、multipart、presigned GET/PUT、过期和跨 namespace 拒绝。
- [ ] 使用 Temporal `WorkflowEnvironment` 或测试 Server 验证启动、重复提交、结果、取消、Worker 和优雅关闭。
- [ ] 使用测试 JWKS Server 验证缓存、轮换、超时和不可用场景。
- [ ] 使用 FastMCP Client 对 Streamable HTTP 做认证、Tool 调用、错误映射和健康检查测试。
- [ ] 将核心集成测试纳入 CI；较慢测试可以独立 job 运行，但必须是 Release PR 的必需检查。

**阶段完成条件：** runtime 不依赖 mock 也能同时连接 PostgreSQL、MinIO、Temporal 和 JWKS，
并完成一次经过认证的 MCP 请求及 Workflow/Artifact 生命周期。

## 阶段 5：参考服务与跨仓库验收

- [ ] 在 `mcp-service-template` 中加入按 Git Tag 固定的 `mcp-runtime` 依赖示例。
- [ ] 模板生成的服务只需少量业务代码即可启动 Server 和 Worker。
- [ ] 建立一个最小参考 Tool：认证请求、写 Job、启动 Workflow、Worker 执行 Activity、写回 Artifact、查询结果。
- [ ] 验证 Gateway 签发的真实内部 JWT 可被 runtime 接受，scope 和 audience 错误会被拒绝。
- [ ] 验证一个服务无法访问另一个服务的数据库 Schema、S3 prefix、Temporal Namespace/Task Queue。
- [ ] 在至少一个真实计算服务的 staging 分支完成试接入，记录所有需要绕过 runtime 的地方。
- [ ] 将试接入暴露出的共享能力补回 runtime，业务特有逻辑继续留在服务仓库。

**阶段完成条件：** 至少一个实际消费者完成端到端调用，且无需复制 auth、存储、Workflow 或
Engine 初始化代码。

## 阶段 6：安全、可靠性与可运维性

- [ ] 为 S3 客户端设置有限超时、标准/自适应重试和与并发匹配的连接池。
- [ ] 为 JWKS、PostgreSQL 和 Temporal 设置有限连接/RPC 超时及明确的重试边界。
- [ ] 验证日志中不会出现 JWT、S3 Secret、数据库密码或 presigned URL。
- [ ] 定义 `/livez` 与 `/readyz`，并明确依赖故障时 readiness 行为。
- [ ] 输出可关联的 request ID、principal subject、job ID、workflow ID 和错误分类。
- [ ] 定义最低限度的 metrics/告警接口，至少覆盖认证失败、请求错误、Workflow 提交失败和存储失败。
- [ ] 验证进程收到 SIGTERM 时停止接收请求、关闭连接并让 Worker 优雅退出。
- [ ] 完成依赖漏洞扫描，并在 CI 或 Dependabot 中持续执行。
- [ ] 对跨网络状态修改执行超时、重试、重复请求和部分失败演练。

**阶段完成条件：** 常见依赖故障不会导致无限等待、身份串号、连接泄漏、重复 Workflow 或敏感信息泄漏。

## 阶段 7：包与发布工程

- [ ] 完成 `README.md`：定位、安装、最小 Server/Worker 示例、全部环境变量、错误处理和升级方式。
- [ ] 添加 `py.typed`，验证 wheel 中包含该文件，并验证外部项目可读取内联类型。
- [ ] 消除 `pyproject.toml` 与 `mcp_runtime.__version__` 的手工双版本来源，或增加一致性测试。
- [ ] 为可能破坏兼容性的依赖设置 major 上限，并测试声明的最低依赖版本。
- [ ] 将 Python 支持范围改为实际测试范围，或在 CI 增加所有声称支持的 Python 版本。
- [ ] 使用干净环境安装构建出的 wheel，并运行 import、类型和最小行为 smoke test。
- [ ] 增加 `uv lock --check`、依赖审计和构建产物检查。
- [ ] 增加 Dependabot 配置，持续更新 Python 和 GitHub Actions 依赖。
- [ ] 确认仓库应为 Public 还是 Private；若保持 Public，补齐 LICENSE、SECURITY 和公开信息检查。
- [ ] 添加 CODEOWNERS，并要求 Release PR 至少一次人工审批。
- [ ] 保护 `v*` Tag，禁止发布后移动或删除；消费者继续在 `uv.lock` 中锁定 commit。
- [ ] 确认 release workflow 失败时不会留下被误认为完整发布的 Release。
- [ ] 在 Release Notes 中说明 `0.x` 兼容策略、已知限制和升级步骤。

**阶段完成条件：** 从 Git Tag 或 Release wheel 安装得到的内容一致、可复现、类型完整，且发布需要显式人工批准。

## 阶段 8：staging 验收与 v0.1.0 发布

- [ ] 在 staging 使用与生产一致的 Python、PostgreSQL、MinIO、Temporal 和 Gateway 配置运行。
- [ ] 完成正常提交、重复提交、取消、失败重试、超时、依赖重启和凭据/JWKS 轮换演练。
- [ ] 验证结构化日志、readiness、告警和故障定位信息足够完成值班诊断。
- [ ] 记录数据库、Temporal 和 Artifact 中的实际结果，确认状态权威来源符合架构文档。
- [ ] 完成一次回滚演练：消费者可恢复到上一已知 commit，不破坏已有 Job/Workflow 数据。
- [ ] 由 runtime、Gateway 和首个消费服务的负责人共同完成 Go/No-Go Review。
- [ ] 合并 Release Please PR，等待 Tag、GitHub Release 和构建产物全部成功。
- [ ] 从最终 `v0.1.0` Tag 在干净环境重新安装并执行 smoke test。

## 最终发布门禁

只有以下条件全部成立，`v0.1.0` 才是 **Go**：

- [ ] 公开 API 中不存在占位实现；
- [ ] 所有 CI 必需检查通过；
- [ ] PostgreSQL、MinIO、Temporal、JWKS 和 FastMCP 集成测试通过；
- [ ] 至少一个真实服务完成 staging 端到端验收；
- [ ] 不存在未接受的高危安全问题或数据隔离问题；
- [ ] README、版本、类型标记、依赖边界和 Release Notes 完整；
- [ ] 发布 Tag 受保护且 Release PR 已人工批准；
- [ ] 回滚路径经过验证。

## 本地必跑检查

```bash
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
uv run --no-sync pytest
uv build
```

集成测试和干净 wheel 安装命令应在对应测试设施落地后补充到这里，并与 CI 保持一致。
