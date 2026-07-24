# 如何发布 `mcp-runtime`

本指南面向具有 Release PR 审批和合并权限的维护者。一次完整发布会产生不可变的
`vX.Y.Z` Git tag、GitHub Release、wheel 和 source distribution（sdist）。
`mcp-runtime` 不发布到包索引；消费方通过 Git tag 引用版本，并在自己的 `uv.lock`
中锁定解析后的 commit。

## `v0.2.0` 发布范围

`v0.2.0` 在 `v0.1.0` 的 authenticated private MCP server foundation 上增加下游服务
支持的鉴权契约测试层：

- typed `mcp_runtime.testing` 子模块，不改变顶层 `mcp_runtime.__all__`；
- 隔离的临时 RSA signing identity、canonical Credential 和内存 JWKS transport；
- 经真实 Bearer middleware 和 stateful Streamable HTTP Session 的进程内 Client；
- pytest-independent HTTP 401 断言，不向下游暴露 SDK/AnyIO 异常形状；
- 成功、拒绝、失败、并发退出和取消路径的资源与兼容 patch 清理；
- wheel 干净安装、`py.typed` 和 service-shaped 外部消费运行/类型检查。

该测试 Factory 不是生产 Gateway signer。`v0.2.0` 不增加任意 JWT builder、私钥运维、
外部 OAuth、业务授权、数据库、Artifact、S3 或 Temporal 能力。

## `v0.2.0` Go/No-Go 门禁

除通用发布门禁外，只有以下条件全部成立才可发布 `v0.2.0`：

- 公开 Factory 只生成 Platform 契约允许的 RS256 Credential，并在返回 Token 前拒绝
  空 subject、无效/重复 scope 和无效目标 service ID；
- 有效、缺失和其他服务 audience 用例通过真实 stateful Streamable HTTP 鉴权路径；
- Client 和断言不向下游暴露 FastMCP、MCP SDK、AnyIO 或 `ExceptionGroup` 细节；
- 并发、重复 lifespan、startup failure、401 和 cancellation 测试证明资源与兼容
  patch 被清理；
- `mcp_runtime.testing` 从安装 wheel 的隔离环境成功运行并通过外部消费类型检查；
- Quality job 和本地完整 coverage/distribution gate 全部通过；
- 维护者审批并合并 Release Please 生成的 `v0.2.0` Release PR。

## `v0.1.0` 发布范围

`v0.1.0` 只发布已批准的 authenticated private MCP server foundation：

- `RuntimeSettings`、`ServerSettings` 和 `InternalAuthSettings`；
- Gateway 内部 RS256 JWT 与 JWKS 验证；
- immutable `Principal` 和请求内 `get_principal()`；
- 固定安全策略的 stateful Streamable HTTP Server 组装与运行入口；
- 对应的单元测试、真实 JWT/JWKS wire 测试和 ASGI Streamable HTTP 集成测试。

数据库、Job/Artifact、S3、Temporal、健康探针、Gateway signer/JWKS Route、服务模板接入
和多副本 Session 协调不属于这个版本。它们是后续消费方驱动的切片，不是
`v0.1.0` 的发布阻塞项。完整边界与已知限制见
[`README.md`](../README.md) 和 [`authentication.md`](authentication.md)。

## `v0.1.0` Go/No-Go 门禁

只有以下条件全部成立，`v0.1.0` 才是 **Go**：

- Platform Internal Credential Contract 已合并；
- authenticated runtime 实现和文档已合并，公开 API 中没有占位实现；
- Runtime CI 的 lint、format、type、测试、statement/branch coverage 和 build 全部通过；
- Release Please 明确使用 pre-1.0 MINOR 破坏性变更策略和 `vX.Y.Z` tag；
- Release Notes 只描述最终存在的能力，并明确 `0.x` 兼容策略和当前限制；
- wheel/sdist 通过干净环境安装、`py.typed`、公开导入和外部消费类型检查；
- `XDenovo/mcp-runtime` 已启用 immutable releases；
- Release PR 已由维护者显式审批并决定发布。

CI 通过本身不等于发布决定。合并 Release PR 是维护者作出的显式、外部可见发布动作。

## Release Please 配置

[`release-please-config.json`](../release-please-config.json) 固定以下策略：

- `bump-minor-pre-major: true`：`0.x` 的 breaking change 产生 MINOR bump；
- `include-component-in-tag: false`：tag 使用 `vX.Y.Z`，不添加包名前缀；
- `draft-pull-request: true`：Release PR 在人工审查前保持 Draft；
- `draft: true`：先创建 Draft Release，上传并核验产物后才发布；
- `bootstrap-sha`：首版 Changelog 从 repository reset 之后开始，排除已经删除的
  placeholder API 历史。

`bootstrap-sha` 只影响首次发布；`v0.1.0` 生成后，Release Please 会以最近已发布版本
作为后续 Changelog 的起点。

## 发布前确认

### 找到并审查 Release PR

日常变更合并到 `main` 后，[`release-please`](https://github.com/googleapis/release-please)
会创建或更新带 `autorelease: pending` 标签的 Draft PR。不要只依赖可能变化的 PR 标题。

审查时确认：

- `.release-please-manifest.json`、`pyproject.toml` 和 `CHANGELOG.md` 使用同一版本；
- `CHANGELOG.md` 与 PR 描述准确概括实际存在的用户可见能力；
- 破坏性变更包含具体迁移说明；
- 首版说明 `0.x` 兼容策略与已知限制；
- CI 的 `Quality` job 通过。

若有应发布的提交但没有 Release PR，检查
[`release-please.yml`](../.github/workflows/release-please.yml)。若
`Generate release-please token` 失败，确认 `xdenovo-release-bot` 仍安装在本仓库，
并由组织管理员检查 `APP_ID` 和 `APP_PRIVATE_KEY` secrets。不要改用默认
`GITHUB_TOKEN` 绕过组织策略。

### 本地验证

从干净的发布候选分支运行：

```bash
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
uv run --no-sync pytest \
  --cov=mcp_runtime \
  --cov-config=pyproject.toml \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-fail-under=90
uv build
uv run --no-sync python scripts/validate_distribution.py dist/*.whl
```

最后一条命令接收 `uv build` 生成的明确 wheel；若本地 `dist/` 留有多个版本，请把通配符
替换成当前构建的具体文件名。它从下游服务的公开边界验证：

- wheel 可安装到独立 Python 3.13 环境；
- 安装包包含标准 `py.typed` marker；
- service-shaped consumer 能生成 Credential，并通过真实鉴权会话列出 Tool；
- 同一份 consumer 源码能针对安装产物通过 `ty`。

`uv build` 仍生成并检查可构建的 sdist，Release workflow 也会验证并上传一个 sdist；
distribution smoke 不再重复安装 sdist 或枚举 archive 内部文件。

## 合并并监控发布

1. 审批 Release PR 并将其标记为 Ready。
2. 合并 Release PR；不要预先手工创建 tag 或 Release。
3. 观察该 merge 触发的 `Release Please` workflow。
4. Workflow 在调用 Release Please 前构建并验证产物。
5. Release Please 创建 Draft Release。
6. Workflow 上传 wheel 与 sdist，确认 Draft 中各有且仅有一个对应产物。
7. 只有上述步骤全部成功，Workflow 才把 Draft 发布为正式 Release。

仓库必须在首次发布前启用 immutable releases。发布后，GitHub 会锁定 Release
资产和关联 tag；修复必须使用更高版本，不能移动 tag 或替换资产。

## 验证发布结果

逐项确认：

- `Release Please` workflow 成功；
- tag 恰为预期的 `vX.Y.Z`，并指向 Release PR merge commit；
- GitHub Release 已发布、不是 Draft，并标记为 immutable；
- Release Notes 与已批准的 `CHANGELOG.md` 一致；
- Release 同时包含一个 wheel 和一个 sdist；
- tag 中 `.release-please-manifest.json`、`pyproject.toml` 和 `CHANGELOG.md`
  版本一致；
- 下载 Release wheel 到干净目录后，再次运行隔离 import smoke test。

这些检查完成后，才能关闭发布工作和对应的 Platform Initiative。

## 处理发布失败

若 build 或 distribution validation 失败，Release Please 尚未运行，因此不会创建 tag
或 Release。修正根因后重新运行 workflow。

若 Draft Release 创建后，上传或产物核验失败，Draft 保持未发布；不要手工发布它。
修正根因后重跑 workflow，上传步骤允许覆盖 Draft 中的同名产物。

若正式 Release 已发布后发现缺陷，immutable release 不允许替换资产或移动 tag。
保留原版本，通过新的更高版本修复；消费方应恢复到上一已知 commit 或升级到修复版本。
