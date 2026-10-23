# Oh Story Lite

[![CI](https://github.com/upuphero/oh-story-lite/actions/workflows/ci.yml/badge.svg)](https://github.com/upuphero/oh-story-lite/actions/workflows/ci.yml)
[![Sync upstream](https://github.com/upuphero/oh-story-lite/actions/workflows/sync-upstream.yml/badge.svg)](https://github.com/upuphero/oh-story-lite/actions/workflows/sync-upstream.yml)

面向 Windows + DeepSeek Harness（DSH）的 **Oh Story 非官方双 Skill 精简镜像**。保留长篇正文写作和去 AI 味所需的完整资料与脚本，通过 GitHub Actions 跟随上游正式 Release 更新。

| Skill | 用途 |
|---|---|
| `story-long-write` | 根据卷纲、章节细纲、设定与追踪状态创作、续写和修改长篇正文 |
| `story-deslop` | 从表达、叙事详略与故事因果三层审读和精修正文 |

只分发这两个 Skill，不打包扫榜、拆文、封面等其他 Skill。模型使用 DSH 当前配置，本仓库不提供模型、不保存 API Key，也不收集小说资料。

## 来源与归属

| 项目 | 在本仓库中的用途 |
|---|---|
| [zenstory-ai/oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode) | **唯一 Skill 源码上游**。完整复制 `skills/story-long-write/**`、`skills/story-deslop/**` 和原版 `LICENSE` |
| [zenstory-ai/oh-story-dsh](https://github.com/zenstory-ai/oh-story-dsh) | DSH 封装的兼容性参考；不从它混合同步文件，不分发其插件、Role、Hooks 或工作台 |
| 本仓库维护代码 | 安装器、备份/回滚、同步器、CI/CD、离线测试及说明文档；与上游 Skill 分开维护 |

原版权声明 **Copyright (c) 2025-2026 oh-story-claudecode** 和 MIT 许可正文原样保存在 [LICENSE](LICENSE)。更多归属说明见 [NOTICE.md](NOTICE.md)。本仓库不是 zenstory-ai 官方发行版。

首次导入版本为 [`v0.9.0`](https://github.com/zenstory-ai/oh-story-claudecode/releases/tag/v0.9.0)，固定提交为 [`74080143dd1ac9a39a930fafd99a0dbbe61b946a`](https://github.com/zenstory-ai/oh-story-claudecode/commit/74080143dd1ac9a39a930fafd99a0dbbe61b946a)。**当前接受版本始终以 [upstream-lock.json](upstream-lock.json) 为准**；其中包含完整 SHA、逐文件摘要及子树摘要。镜像内两个 Skill 无本地行为补丁。

## 安装到 DSH

需要 Git、Python 3.11+ 和 Node.js 18+。在 PowerShell 中执行：

```powershell
git clone https://github.com/upuphero/oh-story-lite.git
Set-Location oh-story-lite

$agentsRoot = if ([string]::IsNullOrWhiteSpace($env:DSH_AGENTS_HOME)) {
    Join-Path $env:USERPROFILE '.agents'
} else {
    $env:DSH_AGENTS_HOME
}
$target = Join-Path $agentsRoot 'skills'
.\install.ps1 -Action Install -Destination $target
```

安装器支持 Windows PowerShell 5.1 / PowerShell 7；`-Destination` 必须显式提供。如 DSH 使用显式 `agentsHome` 配置，以该配置下的 `skills` 为目标。安装前会保存已有同名目录，只替换两个 Skill，保留其他 Skill。

然后在 DSH 中打开**自己的私人小说目录**，新建对话。不要将小说正文、细纲、追踪或供应商配置提交到本仓库。

写指定章节：

```text
/story-long-write

小说目录：D:\小说\我的书
依据已有卷纲、细纲、设定和前文，写第12章正文，2500—3000字。
保留已定剧情、人物选择和停笔点，只写这一章。
没有专业写作 Agent 时由你直接执行；先核对必需材料，缺少事实时向我确认。
```

精修已有正文：

```text
/story-deslop

请对 D:\小说\我的书\正文\第012章_夜访.md 去AI味。
按 Skill 要求先备份原文，保留剧情、人物动机、伏笔与揭露顺序。
改善机械句式、对白和叙事详略；需要改变剧情的因果问题先给建议。
```

只要报告时加上“只检测和标注，不修改文件”。示例路径、书名和章节均需替换。

## 升级与回滚

仓库同步和本机安装是两个独立步骤。上游更新 PR 合并后，在本地获取新版本，再运行安装器：

```powershell
git pull --ff-only
.\install.ps1 -Action Upgrade -Destination $target
.\install.ps1 -Action Status -Destination $target
```

查看备份并按明确 ID 回滚：

```powershell
.\install.ps1 -Action Backups -Destination $target
.\install.ps1 -Action Rollback -Destination $target -BackupId '<需要恢复的完整备份 ID>'
```

每次实际变更前保存当前状态；回滚本身也会备份。完全相同的快照不生成新备份。完整子树替换可移除旧版本已删除的文件。备份位于 Skills 目录外的 `.oh-story-lite/` 中，中断恢复使用 `-Action Recover`。详见 [Windows 安装说明](docs/windows-install.md)。

## CI/CD 与上游自动更新

### 自动同步

[sync-upstream.yml](.github/workflows/sync-upstream.yml) **每日 09:23 UTC** 检查上游最新正式 Release，也支持在 [Actions 页面](https://github.com/upuphero/oh-story-lite/actions/workflows/sync-upstream.yml) 手动运行。

```text
最新正式 Release → tag 解析为完整 SHA → 只提取两个 Skill 和 LICENSE
→ 比较路径与原始字节 → 验证候选 → 封装及复核摘要
→ 创建或更新 bot/sync-oh-story 分支的同一个 PR → 维护者审核合并
```

- **有相关内容变化才更新**：同步新增、修改和删除。仅上游版本号、其他 Skill 或 DSH UI 变化不会创建 PR，也不改 lock。
- **跟踪正式 Release**：跳过 draft / prerelease；未发布到正式 Release 的 `main` 提交不触发同步。每日轮询不保证发布后即时到达。
- **更新以 PR 交付**：不直接推送 `main`，不自动合并。PR 写明上游版本、完整 SHA、文件变化、依赖提示和检查结果。
- **读写 Job 隔离**：只有只读 Job 执行候选脚本；写入 Job 在独立 Runner 上复核产物，只替换两个子树、LICENSE 和 lock，不执行上游代码。
- **失败不发布更新**：缺硬依赖、越界路径、异常文件、许可不完整或校验失败均阻断；新增依赖需人工适配。
- **许可变化单独检查**：仅 LICENSE 变化时报告需人工处理；与 Skill 同时变化时在 PR 中明确标记。
- 自动更新仓库后，**不会远程改动你的本机 Skills**，本地升级仍由你运行上面的命令。

### 质量检查

[ci.yml](.github/workflows/ci.yml) 在 `pull_request`、`push(main)` 和手动触发时执行：

- Ubuntu / Windows：目录与元数据、完整 lock、许可、引用、依赖、Python / JavaScript 语法和离线测试。
- 检测器正反样例、合成项目运行及隔离的安装/升级/回滚/恢复检查。
- Windows 的隔离 Skills 目录发现检查。
- 独立 actionlint 工作流检查；第三方 Action 固定完整提交 SHA，工具下载核对 SHA-256。

全部检查不调用付费模型。机器人 PR 的后续 CI 可能需要维护者点击 **Approve workflows to run**；参见 [GitHub Token 行为说明](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs)。候选准备 Job 已完成验证，PR 检查获准并通过后再合并。

GitHub 定时任务可能延迟；公开仓库长期无活动时 schedule 可能停用，可手动运行恢复检查。权限结构及排障见 [GitHub Actions 说明](docs/github-actions.md)。

## 工作原理与使用边界

DSH 发现 Skill 后加载 `SKILL.md`，当前模型按指令读取 `references/`、调用本地 `scripts/` 并处理小说。长篇流程组装章节上下文，检查字数、句式、重复等问题，并通过脚本维护追踪状态；去味流程结合表达、叙事与因果进行语义审读。脚本命中提供定位线索，改写仍需要模型结合上下文判断。

- 长篇写作仍要求上游格式的卷纲、章节细纲及追踪状态。此版本尚未实现“任意大纲直接写正文”的行为适配。
- `story-import`、`story-setup` 未打包；已有小说缺少标准追踪时，可能需要本镜像以外的导入能力。
- 两个 Skill 不包含专业 Agent、DSH 专属 Role / Hooks。专业 preset 缺失返回 not-found；主模型直接执行属于 Skill 指令约定，不是 DSH 的自动路由。
- 本机 DSH `0.2.1-rc.2` 原始 API 已在最小隔离组合中发现并读取两个 Skill；完整桌面 profile、模型回退与真实章节写作尚未验收。
- 同名来源存在优先级，不能只看磁盘目录判断实际加载版本。扫描路径、来源优先级和验证边界见 [DSH 隔离发现记录](docs/dsh-discovery.md)。

## 本地维护

```powershell
python scripts/validate_all.py
python scripts/lint_workflows.py
python scripts/sync_upstream.py --check
```

维护 Python 代码使用标准库，不需要 pip/npm 安装依赖。actionlint 首次下载到被忽略的 `.cache/`，之后可用 `--offline`。同步器支持仅报告及输出新候选目录，普通本地同步不覆盖当前工作树。

原始需求见 [plan.md](plan.md)，依赖审查见 [docs/dependencies.md](docs/dependencies.md)，历史验证记录保留于 `docs/`。`.cache/`、`.env`、本地安装状态与私人小说目录均排除在 Git 之外。
