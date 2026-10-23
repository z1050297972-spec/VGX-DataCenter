你在工单「Web 骨架与前端检查链」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-02-web-skeleton-frontend-check-chain（git worktree，分支 t/m0-02-web-skeleton-frontend-check-chain）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/02-web-skeleton-frontend-check-chain.md，以及它引用的 spec（/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/spec.md）、ADR（/home/shawn/桌面/robot-data-platform/docs/adr/ 下的 0001、0002、0005），和 /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里的术语

用 $enterprise-coding。本票把派工 A 拆成了 A1、A2 两段（见工单「派工分段」）。这一次只做**派工 A1**：只交一个文件 `src/web/package.json`，不跑任何检查。前端依赖还没装；A1 交回以后由 Claude 用 `pnpm add` 装依赖（它会把依赖表写进这个文件）、做依赖提交，再续接这个会话做 A2。

`src/web/package.json` 的要求：
- 只写四个字段：`name`（建议 `"rdp-web"`）、`private: true`、`type: "module"`、`scripts`。
- **不写**依赖表（`dependencies`、`devDependencies`、`peerDependencies`、`optionalDependencies`），也不写 `packageManager`、`engines`、`pnpm` 字段。依赖表只由 Claude 用 `pnpm add` 写。
- `scripts` 只给开发者本地用，`make check` 不会调用它们（工单：`make check` 里不出现 `pnpm`，前端工具一律从 `src/web/node_modules/.bin/` 调用）。建议放这几个：`dev`（`vite`）、`build`（`vite build`）、`preview`（`vite preview`）。检查类的命令以 Makefile 为准，不在这里重复，免得两处不一致。
- JSON 不能写注释。为什么只有这几个字段、为什么 scripts 不含检查命令，写在最终回复第 4 块里，A2 再把理由写进 Makefile 的注释。

不要建别的文件，包括 `src/web/` 下的其他文件、`pnpm-workspace.yaml`、`tsconfig*.json`、配置文件、`Makefile` 的改动、`src/rdp/` 和 `tests/` 的改动：它们都留到 A2。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`Makefile`、`pyproject.toml`（只改 `[tool.importlinter]` 和 FastAPI 带来的 ruff、basedpyright 配置调整）、`scripts/check_contracts.py`（只改 `test_*` 的跳过范围和对应 docstring）、`src/web/package.json`（新建，只写 `name`、`private`、`type`、`scripts`）、`src/web/tsconfig*.json`、`eslint.config.*`、`vite.config.*`、Prettier 配置和 `.prettierignore`（新建）、`.gitignore`（只追加前端产物）、`.githooks/pre-commit`（只在实测必须改时改）。`pnpm-lock.yaml`、`uv.lock`、`pnpm-workspace.yaml` 不改。**这一次（A1）只新建 `src/web/package.json`，其余几个留到 A2。**
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 沙箱不能联网，不要尝试安装任何东西。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：这一次不适用，写"A1 不跑检查"。另外原样贴出工作目录里 `git status --porcelain --untracked-files=all` 的输出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
