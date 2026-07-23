# 如何发布 `mcp-runtime`

本指南面向具有 Release PR 审批和合并权限的维护者。一次完整发布会产生
不可变的 `vX.Y.Z` Git tag、GitHub Release、wheel 和 source distribution
（sdist）。`mcp-runtime` 不发布到包索引；消费方通过 Git tag 引用版本，并在
自己的 `uv.lock` 中锁定解析后的 commit。

> [!WARNING]
> `v0.1.0` 当前为 **No-Go**。在 [`TODO.md`](../TODO.md) 的最终发布门禁全部满足前，
> 不得合并 Release PR，也不得创建或移动发布 tag。
>
> 当前 [`release-please-config.json`](../release-please-config.json) 还没有显式设置
> `bump-minor-pre-major: true` 和 `include-component-in-tag: false`。在配置与下述
> 版本和 tag 策略一致前，不得合并 Release PR。

## 发布前确认

### 确认版本已经具备发布条件

确认当前版本的发布 Issue 或检查清单已经给出明确的 Go 决定。对于
`v0.1.0`，使用 [`TODO.md`](../TODO.md) 的最终发布门禁；CI 通过本身不代表
版本已经可以发布。

如果本次发布包含公开 API 的破坏性变更，确认
[`design.md`](./design.md)、行为测试、Release Notes 和消费方迁移说明已经同步更新。

### 找到 Release PR

日常变更合并到 `main` 后，[`release-please`](https://github.com/googleapis/release-please)
会根据 `main` 上的 Conventional Commits 创建或更新 Release PR。查找带有
`autorelease: pending` 标签的开放 PR，不要依赖可能随配置变化的 PR 标题。

如果存在应发布的提交但没有 Release PR，先检查
[`Release Please` workflow](../.github/workflows/release-please.yml)。若
`Generate release-please token` 步骤失败，确认 `xdenovo-release-bot` 仍安装在
本仓库，并请组织管理员检查 `APP_ID` 和 `APP_PRIVATE_KEY` secrets 的可见范围。
不要改用默认 `GITHUB_TOKEN` 绕过该流程；XDenovo 组织策略禁止它创建或批准 PR。

### 核对目标版本和 tag

`mcp-runtime` 使用 SemVer。审查 0.x Release PR 时，至少核对以下约束：

- `fix:` 产生 PATCH bump；
- `feat:` 产生 MINOR bump；
- `feat!:`、其他带 `!` 的类型或 `BREAKING CHANGE:` footer 产生 MINOR bump；
- tag 必须为 `vX.Y.Z`，不得包含包名或其他前缀。

其他提交类型是否形成发布由 `release-please` 的 Python 策略和仓库配置决定；
如果 Release PR 提议的版本无法由 `main` 上的提交解释，也应停止发布。

上述 breaking-change 和 tag 策略依赖
[`release-please-config.json`](../release-please-config.json) 中的
`bump-minor-pre-major: true` 和 `include-component-in-tag: false`。如果配置缺少任一
设置，或者 Release PR 提议的版本与策略不一致，停止发布并先修正自动化。

发布 `1.0.0` 需要单独确认 API 已经稳定并批准版本策略变更，不能仅通过修改
Release PR 或手工创建 tag 完成。

### 审查 Release PR

确认 Release PR 对以下文件使用同一个目标版本：

- `.release-please-manifest.json`；
- `pyproject.toml`；
- `src/mcp_runtime/__init__.py` 中的 `mcp_runtime.__version__`；
- `CHANGELOG.md` 中的新版本条目。

检查 `CHANGELOG.md` 和 PR 描述是否准确概括用户可见变更。破坏性变更必须包含
具体迁移步骤；首个版本还必须说明已知限制。如果版本文件不一致，停止发布并修正
`release-please` 配置或版本来源，不要通过手工修改 tag 补偿。

最后确认 Release PR 已获得要求的人工审批，且
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) 中的 `Quality` job 全部
通过。

## 合并并监控发布

1. 合并已经批准的 Release PR。不要在此之前手工创建 tag 或 GitHub Release。
2. 打开这次合并触发的 `Release Please` workflow run。
3. 等待 workflow 创建 tag 和 GitHub Release，然后从该 tag 构建 wheel 与 sdist 并
   上传到 Release。
4. 只有整个 workflow 成功后，才进入发布结果验证。

Release PR 不会自动合并；合并动作是维护者作出的显式发布决定。

## 验证发布结果

逐项确认：

- `Release Please` workflow run 成功；
- tag 名为预期的 `vX.Y.Z`，并指向合并后的 Release PR commit；
- GitHub Release 已发布，Release Notes 与已批准的变更内容一致；
- Release 同时包含 wheel 和 sdist；
- tag 中的 `.release-please-manifest.json`、`pyproject.toml`、
  `mcp_runtime.__version__` 和 `CHANGELOG.md` 版本一致；
- 当前版本发布清单要求的干净环境安装和 smoke test 已通过。

对于 `v0.1.0`，还必须完成 [`TODO.md`](../TODO.md) 中从最终 tag 安装并执行 smoke
test 的步骤。所有检查完成后，才能在发布 Issue 中将发布标记为完成。

## 处理发布失败

如果 workflow 在创建 tag 和 GitHub Release 前失败，修正根因后重新运行 workflow；
不要改为手工创建发布对象。

如果 tag 或 GitHub Release 已经创建，但构建或附件上传失败：

1. 将此次发布视为不完整，不要对外宣告成功；
2. 不要移动、删除或复用已经创建的 tag；
3. 在发布 Issue 中记录已创建的对象、失败步骤和 workflow run；
4. 按经过批准的恢复流程补齐发布，或发布一个更高的新版本。

在首个版本发布前，必须先解决 [`TODO.md`](../TODO.md) 中“release workflow
失败时不会留下被误认为完整发布的 Release”这一门禁。如果完整发布后才发现
产品缺陷，保留原有 tag，并通过新的更高版本修复；需要回滚的消费方应恢复到
上一已知可用的 tag 或已锁定 commit。
