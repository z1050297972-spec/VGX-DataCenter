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
- **沙箱与依赖**：`workspace-write` 沙箱没有网络，新增依赖由谁、在什么时候安装。

**完成标准**：以上各项都有结论，写在本票 Answer 里。`docs/agents/codex-workflow.md` 在 M0 据此成文，并用一张小工单把 ①–⑦ 完整跑通一遍。
