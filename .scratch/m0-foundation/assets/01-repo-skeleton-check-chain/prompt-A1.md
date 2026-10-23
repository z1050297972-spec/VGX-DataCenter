你在工单「仓库骨架和检查链」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain（git worktree，分支 t/m0-01-repo-skeleton-check-chain）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/01-repo-skeleton-check-chain.md，以及它引用的 ADR（/home/shawn/桌面/robot-data-platform/docs/adr/0002-技术栈.md），和 /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里的术语。本票没有 spec。

用 $enterprise-coding。本票把派工 A 拆成了 A1、A2 两段（见工单「派工分段」）。这一次只做**派工 A1**：只交下面两个文件，不跑任何检查。检查工具还没装，`make check` 也还不存在；A1 交回以后由 Claude 装依赖，再续接这个会话做 A2。

1. `pyproject.toml`：只有 `[project]` 和 `[build-system]` 两张表。
   - `[project]`：`name = "rdp"`；`version` 写静态值 `"0.1.0"`（uv_build 不支持动态版本）；`requires-python = "==3.12.*"`；`dependencies = []`。可以写一句中文的 `description`。不写 `readme`（仓库根没有 README，你也不能建），不写 `authors`。
   - 依赖表留空：`dependencies` 保持空列表，不写 `[dependency-groups]` 和 `[project.optional-dependencies]`。依赖由 Claude 在 A1 之后用 `uv add` 写进去。
   - `[build-system]`：构建后端用 uv_build，负责人已按规则 7 批准（工单 Comments 里的 D1）。本机装的 uv 是 **0.13.5**，所以写 `requires = ["uv_build>=0.13.5,<0.14.0"]` 和 `build-backend = "uv_build"`，和 uv 0.13.5 的 `uv init` 生成的一致。uv_build 的默认布局就是 `src/<包名>/`，不用另配 `[tool.uv.build-backend]`。
   - 这一次不写任何 `[tool.*]` 表，检查配置留到 A2。
   - 按规则 5，用中文注释说明不直观的地方，例如为什么固定 3.12、构建后端为什么用 uv_build、版本上限是什么意思。
2. `src/rdp/__init__.py`：只有包的 docstring，不写任何代码。按 CODING_STANDARDS 4.1 写：这是平台包 `rdp` 的根；三层（入口层 `rdp.api`、`rdp.ops` → 领域层 → 基础层 `rdp.infra`）只能从上往下依赖；根包本身不放逻辑；相关的 ADR 和工单。

不要建别的文件，包括 `src/rdp/` 下的子包、`tests/`、`Makefile`、`.python-version`、`py.typed`：它们要么留到 A2，要么不在本票。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`、`Makefile`、`scripts/check_contracts.py`、`.githooks/pre-commit`、`.gitignore`，各自允许做什么见工单「允许改的受保护文件」。**这一次（A1）只新建 `pyproject.toml`，其余几个留到 A2。**
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 沙箱不能联网，不要尝试安装任何东西。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：这一次不适用，写"A1 不跑检查"。另外原样贴出工作目录里 `git status --porcelain --untracked-files=all` 的输出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
