# M3：GitHub Actions 设计与本地使用

本仓库通过 [CI](https://github.com/upuphero/oh-story-lite/actions/workflows/ci.yml) 和 [上游同步](https://github.com/upuphero/oh-story-lite/actions/workflows/sync-upstream.yml) 两个 GitHub Actions 工作流运行检查与更新。历史本地验证数据见 `m3-validation.md`；远端最新执行状态以 Actions 页面为准。

## 独立 CI

`.github/workflows/ci.yml` 在 `pull_request`、`push(main)` 和手动触发时运行：

- Ubuntu / Windows：Python 3.11、Node.js 24，运行 `python scripts/validate_all.py`。
- Windows：额外运行 `python scripts/smoke_install.py`，在临时 home 下复制并通过文件元数据发现恰好两个 Skill，确认原始字节一致。不会触碰真实用户目录，也不能据此声称 DSH 运行时已加载成功。
- 独立 Ubuntu Job：校验 Action 的完整 SHA，并运行固定版本、校验和锁定的 actionlint。

统一测试入口会自动发现 `tests/test_installer.py`，在隔离目录验证安装、升级、回滚和恢复；Windows 上还会运行可用的 PowerShell 入口及 NTFS junction 拒绝测试。安装器测试不使用真实 Skills 目录。

所有 CI Job 仅有 `contents: read`，checkout 不持久保存凭据。没有使用 `pull_request_target` 或 `workflow_run`。

## 每日同步

`.github/workflows/sync-upstream.yml` 每日 09:23 UTC（Phoenix 02:23）轮询，并支持 `workflow_dispatch`。手动运行仅接受默认分支；在其他分支运行会跳过。固定 concurrency group，避免同步并发更新同一分支。

`prepare-and-validate` 只有 `contents: read`：

1. 签出默认分支触发时的固定仓库提交。
2. 从上游正式 Release tag 解析完整 SHA，生成两子树候选。
3. 无相关变化时不执行候选脚本、不上传产物，也不启动写入 Job。
4. 有变化时运行全部本地验证与离线测试，写出成功报告。
5. 重新核对候选 lock 和报告，将原始候选及报告封装为 `snapshot.tar`，输出包的 SHA-256。
6. 上传唯一文件，保留三天。上游执行不接触 PR 写权限或发布凭据。

`create-update-pr` 在前一个 Job 成功且 `changed == true` 时运行，只有它具备 `contents: write`、`pull-requests: write`：

1. 独立 Runner 签出当前可信默认分支，下载同一次运行的产物到 checkout 以外。
2. 要求当前 HEAD 仍等于工作流触发提交；若默认分支已推进则失败，重新运行同步，不将旧候选覆盖到新基线。
3. 核对整个 tar 包的 SHA-256，并重新检查成员路径、重复/大小写冲突、文件类型/大小、lock、许可、静态引用与数据模式。
4. 产物只允许 `snapshot/skills/story-long-write/**`、`snapshot/skills/story-deslop/**`、`snapshot/LICENSE`、`snapshot/upstream-lock.json` 和 `validation.json`；不使用 tar 自动解包，也不导入或运行候选脚本。
5. 只替换两个完整子树、LICENSE 和 lock。旧子树整体移走，因此上游删除的文件不会残留；捕获到移动失败时恢复原快照。
6. 使用固定 `bot/sync-oh-story` 分支创建或更新一个 PR。Action 的 `add-paths` 仍只允许四个更新目标。

PR 正文由可信维护代码生成，列出 Release、完整 SHA、基线、摘要、上游比较链接、增改删数量、每个子树变化、测试覆盖、脚本/依赖审查提示和回退方法。不自动合并，不直接推送默认分支。

只读 Job 的测试报告用于记录和内容绑定，不构成对任意上游代码的安全证明。不同 Runner、写入侧路径限制和不执行候选代码共同维护权限边界；更新仍需人工审查。

## 本地验证命令

```powershell
python scripts/validate_all.py
python scripts/smoke_install.py
python scripts/lint_workflows.py
```

`lint_workflows.py` 首次从 [actionlint 官方 Release](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) 下载固定工具到 `.cache/tools/`，核对提交到 `.github/action-pins.json` 的 SHA-256 后才执行；缓存后可用 `--offline`。支持 Windows/Linux x64，不需要 pip/npm 依赖。禁用外部 shellcheck/pyflakes 调用，使用 actionlint 的 YAML、表达式和 Action 语法检查。

`validate_all.py --report-file <新文件>` 仅在整套验证成功后写出机器报告。`--skip-unit-tests` 的报告不能用于封装同步产物。

`tests/test_actions.py` 使用合成源码包、临时本地 Git 仓库和模拟报告测试产物交接、no-op、文件删除、篡改/越界拒绝、默认分支漂移、失败恢复及写入 Job 不执行上游代码。模拟报告只用于单元测试；完整本地重放另见 `docs/m3-validation.md`。

## 仓库设置与日常维护

仓库部署及维护时需确保：

- 启用 Actions，允许 Actions 创建 PR，配置 main 的 PR 和质量检查规则；默认 Token 权限为只读，写入 Job 单独声明权限。
- 首次手动同步，确认无变化不创建 PR、有变化更新固定 PR 分支的真实平台行为。
- 批准机器人 PR 的待运行 CI，然后核对 Ubuntu / Windows 托管结果再合并。GitHub 当前会将由 `GITHUB_TOKEN` 创建/更新 PR 触发的 CI 置于需批准状态，详见 [GitHub 官方说明](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs)。
- 定期检查 schedule 是否仍启用；定时任务可能延迟，长期闲置的公开仓库可能被禁用，见 [GitHub schedule 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
- 本机 DSH 原始 API 的隔离发现已完成；完整桌面会话和模型端到端写作留在 M4。

`.github/action-pins.json` 记录已核对的版本与完整提交 SHA。升级 Actions 或 actionlint 时应人工修改锁定信息与对应工作流，重新运行检查；上游 Skill 同步不能修改它们。
