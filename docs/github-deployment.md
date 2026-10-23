# GitHub 公开部署记录

日期：2026-10-23（America/Phoenix）。用户授权将项目部署到公开仓库，并明确选择自动创建/更新 PR、由维护者审核合并。

- 仓库：[upuphero/oh-story-lite](https://github.com/upuphero/oh-story-lite)，Public，默认分支 `main`。
- 初始发布提交：`9dcc8f507dfce638fc537f70244511b2aba6957d`。
- 初始公开内容：142 个文件，包含两个原始 Skill 的 102 个文件、MIT LICENSE、归属说明、安装器、CI/CD 与测试。
- 原始数据、凭据、个人路径标识、缓存与大文件检查在发布前执行；`.cache/`、本地备份和私人小说目录未提交。
- Git 提交使用 GitHub noreply 邮箱，没有发布本机配置的私人提交邮箱。

## 已通过的远端执行

| 工作流 | 执行链接 | 结果 |
|---|---|---|
| 首次 CI | [40010970672](https://github.com/upuphero/oh-story-lite/actions/runs/40010970672) | Ubuntu、Windows、actionlint 三个 Job 均成功；Windows 目录发现 smoke test 成功 |
| 首次手动上游同步 | [40010983256](https://github.com/upuphero/oh-story-lite/actions/runs/40010983256) | `changed: false` / `No relevant changes`；未上传候选，PR Job 正确跳过 |

上游正式 Release 仍为 `v0.9.0`；镜像锁定提交及两个 Skill 原字节保持不变。

## 仓库运行策略

- CI 和上游同步工作流均启用；同步每日 09:23 UTC，另可手动运行。
- 默认 `GITHUB_TOKEN` 为只读，仓库允许 Actions 创建 PR；只有独立写入 Job 声明 contents / pull-requests 写权限。
- 自动合并关闭；有相关变化时更新 `bot/sync-oh-story` 的固定 PR 分支，维护者审核后手动合并。
- `main` 保护要求 PR、分支保持最新，以及 `Validate (ubuntu-latest)`、`Validate (windows-latest)`、`Lint workflows` 三项成功；禁止强推和删除。
- 单人维护不强制额外的第二人审批；讨论需解决，合并仍由维护者手动完成。
- GitHub 同步不会自动改动本机已安装的 Skills；本地使用者在接受更新后运行安装器升级。

没有相关变化时不制造测试更新 PR。真实上游更新到来后的机器人 PR 创建/更新及 Token 审批交互，仍需在那次实际更新中核对；本次不把跳过的写入 Job 报为已执行。

GitHub 最新状态以 [CI](https://github.com/upuphero/oh-story-lite/actions/workflows/ci.yml) 和 [上游同步](https://github.com/upuphero/oh-story-lite/actions/workflows/sync-upstream.yml) 页面为准。工作流机制见 [github-actions.md](github-actions.md)，归属与安装见仓库 README。
