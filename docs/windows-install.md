# Windows 安装、升级与回滚

入口为仓库根目录的 `install.ps1`，使用同仓库的 Python 标准库维护代码。需要 Python 3.11+；支持 Windows PowerShell 5.1 和 PowerShell 7。安装器离线读取本地快照，不下载版本、不执行 Skill 脚本、不安装 Role/Hooks，也不修改执行策略。

**必须显式提供 `-Destination`。** 没有真实用户 Skills 目录默认值。以下命令全部使用仓库 `.cache/` 下的隔离目录；本阶段未向真实 Skills 目录安装。

## 安装与查询

从已通过仓库 CI 的版本安装。维护者可运行完整验证；安装器自身仍会执行静态完整性校验。`-Source` 默认为安装器所在仓库；其他本地快照也必须包含两个 Skill、LICENSE 和有效的 `upstream-lock.json`。

```powershell
$target = Join-Path $PWD '.cache/install-demo/home/.agents/skills'
.\install.ps1 -Action Install -Destination $target
.\install.ps1 -Action Status -Destination $target
.\install.ps1 -Action Backups -Destination $target
```

如 `python` 不在 PATH，用 `-PythonExecutable 'C:\path\to\python.exe'` 指定实际解释器文件。可在当前 PowerShell 中运行脚本，也可用 `pwsh -NoProfile -File .\install.ps1 ...` 启动单独进程。

`Install` 既能首次安装，也能接管已存在的同名目录：先备份其原始内容，包括本地改动、空目录和二进制文件，再整体替换。仅允许改动目标下的 `story-long-write`、`story-deslop`；其他 Skill 不参与备份或替换。

`Status` 输出已安装的 tag、完整 SHA、是否有文件改动、状态目录及恢复需求。`locally_modified` 比较文件路径和原始字节，不是 DSH 加载结果。`Status` 和 `Backups` 不创建缺失的目录。

## 升级到本地固定版本

```powershell
# 替换为已经审核并通过验证的本地快照目录；这里不自动获取远端。
$nextSnapshot = 'C:\path\to\validated-snapshot'
.\install.ps1 -Action Upgrade -Destination $target -Source $nextSnapshot
```

`Upgrade` 要求目标已有受管理安装。未受管理的同名目录用 `Install` 备份并接管。指定旧版快照也可恢复到该固定版本，当前状态仍先备份。

实际步骤为：校验源码布局、lock、许可及静态依赖 → 暂存两个完整子树并复核文件 → 备份当前两个目录和版本记录 → 写恢复日志 → 逐目录替换 → 核对结果 → 提交版本记录并清理暂存。整棵子树替换会同步删除旧版中已被移除的文件。

源快照与当前安装完全相同时不替换、不重写版本记录，也不新增备份。本地编辑过的内容会先保存在备份中，再按指定快照升级。

## 查看备份与回滚

```powershell
.\install.ps1 -Action Backups -Destination $target

# 复制上一步输出中所需版本的完整 id；不接受 latest 或任意文件路径。
$backupId = '<从 Backups 输出复制完整 id>'
.\install.ps1 -Action Rollback -Destination $target -BackupId $backupId
.\install.ps1 -Action Status -Destination $target
```

每个备份代表该次实际变更**之前**的状态，`before_version` 是它包含的安装版本；未受管理的目录或首次安装前的缺省状态显示 null。回滚恢复的是备份中的实际字节，包含此前的本地修改，而不是重新从上游下载。

回滚本身也先备份当前状态，输出新的 `backup_id`，因此可以再次回滚撤销这次回滚。回滚首次安装生成的空备份，会恢复到安装前两个目录均不存在的状态；其他 Skill 仍保留。备份不会被移动消耗或自动清除。

备份与指定目标绑定，不能把另一目标的备份 ID 用于当前目录。恢复前检查清单、文件摘要和元数据；损坏、越界或多余目录会阻断恢复。

## 状态和备份位置

例如目标为：

```text
隔离 home/.agents/skills/
  story-long-write/
  story-deslop/
  其他已有 Skill/
```

安装器状态位于其外部：

```text
隔离 home/.agents/.oh-story-lite/<目标绝对路径的摘要>/
  install.json          # 当前上游 lock 与目标绑定
  LICENSE               # 对应快照的原始许可
  installer.lock        # 内核互斥锁；进程退出自动释放锁定
  backups/<id>/         # 每次变更前的完整备份、路径与摘要清单
  transactions/<id>/    # 暂存及错误恢复数据
  pending.json          # 仅事务尚需恢复/清理时存在
```

备份不位于 Skills 扫描目录内，避免把旧副本当成额外 Skill。`.oh-story-lite/` 已加入 `.gitignore`；备份可能包含本地修改，应留在本地。

## 失败与中断恢复

普通复制、写入或移动错误会中止；已开始替换时自动恢复先前两个目录和版本记录。如果恢复也遇到占用或空间问题，保留备份、暂存和日志，解决后重试：

```powershell
.\install.ps1 -Action Status -Destination $target
.\install.ps1 -Action Recover -Destination $target
```

进程在提交前中断，`Recover` 恢复原状态；已经提交完成、仅清理中断，则完成清理并保留新版本。待恢复事务存在时，拒绝开始新的安装、升级或回滚。不要手动删除日志或事务目录。

安装器拒绝目标、相关祖先或待复制子树中的符号链接 / NTFS reparse point，以及源目标重叠、文件系统根目录、UNC/device 路径。互斥锁只协调安装器进程；升级期间应停止使用这两个 Skill 写入文件。

两个目录的替换不是一次文件系统原子操作，日志与备份用于恢复。测试覆盖故障注入和中断恢复，不包括真实断电或磁盘损坏。安装器的静态校验也不替代源码来源审核与完整 CI。

## 当前验收范围

安装器仅在隔离目录验证，没有向真实 `.agents/skills` 安装。后续已使用本机 DSH 原始模块，在最小隔离组合中验证发现、读取和同名优先级；完整桌面会话、Role/Hooks 和模型章节写作仍未验收。分别见 [`m4-validation.md`](m4-validation.md) 与 [`dsh-discovery.md`](dsh-discovery.md)。
