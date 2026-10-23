# M4：本机 DSH 隔离发现验收

日期：2026-10-23（America/Phoenix）。本次使用本机已安装 DSH 的原始模块，验证发现、加载、同名优先级与缺失专业 Agent 的运行时结果。没有启动真实桌面 profile、创建 Agent/会话、调用模型、改动真实 Skills 或发布。

## 本机版本与启动入口

| 项目 | 本次观察 |
|---|---|
| Windows 桌面程序 ProductVersion | `0.2.1.0` |
| 打包应用及 CLI 的实际版本 | `0.2.1-rc.2`；包元数据与实际 `--version` 输出一致 |
| 本次 DSH 进程内核 | Node.js `24.21.0`，Electron `44.7.0` |
| 安装目录 | `%LOCALAPPDATA%\Programs\DeepSeek Harness` |
| 桌面启动 | 开始菜单 `DeepSeek Harness.lnk` → 安装目录的 `DeepSeek Harness.exe`，无附加参数 |
| CLI 启动 | `resources\runtime\cli\bin\dsh.cmd`；当前 PATH 未提供 `dsh` 命令 |

CLI 启动脚本设置 `ELECTRON_RUN_AS_NODE=1`，以桌面可执行文件的 Node 模式运行 ASAR 中的 `@deepseek-ai/dsh-desktop-host/lib/cli.js`。本次执行同等入口，并先加载离线检查 guard。实际 `--help` 确认支持 `--profile <name>`、`--patch`、`--dump-config` 等参数；只执行全局 `--version` / `--help`，不启动任何 profile。

本次安装包 `resources/app.asar` 的 SHA-256：`47874618bf5b3011fcaac10cd4c85f69da333e70d4f99b921207c78d0999512a`。被调用模块的版本和源码字节摘要另存于被忽略的 `.cache/m4-dsh-discovery-01/report.json`，以区分后续安装更新。

## 隔离方式与实际调用

新增 `scripts/smoke_dsh.py`、`scripts/dsh_discovery_probe.mjs` 和 `scripts/dsh_offline_guard.cjs`。Python 使用现有安装器把两个完整 Skill 安装到工作区 `.cache/` 内的测试 home，DSH 模块仍直接从本机安装包导入。

子进程的 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA`、`TEMP`、`TMP` 全部指向测试目录，同时设置：

```text
DSH_HOME=<隔离根>/home/.dsh
DSH_AGENTS_HOME=<隔离根>/home/.agents
```

工作目录自带一个空 `.git` 边界，阻止项目根查找上溯到真实仓库。未复制真实 profile、登录配置、会话、插件或密钥；父进程的 API Key、Token、NODE_OPTIONS 等环境变量不会传入测试进程。

实际调用链：安装包的 Cordis `Context` → `SkillRegistry` → `skill-filesystem` → `skills.snapshot/list/get`。同时挂载原始 SystemPrompt / ToolRuntime，在无 Agent 的最小组合中直接应用安装包的 `tool-skill`，实际执行其 `skill` 工具的只读加载路径并核对内容。这不是用本仓库的 Markdown 扫描器代替 DSH，也不是完整桌面会话验收。

发现时关闭文件监听，修改测试候选后重建 Context；没有验收 watcher 的实时刷新。没有提供 LLM、Agent 或 subagent 执行服务。原始 AgentPresetRegistry 只进行空名册和缺失 ID 的读取，不挂载 preset 或创建 Agent。

## 扫描路径与同名优先级

本机 `dsh-home-paths` 原代码确认：显式配置优先于环境变量，其次才是默认 home。默认 `DSH_HOME=~/.dsh`，`DSH_AGENTS_HOME=~/.agents`；两个根相互独立。

在同一作用层中，较小 rank 优先：

| 来源 | 路径或注册方式 | rank |
|---|---|---:|
| project-dsh | `<项目根>/.dsh/skills` | 100 |
| project-agents | `<项目根>/.agents/skills` | 200 |
| runtime | `ctx.skills.register(...)` | 250 |
| custom | `customSkillDirs` | 300 |
| user-dsh | `$DSH_HOME/skills` | 400 |
| user-agents | `$DSH_AGENTS_HOME/skills` | 500 |
| bundled | `bundledSkillDir` / 对应环境变量 | 600 |

本次实际发现和优先级验证共 9 项，全部通过：

1. 共享用户根发现恰好 `story-deslop`、`story-long-write`，来源为 `user-agents` / `filesystem`。
2. 未打包的 `story-import` 被真实 `skill` 工具以 unknown 拒绝。
3. 用户共享目录中的同名 Skill 优先于 bundled 目录。
4. runtime 注册的同名 Skill 优先于用户共享目录。
5. 自定义目录优先于用户共享目录。
6. 用户 DSH 目录优先于用户共享目录。
7. 项目 `.agents/skills` 优先于两个用户目录。
8. 项目 `.dsh/skills` 优先于项目 `.agents/skills`。
9. `includeDefaultRoots=false` 时仅从明确提供的自定义目录发现。

作用层也会影响选择；本次未验证 preset 的多层组合。因此不能笼统承诺“全局 Skill 总能覆盖插件”。真正排查重名时，应核对 DSH 返回的 `source`、`provider`、实际路径和内容摘要。

两个 Skill 的 `userInvocable` / `modelInvocable` 均为 true；完整正文已通过原始工具加载，`resourceBase` 指向隔离安装目录，原始 SKILL.md 摘要与仓库 lock 一致。该结果证明可发现和读取，不代表模型已经调用或执行。

## 专业 Agent 不可用时的实际结果

隔离的纯 Skills 组合未注册专业 Agent、`oh_story_role` 或 `invoke_subagent`。对以下五个 ID 调用原始 DSH preset 注册表的只读 `resolve()`：

```text
narrative-writer
story-architect
story-explorer
story-continuity
story-researcher
```

五次均返回 `agent-preset/not-found` / `Unknown agent preset: <id>`。该运行时行为是拒绝未知 preset，**没有自动转交主 Agent 的路由**。

两个实际加载的 Skill 都保留了主 Agent 直接执行的指令：长篇写作要求不可用时报告 fallback 并 solo/direct 执行；去味要求不可用时由主会话直接改。这是已加载的行为约定，需要主 Agent 遵循。此次未运行模型，不能据此证明模型会正确执行回退、读取全部前置材料或维护追踪。

此名册只代表本次隔离组合，不代表用户现用桌面 profile 的 Agent / 插件名册；没有读取或修改真实 profile 来做该断言。

## 本地运行与验证边界

```powershell
# 替换为已核对的本机安装目录；工作目录必须是本仓库 .cache 下的新目录。
python scripts/smoke_dsh.py --desktop-root '<本机 DeepSeek Harness 安装目录>' --work-dir .cache/dsh-discovery-next
python -m unittest discover -s tests -p test_dsh_probe.py -v
```

实际 DSH 集成检查为显式命令，不要求没有安装 DSH 的 CI Runner 具备该程序。新增 9 项通用离线测试验证 ASAR 元数据读取、环境隔离、受保护读取、越界写入、网络及子进程拒绝；维护 JavaScript 语法检查已纳入统一验证入口。

本次完整 `validate_all.py` 回归实际运行 **107 项测试，全部通过、无跳过**；机器报告在 `.cache/m4-dsh-regression.json`。通用回归不会自动启动本机应用，它的 `runtime.dsh_discovery` 仍表示未包含这项检查；本次原生 DSH 的 9 项结果单独记录在 `.cache/m4-dsh-discovery-01/report.json`。两个报告的范围不同。

主探测进程与 CLI 进程的四项计数均为 0：网络尝试、子进程尝试、真实用户配置/Skills 读取尝试、隔离根之外的写入尝试。检查 guard 是最小诊断环境的回归防护，不是面对任意恶意原生代码的系统沙箱。

真实 Skills 没有被安装或改动，仓库两个子树、LICENSE 和 lock 保持原样。M4 尚未完成的项目是桌面真实会话/模型行为、章节写作与独立去味等人工验收；M3 远端 PR 与托管 Runner 验收也仍待进行。
