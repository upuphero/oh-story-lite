# M4 安装器隔离验收记录

日期：2026-10-22（America/Phoenix）。范围仅包括 Windows 安装器及隔离目录验证，没有安装到真实用户 Skills 目录，没有创建远端仓库、推送或发布。

后续记录：2026-10-23 已完成本机 DSH 原始模块的隔离发现、读取和同名优先级验证，见 [dsh-discovery.md](dsh-discovery.md)。本文保留安装器当日的验收范围与数据。

## 交付

- `install.ps1`：PowerShell 5.1 / 7 入口，必须显式指定 `-Destination`，支持 Install、Upgrade、Rollback、Backups、Status、Recover。
- `scripts/manage_install.py`：复用现有静态校验；先暂存与完整备份，再整体替换两个 Skill；保存版本与原始许可；支持精确回滚和事务恢复。
- `tests/test_installer.py`：新增 28 项隔离测试。
- `.gitignore`：排除 `.oh-story-lite/`，防止本地备份和路径元数据被提交。
- `docs/windows-install.md`、README 与 plan：补齐命令、状态位置和验收边界。

备份在目标 Skills 目录外的 `.oh-story-lite/<目标路径摘要>/backups/<id>/`，不会作为额外 Skill 被复制到扫描目录。回滚前也保存当前状态，因此回滚可撤销。完全相同的快照为 no-op，不新增备份，不重写安装记录。

## 实际运行结果

环境：Windows、Python 3.11.5、Node.js 24.19.0；原生 Windows PowerShell 5.1 与 PowerShell 7 均完成入口测试。

| 检查 | 结果 |
|---|---|
| 安装器专项测试 | 28/28 通过，无跳过 |
| `python -B -X utf8 scripts/validate_all.py --report-file .cache/m4-full-validation.json` | 退出 0；完整 98/98 测试通过，无跳过 |
| 原始 Skill 静态检查 | 102 个文件（90 + 12），目录、lock、许可及 591 处引用检查通过 |
| 语法与运行检查 | 7 个上游 Python + 10 个 JavaScript 语法通过；12 项检测用例、10 项合成运行检查通过 |
| PowerShell 入口 | 两个原生运行时均实际调用安装、升级、回滚、状态；目标包含中文和空格；没有指定目标时失败退出 |
| NTFS junction | 在目标根及祖先路径实际创建隔离 junction；安装器均拒绝，指向目录内容保持不变 |
| 工作流检查 | actionlint 与 13 处完整 Action SHA 检查仍通过；现有 CI 自动发现新增测试，无需新增安装到真实目录的步骤 |

沙箱最初限制了 Windows PowerShell 5.1 / junction 原生调用；最终专项与完整测试在允许这些 Windows API 的本地进程中完成，所有测试目标仍严格位于本仓库 `.cache/`。没有修改系统执行策略。

## 验证过的行为

1. 首次安装准确复制两个 Skill，并保留其他 Skill 的哨兵文件。
2. 接管已有同名目录前保存原始文件；不完整旧目录、二进制本地文件和空目录均能精确还原。
3. 从合成旧版升级到合成新版，旧版已删除资产不残留，新增和修改文件正确安装，版本记录同步变化。
4. 回滚恢复旧版文件、版本记录及本地修改；回滚首次安装可恢复两个目录缺省状态；回滚操作本身可再次撤销。
5. 同内容重复升级不改变 receipt 的字节或修改时间，不新增备份；Windows 路径大小写变化不造成伪更新。
6. 损坏源、越界 ID、外来或篡改备份、多余备份路径、源目标重叠、文件系统根和 junction 均被拒绝。
7. 备份写入失败不改动当前安装；替换失败自动恢复前态。
8. 注入进程中断后，保留日志并阻止新变更；Recover 还原原状态。恢复再次失败时保留备份和日志供重试。
9. 已提交但清理失败时，Recover 完成清理并保留新版本。
10. 并发安装被内核互斥锁阻止；安装器本身不执行任何上游 Skill 脚本。

测试源是隔离快照，使用合成 `v0.9.0` / `aaaa…aaaa`、`v0.9.1` / `bbbb…bbbb` 及专用增删文件，不代表真实上游更新。测试安装、备份和恢复均不涉及真实小说、供应商配置或用户 Skills。

## 保持不变与尚未验收

真实仓库仍锁定 `v0.9.0`、`74080143dd1ac9a39a930fafd99a0dbbe61b946a`。两个 Skill、LICENSE 和 lock 的原始字节均未修改：

- Skill 摘要：`f964993429610efc1d1f1918269300a3e65f4fb8f6da2d7811d258fd188bbd45`。
- lock 文件字节 SHA-256：`69c383ac7e3e8a5b2d547f2fb79ff327e4ab0178fb71a6b9a38f4d75b44e60ab`。

M4 的真实 DSH 加载、同名优先级、Role/Hooks 和章节写作人工验收尚未执行；M3 的远端 PR 与托管 Runner 验收也仍待进行。恢复测试使用故障注入，不覆盖真实断电和磁盘损坏；安装器不是两个目录的一次原子文件系统事务。
