# 本地 M0～M2 验收记录

日期：2026-10-21（America/Phoenix）。本次只操作本地工作区，没有创建公开仓库、设置远端、提交发布、配置 Actions 或安装全局 Skill。

## 交付内容

- M0：依赖核查见 `docs/dependencies.md`，动态依赖清单见 `scripts/dependencies.json`。
- M1：两个原始 Skill、原版 LICENSE、`upstream-lock.json`、本地 Git 初始化、换行保护、README 与 NOTICE。
- M2：只读检查/候选同步器、布局与引用验证、差异报告、统一验证入口、44 项离线测试及 3 个专用合成样例。

固定上游：`zenstory-ai/oh-story-claudecode`，正式 Release `v0.9.0`。

完整提交 SHA：`74080143dd1ac9a39a930fafd99a0dbbe61b946a`。

两个 Skill 合并摘要：`f964993429610efc1d1f1918269300a3e65f4fb8f6da2d7811d258fd188bbd45`。

## 实际验证结果

环境：Windows，Python 3.11.5，Node.js v24.19.0，Git 2.45.1.windows.1。

| 检查 | 结果 |
|---|---|
| `python scripts/validate_all.py` | 退出 0，`PASS: local validation complete` |
| 离线测试 | 44/44 通过 |
| 目录、元数据与 lock | 两个 Skill，90 + 12 个文件，摘要和逐文件清单一致 |
| 静态依赖与引用 | 591 处检查通过，另明确报告 7 项已审查可选引用/路由提示 |
| Python / JavaScript 语法 | 7 个上游 Python、10 个上游 JavaScript 通过；维护 Python 脚本亦通过语法检查 |
| 检测器样例 | 两个 Skill 各自运行两套检测器；干净样例退出 0，阻断样例退出 1 且有预期 finding，缺文件退出 2；共 12 项通过 |
| 只报告行为 | 检测后合成样例字节不变 |
| 动态运行检查 | 10 项合成运行检查通过，包括排纲任务包、追踪 init/check、缺输入拒绝、题材卡、作者记忆、storyctl 检测链、非法细纲拒绝 |
| 直接对照上游源码包 | 两个子树的 102 个文件及 LICENSE 共 103 个文件逐字节一致 |
| 在线 `python scripts/sync_upstream.py --check` | 正确解析正式 Release 和完整 SHA；`changed: false`、`No relevant changes`，退出 0 |
| 私人数据模式 | 分发树高置信检查通过；缓存、`.env`、私人目录被 Git 忽略 |
| 远端 | `git remote -v` 为空 |

离线测试覆盖文件新增、修改、删除、首次导入、相同内容的新 tag、无关上游变化、现有输出保护、当前快照损坏、缺失目录/资产、错误 SHA、路径穿越、Windows 路径别名、重复/大小写冲突、链接/特殊文件、文件大小、MIT/版权完整性、仅许可变化、未知依赖、越界引用、私人文件和摘要篡改。同步准备阶段不会执行上游脚本，也有对应测试。

## 验收边界

- 同步器输出的是通过静态门禁的新候选目录；完整验收仍须运行 `validate_all.py --root <候选目录>`。它不会自动替换当前快照。
- `outline-reverse-rules.md` 是上游主动忽略缺失的可选报告来源；不引入其他 Skill 补齐。
- `story-import` 等六个路由未打包；已有小说缺少标准追踪时，导入流程可能不可用。
- 专业 Agent 的直接执行回退来自上游文档，尚未在 DSH 模型会话中验证。
- 未完成 DSH 发现、真实章节写作、Role/Hook 兼容性和人工文学质量验收；这些属于 M4。
- 静态引用扫描和凭据模式不能证明所有动态路径或所有私人数据风险；动态依赖依靠显式清单及选定运行检查。
- 未启用 Lite 行为补丁，因此补丁应用/冲突测试后置。没有自动化 PR、自动合并或发布行为。
