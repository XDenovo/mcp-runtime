# mcp-runtime 设计

本文定义 `mcp-runtime` 的职责边界和公开 API。`mcp-runtime` 是
`pepmimic-mcp`、`graphpep-mcp`、`bindcraft-mcp` 三个计算服务共享的运行时基础库，
不是可独立运行的服务。系统级架构见
[`architecture.md`](https://github.com/XDenovo/platform/blob/main/docs/architecture.md)，
技术选型见
[`techstack.md`](https://github.com/XDenovo/platform/blob/main/docs/techstack.md)；本文只覆盖
`mcp-runtime` 自身的模块划分和接口。
版本策略和发布流程见 [`releasing.md`](./releasing.md)。

本文档描述的是**接口形状**，对应的 `src/mcp_runtime/*.py` 文件是可类型检查的骨架
（签名 + docstring，函数体为 `raise NotImplementedError`），尚未包含真实实现逻辑。

## 1. 定位

`architecture.md` §4.4 规定三个计算服务共享同一组平台边界：

- 只在私网提供服务，验证 Gateway 签发的内部凭证并从中取得身份和权限；
- 拥有本服务的 Job、JobStep、Artifact 元数据；
- 作为 Workflow Client 提交计算任务，不在 MCP Server 进程内执行 GPU 工作；
- 不访问其他计算服务的数据库 Schema、Artifact 命名空间或 Workflow Namespace。

这些边界与三个服务具体做什么科学计算无关，是纯粹的平台层问题，因此适合下沉到
`mcp-runtime`。`techstack.md` §5.2 同时明确：第三方科学计算依赖、服务特定的业务逻辑
不应该进入 `mcp-runtime`，除非它们确实是所有服务共享的运行时能力。

## 2. 模块与职责

| 模块 | 职责 | 明确不做什么 |
|---|---|---|
| `config` | 从环境变量加载 `RuntimeConfig`；DB Schema / S3 命名空间 / Temporal Namespace 与 Task Queue 默认从 `service_name` 派生 | 业务配置（价格、并发上限等，属于 Gateway 或待决策） |
| `auth` | 校验 Gateway 签发的内部 JWT（JWKS、audience、issuer、exp），暴露 `Principal` 给 Tool Handler | 业务级授权（"这个 Job 是否属于当前用户"由各服务自行校验） |
| `server` | 组装预置了 auth 中间件、健康检查、结构化日志的 FastMCP app 工厂 | 定义任何具体 Tool |
| `workflow` | 绑定到本服务 Namespace/Task Queue 的 Temporal Client，提供幂等 `start`；供 Worker 进程使用的 `build_worker` | 定义具体 Workflow/Activity |
| `jobs` | `JobStatus` 枚举、`JobMixin`/`ArtifactMixin` SQLAlchemy Mixin、幂等 Job Id 生成、Engine 构造 | 通用 Repository/查询层；Job/Artifact 的领域字段 |
| `storage` | 限定到本服务命名空间的 S3 客户端 `ArtifactStore`，所有 key 自动加命名空间前缀 | 服务内部如何组织 Artifact 路径 |
| `observability` | 结构化日志（stdout JSON）、请求与 Job 的关联 id | Metrics/Tracing 供应商选型（`techstack.md` 标记为待定，仅预留扩展点） |
| `testing` | `fake_principal()`、`InMemoryVerifier` 等测试替身，供各服务自己的 pytest 套件复用 | — |

### 2.1 隔离性设计原则

服务只能通过 `RuntimeConfig` 拿到自己的 Schema、命名空间、Task Queue；
`workflow.WorkflowClient`、`storage.ArtifactStore`、`jobs.create_engine_*` 都从
`RuntimeConfig` 构造，且不接受能够指向"别的服务"的参数（例如
`WorkflowClient.start` 的 `task_queue` 默认且只能是本服务队列）。这是用代码结构强制
`architecture.md` §4.4 的隔离要求，而不是仅仅依赖约定或 code review。

## 3. 公开 API

### 3.1 `mcp_runtime.config`

```python
class RuntimeConfig(BaseSettings):
    service_name: str
    environment: Literal["development", "staging", "production"]

    http_host: str = "0.0.0.0"
    http_port: int

    gateway_jwks_url: str
    internal_jwt_audience: str
    internal_jwt_issuer: str

    postgres_dsn: str
    db_schema: str            # 默认 = service_name

    s3_endpoint_url: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str
    s3_namespace: str         # 默认 = service_name

    temporal_address: str
    temporal_namespace: str   # 默认 = service_name
    temporal_task_queue: str  # 默认 = service_name

    log_level: str = "INFO"

    @classmethod
    def from_env(cls, **overrides: Any) -> "RuntimeConfig": ...
```

`service_name` 是唯一必须显式提供、且驱动其余默认值的字段；`db_schema` /
`s3_namespace` / `temporal_namespace` / `temporal_task_queue` 允许显式覆盖，但默认
值恒等于 `service_name`，让"一个服务默认只能碰自己的资源"成为开箱即用的行为。

### 3.2 `mcp_runtime.auth`

```python
@dataclass(frozen=True)
class Principal:
    subject: str
    audience: str
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    claims: Mapping[str, Any]

    def has_scope(self, scope: str) -> bool: ...


class TokenVerificationError(Exception): ...


class InternalTokenVerifier:
    def __init__(
        self,
        jwks_url: str,
        audience: str,
        issuer: str,
        *,
        leeway_seconds: int = 30,
    ) -> None: ...

    def verify(self, token: str) -> Principal: ...


def install_auth(app: FastMCP, verifier: InternalTokenVerifier) -> None: ...
def current_principal() -> Principal: ...
```

`InternalTokenVerifier` 内部包装 `PyJWKClient`（带缓存和刷新）。`verify` 校验失败时
抛出 `TokenVerificationError`，由 `server` 模块统一映射为标准 MCP 鉴权错误，避免每个
服务各自处理裸的 JWT 异常。`current_principal()` 通过 contextvar 读取当前请求绑定的
身份，供 Tool Handler 内部访问。

### 3.3 `mcp_runtime.server`

```python
@dataclass
class ServerRuntime:
    app: FastMCP
    config: RuntimeConfig


def create_server(
    config: RuntimeConfig,
    *,
    verifier: InternalTokenVerifier | None = None,
) -> ServerRuntime: ...

def run_server(runtime: ServerRuntime) -> None: ...
```

`create_server` 返回的 `app` 已经挂好 auth 中间件、健康检查端点和结构化请求日志；
服务在拿到 `ServerRuntime` 之后只需要用 `@runtime.app.tool()` 注册自己的 Tool，
再调用 `run_server(runtime)` 作为 `__main__.py` 的入口。

### 3.4 `mcp_runtime.workflow`

```python
class WorkflowClient:
    def __init__(self, address: str, namespace: str, task_queue: str) -> None: ...

    @classmethod
    async def connect(cls, config: RuntimeConfig) -> "WorkflowClient": ...

    async def start(
        self,
        workflow: type | str,
        *args: Any,
        workflow_id: str,
        task_queue: str | None = None,
    ) -> WorkflowHandle: ...

    async def result(self, workflow_id: str) -> Any: ...
    async def cancel(self, workflow_id: str) -> None: ...


def build_worker(
    client: WorkflowClient,
    *,
    workflows: Sequence[type],
    activities: Sequence[Callable[..., Any]],
) -> Worker: ...
```

`start` 使用 workflow_id 幂等语义（同一个 `workflow_id` 重复调用不会产生第二次
提交），对应 `architecture.md` §6.2 "计算服务使用相同的 `workflow_id` 幂等启动
Workflow"。`task_queue` 省略时默认使用本服务队列；显式传参也只允许传入
`RuntimeConfig` 派生出的队列名，不提供访问其他服务队列的路径。`build_worker`
供独立的 Worker 进程入口使用，与 MCP Server 进程分开部署。

### 3.5 `mcp_runtime.jobs`

```python
class JobStatus(str, Enum):
    PENDING = "pending"
    SUBMITTING = "submitting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobMixin:
    # Plain mixin, NOT a DeclarativeBase subclass: every direct subclass of
    # DeclarativeBase starts its own ORM registry, so a shared abstract base
    # would conflict with each service's own Base. Combine like:
    #   class Job(JobMixin, Base):
    #       __tablename__ = "job"
    #       ...domain-specific columns...
    id: Mapped[str]
    workflow_id: Mapped[str]
    status: Mapped[JobStatus]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ArtifactMixin:
    id: Mapped[str]
    job_id: Mapped[str]
    storage_key: Mapped[str]
    created_at: Mapped[datetime]


def generate_job_id(service_name: str) -> str: ...
async def create_engine_async(config: RuntimeConfig) -> AsyncEngine: ...
def create_engine_sync(config: RuntimeConfig) -> Engine: ...
```

`SUBMITTING` 状态对应 `architecture.md` §6.2 "Job 元数据写入和 Workflow 启动跨越
两个系统"这一段描述的中间态：Job 行已写入但尚未确认 Workflow 已经成功启动，
供后续的核对/恢复机制使用。`JobMixin`/`ArtifactMixin` 只定义跨服务共享的列，
且刻意不继承 `DeclarativeBase`（原因见代码注释）；各服务把它们和自己的
`DeclarativeBase` 子类组合，再添加领域字段。`create_engine_async` 用于 MCP Server
的并发请求路径，`create_engine_sync` 用于 Worker 进程，两者都从同一个
`RuntimeConfig.postgres_dsn` + `db_schema` 构造，保证连接目标和身份配置来源一致。

### 3.6 `mcp_runtime.storage`

```python
class ArtifactStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        namespace: str,
    ) -> None: ...

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "ArtifactStore": ...

    def put(self, key: str, data: BinaryIO, *, content_type: str | None = None) -> str: ...
    def get(self, key: str) -> BinaryIO: ...
    def presign_get(self, key: str, *, expires_in: int = 3600) -> str: ...
    def presign_put(self, key: str, *, expires_in: int = 3600) -> str: ...
    def delete(self, key: str) -> None: ...
```

所有方法接受的 `key` 都是命名空间内的相对路径，实现内部会拼接
`f"{namespace}/{key}"`；没有任何方法接受绝对路径或跨命名空间路径，
对应 `architecture.md` §4.7 对象存储部分"只有路径前缀而没有访问策略不构成安全
隔离"的要求——这里额外在客户端代码层面也做一次限制。

### 3.7 `mcp_runtime.observability`

选型：`structlog`，而不是裸 stdlib `logging`。理由是 `bind_context` 想要的语义——
"在这个作用域内，之后所有日志行都自动带上这几个字段"——正是 `structlog.contextvars`
内置提供的能力（`merge_contextvars` 处理器 + `bound_contextvars` 上下文管理器），
自己在 stdlib `logging` 上重新实现等于重复造轮子。代价是要把 `fastmcp`、
`sqlalchemy`、`temporalio`、`boto3` 这些走 stdlib `logging` 的三方库也接进同一条
JSON 输出链路，做法是 structlog 官方推荐的 `ProcessorFormatter` 集成：structlog
自身的处理器链和 stdlib root logger 的 `foreign_pre_chain` 共用同一组
"公共处理器"（`merge_contextvars`、`add_logger_name`、`add_log_level`、
`TimeStamper`、`StackInfoRenderer`、`format_exc_info`），最终都渲染成
`JSONRenderer()` 输出，保证容器 stdout 是一条格式一致的流
（对应 `architecture.md` §7.1 "容器标准输出和 journald"）。

```python
def configure_logging(config: RuntimeConfig) -> None: ...
def get_logger(name: str) -> structlog.stdlib.BoundLogger: ...

@contextmanager
def bind_context(**kv: Any) -> Iterator[None]: ...
```

与其他模块不同：`observability` 不依赖任何外部基础设施（不需要真的 Postgres、
Temporal、MinIO 或 Gateway），所以 `mcp-runtime/src/mcp_runtime/observability.py`
在这一版里是**真实实现**，不是骨架签名；`get_logger`/`bind_context` 是对
`structlog.get_logger`/`structlog.contextvars.bound_contextvars` 的薄封装，
`configure_logging` 按上面的 `ProcessorFormatter` 方案接管 stdlib root logger。

### 3.8 `mcp_runtime.testing`

```python
def fake_principal(**overrides: Any) -> Principal: ...

class InMemoryVerifier(InternalTokenVerifier):
    """接受任意 token，返回 fake_principal()，供服务自己的测试套件使用。"""
```

## 4. Non-goals

以下内容明确不属于 `mcp-runtime`，即使将来某个服务需要，也应该留在服务自己的
仓库或 Compute Job 镜像里：

- 任何 Tool 的业务参数校验和处理逻辑；
- `Job`/`JobStep`/`Artifact` 的领域字段和查询/Repository 层；
- Temporal Activity 的具体实现和 Compute Job 容器镜像；
- 定价、配额、准入策略（属于 Gateway 或平台级待决策事项，见 `architecture.md` §9.1）；
- Alembic 迁移文件内容（每个服务管理自己的 Schema 迁移，`mcp-runtime` 只提供
  Engine 构造）；
- Metrics/Tracing 具体供应商选型（`techstack.md` §9 标记为待定，`observability`
  模块只预留扩展点）。

## 5. 依赖

对应 `techstack.md` §5.1 "已采用的共享基础"，`mcp-runtime` 依赖：`fastmcp[apps]`、
`pyjwt`（含 `PyJWKClient`）、`temporalio`、`boto3`、`sqlalchemy[asyncio]`、
`asyncpg`、`pydantic-settings`、`structlog`。具体版本以 `pyproject.toml`/`uv.lock`
为准；`techstack.md` 只记录跨项目协作需要的选型和状态，不重复本文档已有的模块级细节。
