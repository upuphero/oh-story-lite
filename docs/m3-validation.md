# M3 本地验收记录

日期：2026-10-22（America/Phoenix）。本次仅编写工作流并本地验证；没有创建远端仓库、配置远端权限、推送、运行托管 Actions、创建 PR 或发布。

## 本次实现

| 文件 | 用途 |
|---|---|
| `.github/workflows/ci.yml` | PR / main / 手动触发的 Ubuntu、Windows 验证，以及独立工作流检查 |
| `.github/workflows/sync-upstream.yml` | 每日与手动同步；只读验证、封包与 PR 写入分为独立 Runner / Job |
| `.github/action-pins.json` | 6 个第三方 Action 的版本和完整 SHA，以及 actionlint 的固定版本/校验和 |
| `scripts/ci_sync.py` | 无变化时结束，有变化时完成全部验证并封装候选，输出受控 Job 字段 |
| `scripts/sync_artifact.py` | 包摘要/路径/lock/报告复核，默认分支基线检查、受限替换、失败恢复及 PR 元数据生成 |
| `scripts/validate_all.py` | 增加成功后的机器报告；未运行单元测试的报告不能封包 |
| `scripts/lint_workflows.py` | SHA pin 检查、固定 actionlint 下载校验及离线缓存运行 |
| `scripts/smoke_install.py` | 在临时 home 下复制并通过元数据发现两个 Skill，保持原字节，不修改真实 home |
| `tests/test_actions.py` | 新增 26 项产物、准备/写入隔离与工作流回归测试 |
| `docs/github-actions.md` | 运行方式、权限边界及未来远端接入说明 |

真实仓库的两个 Skill、LICENSE 和 `upstream-lock.json` 未更改，仍锁定正式上游 `v0.9.0` / `74080143dd1ac9a39a930fafd99a0dbbe61b946a`，共 102 个 Skill 文件。

## 实际执行结果

环境：本地 Windows，Python 3.11.5，Node.js 24.19.0。

| 验证 | 结果 |
|---|---|
| `python scripts/lint_workflows.py`，随后 `--offline` | 均退出 0；actionlint 1.7.12 通过，两工作流 13 处 Action 引用完整 SHA 锁定通过 |
| 独立 YAML 解析 | 两工作流触发器与 Job 结构正常；仅用于额外本地核查，不新增 Python 依赖 |
| `python -m unittest discover -s tests -p test_actions.py -v` | 新增 26/26 测试通过 |
| 完整验证入口，在合成更新候选上由 `ci_sync.prepare_job` 实际调用 | 70/70 离线测试通过（原 44 + 新 26）；未跳过单元测试，成功写出机器报告 |
| 候选语法 / 引用 / 检测与运行样例 | 7 Python + 10 JavaScript；591 处引用；12 检测用例；10 合成运行检查全部通过 |
| `python scripts/smoke_install.py` | 恰好两个 Skill，原字节保留，真实 home 未修改；未测试 DSH 运行时 |
| 三种本地场景 | 无变化与无关变化均不产出包；相关变化完成验证、封包、摘要复核、受限替换和 PR 标题/正文生成 |

本地完整重放在 `.cache/m3-replay/` 的临时 Git 测试仓库中执行，使用合成 `v0.9.1`、`bbbb…bbbb` SHA 和一份新增的测试 Markdown。它们不是新的真实上游版本，也没有写入真实仓库的 Skill 或 lock。缓存及测试仓库均被 `.gitignore` 排除。

重放的实际 Git 变更仅有测试仓库的 `upstream-lock.json` 与 `skills/story-deslop/references/sync-fixture.md`。受保护 README、工作流、提示文件均保持原样。PR 标题/正文保存为本地文件，没有调用 GitHub 写接口。

新增测试还验证了：禁止覆盖工作流/维护代码/第三个 Skill、拒绝摘要和文件篡改、路径穿越与链接、检测缺失/跳过测试的报告、基线漂移、脏 checkout、同步删除、移动失败恢复，以及写入侧只调用 Git 状态查询而不执行候选代码。

## 保留的验证边界

- 这是工作流与本地链路验收；固定分支 PR 的真实创建/更新、Token 审批、上传/下载 Action 服务和托管 Ubuntu / Windows Runner 仍待远端接入后验证。
- actionlint 使用内建 YAML / 表达式 / Action 检查，未调用外部 shellcheck 或 pyflakes。
- Windows 检查仅验证隔离目录复制和文件元数据发现，不代表 DSH 实际加载成功。DSH 与模型端到端写作仍属 M4。
- 产物报告能绑定测试所用内容，不能证明上游脚本无恶意行为。写入 Job 的独立 Runner、可信维护代码、严格路径范围和不执行候选代码是权限隔离边界；合并仍需人工审核。

真实仓库保留的 Skill 摘要为 `f964993429610efc1d1f1918269300a3e65f4fb8f6da2d7811d258fd188bbd45`。lock 文件字节 SHA-256 为 `69c383ac7e3e8a5b2d547f2fb79ff327e4ab0178fb71a6b9a38f4d75b44e60ab`。
