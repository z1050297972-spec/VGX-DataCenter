# 仓库骨架和检查链

Status: in-review

## 依据

- **现在还没有 M0 的 spec。** 本票依据 ADR 0002（技术栈），以及「技术栈与工程规范」（`.scratch/platform-v1/issues/03-tech-stack-standards.md`）和「Codex 协作规程」（`08-codex-workflow.md`）的 Answer。M0 的 spec 等平台 v1 这张图的决策票走完后再写。
- 规范：`docs/standards/CODING_STANDARDS.md`（草稿）。流程：`docs/agents/codex-workflow.md`（草稿，定稿之前以 08 号票的 Answer 为准）。
- 环境事实：`docs/brief/0006`、`0009`（Codex 沙箱）。

## 目标

1. 搭出后端的包骨架和整条检查链：`make check` 能跑完，能拦住违规，提交前由 git 钩子自动跑。之后的每张票都在这条检查链上交付。
2. 用这张小票把 Codex 派工流水线（`codex-workflow.md` 第 3 节）完整跑一遍。跑下来要改的地方记进 Comments，跑通后 `codex-workflow.md` 和 `CODING_STANDARDS.md` 定稿。

## 范围

- Python 3.12 + uv 的包骨架：包名 `rdp`，代码在 `src/rdp/`。
- 三层的占位包，加一个最小的示例模块和它的测试，用来证明整条检查链在真实代码上能跑通。
- 检查工具的配置：ruff（format 和 check）、basedpyright 严格模式、import-linter、pytest。规则集和阈值按 03 号票 Answer 的「后端检查链」。
- 契约检查脚本 `scripts/check_contracts.py`，检查 docstring 的六项。
- `Makefile` 里的 `make check` 和 `make fmt`。
- `.githooks/pre-commit`。

## 不在本票

- **前端骨架**（`src/web/`、pnpm、ESLint、Prettier、tsc、Vitest，以及 `make check` 的前端部分）：建议单独开第 2 张，理由见文末「前端放哪张票」。
- **运行依赖**（fastapi、uvicorn、sqlalchemy、alembic、argon2-cffi）和 httpx：已获批准，等第一张用到它们的工单再装，不用再申请（`CODING_STANDARDS.md` 9.3）。本票只装 4 个开发工具。
- 日志和报错框架、数据库与迁移、运维命令、存储根、worker：M0 后续的工单。
- "领域层不 import FastAPI"的 import-linter 合约：FastAPI 装上以后再加。

## 允许改的受保护文件

除了 `src/`、`tests/`，Codex 在本票里只能改下面这些：

| 文件 | 允许做什么 |
|---|---|
| `pyproject.toml` | 新建；写 `[project]`、`[build-system]` 和 `[tool.*]` 下的检查配置。依赖表（`[project] dependencies`、`[dependency-groups]`）只由 Claude 用 `uv add` 写 |
| `Makefile` | 新建 |
| `scripts/check_contracts.py` | 新建。`scripts/` 下只有这一个文件 |
| `.githooks/pre-commit` | 新建，带可执行位 |
| `.gitignore` | 只追加检查链产生的缓存目录 |

- `.gitignore` 不在规则 3 的受保护清单里，但它在 `src/`、`tests/` 之外，所以同样要在这里写明。
- `uv.lock` 只由 Claude 的 `uv add` 生成，Codex 不改。
- 其他路径都不动，包括仓库根的 README、`.python-version`、`docs/`、`.scratch/`。

## 要求

### 包骨架与分层

- `[project]`：`name = "rdp"`，`requires-python = "==3.12.*"`，不写 `readme`（仓库根没有 README，Codex 也不能建）。
- 构建后端用 `uv_build`（待负责人确认，见下文第 1 条），版本范围按 Claude 在派工提示里告知的 uv 版本写。
- 占位包。每个 `__init__.py` 的 docstring 写明这一层负责什么、不负责什么（`CODING_STANDARDS.md` 4.1）：
  - 入口层：`rdp.api`（FastAPI 接口）、`rdp.ops`（运维命令）。
  - 基础层：`rdp.infra`（数据库、配置、日志等）。包名是建议，负责人没有异议就用它。
  - 领域层：现在还没有模块，等「核心领域模型与术语」「作业模型」的结论和 M0 的 spec。
- import-linter 合约：入口层在上，基础层在下，领域层将来插在中间的位置用注释标出来。

### 示例模块

`src/rdp/infra/timeutil.py` 里的 `ensure_utc(value: datetime) -> datetime`。它也是 `CODING_STANDARDS.md` 5.1"时刻一律 UTC"以后要用的小工具：

- 带时区的 `datetime` 换算成 UTC 返回，表示的时刻不变。
- 不带时区的报 `ValueError`（程序缺陷）。标准库的 `astimezone()` 会把不带时区的值默认当成本地时间，这正是这个函数要拦的；这一点写进模块注释，说明为什么不直接用标准库（规则 7）。
- 换算后超出 `datetime` 能表示的范围时怎么处理，写进契约并测试。
- 测试的期望值手算，输入按边界取：`+08:00` 的值、本来就是 UTC 的值、带微秒的值、不带时区的值、换算后越界的值。

### 契约检查脚本

`scripts/check_contracts.py`：

- 检查 `src/rdp/` 和 `scripts/` 下的 Python 文件，规则按 `CODING_STANDARDS.md` 3.1：
  - 公开函数六项齐全、顺序和规则 4 一致、每项都有内容（不适用的写"无"）。
  - 私有函数和 `@property` 至少一句职责；`@dataclass` 有 `Attributes:`。
  - 生成器用 `Yields:` 代替 `Returns:`；`@overload` 的签名、嵌套函数不查。
- 小节标题必须和规则 4 一字不差，例如写成 `Side effects:` 算缺了 `Side Effects:`。
- 每个问题输出一行：`文件:行号  函数全名  缺了哪几项（或者哪项为空、顺序不对）`。最后一行输出问题总数。
- 退出码：没有问题 0；有问题 1；参数错误或文件解析失败 2。
- 只用标准库（`ast`）。模块注释写明为什么不用现成的工具：ruff 的 pydocstyle、pydoclint 规则只认 Google 风格的标准小节，查不了 `Side Effects:` 和 `Time Semantics:`（规则 7）。
- 测试在临时目录里生成样例源文件，再运行脚本，断言退出码和输出。上面每条行为至少一个测试。

### Makefile 与钩子

- `make check` 依次跑：格式检查（`ruff format --check`）、`ruff check`、basedpyright、import-linter、契约检查、pytest，遇错即停。每一步开始时输出一行步骤名，失败时一眼能看出是哪一步。`make fmt` 跑 `ruff format` 和 `ruff check --fix`。
- 工具一律从项目环境里调用，例如 `.venv/bin/<工具>`，或者 `uv run --no-sync <工具>`。PATH 上有 miniconda 的 Python 3.14 和 ruff 0.16.3，调用错了，检查结果就不对。
- `make check` 不联网，也不触发 uv 的同步或加锁：Makefile 里不出现 `uv sync`、`uv lock`，也不出现不带 `--no-sync` 的 `uv run`。
- basedpyright 要明确分析项目 `.venv` 里的 Python 3.12（例如配置 `venvPath` 和 `venv`），不能落到 PATH 上的 3.14。
- 跑完 `make check` 以后，`git status --porcelain` 不多出任何东西：检查链的缓存（例如 import-linter 的 `.import_linter_cache/`）要么加进 `.gitignore`，要么关掉。
- `.githooks/pre-commit`：bash，`set -euo pipefail`，切到仓库根后跑 `make check`；失败时提示"修好后重新提交"。只改规划文件的提交跳不跳过检查，按下文第 2 条的结论。
- 派工 A2 时契约检查脚本还是桩，所以那时 `make check` 先不含契约检查这一步，在 Makefile 里用注释标明；派工 B 实现脚本后接上。

### 检查配置的注意点

- 03 号票里"关掉 D400、D415""RUF001–003 加中文全角标点白名单"，是在 ruff 0.16.3 上实测的。项目装的 ruff 版本可能不同，要在装上的版本上再验一次（验收第 5 条）。
- pydoclint 的规则（DOC201、DOC501 等）要和规则 4 的写法兼容：`Returns: 无`、`Raises: 无`，以及骨架阶段只有 `raise NotImplementedError` 的函数体，都不能报错（`CODING_STANDARDS.md` 3.3.1）。哪条规则和规则 4 冲突就不开，在最终回复里说明，由契约检查脚本兜底。
- 豁免：不带规则码的豁免、多余的豁免都要让 `make check` 失败，例如 ruff 的 PGH004、RUF100，basedpyright 的 `reportIgnoreCommentWithoutRule`、`reportUnnecessaryTypeIgnoreComment`，以装上的版本为准。`CODING_STANDARDS.md` 8.1 里带理由的单条豁免写法要能用。
- 测试函数也写 docstring，写明验证哪条契约行为。ruff 的 docstring 规则在 `tests/` 里保留"要有 docstring"这一条（D103），其余的按需放宽，每条放宽在配置里写理由（`CODING_STANDARDS.md` 8.2）。
- 工作目录在中文路径下（`~/桌面/…`），editable 安装也指向这里。沙箱里 `make check` 全绿就说明没问题。

## 派工分段

沙箱不能联网，依赖由 Claude 装；而 `uv add` 要先有 `pyproject.toml` 和 `src/rdp/__init__.py`，才能以 editable 方式装上 `rdp`。所以派工 A 拆成两段，中间由 Claude 装依赖，然后续接同一个会话。

- **派工 A1**（新会话）：只交两个文件，不跑任何检查（工具还没装）。A1 很小，正好先把派工这个动作试一遍。
  - `pyproject.toml`：只有 `[project]` 和 `[build-system]`，依赖表留空。
  - `src/rdp/__init__.py`：只有包的 docstring。
- **中间**：Claude 装依赖，做依赖提交（见「Claude 的步骤」第 7–9 步）。
- **派工 A2**（续接）：契约骨架。
  - `pyproject.toml` 里的 `[tool.*]` 检查配置；`Makefile`（暂不含契约检查）；`.githooks/pre-commit`；需要时追加 `.gitignore`。
  - 占位包、示例模块、契约检查脚本的契约骨架：签名、类型、六项 docstring，函数体 `raise NotImplementedError`。
  - 测试清单：跳过的测试，每个测试的 docstring 写明它验证哪条契约行为。
  - 在沙箱里把 `make check` 跑到全绿。验收第 4 条在这里第一次检验。
- **派工 B**（续接）：用 TDD 实现示例模块和契约检查脚本，再把契约检查接进 `make check`，最后 `make check` 全绿。

## 验收标准

Claude 评审时逐条核对，结果记进 Comments。

1. **环境**：在工作目录里，`.venv/bin/python -c 'import rdp, sys; print(sys.version)'` 输出 3.12.x；`uv.lock` 已入库；Codex 的改动里没有依赖表和 `uv.lock` 的变化。
2. **空骨架全绿**：在工作目录里，`make check` 按上面的顺序跑完六步，退出码 0；`make fmt` 能跑。用时记进 Comments。
3. **骨架阶段也全绿**：在契约提交上（函数体是桩、测试是跳过的），`make check` 退出码 0。
4. **沙箱里能跑**：派工 A2 和派工 B 的运行日志里，Codex 在沙箱中执行了 `make check`，basedpyright 那一步真正跑完、输出了检查结果（不是跳过，也不是环境错误），整条退出码 0。
   - basedpyright 跑不起来时，Codex 停下，原样报告报错，不把它从 `make check` 里拿掉。Claude 按 ADR 0002 的退路处理，并告诉负责人。
5. **违规会失败**：在探针工作目录里（`codex-workflow.md` 5.2）逐个放入下面的违规，`make check` 每次都失败，并且失败在对应的那一步；去掉以后恢复全绿。
   - 格式：一行不符合 ruff format。
   - ruff：`print(...)`；不带时区的 `datetime.now()`；裸 `except:`；被注释掉的代码；6 个参数的函数。
   - basedpyright：一个类型错误。
   - import-linter：基础层 import 入口层。
   - 契约检查：公开函数缺 `Time Semantics:`；私有函数没有 docstring；`@dataclass` 没有 `Attributes:`；小节顺序颠倒；某一项是空的。
   - pytest：一个失败的断言。
   - 豁免：不带规则码的 `# noqa` 和 `# type: ignore`；多余的 `# noqa: <规则码>`。
   - 下面这些不能失败：注释和 docstring 里的中文全角标点；以"。"结尾的 docstring；`Returns: 无` 和 `Raises: 无`；带理由的单条豁免。
6. **钩子能拦**：在探针工作目录里，用 `git -c core.hooksPath=.githooks commit` 提交一处违规，提交被拒，没有产生新提交；去掉违规后，同样的命令提交成功。`.githooks/pre-commit` 在提交里的权限是 `100755`。
7. **契约脚本能抓缺项**：第 5 条里契约检查的五种违规，输出都指到文件:行号、函数全名和缺的项；没有问题时退出码 0，有问题时 1，传入不存在的路径时 2。
8. **不留痕迹**：跑完 `make check` 以后，工作目录的 `git status --porcelain` 和跑之前相同。
9. **文件归属**：工作目录里只有 `src/`、`tests/` 和「允许改的受保护文件」里的改动；主仓库目录里规划文件以外没有改动；运行日志里没有碰两个旧项目（`codex-workflow.md` 3.5 第 2、4 项）。
10. **注释与契约**：示例模块和契约检查脚本符合规则 4、5，以及 `CODING_STANDARDS.md` 第 3、4、7 条（`/code-review` 的 Standards 轴）。

## Claude 的步骤

按顺序做。每一步的结果（版本号、会话编号、快照名、命令和输出摘要）记进 Comments。

- 工作目录：`~/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain`
- 分支：`t/m0-01-repo-skeleton-check-chain`
- assets：`.scratch/m0-foundation/assets/01-repo-skeleton-check-chain/`

**派工前**

1. 负责人批准本票，并回答「待负责人确认」；Status 改成 `ready-for-agent`。
2. **装 uv**：用官方的独立安装方式，装一个固定版本到 `~/.local/bin`（已在 PATH 上）；设 `UV_NO_MODIFY_PATH=1`，不改 shell 配置文件。记下 `uv --version`。
3. **装 Python**：`uv python install 3.12`，不加 `--default`，免得覆盖 PATH 上的 `python3`。记下装上的具体版本。
4. **开票**：Status 改成 `in-progress`；`git -C ~/桌面/robot-data-platform worktree add -b t/m0-01-repo-skeleton-check-chain <工作目录> main`。这时还没有 `pyproject.toml`，`codex-workflow.md` 3.1 的第 4、5 步（装依赖、跑基线）跳过。

**派工 A1**

5. 写 `prompt-A1.md`：用 `codex-workflow.md` 第 7 节的派工 A 模板，交付改成上文「派工分段」里 A1 的两个文件，并告知第 2 步装上的 uv 版本。拍快照 `A1`，派工，记下会话编号。
6. **审 A1**：工作目录的 `git status --porcelain --untracked-files=all` 只有这两个文件，内容符合「包骨架与分层」。

**装依赖**

7. 在工作目录里跑 `uv add --dev ruff basedpyright import-linter pytest`。它会解析依赖、写 `[dependency-groups]`、生成 `uv.lock`、建 `.venv`，并以 editable 方式装上 `rdp`（构建时要用到 A1 的 `src/rdp/__init__.py`）。
8. **核对**：`.venv/bin/python -c 'import rdp, sys; print(sys.version)'` 输出 3.12.x；`.venv/bin/basedpyright --version` 能跑。用 `uv tree --depth 1` 记下四个工具的版本，确认构建后端没有带进别的包。
9. **依赖提交**：`git add pyproject.toml uv.lock src/rdp/__init__.py`，提交说明 `依赖：ruff、basedpyright、import-linter、pytest（仓库骨架和检查链）`，正文注明附带了派工 A1 的最小包（没有它，uv 装不上 `rdp`）。这是唯一一个不经过钩子的提交，因为检查链这时还不存在。提交后工作目录干净。

**派工 A2**

10. 写 `prompt-A2.md`（派工 A 模板，交付见「派工分段」的 A2），拍快照 `A2`，先 `cd <工作目录>` 再续接。

**骨架关卡**

11. 按 `codex-workflow.md` 3.3 审骨架。另外，在快照 `A2-done` 的探针工作目录里，把验收第 5 条中除"契约检查"以外的违规逐个试一遍，再做验收第 6 条的钩子试验。试验写成脚本 `violation_probe.sh` 放进 assets，输出存成 `violation_probe-<快照名>.txt`；派工 B 之后还要再跑一次。
12. 一页摘要写进 Comments，Status 改成 `in-review`，交回主会话。这张票的摘要除了函数清单和测试清单，还要列出检查配置的要点：开了哪些规则、阈值多少、豁免了什么、为什么。
13. 负责人说"通过"以后：
    - 跑 `git config core.hooksPath .githooks`。这个设置在主仓库的 `.git/config` 里，所有工作目录共用；相对路径按各自的工作目录解析，所以合并之前 main 上没有 `.githooks/`，主仓库目录和原型工作目录都不受影响。
    - 做契约提交 `契约：仓库骨架和检查链`。这是第一个经过钩子的提交（验收第 3 条）。
    - Status 改回 `in-progress`。

**派工 B 与评审**

14. 写 `prompt-B.md`，拍快照 `B`，续接派工。
15. **评审**：按 `codex-workflow.md` 3.5 做。在快照 `B-done` 的探针工作目录里重跑 `violation_probe.sh`，这次包括契约检查的违规（验收第 5、6、7 条），并核对验收第 8 条。十条验收逐条记下结果。
16. 打回最多 3 轮（`codex-workflow.md` 3.6、6.3）。
17. 通过以后做实现提交 `实现：仓库骨架和检查链`（经过钩子），起草完工汇报，Status 改成 `in-review`，交回主会话。

**合并以后**（主会话）

18. 按 `codex-workflow.md` 3.7 合并。主仓库目录这时还没有 `.venv`，那一节第 3 步的 `uv sync --frozen` 会建一个。
19. 从这以后，主仓库目录里的提交也会经过钩子，规划提交怎么处理见下文第 2 条。
20. 按跑下来的情况修订 `codex-workflow.md` 和 `CODING_STANDARDS.md`，然后定稿。超时、快照这些暂定的做法，在 `/retro` 里调整。

## 风险

- **basedpyright 在沙箱里跑不起来**（03 号票留下的风险）：在派工 A2 第一次检验。退路按 ADR 0002：先改用 npm 装的 pyright（由 Claude 安装）；再不行，就只在评审时由 Claude 跑类型检查。用了哪种退路，都要告诉负责人。
- **uv 在沙箱里的行为**：`uv run` 可能要写 `~/.cache/uv`，而沙箱里写不了。Makefile 直接调 `.venv/bin/` 下的命令可以绕开；用 `uv run --no-sync` 的话，要在沙箱里实测。
- **钩子查的是工作目录，不是暂存区**：只做整体提交（`codex-workflow.md` 5.1）。
- **流水线第一次跑**：快照、探针工作目录、分段派工、超时这些做法，都还没在真实工单上跑过。跑下来的问题记进 Comments，留给定稿和 `/retro`。

## 待负责人确认

1. **构建后端用 `uv_build`。** `rdp` 要以 editable 方式装进环境，测试和 import-linter 才能 import 它，以后的运维命令入口也要靠打包，这需要一个构建后端。它不在 03 号票的首批清单里，按规则 7 要批准。
   - 建议用 `uv_build`：它和 uv 出自同一个项目，只在构建时用，不进运行环境。装的时候核实它没有传递依赖。
   - 备选是 hatchling，会多带几个传递依赖。
2. **规划提交要不要跑全量 `make check`。** 合并以后，钩子在主仓库目录里同样生效：主会话每次提交规划文件，都要跑一遍 `make check`，主仓库目录的 `.venv` 也得一直和锁文件一致。
   - 建议钩子先看暂存了哪些文件：只动了规划文件（`.scratch/`、`docs/`、`GLOSSARY.md`、`AGENTS.md`、`CLAUDE.md`）时，跳过检查并打印一行说明；动了其他文件，就跑全量。
   - 03 号票原定"跑全量 `make check`"，这是一处改动。不同意的话，钩子一律跑全量。

## 前端放哪张票

建议单独开第 2 张「Web 骨架与前端检查链」，本票只做后端：

- **本票的第一次已经够多**：第一次装 uv 和 Python 3.12，第一次在沙箱里跑 basedpyright，第一次把流水线从头跑到尾。再加上 pnpm、ESLint、Prettier、tsc、Vitest，出了问题不好分辨是哪一块，骨架关卡要看的配置也会翻倍。
- **前端检查链要一个 FastAPI 应用**：其中"OpenAPI 生成的类型是否过期"这一步，要靠 FastAPI 产出 OpenAPI，而本票不装 FastAPI。第 2 张票把最小的 FastAPI 应用（同进程托管前端构建产物，ADR 0001）和前端骨架放在一起，正好是一条能演示的竖切。
- **流程先修一遍**：本票跑完、流程按跑下来的情况修过以后再做第 2 张，第二次走流水线会更顺。
- **代价**：钩子和 Makefile 在第 2 张票里要再改一次，那张票的「允许改的受保护文件」里要写上；`.gitignore` 也要加上 `node_modules/` 这类条目。

## Comments

- 2026-10-22，起草（后台 agent）。依据见上；等负责人过目，回答「待负责人确认」后改成 `ready-for-agent`。
- 2026-10-22，负责人批准本票（"确认"；三个问题都没提异议，按推荐答案记下）：
  - **D1**：构建后端用 `uv_build`，按规则 7 批准。安装时核实它没有传递依赖。
  - **D2**：钩子先看暂存了哪些文件。只动了规划文件（`.scratch/`、`docs/`、`GLOSSARY.md`、`AGENTS.md`、`CLAUDE.md`）时，跳过检查并打印一行说明；动了其他文件，照常跑全量 `make check`。
  - **D3**：前端骨架单独开第 2 张工单「Web 骨架与前端检查链」，和最小的 FastAPI 应用放在一起。本票跑完、流程按跑下来的情况修过以后再起草。
  - 基础层包名用 `rdp.infra`。
  - 同时在 `AGENTS.md` 的"开工前先读"里加了一条：写代码或评审代码时，读 `docs/standards/CODING_STANDARDS.md`。
  - Status 改成 `ready-for-agent`，由执行线的后台 agent 按「Claude 的步骤」推进，做到骨架关卡后交回主会话。
- 2026-10-22 10:57，第 2 步装 uv（执行线）。
  - 版本：uv 当前稳定版 0.13.5，PyPI 和 GitHub releases 一致（GitHub 发布于 2026-10-22T01:35Z，标为 stable）。固定 0.13.5。
  - 安装：官方独立安装脚本 `https://github.com/astral-sh/uv/releases/download/0.13.5/uv-installer.sh`，和 `https://astral.sh/uv/0.13.5/install.sh` 逐字节相同（sha256 `1c6e7f02…`）。先下载成文件、看过内容：cargo-dist 0.32.0 生成；内嵌的 `uv-x86_64-unknown-linux-gnu.tar.gz` 校验值 `f68d291c…` 和 release 里的 `.sha256` 一致；`NO_MODIFY_PATH=1` 时不碰 shell 配置文件。然后 `UV_NO_MODIFY_PATH=1 sh uv-installer-0.13.5.sh`，退出码 0。
  - 结果：`~/.local/bin` 里多了 `uv` 和随它发布的 `uvx`，此外只写了回执 `~/.config/uv/uv-receipt.json`（`"modify_path":false`，供 `uv self update` 用）。`.profile`、`.bashrc` 的 sha256 装前装后相同。
  - `uv --version`：`uv 0.13.5 (x86_64-unknown-linux-gnu)`。
- 2026-10-22 10:58，第 3 步装 Python。
  - 命令：`uv python install 3.12 --no-bin`，不加 `--default`。
  - 另加了 `--no-bin`：uv 0.13 默认会把 `python3.12` 放进 `~/.local/bin`，而这一步要求 `~/.local/bin` 里只装 uv。不加 bin 不影响项目：uv 建 `.venv` 时直接找 `~/.local/share/uv/python/` 下的解释器。
  - 结果：CPython 3.12.15，在 `~/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/`。PATH 上的 `python3` 仍是 miniconda 的 3.14.6。
- 2026-10-22 10:58，第 4 步开票。扫过 `.scratch/m*/issues/*.md` 的 `Status:` 行，没有别的实现票在进行中。Status 改成 `in-progress`。`git -C ~/桌面/robot-data-platform worktree add -b t/m0-01-repo-skeleton-check-chain ~/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain main`，工作目录在 `28b6e1c`，`git status --porcelain --untracked-files=all` 为空。按本票，`codex-workflow.md` 3.1 的第 4、5 步跳过。
- 2026-10-22 11:01，第 5 步派工 A1。
  - 提示 `assets/01-repo-skeleton-check-chain/prompt-A1.md`（派工 A 模板，交付改成 A1 的两个文件；告知 uv 0.13.5，`[build-system]` 写 `uv_build>=0.13.5,<0.14.0`，和 uv 0.13.5 的 `uv init` 生成的一致）。
  - 快照 `refs/rdp/m0-01/A1`（`ead26a4`）。会话 `01a16490-d7e5-7862-b467-af073a447b22`。
  - 命令：在工作目录里 `timeout 3600 codex exec -m gpt-6-astra -c model_reasoning_effort='"high"' -C <工作目录> -s workspace-write --json -o assets/…/out-A1.md - < prompt-A1.md`。运行日志 `<执行线临时目录>/m0-01/ev-A1.jsonl`、`err-A1.txt`。
  - 派工前核实：PyPI 上 `uv-build` 0.13.5 的 `requires_dist` 为空（没有传递依赖），许可证 MIT OR Apache-2.0。
  - 环境变化（和 0011 不同）：`~/.codex/config.toml` 的 `base_url` 现在是 `http://10.1.179.3:8088/v1`（本机 Wi-Fi 地址，在 `no_proxy` 的 10.0.0.0/8 里，直连 200），默认 `model_reasoning_effort` 是 `"max"`。命令里照常显式写 `high`。
- 2026-10-22 11:05，第 6 步审 A1：通过。
  - Codex 11:02:56 开始、11:04:06 退出，退出码 0；运行日志最后一条是 `turn.completed`，`out-A1.md` 已存进 assets。stderr 为空；运行日志开头两条 `disable_response_storage` 的 `error` 事件是已知现象（`codex-workflow.md` 第 9 节）。
  - 文件归属：工作目录 `git status --porcelain --untracked-files=all` 只有 `?? pyproject.toml`、`?? src/rdp/__init__.py`。主仓库目录 `-- src tests` 为空，非规划文件的检查也为空（只有主会话自己的规划改动）。
  - 内容：`pyproject.toml` 只有 `[project]`（`rdp`、静态版本 `0.1.0`、`==3.12.*`、`dependencies = []`，没有 readme、authors）和 `[build-system]`（`uv_build>=0.13.5,<0.14.0`），注释是中文。`src/rdp/__init__.py` 只有包的 docstring：根包不放逻辑，三层从上往下依赖，依据 ADR 0002 和本票。
  - 运行日志：执行了 10 条命令（读规划文件、enterprise-coding 的 SKILL.md、`git status`、`rg --files`），没有碰两个旧项目和 `/mnt`。检查办法：从 JSONL 里取出 `command_execution` 的命令逐条看，不只 grep 全文（全文 grep 会命中 `cat AGENTS.md` 的输出）。
- 2026-10-22 11:08，第 7–9 步装依赖（执行线）。
  - 第 7 步：在工作目录里 `uv add --dev ruff basedpyright import-linter pytest`，退出码 0，用时 29 秒。`Using CPython 3.12.15`，建了 `.venv`，解析 17 个包，装 16 个，`rdp` 以 editable 方式装上。`pyproject.toml` 新增 `[dependency-groups] dev`，四项都是 `>=` 下限。
  - 第 8 步核对：
    - `.venv/bin/python -c 'import rdp, sys; print(sys.version)'` 输出 `3.12.15 (main, Oct 21 2026, 17:47:06) [Clang 23.1.3 ]`，`rdp.__file__` 指向工作目录的 `src/rdp/__init__.py`。
    - `.venv/bin/basedpyright --version`：`basedpyright 1.40.2`，`based on pyright 1.1.414`。
    - `uv tree --depth 1`：ruff 0.17.1、basedpyright 1.40.2、import-linter 2.15、pytest 9.1.1。传递依赖：basedpyright 带 nodejs-wheel-binaries 24.19.0；import-linter 带 click 8.5.0、grimp 3.17、rich 15.0.0（markdown-it-py、mdurl、pygments）、typing-extensions 4.16.0；pytest 带 iniconfig、packaging 26.3、pluggy 1.7.0、pygments 2.21.0。
    - **项目装的 ruff 是 0.17.1，不是 03 号票实测用的 0.16.3**（PATH 上 miniconda 的那个）。所以 D400/D415、RUF001–003 白名单要在 0.17.1 上再验一次（验收第 5 条），已写进 A2 的提示。
    - 构建后端：`uv.lock` 里没有 uv-build；`.venv` 里也没有。uv 0.13.5 对 `uv_build>=0.13.5,<0.14.0` 走自带构建后端的快速路径（`uv build --help` 里的 `--force-pep517` 说明了这条路径），没有下载 uv_build，`~/.cache/uv/builds-v0` 为空。另外下载了 PyPI 上 uv_build 0.13.5 的 manylinux x86_64 wheel（sha256 和 PyPI 一致），METADATA 里 `Requires-Dist` 0 条，许可证 MIT OR Apache-2.0：D1 要求的"没有传递依赖"成立。
    - 输出存在 `<执行线临时目录>/m0-01/step8-verify.txt`。
  - 第 9 步：依赖提交 `4ee62d2 依赖：ruff、basedpyright、import-linter、pytest（仓库骨架和检查链）`，在工单分支上，含 `pyproject.toml`、`uv.lock`、`src/rdp/__init__.py`，正文注明附带了 A1 的最小包。提交前确认 `core.hooksPath` 没设、`.git/hooks` 里没有生效的钩子，没加 `--no-verify`。提交后工作目录 `git status --porcelain --untracked-files=all` 为空（`.venv/` 已在 `.gitignore` 里）。
- 2026-10-22 11:20，第 10 步派工 A2（续接）。
  - 提示 `assets/01-repo-skeleton-check-chain/prompt-A2.md`：派工 A 模板，交付见「派工分段」的 A2；附上装依赖时核实的版本，和三处容易出错的地方（钩子读暂存清单要用 `-z`，中文路径；`make check` 不留痕迹；`make fmt` 要能跑）。最终回复在四块之外加了第五块"检查配置的要点"，供骨架摘要用。
  - 执行线派工前在 ruff 0.17.1 上预先试过（临时目录，不在仓库里）：D415 仍然不认"。"；RUF002/RUF003 会报 `：（），；`；DOC202 会报 `Returns: 无`；DOC501、DOC502 不报骨架的 `raise NotImplementedError`；`# noqa: T201  # 理由：…` 能用；多余的 noqa 报 RUF100，不带规则码的报 PGH004。评审时据此核对 Codex 的配置。
  - 快照 `refs/rdp/m0-01/A2`。先 `cd <工作目录>`，再 `timeout 3600 codex exec resume 01a16490-d7e5-7862-b467-af073a447b22 -m gpt-6-astra -c model_reasoning_effort='"high"' -c 'sandbox_mode="workspace-write"' --json -o assets/…/out-A2.md - < prompt-A2.md`。运行日志 `<执行线临时目录>/m0-01/ev-A2.jsonl`、`err-A2.txt`。
- 2026-10-22，派工 A2 交回，第 11 步审骨架（`codex-workflow.md` 3.3）。
  - 运行：11:11:46–11:23:09，退出码 0，最后一条 `turn.completed`，`out-A2.md` 在 assets。没有网关断开。
  - **重跑**：工作目录里 `make check` 退出码 0，五步依次是 `[1/5] ruff format --check`、`[2/5] ruff check`、`[3/5] basedpyright`（`0 errors, 0 warnings, 0 notes`）、`[4/5] import-linter`（1 kept）、`[5/5] pytest`（56 skipped），用时 0.55 秒。跑之前和之后 `git status --porcelain --untracked-files=all` 相同（验收第 8 条）。`make fmt` 退出码 0，没改动任何文件（验收第 2 条）。按 A2 的约定，`make check` 这时是五步，契约检查在派工 B 接上后才是六步。
  - **沙箱里能跑（验收第 4 条，第一次检验）**：运行日志第 48 行，Codex 在沙箱里跑 `make check`，basedpyright 一步输出 `0 errors, 0 warnings, 0 notes`，整条退出码 0。basedpyright 在沙箱里能用，不需要 ADR 0002 的退路。
  - **文件归属**：工作目录只有 ` M pyproject.toml`（只加了 `[tool.*]`，`[project]`、`[build-system]`、`[dependency-groups]` 没动，`uv.lock` 没动）、`Makefile`、`.githooks/pre-commit`（755）、`scripts/check_contracts.py`、`src/rdp/{api,ops,infra}/__init__.py`、`src/rdp/infra/timeutil.py`、`tests/test_timeutil.py`、`tests/test_check_contracts.py`。`.gitignore` 没改：import-linter 用 `--no-cache` 关掉了缓存。主仓库目录 `-- src tests` 为空，非规划文件为空。
  - **运行日志**：18 条命令，没有碰两个旧项目和 `/mnt`。Codex 在 `/tmp/rdp-a2-*` 留了 6 个试验文件（规则清单、探针、输出），不在仓库里，不违反规则 3；记一笔，派工 B 的提示里要求用完删掉。
  - **审骨架**：两个公开函数六项齐全、内容具体（`ensure_utc`：无时区按 `tzinfo is None or utcoffset() is None` 判定报 `ValueError`，越界报 `OverflowError`；`check_file`、`main`：输出格式、退出码 0/1/2、出错时只写 stderr 不出部分报告）。三个占位包按 4.1 写了层、职责、边界。测试清单 10 + 46 个，覆盖每条 `Raises:`、每种返回和验收第 7 条的五种违规；期望值是手算的（08:30+08:00 → 00:30Z、23:30−02:00 → 次日 01:30Z）。没有工单之外的公开函数。
  - 快照 `refs/rdp/m0-01/A2-done`（`01219f2`），`.githooks/pre-commit` 在快照里是 `100755`。
- 2026-10-22，第 11 步违规试验和钩子试验。脚本 `assets/…/violation_probe.sh`，输出 `violation_probe-A2-done.txt`。
  - 第一次跑（`violation_probe-A2-done-try1.txt`）有 11 项"不通过"，**全是探针脚本的问题，不是检查链的**：ruff 0.17.1 的默认输出写规则名（`print:`），不写规则码，期望标记没对上；探针里的私有函数没人调用，basedpyright 严格模式报 `reportUnusedFunction`，连带钩子"去掉违规后提交"失败，暂存区没清空，又带坏了 D2 那一项。改成公开函数名、按规则名匹配、D2 试验前先 `git reset` 后重跑。
  - 第二次：**23 项全部通过**。基线全绿 0.7 秒。格式、print、`datetime.now()`、裸 except、注释掉的代码、6 个参数、类型错误、基础层 import 入口层、失败断言，各自失败在对应的那一步；豁免类：不带规则码的 `# noqa`（单独一行、压在真实违规上）报 blanket-noqa，`# type: ignore` 和不带规则名的 `# pyright: ignore` 都在 ruff 那步报 blanket-type-ignore，多余的 `# noqa: T201` 报 unused-noqa，多余的 `# pyright: ignore[…]` 在 basedpyright 那步失败。去掉每一处以后工作区和基线相同、`make check` 全绿。不能失败的：中文全角标点、以"。"结尾、`Returns: 无`/`Raises: 无`、带理由的单条豁免，都全绿。
  - 钩子（验收第 6 条）：`git -c core.hooksPath=.githooks commit` 提交 print 违规被拒、HEAD 没变；去掉后同样的命令提交成功。D2：只暂存中文文件名的规划文件时跳过检查（工作区另有未暂存的违规也不跑）；规划文件加代码一起暂存时跑全量并被拒；把代码文件改名进 `docs/` 时也跑全量。没有改任何 git 配置；探针工作目录已删除，里面的提交都是游离提交。
- 2026-10-22，流程冲突记录（按派工要求记下）：08 号票 Answer 写"主仓库目录的 `git status --porcelain` 必须为空"，`codex-workflow.md` 3.5 的〔2026-10-22〕条目和本票验收第 9 条写"规划文件以外没有改动"。规划和执行并行时主仓库目录里总有主会话的规划改动，按 08 的写法每次都会判越界，所以本票按后者核对。定稿时把 08 的这句改掉。另外 `--no-bin`（第 3 步）是对本票步骤的补充。
- 2026-10-22，**骨架关卡一页摘要**（执行线起草，交主会话转负责人）。
  1. **这张票做什么**：搭后端包骨架 `rdp` 和整条检查链（`make check` + `make fmt` + 提交前钩子），并用它把 Codex 派工流水线第一次走通。
  2. **函数清单**：

     | 模块 | 函数 | 职责 | 改动什么 | 什么情况下报错 |
     |---|---|---|---|---|
     | `rdp.infra.timeutil` | `ensure_utc(value) -> datetime` | 带时区的时刻换算成 UTC，时刻不变 | 无 | 不带时区（`tzinfo` 或 `utcoffset()` 为 None）报 `ValueError`；换算后越出 1–9999 年报 `OverflowError` |
     | `scripts/check_contracts.py` | `check_file(path) -> list[str]` | 只读解析一个文件，返回每个有问题定义的一行 | 无（不导入、不执行源码） | 非 .py 或非普通文件 `ValueError`；读不到 `OSError`；语法错 `SyntaxError`；解码失败 `UnicodeError` |
     | `scripts/check_contracts.py` | `main(argv) -> 0/1/2` | 检查给定路径（默认 `src/rdp`、`scripts`），输出问题行和"问题总数: N" | 只写 stdout/stderr | 返回码：0 无问题，1 有问题，2 参数、路径、读取或解析错误；stdout/stderr 写失败抛 `OSError` |

     另有三个只有 docstring 的占位包 `rdp.api`、`rdp.ops`（入口层）、`rdp.infra`（基础层）。
  3. **测试清单**（全部 `pytest.skip`，派工 B 逐个实现）：`test_timeutil.py` 10 个：+08:00、−02:00 跨日、本来就是 UTC、微秒、无时区、有 tzinfo 但 utcoffset 为 None、下界越界、上界越界、datetime.min/max 本身、输入不被修改。`test_check_contracts.py` 46 个：六项齐全通过、写"无"通过、骨架通过；缺职责、逐项缺失、逐项为空、顺序颠倒、标题大小写不符、重复小节；私有函数、私有模块和包、`__init__.py`、公开类方法、`__init__`、property、dataclass `Attributes:`、装饰器别名、生成器 `Yields:`、async、overload、嵌套函数、测试函数；输出格式、一个定义一行、排序和总数、空文件；默认路径、显式路径、去重、软链接、帮助、未知选项、不存在的路径、非 .py、语法错、编码、OSError 传递。
  4. **检查配置要点**：
     - ruff 0.17.1：行宽 100；默认 E4/E7/E9/F，加 B、UP、I、N、PTH、SIM、D（google）、T20、DTZ、S、ERA001；阈值 C901 圈复杂度 ≤ 10、PLR0913 参数 ≤ 5、PLR0915 语句 ≤ 40、PLR0912 分支 ≤ 12；豁免检查 PGH003、PGH004、RUF100；pydoclint 用 `explicit-preview-rules` 点名开 DOC102/201/402/403/501。
     - 关掉的：D400、D415（0.17.1 上仍不认"。"）；DOC202（会报 `Returns: 无`）；DOC502（会把 `Raises: 无` 当异常名，也不许写有意穿过的下层异常）。这几条由契约脚本兜底。RUF001–003 保留，加了 17 个中文标点的白名单。
     - 测试目录只放宽 S101（pytest 用 assert）和 D417（fixture 参数不写 Args），D103 保留。
     - basedpyright 1.40.2 严格模式，绑定 `.venv`（3.12）；不带规则名的豁免、多余的豁免都报错；`# type: ignore` 不起抑制作用（规范 8.1 只认 `# pyright: ignore[规则]`）。
     - import-linter：层合约"`rdp.api | rdp.ops` → （领域层预留）→ `rdp.infra`"，两个入口互不 import；`--no-cache`，不留缓存目录。
     - 钩子按 D2：`-z`、`--no-renames` 读暂存清单；只动规划文件就跳过；暂存区为空时跑全量。
  5. **要负责人拍板的**：
     1. 入口层 `rdp.api` 和 `rdp.ops` 互不 import（Codex 选的，比工单写的严）。建议：采纳，两个入口共用的逻辑放领域层。
     2. 契约脚本的两处取舍：总数按"有问题的定义"计，不按缺项计；显式传入软链接路径直接退出 2，目录里的软链接不跟随。建议：采纳，都更保守。
     3. basedpyright 只在有 error 时失败，warning 不让 `make check` 失败。严格模式下大部分规则已是 error（实测 `reportDeprecated` 是 error），但没有逐条核过。建议：派工 B 里顺手加 `failOnWarnings = true`，零成本。
  6. **结论：建议通过。** 检查都由执行线重跑过：`make check` 0.55 秒全绿；basedpyright 在沙箱里真正跑完；违规试验和钩子试验 23 项全过；文件归属干净；没打回（0 轮）。负责人说"通过"以后做第 13 步。
- 2026-10-22，骨架关卡（主会话）：负责人"通过"。G1 入口层互不 import：采纳；G2 契约脚本按定义计数、显式软链接退出 2：采纳；G3 派工 B 加 basedpyright `failOnWarnings = true`：采纳。
  - 第 13 步：`git config core.hooksPath .githooks`（共用的 `.git/config`）；契约提交 `b1fec00 契约：仓库骨架和检查链`，经过钩子，五步全绿、56 个跳过（验收第 3 条）；`.githooks/pre-commit` 在提交里是 `100755`。工作目录提交后干净。
  - Status 改回 `in-progress`，执行线从第 14 步继续。
- 2026-10-22，第 14 步派工 B（续接）。提示 `assets/…/prompt-B.md`：派工 B 模板，加上把契约检查接进 `make check`（第 4/6 步，在 import-linter 和 pytest 之间）、G3 的 `failOnWarnings = true`、G1/G2 照现有契约、验收第 7 条的五种违规、删掉上一轮留在 `/tmp` 的 `rdp-a2-*`。快照 `refs/rdp/m0-01/B`（基于契约提交 `b1fec00`，工作目录干净）。会话 `01a16490-d7e5-7862-b467-af073a447b22`，先 `cd <工作目录>` 再 `codex exec resume … -m gpt-6-astra -c model_reasoning_effort='"high"' -c 'sandbox_mode="workspace-write"' --json -o assets/…/out-B.md - < prompt-B.md`。运行日志 `<执行线临时目录>/m0-01/ev-B.jsonl`、`err-B.txt`。网关 `10.1.179.3:8088` 直连 200。
- 2026-10-22，派工 B 交回，第 15 步评审（`codex-workflow.md` 3.5）。
  - 运行：21:41:15–22:06:49，退出码 0，最后一条 `turn.completed`，`out-B.md` 在 assets。没有网关断开。
  - **1 重跑**：工作目录 `make check` 退出码 0，六步 `[1/6]`…`[6/6]`：ruff format、ruff check、basedpyright（`0 errors, 0 warnings, 0 notes`）、import-linter（1 kept）、契约检查（`问题总数: 0`）、pytest（`56 passed`），用时 3.5 秒。`pytest -rs` 没有跳过。跑之前和之后 `git status` 相同。
  - **2 文件归属**：工作目录只有 ` M` `Makefile`、`pyproject.toml`、`scripts/check_contracts.py`、`src/rdp/infra/timeutil.py`、`tests/test_check_contracts.py`、`tests/test_timeutil.py`。`pyproject.toml` 只改了 `[tool.*]`：加 `failOnWarnings = true`（G3）、`tmp_path_retention_policy = "none"`，改了两条注释；`uv.lock`、依赖表、`.githooks/`、`.gitignore` 没动。主仓库目录非规划文件为空。
  - **3 对比契约**：`ensure_utc`、`check_file`、`main` 的签名和 docstring，以及两个模块的 docstring，和契约提交 `b1fec00` 逐字相同（用 `ast` 比的）。没有新的公开函数。
  - **4 运行日志**：84 条命令，没有碰两个旧项目和 `/mnt`；唯一碰到 `/tmp` 的是只读列出 `/tmp/pytest-of-shawn`。上一轮留的 `/tmp/rdp-a2-*` 已删。沙箱里两次 `make check`（日志第 231、244 行）都是六步全绿，basedpyright 和契约检查都真正跑完（验收第 4 条）。
  - Codex 自述：有些测试去掉跳过后第一次就通过（前面的实现或标准库行为已经覆盖），不是每个都先红后绿。
  - **违规试验**：快照 `refs/rdp/m0-01/B-done`（`12ed832`），`violation_probe.sh B-done --with-contracts`，输出 `violation_probe-B-done.txt`：**29 项全部通过**。A2 那 23 项照样通过，另外：契约检查的五种违规（缺 `Time Semantics:`、私有函数没有 docstring、`@dataclass` 没有 `Attributes:`、顺序颠倒、`Side Effects:` 为空）都失败在 `[5/6] 契约检查`，输出形如 `src/rdp/infra/probe_contract.py:4  rdp.infra.probe_contract.no_time  缺少 Time Semantics:`；脚本退出码 0 / 1 / 2（无问题 / 有问题 / 不存在的路径）。基线 3.6 秒。
  - **5 两轴评审**：在检出 `B-done` 的探针工作目录里跑 `/code-review`（基准 `28b6e1c`，即 main 的合并基点），结果见下一条。
- 2026-10-22，第 15 步第 5 项两轴评审（`/code-review`，探针工作目录检出 `B-done`，基准 `28b6e1c`）。
  - **Standards 轴**：没有硬性违规。3.2、4.1、4.2、7.1、7.2、7.6、8.3、规则 7 都通过。新增豁免 5 处：两处 `noqa: S603`、一处 `noqa: DTZ001`，以及 per-file-ignores 的 S101、D417，都只针对单条规则并写了理由。判断题：
    - `test_input_unchanged` 的 docstring 写了"不依赖系统时钟或本地时区"，但测试没有改 `TZ`，这句没验证到。
    - 几个测试在函数里用 `for` 循环跑多个用例，可以改成 parametrize。
    - `_run` 和 `_run_api` 重复。
  - **Spec 轴**：没有缺项，也没有越界。实现上有偏差，执行线已逐条复现：
    1. `@<名>.setter` / `.deleter` 被当成公开函数，要求六项。工单写的是"私有函数和 `@property` 至少一句职责"。
    2. `functools.cached_property` 没被认作 property。
    3. 同一行写 `Returns: 无` 被报成"缺少 Returns:"，提示有误导性；标题行带尾随空格也报"缺少"。
    4. 非 .py 参数的报错里路径重复了一遍：`检查失败: x.txt: x.txt: 不是 .py 文件`。
  - 另外，执行线发现 `tmp_path_retention_policy = "none"` 和 CODING_STANDARDS 7.8"测试没过时先保留证据"冲突。是我的提示写成"用完不留"引起的。
  - 风险（不改，写进汇报）：契约规定 `test_` 开头的函数不查，所以 `src/rdp` 里叫 `test_*` 的公开函数也会被放过。这条写在已批准的契约里，要改就是改含义，得负责人决定。
- 2026-10-22，**打回第 1 轮（r1）**。Status 先改成 `changes-requested`，发出修复轮时再改成 `in-progress`。修复清单：
  1. 问题：property 的 setter、deleter 被当成公开函数查。位置：`scripts/check_contracts.py`，装饰器识别（`_DECORATOR_KINDS` 一带）。期望：`@<名>.setter`、`@<名>.deleter` 和 getter 一样，只要一句非空职责；加测试。
  2. 问题：`functools.cached_property`（直接名、限定名、导入别名）没被认作 property。期望：按 property 处理；加测试。执行线批准：这是对契约"识别 property"的补充说明，不改含义。
  3. 问题：小节标题行有尾随空格，或者标题和内容写在同一行（`Returns: 无`）时，报的是"缺少 Returns:"。期望：尾随空格不影响识别标题；同一行写内容时，报一条准确的问题（例如"Returns: 标题后要换行再写内容"），不报"缺少"。仍然算问题、退出 1。加测试。
  4. 问题：非 .py 参数的报错路径重复。位置：`main` 的报错输出。期望：`检查失败: x.txt: 不是 .py 文件`，路径只出现一次；相关测试断言改严。
  5. 问题：`test_input_unchanged` 的 docstring 说"不依赖本地时区"，但没有验证。位置：`tests/test_timeutil.py`。期望：用 `monkeypatch.setenv("TZ", …)` 加 `time.tzset()` 换两个本地时区，结果相同；测试结束后恢复。
  6. 问题：`tmp_path_retention_policy = "none"` 会删掉失败测试的现场（CODING_STANDARDS 7.8）。位置：`pyproject.toml`。期望：改成 `"failed"`，注释写明理由。
  - 契约（三个公开函数的签名和 docstring）不改。
- 2026-10-22，派工 r1（续接）。提示 `assets/…/prompt-r1.md`（修复轮模板，就是上面的 6 条），快照 `refs/rdp/m0-01/r1`，Status 改成 `in-progress`。会话 `01a16490-d7e5-7862-b467-af073a447b22`，先 `cd <工作目录>` 再续接，参数同派工 B；运行日志 `ev-r1.jsonl`、`err-r1.txt`。
- 2026-10-22，r1 交回并评审：**通过**。
  - 运行：22:36:16–22:44:23，退出码 0，最后一条 `turn.completed`，`out-r1.md` 在 assets。没有网关断开。
  - 重跑：`make check` 六步全绿，`61 passed`，4.5 秒；跑之前和之后 `git status` 相同。
  - 文件归属：在 B 的基础上多了 `?? tests/test_check_configuration.py`。受保护文件只改了 `tmp_path_retention_policy = "failed"` 和它的注释。主仓库目录非规划文件为空。
  - 契约：三个公开函数和两个模块 docstring 和 `b1fec00` 逐字相同。
  - 运行日志：没有碰旧项目和 `/mnt`，`/tmp/rdp-*` 没有残留。
  - 执行线用自己写的样例复现了 6 条：
    - setter、deleter、`functools.cached_property`、`cached_property` 别名都只要一句职责；
    - 标题行带尾随空格能识别；同一行写 `Returns: 无` 报 `Returns: 标题后要换行再写内容`，退出 1；
    - `x.txt` 的报错是 `检查失败: x.txt: 不是 .py 文件`，退出 2；
    - `test_input_unchanged` 换了上海、纽约两个 `TZ`。
  - 新增的 `test_check_configuration.py` 用子进程跑 pytest，验证"失败现场保留、成功的清理"。它测的是配置不是平台代码，算轻微越界；但它守住了一条配置决定，留着。
  - 违规试验：快照 `refs/rdp/m0-01/r1-done`（`e33f945`），`violation_probe-r1-done.txt`，29 项全部通过。打回共 1 轮。
- 2026-10-22，第 17 步：实现提交 `baf56e3 实现：仓库骨架和检查链`，经过钩子（六步全绿，`61 passed`），提交后工作目录干净。Status 改成 `in-review`，等负责人说"合并"（主会话按 `codex-workflow.md` 3.7 做）。
- 2026-10-22，**完工汇报**（执行线起草）。
  - **改了什么**（分支 `t/m0-01-repo-skeleton-check-chain`，三个提交）：
    - `4ee62d2` 依赖：ruff 0.17.1、basedpyright 1.40.2、import-linter 2.15、pytest 9.1.1，以及 `uv.lock`。
    - `b1fec00` 契约：检查配置、Makefile、钩子、三层占位包、两个模块的契约骨架，56 个跳过的测试。
    - `baf56e3` 实现：`ensure_utc` 和契约检查脚本；`make check` 改成六步；`failOnWarnings`（G3）；`tmp_path_retention_policy = "failed"`。
  - **测试**：61 个，全部通过（timeutil 10 个，契约脚本 50 个，配置 1 个），没有跳过。`make check` 六步约 3.5–4.5 秒。违规试验三轮快照（A2-done 23 项，B-done、r1-done 各 29 项）全部通过。
  - **十条验收**：
    1. 环境：通过。`.venv` 是 3.12.15，`uv.lock` 已入库；依赖提交之后，依赖表和 `uv.lock` 都没变过。
    2. 空骨架全绿：通过。A2 时五步（契约检查当时是桩，按约定不接），0.55 秒；`make fmt` 能跑。
    3. 骨架阶段全绿：通过。契约提交 `b1fec00` 经过钩子，五步全绿、56 个跳过（主会话做的提交）。
    4. 沙箱里能跑：通过。A2 和 B 的运行日志里，Codex 在沙箱中跑了 `make check`，basedpyright 都输出了 `0 errors, 0 warnings, 0 notes`，退出码 0。不需要退路。
    5. 违规会失败：通过。每种违规都失败在对应的那一步，去掉后恢复全绿；"不能失败"的四种都是全绿。
    6. 钩子能拦：通过。违规提交被拒、HEAD 没变，去掉违规后提交成功；D2 的三种情况都对；`.githooks/pre-commit` 在提交里是 `100755`。
    7. 契约脚本能抓缺项：通过。五种违规都输出了文件:行号、函数全名和问题；退出码 0 / 1 / 2。
    8. 不留痕迹：通过。每次跑 `make check` 前后，`git status` 都相同。
    9. 文件归属：通过。工作目录只动了 `src/`、`tests/` 和允许改的受保护文件；主仓库目录只有规划文件的改动；运行日志里没有碰两个旧项目，也没有碰 `/mnt`。
    10. 注释与契约：通过。`/code-review` 的 Standards 轴没有硬性违规；Spec 轴发现的偏差在 r1 修好，执行线复现确认。
  - **风险**：
    - 契约规定 `test_` 开头的函数不查，所以 `src/rdp` 里叫 `test_*` 的公开函数也会被放过。要收紧就得改契约含义，需要负责人决定，可以留到 `/retro`。
    - Codex 自己说，有一部分测试去掉跳过后第一次就通过了，不是每个都先红后绿。
    - 新增的 `tests/test_check_configuration.py` 测的是 pytest 配置，算轻微越界，留着。
    - 规程待定稿：08 号票里"主仓库目录必须为空"那句要改；违规试验脚本要按 ruff 的规则名匹配（第一次跑踩过）；Codex 会在 `/tmp` 留试验文件，提示里要写明用完删掉。
    - Standards 轴的判断题没改：测试里的 `for` 循环可以改成 parametrize，`_run` 和 `_run_api` 有重复。
  - **下一张**：按 D3，起草第 2 张「Web 骨架与前端检查链」（最小 FastAPI 应用 + 前端骨架）。先按这张票跑下来的情况修订 `codex-workflow.md` 和 `CODING_STANDARDS.md`，然后定稿。
