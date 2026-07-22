# mcp-runtime 发布流程

`mcp-runtime` 只发布 Git Tag，不搭建私有包 registry。消费方通过 `uv` 的 Git 依赖
直接锁定某个 tag，见本文第 4 节。职责和公开 API 见 [`design.md`](./design.md)。

## 1. 版本策略

SemVer，Tag 格式 `vX.Y.Z`。项目目前处于 0.x 阶段（初始开发），按 SemVer 关于
initial development 的规则，破坏性变更允许体现为 MINOR 版本号变化，不要求跳到
`1.0.0`；`release-please` 会按这个规则把 `feat!:`/`BREAKING CHANGE:` footer 的
提交映射成 MINOR bump，而不是 MAJOR bump。到了 API 稳定、多个真实服务已经在生产
消费之后，再评估切到 `1.0.0`。

## 2. 发布自动化：release-please

版本号和 CHANGELOG 都由 [`release-please`](https://github.com/googleapis/release-please)
从 Conventional Commits 自动计算，不手动维护：

- `release-please-config.json` / `.release-please-manifest.json`：单包配置，
  `release-type: python`，包路径是仓库根目录。
- `.github/workflows/release-please.yml`：每次 push 到 `main` 都会运行。它会维护
  一个常驻的 `chore(main): release X.Y.Z` PR，PR 里包含自动生成的 `CHANGELOG.md`
  条目和 `pyproject.toml` 里 `version` 字段的更新。

### 2.1 为什么用 GitHub App，而不是默认 `GITHUB_TOKEN`

`XDenovo` 组织级别禁止 Actions 用默认 `GITHUB_TOKEN` 创建或批准 PR，这是组织级硬
限制，**不能**在单个仓库里覆盖（repo 级别的 `actions/permissions/workflow` API
会直接返回 409）。这条限制会挡住 org 里任何仓库的任何"自动开 PR"的 workflow，
不只是这里的 release-please。

因此没有直接打开组织级开关（那会让 org 里所有仓库的所有 workflow 都能开/批
PR，攻击面比"只让 release-please 开它自己的那种 PR"大得多），而是用一个权限
收窄到 `Contents: write` + `Pull requests: write` 的 GitHub App
（`xdenovo-release-bot`，只装在需要的仓库上）来发短期 token。App 的 `APP_ID`/
`APP_PRIVATE_KEY` 存成**组织级 secret**（目前 visibility 限定在 `mcp-runtime`），
workflow 里用 `actions/create-github-app-token` 换出 token 再传给
`release-please-action`，而不是用 `secrets.GITHUB_TOKEN`。以后其他仓库
（`pepmimic-mcp`/`graphpep-mcp`/`bindcraft-mcp`/Website/Gateway）要接类似的
自动开 PR 流程时，直接把这两个组织级 secret 的 visibility 加上对应仓库即可，
不用重新建 App。

发布流程：

1. 日常改动通过 PR 合并进 `main`，PR 标题/commit 遵循 Conventional Commits
   （`feat:`、`fix:`、`feat!:`/`BREAKING CHANGE:` 等），这是 `AGENTS.md` 里已经要求
   的规范，`release-please` 直接复用它来判断版本号怎么变。
2. release-please 持续更新那个常驻 release PR，不会自动合并。
3. **人工决定何时发布**：确认要发的时候，合并那个 release PR。合并动作本身触发
   release-please 打 Tag、创建 GitHub Release。
4. `.github/workflows/release-please.yml` 里的后续步骤检测到
   `release_created` 后，会 `uv build` 出 sdist/wheel 并上传到对应 Release，方便
   直接下载，但这不是消费 `mcp-runtime` 的主要方式（见第 4 节）。

## 3. CI 门禁

`.github/workflows/ci.yml` 在每次 push/PR 到 `main` 时跑
`ruff check` / `ruff format --check` / `ty check` / `pytest` / `uv build`。
release PR 本身也是一个普通 PR，会经过同一套门禁。

## 4. 消费方式（前瞻性说明）

`mcp-service-template` 和三个真实服务尚未接入，这里只记录预期的用法，方便以后
对照实现：

```toml
dependencies = [
    "mcp-runtime @ git+https://github.com/XDenovo/mcp-runtime.git@v0.1.0",
]
```

`uv.lock` 会把这个 Git 依赖解析到具体的 commit，锁定结果不会因为 `mcp-runtime`
后续新提交而漂移；升级版本时手动把 `@v0.1.0` 改成新 tag，再 `uv lock` 重新解析。
