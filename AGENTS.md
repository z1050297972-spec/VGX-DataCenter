# robot-data-platform

机器人数据管理平台。本文件是 Codex 和 Claude 共用的唯一规则来源。

## 开工前先读

- 任何任务：先读 `docs/README.md`，弄清文档放在哪、谁能改什么。
- 做规划、设计，或拿不准需求时：读 `docs/brief/`。其中 `0001` 是原始需求与约束，`0002` 是环境事实（后续的 `000N-环境事实更新-*` 是对它的更正和补充，冲突时以新的为准），`0003` 是已批准的方案。
- 实现某张工单时：读该工单文件本身，以及它引用的 spec、ADR 和 `GLOSSARY.md` 里的术语。

## 硬性规则

1. **数据只读。** 不往 `/mnt/dataset1`、`/mnt/dataset2` 和 NAS 写任何东西。`/mnt/datasets` 导航层只能通过平台提供的受控接口修改。测试只能使用临时目录，或 `tests/` 里的假导航层，不碰真实路径。
2. **不参考旧项目。** 不读取、不复用 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`。
3. **文件归属。**
   - Codex 只改 `src/`、`tests/`。`pyproject.toml`、`Makefile` 只有在工单明确允许时才能改。
   - `.scratch/`、`docs/`、`GLOSSARY.md`、`AGENTS.md`、`CLAUDE.md` 只由 Claude 修改。
4. **函数契约先行。**
   - 每张实现工单分两次提交：先提交契约骨架（签名、类型、完整 docstring，函数体只写 `raise NotImplementedError`），骨架获批后再逐函数用 TDD 实现。
   - docstring 必须写清：职责、参数（含单位和取值范围）、返回值、会抛的异常及触发条件、副作用、时间语义。
   - 函数级文档只写在 docstring 里，不另写 markdown。
5. **新增依赖必须经负责人批准。**

## Agent skills

### Issue tracker

工单以 markdown 文件形式存放在 `.scratch/` 下（本地 tracker）。见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五个 triage 角色，标签字符串与角色名相同，写在工单的 `Status:` 行。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：根目录 `GLOSSARY.md` + `docs/adr/`。见 `docs/agents/domain.md`。
