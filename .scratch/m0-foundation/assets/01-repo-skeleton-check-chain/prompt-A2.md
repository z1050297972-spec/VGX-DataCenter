派工 A1 已通过评审。Claude 已经装好依赖，并在工单分支上做了依赖提交 `4ee62d2`（`依赖：ruff、basedpyright、import-linter、pytest（仓库骨架和检查链）`）。这个提交里有你在 A1 交的两个文件，以及 `uv add` 写进去的 `[dependency-groups]` 和 `uv.lock`。工作目录现在是干净的。

现在做**派工 A2：契约骨架**。交付见工单「派工分段」的 A2，要求见工单「要求」和「验收标准」。工单在 A1 之后追加了 Comments（装依赖时核实的版本），动手前重读一遍主仓库目录里的版本：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/01-repo-skeleton-check-chain.md 。检查链的规则集和阈值按 /home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/03-tech-stack-standards.md 的 Answer 里「后端检查链」一节。

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。
2. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。
3. `make check` 跑到全绿。

本次交付：
- `pyproject.toml` 里的 `[tool.*]` 检查配置：ruff（format 和 check）、basedpyright 严格模式、import-linter、pytest。`[project]`、`[build-system]`、`[dependency-groups]` 和 `uv.lock` 不动。
- `Makefile`：`make check` 和 `make fmt`。这一次 `make check` 不含契约检查那一步，在 Makefile 里用注释标明，派工 B 实现脚本后再接上。
- `.githooks/pre-commit`，带可执行位，按工单要求和 Comments 里的 D2。
- 需要时往 `.gitignore` 追加检查链的缓存目录。
- 占位包 `rdp.api`、`rdp.ops`、`rdp.infra`（`__init__.py` 的 docstring 按 CODING_STANDARDS 4.1），以及示例模块 `src/rdp/infra/timeutil.py`、契约检查脚本 `scripts/check_contracts.py` 的契约骨架。
- 测试清单：示例模块和契约检查脚本的每个契约行为至少一个测试（CODING_STANDARDS 7.1、7.3），测试体先跳过。

环境事实（Claude 装依赖时核实的）：
- 项目环境：`.venv/bin/python` 是 CPython 3.12.15；ruff 0.17.1、basedpyright 1.40.2（based on pyright 1.1.414）、import-linter 2.15、pytest 9.1.1。`rdp` 以 editable 方式装在 `.venv` 里，指向本工作目录的 `src/rdp/`。
- PATH 上有 miniconda 的 Python 3.14 和 ruff 0.16.3。Makefile 和钩子里一律调用项目环境里的工具：推荐直接用 `.venv/bin/<工具>`，因为 `uv run` 可能要写 `~/.cache/uv`，沙箱里写不了。
- 03 号票"关掉 D400、D415""RUF001–003 加中文全角标点白名单"是在 ruff 0.16.3 上测的，项目里是 0.17.1。在 0.17.1 上重新确认，结论写进配置旁边的注释。DOC 系列规则在 0.17.1 上仍是 preview。
- 沙箱里不能建 socket（docs/brief/0011）。basedpyright 跑不起来时，停下来原样报告报错，不要把它从 `make check` 里拿掉（验收第 4 条）。
- 你写不了 `.git`，钩子没法用真提交来试。可以直接运行 `.githooks/pre-commit` 看它的判断逻辑；真提交的试验由 Claude 在探针工作目录里做（验收第 6 条）。

容易出错的地方：
- 钩子判断"只动了规划文件"时，路径里可能有中文，例如 `docs/brief/0011-环境事实更新-Codex运行与执行线.md`。git 默认会给这类路径加引号、转义成八进制，前缀匹配就会失效。读暂存文件清单时用 `-z`；改名要让新旧两个路径都参与判断（`--no-renames`）；删除也算改动。暂存区为空时，按"动了其他文件"处理，跑全量 `make check`。
- 跑完 `make check` 以后，`git status --porcelain --untracked-files=all` 要和跑之前相同（验收第 8 条）。
- 验收第 5 条的违规试验由 Claude 做，但你的配置要让每种违规失败在对应的那一步，"不能失败"的几种也不能失败。你可以用临时文件自己先试，试完删掉，工作目录里不留试验文件。
- `make fmt` 也要能跑（验收第 2 条）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只写 `[tool.*]` 表，依赖表由 Claude 用 `uv add` 写）、`Makefile`（新建）、`scripts/check_contracts.py`（新建，`scripts/` 下只有这一个文件）、`.githooks/pre-commit`（新建，带可执行位）、`.gitignore`（只追加检查链产生的缓存目录）。`uv.lock` 不改。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 沙箱不能联网，不要尝试安装任何东西。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出，包括 basedpyright 那一步的输出。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
5. 检查配置的要点：开了哪些规则、阈值多少、豁免了什么（关掉的规则、per-file-ignores）、各自的理由；pydoclint 的规则哪几条开了、哪几条没开、为什么；在 0.17.1 上重新确认的结果。
