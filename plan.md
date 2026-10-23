# Oh Story Lite：双 Skill 自动同步仓库实施计划

> **状态**：已发布 GitHub Public Repo；CI 与正式 Release 无变化同步已远端通过。M4 真实会话/模型验收及真实上游更新 PR 的远端交付仍待实际发生。  
> **编写日期**：2026-10-21  
> **建议仓库名**：`oh-story-lite`（GitHub Public Repository）  
> **目标用户环境**：Windows + DeepSeek Harness（DSH）  
> **核心目标**：持续跟随 Oh Story 上游更新，但仓库内只分发「长篇正文写作」与「去 AI 味」两个 Skill。

> **本地实施记录（2026-10-21）**：已初始化本地 Git、完成依赖核查、固定 SHA 首次导入、候选同步器与本地验证；未创建远端仓库或发布。实际验收与限制见 [docs/local-validation.md](docs/local-validation.md)。此处 M0～M2 对应后续讨论中的开发里程碑，覆盖下面 Phase 0 的本地部分及 Phase 1～2；下列远端设置仍未完成。

> **M3 本地实施记录（2026-10-22）**：已实现独立 CI、最小权限双 Job 同步、SHA 锁定与产物复核；actionlint、70 项离线测试及三种本地场景重放通过。未创建公开仓库、推送或触发远端 Actions。详见 [docs/m3-validation.md](docs/m3-validation.md)。

> **M4 安装器实施记录（2026-10-22）**：已实现 `install.ps1` 的本地安装、备份、完整升级、精确回滚和事务恢复；98 项测试通过，包括新增 28 项安装器测试。PowerShell 5.1 / 7 及 junction 拒绝均在隔离目录验证，未安装到真实 Skills 目录。详见 [docs/m4-validation.md](docs/m4-validation.md)。

> **M4 DSH 发现记录（2026-10-23）**：本机 DSH `0.2.1-rc.2` 原模块在最小隔离 Context 中通过 9 项发现、加载及优先级检查；完整回归 107 项通过。缺失专业 preset 返回 not-found；已加载 Skill 的 solo/direct 约定不是运行时自动路由，模型遵循尚未验证。未改真实 Skills 或运行模型写作。详见 [docs/dsh-discovery.md](docs/dsh-discovery.md)。

> **公开部署（2026-10-23）**：用户已授权创建并发布 [upuphero/oh-story-lite](https://github.com/upuphero/oh-story-lite)，明确保留自动更新 PR、人工审核合并。GitHub CI 的 Ubuntu / Windows / actionlint 均通过，首次手动同步确认无相关变化、不生成 PR。见 [docs/github-deployment.md](docs/github-deployment.md)。早期“未发布”记录保留为各阶段历史范围。

## 0. TL;DR：最终想得到什么

建立一个独立 Public Repo，使用 GitHub Actions 定时检测上游的**正式 Release**。检测到以下两个 Skill 的实际文件变化后，将上游快照同步到新分支，完成检查，再创建更新 PR；由维护者审核后合并。没有相关变化就不创建 PR。

**只分发两个 Skill**：

1. `story-long-write`：根据现有大纲、细纲创作和续写长篇正文；保留其必需的 `SKILL.md`、`references/`、`scripts/`。
2. `story-deslop`：对正文进行表达、叙事用笔、故事因果三层检查和精修；保留其必需的 `SKILL.md`、`references/`、`scripts/`。

不分发选题扫榜、拆文、封面、短剧、游戏、视频等 Skill；也不发布任何私人小说、大纲、设定、API Key 或本机 DSH 配置。

**核心约束**：第一阶段是「两个完整 Skill 的精简镜像」，不是随意删除这两个 Skill 内的流程文件。上游 `story-long-write` 仍然依赖它自己的细纲协议、追踪状态与写后检查；要进一步去掉这些约束，必须作为第二阶段的可审查适配工作，不能在同步时静默裁剪。

---

## 1. 已核实的上游情况与架构决策

### 1.1 唯一上游来源

- **权威源码**：<https://github.com/zenstory-ai/oh-story-claudecode>
- **DSH 封装项目**：<https://github.com/zenstory-ai/oh-story-dsh>
- 2026-10-21 核对的最新已发布版本：通用 Oh Story `v0.9.0`（2026-10-18）；DSH 插件 `v0.1.18`（2026-10-19）。
- DSH 插件将上游 Oh Story 内置于 `packages/knowledge/oh-story/skills/`。经对比，两个目标 Skill 的 `SKILL.md`、关键参考文档和检查脚本与通用仓库对应内容一致。

**决策**：自动同步只跟踪 `zenstory-ai/oh-story-claudecode` 的稳定 Release，不同时从两个仓库混合复制文件。DSH 仓库只作为兼容性参考。避免 DSH 插件升级了 UI 但没有改变小说 Skill 时产生无意义更新。

### 1.2 两个 Skill 必须按目录完整复制

上游的一个 Skill 并不等于一个 `SKILL.md` 文件。它的引用资料和脚本均是运行时资产。同步白名单如下：

```text
upstream: zenstory-ai/oh-story-claudecode
├── skills/story-long-write/**  -> 本仓库 skills/story-long-write/**
├── skills/story-deslop/**      -> 本仓库 skills/story-deslop/**
└── LICENSE                    -> 本仓库 LICENSE
```

这两个子树在当前版本中分别约有 **90** 和 **12** 个文件（目录与文件数将来可以变化）；应完整同步而不是人工维护文件白名单。额外目录一律不得同步。

许可证：上游为 MIT，`LICENSE` 内原版权声明必须完整保留。仓库 README 另注明 `zenstory-ai` 来源、上游提交与修改范围；不要将镜像仓库误称为上游官方项目。

### 1.3 同步策略

| 项目 | 决策 |
|---|---|
| 仓库 | `OWNER/oh-story-lite`，Public |
| 默认跟踪 | 上游**最新正式 Release**，而非每次 `main` 提交 |
| 源码锁定 | Release tag + 解析后的完整 commit SHA |
| 检查频率 | 每日一次；另外支持手动触发 |
| 变更判定 | 比较两个 Skill 的**文件内容和相对路径**，不是只比较 tag |
| 变更交付 | 自动创建或更新一个同步 PR，绝不直接 push 到 `main` |
| 合并策略 | 维护者人工审核；初期不启用自动合并 |
| 本地安装 | 从本仓库只安装/复制两个 Skill 到 DSH 能读取的 Skills 目录 |
| 本地个性化规则 | 单独存放在 `prompts/` 等非上游目录，避免同步覆盖 |

**为什么不默认跟踪 `main`？** 上游主分支随时可能含尚未发布的改动。个人日常写作更需要可回退和可复现。未来可添加 `workflow_dispatch` 参数 `ref`，允许手动尝鲜上游指定 tag 或完整 SHA，但不能默认自动合并。

---

## 2. 建议的仓库结构

```text
oh-story-lite/
├── README.md                         # 项目介绍、安装、使用、上游声明
├── plan.md                           # 本实施计划
├── LICENSE                           # 从上游原样保留的 MIT License
├── NOTICE.md                         # 上游归属、同步原则、非官方声明
├── upstream-lock.json                # 上次已接受的上游 tag、SHA、两子树摘要
├── .gitignore
├── skills/
│   ├── story-long-write/
│   │   ├── SKILL.md
│   │   ├── references/                # 全部必要资料；完整保留上游子目录
│   │   └── scripts/                   # 原始配套脚本；完整保留上游子目录
│   └── story-deslop/
│       ├── SKILL.md
│       ├── references/
│       └── scripts/
├── prompts/
│   ├── write-from-outline.md         # 用户定制的正文任务提示（不是 Skill）
│   └── revise-prose.md               # 用户定制的精修任务提示（不是 Skill）
├── scripts/
│   ├── sync_upstream.py              # 固定 Release/SHA、复制两子树、生成锁文件
│   ├── validate_layout.py            # 校验精简范围、目录、文件完整性及许可
│   ├── validate_references.py        # 检查相对链接和脚本依赖路径
│   └── check_sync_diff.py            # 判断两子树是否真正变化
├── tests/
│   ├── fixtures/
│   │   ├── clean.md                   # 干净样例
│   │   └── ai-patterns.md             # 有意触发句式检查的样例
│   └── test_sync.py                   # 同步器的离线单元测试
└── .github/
    └── workflows/
        ├── sync-upstream.yml         # 定时/手动检查 -> 验证 -> 创建 PR
        └── ci.yml                    # PR 和 push 的独立质量检查
```

`skills/` 下**严格只有上述两个一级目录**。仓库根部的同步脚本、测试、说明文档是维护工具，不是第三个可供 Agent 调用的 Skill。

`upstream-lock.json` 示例（字段约定，SHA 在首次同步时由脚本解析写入，不填写占位值发布）：

```json
{
  "upstream": "zenstory-ai/oh-story-claudecode",
  "release_tag": "v0.9.0",
  "commit_sha": "<resolved-40-character-sha>",
  "paths": ["skills/story-long-write", "skills/story-deslop"],
  "content_digest_sha256": "<deterministic-content-sha256>"
}
```

摘要按相对路径排序后，对「文件路径 + 原始文件字节」做稳定编码再计算 SHA-256；忽略时间戳、文件复制顺序。不要在无相关变更时为了更新日期而修改此文件。

---

## 3. GitHub Actions 自动同步 Pipeline

### 3.1 触发机制

`sync-upstream.yml`：

```yaml
name: Sync upstream Oh Story skills

on:
  schedule:
    - cron: '23 9 * * *'  # 每日 09:23 UTC，避开整点拥挤
  workflow_dispatch:

concurrency:
  group: oh-story-upstream-sync
  cancel-in-progress: false
```

说明：cron 是**轮询**，不是上游发布时即时 webhook。GitHub 定时任务可能延迟或漏跑，Public Repo 长期无活动时也可能被自动禁用；保留 `workflow_dispatch` 作为手动恢复入口。

### 3.2 两个 Job：安全隔离

**Job A：`prepare-and-validate`（`contents: read`）**

1. 从 GitHub Releases API 获取最新正式 Release，拒绝 `draft` / `prerelease`；允许手动指定受信任的 tag 或完整 SHA。
2. 解析 tag 指向的完整 commit SHA；从该**不可变 SHA**取快照，不依赖可变的 `main`。
3. 只提取 `skills/story-long-write/`、`skills/story-deslop/` 和 `LICENSE`；拒绝跳出允许目录的相对路径、符号链接、异常文件类型。
4. 检查两个 Skill 的 `SKILL.md`、`references/`、`scripts/` 均存在；核对全部相对引用与必要脚本。
5. 将候选快照与当前 `skills/` 两子树对比，忽略其他上游目录的变化。若完全一致，报告 `No relevant changes` 并结束，不创建 PR。
6. 运行静态和样例检查。**即使上游内容需要执行，也只能在此无写权限、无发布凭据的 Job 中运行。**
7. 保存经过校验的两个 Skill、`LICENSE`、`upstream-lock.json` 为临时构建产物，并输出内容摘要。

**Job B：`create-update-pr`（`contents: write`、`pull-requests: write`）**

1. 只在 Job A 验证通过且两子树有实际变化时运行。
2. 从可信的默认分支签出本仓库，下载候选产物，再次检查路径白名单和 SHA-256 摘要。
3. 仅替换 `skills/story-long-write/`、`skills/story-deslop/`、`LICENSE` 与 `upstream-lock.json`；不得覆盖 `README.md`、`prompts/`、维护脚本或工作流。
4. 使用受信任的 PR 创建流程，例如 `peter-evans/create-pull-request`，固定更新分支 `bot/sync-oh-story`；若已有同一 PR，更新它，避免重复开 PR。
5. **不运行从上游下载的任何 JS/Python/安装脚本**，不执行 `npm install`、`postinstall` 等可能执行上游代码的指令。
6. PR 标题示例：`chore(sync): Oh Story v0.9.x writing/deslop skills`。
7. PR 正文列明原始 tag、完整 SHA、变更文件数量、两子树的 diff 摘要、静态测试结果、任何依赖变化及回退方式。

> GitHub 仓库需在 **Settings → Actions → General → Workflow permissions** 中允许 Actions 创建 PR，并赋予相应 Token 权限。Job A/Job B 需要分别声明最小权限；不要将 PR 写权限传给执行上游代码的 Job。

> 当前 GitHub 对 `GITHUB_TOKEN` 创建的 `pull_request` 工作流有额外审批规则：这类 PR 的 CI 运行可能进入 **requires approval** 状态，需要具有仓库写权限的维护者批准。不要以为 PR 出现就代表 CI 已跑完。首版以 Job A 已完成的验证为准，同时保留 `ci.yml`，等维护者批准 PR 检查再合并。未来如确实需要无人值守触发检查，再评估 GitHub App token，而非扩大默认 Token 权限。

**严禁**为了方便而使用 `pull_request_target` 检出外部未审查代码并执行。

### 3.3 同步器具体算法

`sync_upstream.py` 采取 **allowlist snapshot** 模式，不直接执行 `git subtree merge`、不复制整个仓库后再依赖黑名单删除：

```text
resolve_release()
  -> tag + immutable_sha
fetch_archive(immutable_sha)  # 仅读取上游数据
assert_safe_paths()           # 禁止 path traversal、symlink、特殊文件
stage_only(
  skills/story-long-write/**,
  skills/story-deslop/**,
  LICENSE
)
validate_snapshot()
new_digest = hash_allowed_subtrees()
if new_digest == current_digest:
    exit_noop()
else:
    write_upstream_lock()
    emit_validated_snapshot_for_pr()
```

**重要细节**：

- 删除处理：上游若删除了两个目录内的文件，应在候选快照中同步删除，不保留旧文件。同步时先重建临时子树再原子替换，不能简单 `cp` 追加。
- 上游更名：若 `story-long-write` 或 `story-deslop` 被删除/更名，CI 必须失败并发出清晰日志，不能默默生成空目录。
- 版本变化但内容未变化：不更新锁文件，不开 PR，避免因其他 11 个 Skill 的更新制造噪声。
- 更新涉及新跨目录依赖：先阻断 PR 并标为 `manual adaptation required`，不能偷偷引入第三个 Skill。
- 同步脚本本身的更新走正常人工 PR，不能让上游更新修改 `.github/workflows/` 或 `scripts/`。
- 任何自动提交的 PR 一律先人工审查，不启用 auto-merge。

---

## 4. CI 检查与验收标准

`ci.yml` 的 `pull_request` / `push(main)` 检查（Node.js、Python 都不调用付费模型）：

| 检查 | 通过条件 |
|---|---|
| 目录白名单 | `skills/` 下一级目录**恰好是** `story-long-write` 和 `story-deslop` |
| Skill 元数据 | 两个 `SKILL.md` 存在，frontmatter 名称分别严格匹配目录名 |
| 资产完整性 | 相对 Markdown 链接目标存在、必要脚本存在、不出现越界引用 |
| Python 语法 | 对 `skills/**/scripts/*.py` 编译检查通过 |
| JavaScript 语法 | 对 `skills/**/scripts/*.js` 运行 `node --check` 通过 |
| 去味正向样例 | `check-ai-patterns.js` 与 `check-degeneration.js` 对干净样例返回 0 |
| 去味反向样例 | 有意触发的阻断样例报告对应 finding，返回预期错误码 |
| 版本溯源 | lock 中 tag、完整 SHA、内容摘要与候选文件相符 |
| License | 保留原 MIT 版权及许可正文 |
| 无私人数据 | 不得出现小说正文、大纲、`.env`、凭据、DSH token 与本机绝对个人路径 |
| 无意外执行 | 无 `npm install` / 任意上游 shell 脚本在 PR 写权限 Job 内运行 |

此外，在 Windows Runner 上做一项简单的 Skills 安装/发现 smoke test；确认两个目录能被复制进 `~/.agents/skills`，并能被目标 DSH 版本发现。**目录发现通过不能冒充端到端模型写作通过**。完整版端到端写作需要真实 DSH 会话，另设人工验收，不依赖付费模型跑每次定时 CI。

`validate_references.py` 应区别：

1. **强依赖**：被 Skill 或脚本要求直接读取的本地文件，缺少即失败。
2. **文档链接**：链接到其他上游 Skill 的说明、可选路由，不等于必须打包第三个 Skill；可允许但需要报告。
3. **动态依赖**：运行时拼接的脚本路径，需要建立显式测试清单，不能只靠 Markdown 链接扫描证明完整性。

---

## 5. Windows + DSH 的安装与升级方案

### 5.1 独立 Skills 路径（推荐首版）

目标目录：

```text
%USERPROFILE%\.agents\skills\
├── story-long-write\
│   ├── SKILL.md
│   ├── references\
│   └── scripts\
└── story-deslop\
    ├── SKILL.md
    ├── references\
    └── scripts\
```

本仓库 README 提供一个 **PowerShell 安装/更新脚本**（后续实施）：

```powershell
# 将 OWNER 换成自己的 GitHub 用户名；实际脚本应先备份已有同名目录
$repo = 'https://github.com/OWNER/oh-story-lite.git'
$src = Join-Path $env:TEMP 'oh-story-lite-install'
$dst = Join-Path $HOME '.agents\skills'

# 首次安装演示：目标同名目录应尚不存在
if (Test-Path $src) { Remove-Item $src -Recurse -Force }
git clone --depth 1 $repo $src
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item (Join-Path $src 'skills\story-long-write') $dst -Recurse
Copy-Item (Join-Path $src 'skills\story-deslop') $dst -Recurse
```

升级不能盲目在旧目录上 `Copy-Item -Force`，因为那会留下已被上游删除的旧文件；应**先备份、删除两个目标 Skill 目录，再从通过 CI 的仓库快照完整安装**。不得删除其他用户 Skill。推荐提供 `install.ps1` 来处理下载、版本显示、备份与原子替换。

### 5.2 与 `oh-story-dsh` 插件的边界

- DSH 能读取 `~/.agents/skills`。若已安装 `oh-story-dsh` 插件，同名全局 Skill 的优先级可能**高于**插件内置 Skill，实际行为以当前运行时的加载结果为准。
- 两个原始 Skill 不会因为放到该目录就自动得到 DSH 插件专属的 `oh_story_role` 调度、Hooks、写入保护和小说三栏工作台。
- 没有专用 Role 时，可能降级为 DSH 主 Agent 直接执行写作与去味；要在真实会话中测试这一回退路径。
- **不要混装并假定等价**。首版建议采用「普通 DSH + 本仓库两个 Skill」，若希望保留原生 Role/工作台，另设专门的 DSH Lite 适配项目，不在此次镜像同步范围内。
- 运行模型使用 DSH 当前已配置的模型供应商；Skill 文件不是模型或 API 代理，本仓库不保存 API Key。

### 5.3 对已有小说的最小打扰

在**私人、本地**的小说 Workspace 中保留已定的总纲、卷纲、细纲、人物设定、正文、文风文件，不要求把内容上传到 Public Repo。

```text
本地私人小说项目（不推送到 oh-story-lite）
├── 大纲/...
├── 设定/...
├── 正文/...
└── 追踪/...  # 仅正式长篇工作流需要；由对应脚本维护
```

第一次测试：复制一份小说项目，指定其中一章，验证「从细纲写正文 → 去味 → 备份原文 → 再运行检测脚本」，核对剧情、伏笔、字数与文件变更。绝对不要直接拿唯一原稿进行第一次试运行。

---

## 6. 第二阶段：可选的“只写正文” Lite 行为适配

这是与「仓库只包含两个 Skill」不同的目标，应在第一阶段稳定后再做。

### 6.1 现有上游 `story-long-write` 的隐藏成本

它不只是正文生成提示词，还要求按条件调用如下组件：

- `workflow-chapter.md`、`writing-craft.md`、`long-format.md` 等参考方法。
- 章节细纲结构检查、`build_writer_prompt.py` 等组装器。
- `tracking_commit.py`、`storyctl.py` 等连续性状态及字数/检查工具。
- 如果能用专业 `narrative-writer`，按其协议调用；否则由主 Agent 执行。

所以 **v1 必须如实保留这些能力和前置条件**，不能承诺放进两个文件后就能完全绕开项目初始化直接写正文。

### 6.2 如果确实不想要追踪/建纲系统

在本仓库追加一个本地补丁层，例如 `patches/story-long-write-lite.patch`，但遵循以下规则：

1. 仍只发布两个运行时 Skill 名称：`story-long-write` 和 `story-deslop`。
2. 将「可选规划」与「真正写正文需要的输入」拆开，正文只消费用户现有大纲、细纲、相关设定、最近章节与文风要求。
3. 原始细纲不强制重格式化；未提供的事实不能让模型凭空编造。
4. 取消追踪时，以较轻的 `previous-chapter-summary.md` / `continuity.md`（保存在**私人小说目录**）替代，而不是声称获得原工作流相同的连续性保证。
5. 核心 `story-deslop` 的三层审读规则和两套确定性检查保留；不因为 Lite 就牺牲完整性。
6. 补丁必须可重复应用：**先同步上游原始子树 → 再应用明确版本化补丁 → 跑全部检查**。若补丁冲突或原调用链发生变化，更新 PR 标为失败，人工处理。
7. 在 README 中明确标记为 **forked adaptation**，不宣称与上游 Skill 等价。

**建议排序**：先做不改上游核心内容的 `prompts/write-from-outline.md`、`prompts/revise-prose.md` 和实测；只有现有项目协议的摩擦已经确定时，才进入补丁版。

---

## 7. 分阶段实施任务

### Phase 0：仓库初始化

- [x] 新建 GitHub **Public** Repo：`upuphero/oh-story-lite`，默认分支 `main`。
- [x] 启用 Actions；设置 `Allow GitHub Actions to create and approve pull requests`，默认 Token 权限为 read。
- [x] 建立 main 的 PR 和质量检查保护，不启用自动合并。
- [x] 放入 `README.md`、`NOTICE.md`、`LICENSE`、`plan.md`、`.gitignore`。
- [x] 明确 `.gitignore` 排除 `.env`、个人日志、本地工作区、小说正文等不应出现的文件。

### Phase 1：首次精简导入

- [x] 从正式 `v0.9.0` 对应 immutable commit 构建首个快照。
- [x] 只复制 `story-long-write/**` 和 `story-deslop/**`。
- [x] 写入 `upstream-lock.json`（版本、SHA、子树摘要）。
- [x] 验证两个 Skill 的 `SKILL.md`、references、scripts 及 MIT License 完整。
- [x] 确保 `skills/` 下没有第三个 Skill。

### Phase 2：实现确定性同步器与测试

- [x] 实现 `scripts/sync_upstream.py`，使用固定上游、路径白名单和 SHA 固定。
- [x] 实现路径安全校验、相对引用检查与依赖清单。
- [x] 提供 `--check`（只报告）和 `--sync`（输出候选快照）两种模式。
- [x] 编写 no-op / 更新文件 / 删除文件 / 缺目录 / 越界路径测试，以及许可、摘要、依赖与私人文件拦截测试。
- [ ] 补丁冲突测试：未启用补丁层，随第二阶段行为适配一并实施。
- [x] 对内容无变化的后续 tag 保持 no-op，不生成锁文件噪声。

### Phase 3：实现 GitHub Actions

- [x] 实现 `sync-upstream.yml`：每天 + 手动触发、读写 Job 分离、验证产物、固定更新 PR 分支（尚未远端执行）。
- [x] 实现 `ci.yml`：静态检查、正反样例、Windows 临时目录安装/元数据发现测试（不代表 DSH 实际发现）。
- [x] 锁定第三方 Action 的完整 commit SHA，固定 actionlint 版本与下载校验和。
- [x] 本地测试无变更、目标 Skill 有变更、仅其他 Skill 变化三种情形；目标更新完成真实封包/受限替换重放。
- [x] 查阅 GitHub 官方文档，记录 `GITHUB_TOKEN` 机器人 PR 的 CI 审批规则。
- [x] 远端验证托管 Ubuntu / Windows / actionlint 检查，以及无变化同步跳过 PR。
- [ ] 后续真实上游相关变化发生时，核对固定 PR 创建/更新和实际 Token 审批行为；不为验收制造虚假更新 PR。

### Phase 4：Windows / DSH 验证

- [x] 实现 Windows 安装器的备份、完整升级、版本显示、显式备份 ID 回滚及中断恢复；不触碰其他 Skill。
- [x] 在隔离目录验证安装器，覆盖 PowerShell 5.1 / 7、并发与失败恢复；完整 98 项测试通过。
- [x] 在 Windows 的独立测试环境放入两个 Skill，使用本机 DSH 原模块的最小 Cordis 组合；未启动现用 profile。
- [x] 验证隔离 DSH 实际发现/读取两个 Skill，核对路径及原字节摘要，并验证同名来源优先级；现用桌面 profile 尚未验收。
- [ ] 用副本细纲写指定章节，验证退化/句式脚本运行。
- [ ] 运行独立去味并检查备份、剧情保护与文件路径。
- [ ] 明确记录 Role、Hooks、追踪、细纲要求在纯 Skill 环境的真实模型表现；运行时 preset 缺失与 Skill 回退约定已记录，模型行为仍待验收。

### Phase 5：运行与维护

- [ ] 更新 PR 中必须给出 changelog/diff 和测试报告；人工合并。
- [x] 更新 README 的本地安装/回滚说明；真实 DSH 与远端使用验收尚未完成。
- [ ] 发生异常更新时，可将 `main` 回退到前一个通过 CI 的提交，并重新安装该固定版本。
- [ ] 每月看一次定时 Actions 是否仍处于启用状态（Public Repo 闲置可能影响 schedule）。

---

## 8. Definition of Done（完成验收）

整个项目完成的客观标准：

1. 在 Public Repo 的 `skills/` 里**有且只有**两个 Skill 目录；所有脚本/参考资料完整，不包含上游其他 11 个 Skill。
2. 公开仓库不包含任何真实小说项目资料和密钥；原版 MIT License/版权声明未丢失。
3. 手动运行 Actions 可正确发现上游最新正式 Release；版本已同步且两子树无变化时不产生 PR。
4. 仅当两个子树实际变化，自动创建/更新一个变更 PR；上游其他 Skill/DSH UI 更新不应触发它。
5. PR 前已通过路径校验、依赖检查、语法检查、去味脚本正反样例；失败时阻止 PR 发布。
6. Windows + DSH 能发现两个 Skill；运行真实章节时能够准确报告其前置条件，不能假装原生 Hooks/Role 已被打包。
7. 至少完成一次：细纲 → 一章正文 → 去味 → 备份 → 复检的人工端到端验证，且私人小说始终留在本地。
8. 在更新失效或不满意时，可以明确识别、锁定并恢复上一个通过验收的版本。

---

## 9. 可以直接交给 Codex / Claude Code 的实施指令

> 请严格依据本仓库的 `plan.md` 实施一个 `oh-story-lite` Public Repo。权威上游只使用 `zenstory-ai/oh-story-claudecode` 的最新稳定 Release，仅分发两个完整 Skill 子树 `skills/story-long-write/**` 与 `skills/story-deslop/**`。不得引入第三个 Skill，不得上传私人小说。先实现不可变 SHA 锁定、同步脚本、目录/引用/语法/样例测试；再实现每日检查的 GitHub Actions，分离只读候选验证 Job 与有 PR 写权限的发布 Job。只在目标 Skill 内容真正变化时创建或更新 PR，永不自动合并或直接推送 `main`。保留 MIT License 和上游引用；在 Windows + DSH 使用说明中明确纯 Skills 不等于 DSH 原生插件，不能保证专业 Role、Hooks 或追踪流程自动可用。完成后执行全部离线测试，输出实际建立的文件、验证结果、尚存限制，不要假报通过。

## 10. 参考资料

- [Oh Story 通用仓库](https://github.com/zenstory-ai/oh-story-claudecode)
- [Oh Story DSH 插件](https://github.com/zenstory-ai/oh-story-dsh)
- [长篇写作 Skill](https://github.com/zenstory-ai/oh-story-claudecode/tree/main/skills/story-long-write)
- [去 AI 味 Skill](https://github.com/zenstory-ai/oh-story-claudecode/tree/main/skills/story-deslop)
- [GitHub Actions：安全使用参考](https://docs.github.com/en/actions/reference/security/secure-use)
- [GitHub：Token 触发工作流的行为](https://docs.github.com/en/actions/concepts/security/github_token)
- [GitHub Actions：定时触发](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [create-pull-request Action](https://github.com/peter-evans/create-pull-request)
- [GitHub：Actions 仓库设置](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
