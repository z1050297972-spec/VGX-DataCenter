# Codex 协作规程

Type: grilling
Status: open
Blocked by: 03

## Question

确认 0003 第八节的派工流水线：Codex 负责实现，Claude 负责评审和管理。`CLAUDE.md` 里已经有执行层面的要点，这张票要把细节定下来。

要定的：

- **派工提示模板**：提示 A（只写契约骨架）和提示 B（按契约用 TDD 实现）各包含哪些内容。
- **状态流转**：`ready-for-agent → in-progress → in-review → done`，打回时走 `changes-requested`。这几个状态和 `docs/agents/triage-labels.md` 里的五个角色是什么关系。
- **分支与合并**：分支命名（`t/<里程碑>-<NN>-<slug>`），以及 `--no-ff` 合并的约定。
- **骨架审核摘要**：给负责人的那一页摘要用什么格式。
- **打回上限**：评审最多打回几轮，超过之后怎么升级给负责人。
- **文件归属**：后端在 `src/`、`tests/`；React 前端代码放在哪个目录，是否同样由 Codex 写。
- **沙箱与依赖**：`workspace-write` 沙箱没有网络，新增依赖由谁、在什么时候安装。已在「[技术栈与工程规范](03-tech-stack-standards.md)」定好，见下一节。

## 负责人初步意见

- 2026-10-21：执行工作交给 Codex（GPT），Claude 只负责审核和管理。范围不限于实现工单，走图时 AFK 的执行（task、research 票）也要派出去。已写进 `CLAUDE.md`。
- 由此要补定的点：
  - 非代码任务的派工提示模板
  - 沙箱模式（只读的活用 `read-only`）
  - research 票需要联网时 Codex 能不能做
  - Claude 对调研、盘点结果复核到什么程度

## 「[技术栈与工程规范](03-tech-stack-standards.md)」带来的变化（2026-10-21）

- **Codex 不能提交**（[0006](../../../docs/brief/0006-环境事实更新-Codex沙箱.md)）：
  - 流水线里所有由 Codex 做的提交，都改由 Claude 完成。Codex 把改动留在工作区，Claude 审完后提交；骨架获批后的那次提交就是契约提交。
  - 要定：Claude 在哪几个时间点提交、提交说明怎么写、打回修改时工作区怎么处理。
- **核对文件归属**：改动还没提交时，`git diff --name-only` 看不到新建的文件，要改用 `git status --porcelain`。`CLAUDE.md` 评审步骤的第 2 步要跟着改。
- **依赖安装**：流程已定，见 `AGENTS.md` 硬性规则 7。本票只需把它写进派工模板。
- **前端代码**：放在 `src/web/`，由 Codex 写，已在 ADR 0001 定好。
- **类型检查**：basedpyright 能不能在沙箱里运行，在 M0 第一张工单里实测。

**完成标准**：以上各项都有结论，写在本票 Answer 里。`docs/agents/codex-workflow.md` 在 M0 据此成文，并用一张小工单把 ①–⑦ 完整跑通一遍。
