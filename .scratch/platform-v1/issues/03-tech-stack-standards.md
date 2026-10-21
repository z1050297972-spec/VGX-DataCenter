# 技术栈与工程规范

Type: grilling
Status: resolved
Blocked by: 02

## Question

确认平台的技术栈和"防屎山"机制。0003 第五、六、七节已有推荐答案，原始需求 (11)、(12)、(13) 是来源；前端路线以「[交互形态与前端路线](02-interaction-frontend.md)」的结论为准。

要定的：

- **后端运行环境**：Python 版本；用 uv 管理；平台本身不进 Docker（0003 第五节）。
- **数据库**：SQLite（WAL）+ SQLAlchemy 2 + Alembic。
- **模块划分与依赖方向**：按领域分模块，用 import-linter 合约强制单向依赖。
- **检查链**：
  - 后端：ruff 的规则集和阈值（复杂度、参数个数、语句数）、pyright 严格模式、pytest。
  - 前端：React 对应的检查（TypeScript 严格模式、lint、测试）。
  - 两边都汇总进 `make check`，并接到 pre-commit 上。
- **函数契约模板**：docstring 六项的固定格式（0003 第七节）；前端函数和组件对应的契约要求。
- **新增依赖的审批流程**：后端和前端各怎么走。
- **「交互形态与前端路线」留下的选型**：前端已定为 Vite + React + TypeScript 单页应用，源码在 `src/web/`。还要定：路由、数据获取、组件库用什么；OpenAPI 生成 TS 类型用什么工具；运维命令入口用什么写（Typer 还是标准库 argparse）；口令哈希和登录会话用什么库。
- **lerobot 的依赖方式**：平台运行时直接依赖 lerobot，还是只在测试里拿它当格式判定的基准。lerobot 0.6.x 要求 Python 3.12，而且库版本必须锁定，见「[平台统一的 LeRobot 版本](07-lerobot-version.md)」。

**完成标准**：以上各项都有结论。技术栈写成 ADR；`docs/standards/CODING_STANDARDS.md` 的条目要点写在本票 Answer 里，正文在 M0 成文（从 `docs/standards/engineering-control/` 派生）。

## Answer

2026-10-21 与负责人分轮确认。各项结论落在这些地方：
- **技术栈**：写成 [ADR 0002 技术栈](../../../docs/adr/0002-技术栈.md) 和 [ADR 0003 平台运行时不依赖 lerobot](../../../docs/adr/0003-运行时不依赖lerobot.md)。
- **规则**：已写进 `AGENTS.md`，包括受保护文件、docstring 格式、中文注释、检查链、依赖申请。
- **环境事实**：负责人告知的两条沙箱事实（Codex 不能提交；pyright 在不联网的沙箱里跑不起来）写进 [0006](../../../docs/brief/0006-环境事实更新-Codex沙箱.md)。

### 结论

- **后端**：
  - Python 3.12 + uv，原生运行，不进 Docker。
  - 包名 `rdp`，放在 `src/rdp/`；Web 服务用 uvicorn；配置文件用 TOML。
  - 数据库用 SQLite（WAL）+ SQLAlchemy 2 + Alembic，只用同步写法。
- **lerobot**：平台运行时不依赖 lerobot。读元数据直接读 JSON，需要读 Parquet 时再加 pyarrow。需要 lerobot 的工作都做成工具，以子进程方式运行。代码测试的样本从真实数据里截取（`meta/` 加一两个 episode），放进 `tests/fixtures/`。
- **模块与依赖方向**：
  - 三层，只允许从上往下依赖：入口层（`rdp.api`、`rdp.ops`）→ 领域层 → 基础层（数据库、配置、日志）。
  - 领域模块之间默认互不 import。需要依赖时，在 import-linter 合约里登记方向，不允许成环。
  - 合约写在 `pyproject.toml` 里，受保护。
  - 具体有哪些领域模块，由「[核心领域模型与术语](13-domain-model.md)」和「[作业模型](10-job-model.md)」定。
- **后端检查链**：
  - 格式化用 ruff format，行宽 100。
  - ruff check 在默认规则之上开这些：bugbear、pyupgrade、import 排序、命名、pathlib、简化写法、docstring（google 风格）、禁止 print、禁止不带时区的 datetime、bandit、禁止裸 except、禁止被注释掉的代码。
  - pydoclint 的几条签名核对规则（DOC201、DOC501 等）还是 preview 规则，用 `explicit-preview-rules` 单独开启。
  - 关掉 D400 和 D415，因为它们不认"。"。RUF001–003 里加中文全角标点的白名单。这两点都在本机 ruff 0.16.3 上实测过。
  - 阈值：圈复杂度 ≤ 10，参数 ≤ 5，语句数 ≤ 40，分支 ≤ 12。
  - 类型检查用 basedpyright 严格模式，测试用 pytest。
  - 豁免注释只能针对单条规则，写上规则码和理由；多余的豁免由 RUF100 和 basedpyright 报错。
  - 不设覆盖率门槛。
- **函数契约模板**（后端）：
  - 首行写职责，然后依次是 `Args:`、`Returns:`、`Raises:`、`Side Effects:`、`Time Semantics:`。小节标题用英文，内容写中文。0003 例子里的中文小节名作废。
  - 公开函数六项都必须写，不适用的写"无"；私有函数至少写一句职责；数据类写 `Attributes:`，含单位和取值范围。
  - 六项是否写齐，由 `scripts/check_contracts.py` 检查。这个脚本受保护，所以 Codex 改不松这项检查。
- **前端选型**：pnpm（Node 22）、TanStack Router、TanStack Query、Ant Design；类型用 openapi-typescript 生成，请求用 openapi-fetch 发。
- **前端检查链与契约**：
  - TypeScript 严格模式，再开 `noUncheckedIndexedAccess`。
  - ESLint 用 typescript-eslint 的 `strictTypeChecked`，加上 react-hooks 规则，阈值和后端相同。
  - 格式化用 Prettier；测试用 Vitest + React Testing Library。v1 不做浏览器端到端测试。
  - 导出的函数、hook、组件写 TSDoc，同样六项：组件的"参数"写 props，"副作用"写它发出的请求和改动的 URL 参数，"时间语义"写轮询间隔和缓存过期时间。由 eslint-plugin-jsdoc 强制。
- **运维命令与登录**：
  - 运维命令用 argparse。
  - 口令哈希用 argon2-cffi。
  - 会话存在数据库里：只存随机令牌的哈希，浏览器端用 HttpOnly、SameSite=Lax 的 cookie。
- **中文注释**（负责人在走票时新增的总需求，原话是"编写的代码要加上充分的中文注释"）：
  - 注释写"为什么"，不复述代码。
  - 六类地方必须写注释：模块的职责与边界、不直观的判断、常量和阈值（含义、单位、出处）、顺序约束、权宜做法及其移除条件、每个测试验证的契约行为。
  - 模块开头的说明和被注释掉的代码由 ruff 机械检查。其余各类由 `/code-review` 的 Standards 轴检查。
- **`make check` 与钩子**：
  - `make check` 依次跑：后端（格式、ruff、basedpyright、import-linter、契约完整性脚本、pytest）→ 前端（OpenAPI 类型是否过期、tsc、eslint、prettier、vitest）。另有 `make fmt` 做自动修复。
  - 提交前钩子是普通的 git 钩子 `.githooks/pre-commit`，跑全量 `make check`，不用 pre-commit 框架。
  - Codex 不能提交，所以实际触发钩子的是 Claude 的提交。
  - 全量检查超过 1 分钟左右时，在 `/retro` 里拆成快慢两档。
- **新增依赖**：
  - 流程：Codex 写依赖申请 → Claude 核实维护状况、许可证、体积和传递依赖 → 负责人批准 → Claude 用 `uv add` 或 `pnpm add` 安装，单独做一次提交，并记进工单的 Comments。
  - 锁文件入库。受保护文件的清单见 `AGENTS.md` 硬性规则 3。

### 走票过程中的修正

- 负责人一度提议把 `/mnt/datasets/解压样本/` 改成测试区。后来澄清，负责人指的是**机器人数据转换的试跑区**，不是代码测试。
- 所以按原方案处理：代码测试仍然只用 `tests/fixtures/` 和临时目录，硬性规则 1 不变。
- 试跑区的问题，以负责人初步意见的形式移交「[工具清单与转换血缘](15-tool-manifest-lineage.md)」。我的推荐是做成 NAS 上的暂存区，和正式区放在同一个文件系统上，入库时只需改名。

### `CODING_STANDARDS.md` 的条目要点（M0 成文）

从 `docs/standards/engineering-control/` 派生，`/code-review` 的 Standards 轴按这些条目检查：

1. **模块边界**：三层依赖方向；领域模块不 import 入口层，也不 import FastAPI；跨领域依赖要登记。
2. **规则与副作用分离**：先计算计划，再执行（例如 `plan_*` / `apply_*`）；预检、执行、报告用同一份计划（engineering-control §2）。
3. **函数契约**：六项模板，以及公开函数、私有函数、数据类各自的要求，附 `plan_link` 示例。前端 TSDoc 的对应写法。
4. **中文注释**：六类地方；写"为什么"的例子和反例。
5. **时间**：一律 UTC，datetime 必须带时区；时长和间隔在名字或注释里写明单位。
6. **错误与诊断**：留一个占位，内容由「[可观测性与报错规范](09-observability.md)」填。
7. **测试**：
   - 每个契约行为至少一个测试。
   - 期望值来自契约或独立计算，不调用被测逻辑生成。
   - 用边界值反推测试输入（engineering-control data-pipelines 一节里的表）。
   - 只用临时目录和 `tests/fixtures/`；样本从真实数据截取。
8. **豁免**：只针对单条规则，写明规则码和理由；评审时逐条过。
9. **依赖**：申请流程。
10. **前端**：请求统一经 openapi-fetch 和 TanStack Query 发出；轮询间隔用具名常量，并注明出处（ADR 0001）。

### M0 首批依赖清单（负责人 2026-10-21 过目后一次性批准）

版本在 M0 安装时确定，并写进锁文件。

- **后端运行**：fastapi、uvicorn、sqlalchemy、alembic、argon2-cffi（pydantic 随 fastapi 一起装）。
- **后端开发**：ruff、basedpyright、import-linter、pytest、httpx（FastAPI 的 TestClient 需要它）。
- **前端运行**：react、react-dom、@tanstack/react-router、@tanstack/react-query、antd、openapi-fetch。
- **前端开发**：vite、@vitejs/plugin-react、typescript、openapi-typescript、eslint、typescript-eslint、eslint-plugin-react-hooks、eslint-plugin-jsdoc、prettier、vitest、@testing-library/react、jsdom。
- **本机工具**：uv（目前还没装）。

### 风险

- **basedpyright 在 Codex 沙箱里能否运行**：M0 第一张工单先实测。不行就退回用 npm 安装 pyright；再不行，只在评审时由 Claude 跑类型检查。
- **Node 22 在 2027-04 停止维护**：到时候升级。

### 对其他票的影响（已同步到各票正文）

- 「[Codex 协作规程](08-codex-workflow.md)」：
  - Codex 不能提交，由 Claude 提交，派工流程要随之调整。
  - 改动不提交时，`git diff --name-only` 看不到新建的文件，所以核对文件归属要改用 `git status --porcelain`。
  - 依赖安装方式已在本票定下。
- 「[工具清单与转换血缘](15-tool-manifest-lineage.md)」：
  - 加入负责人的初步意见：转换要有试跑区（暂存区）。
  - 需要 lerobot 的工作都走工具（ADR 0003）。
- 「[数据集板块的数据契约](11-dataset-contract.md)」：
  - 存储根要考虑区分只读和可写。
  - 假导航层的样本从真实数据截取。
- 「[备份方案](17-backup.md)」：NAS 写入例外要和可写存储根对齐。
- 「[可观测性与报错规范](09-observability.md)」：日志用哪个库在这张票定（本票没定）。
- 「[数据集浏览界面](16-dataset-browser.md)」：原型用 Ant Design 做。
