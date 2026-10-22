# robot-data-platform

机器人数据管理平台。本文件是 Codex 和 Claude 共用的唯一规则来源。

## 开工前先读

- 任何任务：先读 `docs/README.md`，弄清文档放在哪、谁能改什么。
- 做规划、设计，或拿不准需求时：读 `docs/brief/`。其中 `0001` 是原始需求与约束，`0002` 是环境事实（后续的 `000N-环境事实更新-*` 是对它的更正和补充，冲突时以新的为准），`0003` 是已批准的方案。
- 实现某张工单时：读该工单文件本身，以及它引用的 spec、ADR、手册和 `GLOSSARY.md` 里的术语。
- 写代码或评审代码时：读 `docs/standards/CODING_STANDARDS.md`。

## 硬性规则

1. **数据只读。**
   - agent 对 `/mnt/dataset1`、`/mnt/dataset2` 和 NAS 上的数据一律只读。
   - 平台运行时，只有 worker 能写存储根，而且只写登记为可写的存储根（NAS 上的平台区）；只新建，已经入库的数据不再修改（ADR 0006）。
   - `/mnt/datasets` 导航层只能通过平台提供的受控接口修改。
   - 测试只用临时目录，或 `tests/` 里的假导航层，不碰真实路径。
2. **不参考旧项目。** 不读取、不复用 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`。
3. **文件归属。**
   - Codex 只改 `src/`、`tests/`。
   - 以下是**受保护文件**，只有在工单明确允许时才能改：
     - `pyproject.toml`、`uv.lock`、`Makefile`、`scripts/`、`.githooks/`
     - `src/web/` 下的 `package.json`、`pnpm-lock.yaml`、`tsconfig*.json`、`eslint.config.*`、`vite.config.*` 和 Prettier 配置
   - `.scratch/`、`docs/`、`GLOSSARY.md`、`AGENTS.md`、`CLAUDE.md` 只由 Claude 修改。
4. **函数契约先行。**
   - 每张实现工单分两步交付，每一步都由 Claude 审核后提交。Codex 的沙箱写不了 `.git`，所以 Codex 只把改动留在工作区。
     - 第一步是契约骨架：签名、类型、完整 docstring，函数体只写 `raise NotImplementedError`。
     - 骨架获批后，第二步逐函数用 TDD 实现。
   - 公开函数的 docstring 写六项：首行写职责，然后依次是 `Args:`（含单位和取值范围）、`Returns:`、`Raises:`（含触发条件）、`Side Effects:`、`Time Semantics:`。
     - 小节标题用英文，这样 ruff 能核对 docstring 和签名是否一致。
     - 内容写中文，不适用的项写"无"。
   - 函数级文档只写在 docstring 里，不另写 markdown。
5. **充分的中文注释。**
   - 注释和 docstring 用中文写，标识符、规则码、库名保留英文。
   - 注释说明"为什么"，以下地方必须写：
     - 模块的职责和边界
     - 不直观的判断
     - 常量和阈值的含义、单位、出处
     - 顺序约束
     - 权宜做法，以及它在什么条件下可以去掉
     - 每个测试验证的是哪条契约行为
6. **检查链。**
   - `make check` 是唯一的检查入口。Codex 交付前要把它跑到全绿。
   - 提交时经过 `.githooks/pre-commit`，不加 `--no-verify`。
   - 豁免注释只能针对单条规则，并且要写明理由。
7. **先用现成的；新增依赖必须经负责人批准。**
   - 写新功能前，按这个顺序找现成的实现：标准库 → 已批准的依赖 → 成熟的第三方库（走依赖申请）→ 最后才自己写。自己写的，在模块注释里写明为什么不用现成的。Claude 评审时把这一条列为一项检查。
   - 需要新依赖时，停下来写一份依赖申请：包名、版本、用途，以及为什么标准库和现有依赖不够用。由 Claude 核实，负责人批准后由 Claude 安装。

## Agent skills

### Issue tracker

工单以 markdown 文件形式存放在 `.scratch/` 下（本地 tracker）。见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五个 triage 角色，标签字符串与角色名相同，写在工单的 `Status:` 行。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：根目录 `GLOSSARY.md` + `docs/adr/`。见 `docs/agents/domain.md`。
