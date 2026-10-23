# Web 骨架与前端检查链

Status: needs-triage

## 依据

- 第 1 张票的决定 D3（「前端放哪张票」）：前端骨架单独开这一张，和最小的 FastAPI 应用放在一起。
- ADR 0001（SPA 由 FastAPI 同进程托管，`/api/*` 是 JSON 接口，前端类型由 OpenAPI 生成并在 `make check` 里查过期）、ADR 0002（技术栈）、ADR 0005（Web 不写导航层）。
- 「技术栈与工程规范」（`.scratch/platform-v1/issues/03-tech-stack-standards.md`）Answer：前端选型、前端检查链、`make check` 的顺序、M0 首批依赖清单。
- 流程：`docs/agents/codex-workflow.md`（2026-10-23 定稿）。规范：`docs/standards/CODING_STANDARDS.md`。本票要补全 3.1 末尾、3.5、8.1、第 10 条里写着"前端骨架工单"的部分。
- 负责人已批准：W3（契约脚本只在 `tests/` 下跳过 `test_*`）、W4（`@types/react`、`@types/react-dom`）。
- 环境事实：`docs/brief/0006`、`0009`、`0011`（沙箱不能联网，也不能建 socket）。

## 目标

1. 一条能演示的竖切：FastAPI 应用提供 `GET /api/health`，并托管前端构建产物；前端一个页面经 openapi-fetch + TanStack Query 调这个接口，显示结果。
2. 前端检查链接进 `make check` 和提交前钩子，能拦住违规；OpenAPI 生成的类型过期时 `make check` 失败。
3. 顺带补上第 1 张票留下的两处检查缺口：FastAPI 的 import-linter 合约（1.3）、契约脚本的 `test_*` 跳过范围（3.1）。

## 范围

**后端**（`rdp.api`，入口层）

- `create_app(web_dist: Path | None) -> FastAPI`：
  - `GET /api/health` 返回 `{"status": "ok"}`，响应模型用 pydantic 定义，进 OpenAPI。
  - `web_dist` 给了：托管其中的静态文件；`/api/` 以外、找不到文件的 GET 一律返回 `index.html`，让 TanStack Router 处理前端路由。`/api/` 下没有的路径返回 404 JSON，不返回 `index.html`。
  - `web_dist` 为 `None`：只提供接口（开发时由 Vite 开发服务器转发 `/api`）。
  - `web_dist` 不存在或缺 `index.html`：报什么错、什么时候报，写进契约。
- OpenAPI 导出：`python -m rdp.api.openapi_export <输出路径>`，把 `create_app(None).openapi()` 写成确定的 JSON（键排序、缩进固定、末尾换行），同样的代码导出两次逐字节相同。不起服务。
- 静态文件用 `fastapi.staticfiles.StaticFiles`，不直接 import starlette（`CODING_STANDARDS.md` 9.2）。
- 启动 Web 的运维命令不在本票，演示时由 Claude 在沙箱外用 `uvicorn --factory` 起。

**前端**（`src/web/`）

- Vite + React + TypeScript，pnpm。路由用 TanStack Router（代码式路由树，不用文件路由插件），一个根路由 `/`。
- `src/web/src/api/`：`openapi.json` 和 openapi-typescript 生成的 `schema.d.ts`（两个都入库）；一个 openapi-fetch 客户端工厂，`fetch` 实现可以注入，测试不碰全局 `fetch`。
- 一个 hook（例如 `useHealth`）和一个页面组件，用 Ant Design 显示"后端正常"或请求失败。缓存时间写成具名常量（10.3）。
  - 权宜：诊断组件（10.5）要等日志和报错框架那张票。本票请求失败时只显示一个 Ant Design 的 `Alert`，在注释里写明权宜和去掉的条件。
- 地址一律相对路径 `/api/...`（10.4）。开发服务器把 `/api` 转发到 `127.0.0.1:8600`（M0 spec S3）。
- 测试和源码放在一起（`src/web/src/**/*.test.ts(x)`），用 Vitest + React Testing Library + jsdom。每个 `it(...)` 的标题写明它验证哪条契约行为（规则 5）。

**检查链**

- `make check` 在后端六步之后接前端五步：OpenAPI 类型是否过期 → tsc → ESLint → Prettier → Vitest（03 的顺序）。每步开头输出 `[n/11] 步骤名`。
- 前端工具一律从 `src/web/node_modules/.bin/` 调用，`make check` 里不出现 `pnpm`，因为 pnpm 可能联网或写 store。`node_modules` 不存在时，第一步就失败，提示"先在 src/web 里运行 pnpm install --frozen-lockfile"，不自动安装。
- 过期检查：导出 OpenAPI、生成类型都写到临时目录，再和入库的两个文件逐字节比较；不一致就失败，提示运行 `make api-types`。新增 `make api-types` 重新生成入库的两个文件。`make fmt` 加上 `prettier --write` 和 `eslint --fix`。
- TypeScript：`strict` 加 `noUncheckedIndexedAccess`，不关 `noImplicitAny`（原型关了）。
- ESLint（flat config）：
  - typescript-eslint 的 `strictTypeChecked`，react-hooks 的 recommended，eslint-plugin-jsdoc。
  - 阈值和后端一致：`complexity` ≤ 10、`max-params` ≤ 5、`max-statements` ≤ 40。后端的"分支 ≤ 12"在 ESLint 里没有对应规则，由 `complexity` 兜底，在配置注释里写明。
  - `no-console`（对应 ruff T20）。用 `no-restricted-globals` 禁止直接用 `fetch`，把 10.1 变成〔机〕；客户端工厂默认取全局 `fetch` 的那一处，用带理由的单条豁免。
  - 豁免（8.1）：`linterOptions.reportUnusedDisableDirectives: "error"`；不带规则名、不带 `-- 理由` 的 `eslint-disable` 用 eslint-comments 插件的 `no-unlimited-disable`、`require-description` 拦（见「待负责人确认」第 1 条）。`@ts-ignore` 和不带说明的 `@ts-expect-error` 由 `@typescript-eslint/ban-ts-comment` 拦。
- TSDoc（3.5）：`jsdoc/require-jsdoc` 覆盖导出的函数、箭头函数、组件；`jsdoc/check-tag-names` 登记 `sideEffects`、`timeSemantics` 两个自定义标签。`@throws`、`@sideEffects`、`@timeSemantics` 必须出现、不能为空：Codex 实测插件能用哪条规则做到（例如 `jsdoc/no-missing-syntax`），在最终回复里逐项写明靠哪条规则。插件做不到的项，报告出来，不自己写脚本。
- 生成的 `schema.d.ts` 不过 ESLint 和 Prettier，在忽略配置旁边写理由（生成文件不手改，8.2）。
- import-linter 加一条 forbidden 合约：`rdp.infra` 不 import `fastapi`、`starlette`、`uvicorn`（1.3），领域层的位置用注释标出。外部包要 `include_external_packages = true`。
- 契约脚本（W3）：名字以 `test_` 开头的函数，只有文件位于仓库根的 `tests/` 下时才跳过；`src/`、`scripts/` 下的照常查六项。`check_file` 的 docstring 跟着改（负责人已批准这处含义变化），加测试。
- 钩子：`.githooks/pre-commit` 预计不用改（它跑 `make check`，前端步骤自动带上）。D2 的规划提交跳过要照常生效。

## 不在本票

- 数据集浏览的 A/B/C 三种布局（16 号票）、账号和登录、诊断组件、按路由拆包：M1 和 M0 后续的工单。
- 启动 Web 和 worker 的运维命令、配置文件、日志框架：M0 后续的工单。
- `vite build` 不进 `make check`（见「待负责人确认」第 3 条）。

## 允许改的受保护文件

| 文件 | 允许做什么 |
|---|---|
| `Makefile` | 加前端五步、`make api-types`，`make fmt` 加前端；后端六步不动 |
| `pyproject.toml` | 只改 `[tool.importlinter]`（forbidden 合约、`include_external_packages`），以及 FastAPI 带来的 ruff、basedpyright 配置调整（每条写理由）。依赖表只由 Claude 用 `uv add` 写 |
| `scripts/check_contracts.py` | 只改 `test_*` 的跳过范围（W3）和对应的 docstring |
| `src/web/package.json` | 新建；写 `name`、`private`、`type`、`scripts`。依赖表只由 Claude 用 `pnpm add` 写 |
| `src/web/tsconfig*.json`、`eslint.config.*`、`vite.config.*`、Prettier 配置和 `.prettierignore` | 新建。Vitest 的配置写进 `vite.config.ts`，不另建文件 |
| `.gitignore` | 只追加 `node_modules/` 这类前端产物；`dist/` 已经有了 |
| `.githooks/pre-commit` | 只在实测发现必须改时改，改了在最终回复里说明 |

- `pnpm-lock.yaml`、`uv.lock`、`pnpm-workspace.yaml`（pnpm 11 的构建脚本白名单如果要用）只由 Claude 写，Codex 不改。
- 其他路径都不动。

## 派工分段

`pnpm add` 要先有 `package.json`，所以和第 1 张票一样，派工 A 拆两段：

- **A1**（新会话）：只交 `src/web/package.json`（没有依赖表），不跑检查。
- **中间**：Claude 装后端和前端依赖，做依赖提交（「Claude 的步骤」第 6–8 步）。
- **A2**（续接）：配置文件、Makefile、import-linter 合约，以及后端、前端、契约脚本改动的契约骨架。TS 函数体只写 `throw new Error("未实现")`；Vitest 用 `it.skip`，pytest 用 `pytest.skip`。导出函数这时是桩，所以过期检查这一步先不接，在 Makefile 里用注释标明，派工 B 接上，同时生成入库的两个文件。
- **B**（续接）：TDD 实现，接上过期检查，`make check` 十一步全绿。

## 验收

Claude 评审时逐条核对，结果记进 Comments。

1. **环境**：工作目录里 `src/web/node_modules/.bin/tsc --version` 是第 2 条确认的版本；`pnpm-lock.yaml`、`uv.lock` 已入库；Codex 的改动里没有依赖表和锁文件的变化。
2. **骨架阶段全绿**：契约提交上 `make check` 十步（过期检查未接）退出码 0，跳过的测试都列在 `pytest -rs` 和 Vitest 的输出里。
3. **实现后全绿**：`make check` 十一步退出码 0，没有骨架阶段的跳过；用时记进 Comments（03：超过约 1 分钟就在 `/retro` 里拆快慢两档）。
4. **沙箱里能跑**：A2 和 B 的运行日志里，Codex 在沙箱中跑完了 `make check`，tsc、ESLint、Vitest 都真正输出了结果，退出码 0。
5. **接口和托管**（pytest + TestClient，静态目录用临时目录）：`/api/health` 返回 200 和 `{"status":"ok"}`；`/` 和 `/datasets/x` 这类前端路由返回 `index.html`；存在的静态文件原样返回；`/api/不存在` 返回 404 JSON；`web_dist` 为 `None` 时 `/` 是 404；`web_dist` 不合格时按契约报错。
6. **导出确定**：同样的代码导出两次逐字节相同；入库的 `openapi.json`、`schema.d.ts` 和重新生成的相同。
7. **前端**（Vitest）：成功时页面显示"后端正常"，失败时显示 `Alert`；请求经注入的 `fetch` 发到相对路径 `/api/health`。
8. **违规会失败**：在探针工作目录里逐个放入，每次失败在对应的那一步，按规则名匹配，去掉后恢复全绿：
   - 过期检查：给健康检查的响应模型加一个字段，不重新生成。
   - tsc：一个类型错误；越界下标当成非 `undefined` 用（`noUncheckedIndexedAccess`）。
   - ESLint：`no-floating-promises`、`rules-of-hooks`、`complexity`、`max-params`、`no-console`、直接调用 `fetch`、导出函数没有 TSDoc、TSDoc 缺 `@sideEffects`、未登记的标签、不带规则名的 `eslint-disable`、不带理由的 `eslint-disable-next-line`、多余的 `eslint-disable`、`@ts-ignore`、不带说明的 `@ts-expect-error`。
   - Prettier：一处不合格式。Vitest：一个失败的断言。
   - import-linter：`rdp.infra` 里 `import fastapi`。
   - 契约脚本：`src/rdp` 里没有六项的公开函数 `test_probe` 被报出。
   - 不能失败的：中文注释和 TSDoc、`@throws 无`、带理由的单条豁免、`tests/` 下没有六项的 `test_*`。
9. **钩子**：提交一处前端违规被拒，HEAD 不变；去掉后提交成功。D2 的三种情况（只暂存规划文件、规划加代码、代码改名进 `docs/`）照旧。
10. **能演示**：Claude 在沙箱外 `vite build` 后，用 `uvicorn --factory` 在 `127.0.0.1:8600` 起应用，`curl` 首页拿到 `index.html`、`/api/health` 拿到 JSON，浏览器打开页面显示"后端正常"。截图或输出放进 assets。
11. **不留痕迹**：跑完 `make check` 以后，工作目录的 `git status --porcelain` 和跑之前相同（Vite、Vitest 的缓存在 `node_modules/` 下，已忽略）。
12. **文件归属与契约**：只动了 `src/`、`tests/` 和上表里的文件；主仓库目录规划文件以外没有改动；运行日志没碰两个旧项目；先红后绿有证据（7.10）；Standards 轴核对第 3、4、7、10 条和 3.5。

## Claude 的步骤

每一步的结果（版本号、会话编号、快照名、命令和输出摘要）记进 Comments。

- 工作目录：`~/桌面/robot-data-platform.wt/m0-02-web-skeleton-frontend-check-chain`；分支 `t/m0-02-web-skeleton-frontend-check-chain`；assets：`.scratch/m0-foundation/assets/02-web-skeleton-frontend-check-chain/`。

**派工前**

1. 负责人批准本票，回答「待负责人确认」；Status 改成 `ready-for-agent`。
2. **开票**（3.1）：确认没有别的实现票在进行中；Status 改成 `in-progress`；开工作目录；`uv sync --frozen`；跑 `make check` 得到绿的基线。这时还没有 `src/web/`，`pnpm install` 跳过。

**派工 A1**

3. 写 `prompt-A1.md`（派工 A 模板，交付只有 `src/web/package.json`），拍快照 `A1`，派工，记会话编号。
4. **审 A1**：`git status --porcelain --untracked-files=all` 只有这一个文件，没有依赖表。

**装依赖**（沙箱不能联网，全部由 Claude 在工作目录里装）

5. 装前核实每个包的最近发布、许可证、传递依赖（9.4）；pnpm 11 默认不跑依赖的构建脚本，有包需要时在 `pnpm-workspace.yaml` 里只放行它，记下是哪个。
6. 后端：`uv add fastapi uvicorn pydantic`（pydantic 要直接 import，按 9.2 声明为直接依赖）、`uv add --dev httpx`。
7. 前端：在 `src/web/` 里 `pnpm add` 03 号票清单里的前端运行和开发依赖、W4 的 `@types/react`、`@types/react-dom`（19.3.x，和 react 19.3.1 对齐），以及「待负责人确认」第 1 条批准的包；`typescript` 按第 2 条定的版本。装完 `pnpm install --frozen-lockfile --offline` 再跑一次，确认 store 里已经齐了（以后合并时要用）。
8. **核对并做依赖提交**：`uv tree --depth 1`、`pnpm list --depth 0` 记下版本；peer 依赖没有告警。`依赖：fastapi、uvicorn 和前端依赖（Web 骨架与前端检查链）`，经过钩子（这时 `make check` 还只有后端六步）。正文注明附带了 A1 的 `package.json`。

**派工 A2 与骨架关卡**

9. 写 `prompt-A2.md`，附上第 8 步的版本，和这几处提醒：`make check` 不调 pnpm；Vitest 在沙箱里要是因为不能建 socket 起不来，先试 `pool: "threads"`，还不行就停下报告；TSDoc 各项靠哪条规则写进最终回复。拍快照 `A2`，先 `cd <工作目录>` 再续接。
10. 按 3.3 审骨架。在快照 `A2-done` 的探针工作目录里跑违规试验（验收第 8 条，过期检查除外）和钩子试验（第 9 条），脚本 `violation_probe.sh` 和输出放进 assets，按规则名匹配。
11. 一页摘要（6.1）写进 Comments，另列检查配置的要点（开了哪些规则、阈值、豁免、TSDoc 靠哪条规则）。Status 改成 `in-review`，交回主会话。负责人"通过"后做契约提交 `契约：Web 骨架与前端检查链`，Status 改回 `in-progress`。

**派工 B 与评审**

12. 写 `prompt-B.md`（派工 B 模板，强调先红后绿要在日志里看得到），拍快照 `B`，续接派工。
13. 按 3.5 的八项评审：重跑 `make check`；文件归属；对比契约；先红后绿；运行日志；`/code-review main`；在 `B-done` 上重跑 `violation_probe.sh`（这次含过期检查）；验收第 10 条的演示由 Claude 在沙箱外做。十二条验收逐条记下。
14. 打回最多 3 轮（3.6、6.3）。通过后做实现提交 `实现：Web 骨架与前端检查链`，起草完工汇报，Status 改成 `in-review`，交回主会话。

**合并以后**（主会话）

15. 按 3.7 合并。第 3 步除了 `uv sync --frozen`，还要在主仓库目录的 `src/web/` 里 `pnpm install --frozen-lockfile`，否则钩子里的前端步骤会失败。
16. 按实测结果补全 `CODING_STANDARDS.md`：3.1 末尾的 W3 说明、3.5 的 ESLint 规则和标签名、8.1 的前端豁免检查、10.1 改成〔机〕，去掉"前端骨架工单"的字样。`codex-workflow.md` 有要改的一并改。

## 风险

- **TypeScript 版本**：原型用的 7.0.2 不能用。typescript-eslint 8.72.0 要求 `typescript >=4.8.4 <6.1.0`，openapi-typescript 7.13.0 要求 `^5.x`（2026-10-23 `npm view` 查到的 peerDependencies）。见「待负责人确认」第 2 条。
- **Vitest 在沙箱里**：沙箱不能建 socket（0011），Vitest 默认的 `forks` 池要用子进程通信，能不能跑未核实。退路是 `pool: "threads"`；再不行，按 ADR 0002 basedpyright 那样的思路，只在评审时由 Claude 跑，并告诉负责人。
- **`vite build` 在沙箱里**会打一条 "Failed to create stream fd"，不影响构建（0011）。本票不把构建放进 `make check`，影响不大。
- **TSDoc 的强制程度**：eslint-plugin-jsdoc 能不能要求 `@throws`、`@sideEffects`、`@timeSemantics` 必须出现且非空，未核实。做不到的项先留在〔审〕，写进第 16 步的定稿。
- **`@types/node` 是否必需**：Vite 的类型文件开头有 `/// <reference types="node" />`，`vite.config.ts` 过 tsc 时大概率要它，未实测。
- **`make check` 变慢**：多了 tsc、类型检查的 ESLint、Vitest，未实测用时。
- **pnpm 离线安装**：合并时主仓库目录的 `pnpm install --frozen-lockfile` 靠第 7 步已经填好的 store（`~/.local/share/pnpm/store/v11`）。离线能不能装齐，第 7 步实测。

## 待负责人确认

1. **补三个前端开发依赖**（规则 7，03 号票清单里没有）：
   - `@testing-library/dom` 10.4.2：`@testing-library/react` 16.3.3 的必需 peer 依赖，不装跑不了组件测试。
   - `@types/node` 22.x（现在是 22.20.5，和本机 Node 22 对齐）：`vite.config.ts` 的类型检查要用。实测不需要就不装。
   - `@eslint-community/eslint-plugin-eslint-comments` 4.8.1：让不带规则名、不带理由的 `eslint-disable` 失败（8.1）。ESLint 自带的选项只能报多余的豁免。
   - 建议：三个都批准，都只在开发时用。
2. **TypeScript 用 5.9.3。** 它同时满足 typescript-eslint（< 6.1）和 openapi-typescript（^5.x）。备选是 6.0.3：typescript-eslint 认，openapi-typescript 的 peer 不认，要实测能不能用。建议 5.9.3，等两边都支持 7.x 以后再升。
3. **`vite build` 不进 `make check`。** 类型和 lint 已经由 tsc、ESLint 覆盖；托管逻辑用临时目录里的假 `index.html` 测；构建只在演示（验收第 10 条）和以后的部署里跑。建议不进，省时间，也避开沙箱里的构建警告。不同意的话，加在 Vitest 之后作为第 12 步。

## Comments

- 2026-10-23，主会话审过草稿：用 `npm view` 重查了 TypeScript 的两处 peer 范围（typescript-eslint 8.72.0 要 `>=4.8.4 <6.1.0`，openapi-typescript 7.13.0 要 `^5.x`）和 @testing-library/react 16.3.3 要 `@testing-library/dom ^10.0.0`，都和草稿一致；端口按 M0 spec S3 改成 8600。
- 2026-10-23，起草（后台 agent）。等负责人过目，回答「待负责人确认」后改成 `ready-for-agent`。起草时只读核实的事实：
  - 本机 `node --version` v22.23.2（`~/.local/bin/node`），`pnpm --version` 11.22.0（`~/.npm-global/bin/pnpm`），pnpm store 在 `~/.local/share/pnpm/store/v11`，约 1.6 GB。
  - 原型（`prototype/dataset-browser`）实际装上的：react、react-dom 19.3.1，antd 6.6.7，vite 8.3.5，@vitejs/plugin-react 6.1.2，typescript 7.0.2；它的 tsconfig 关了 `noImplicitAny`，没有 `@types/react`。
  - `npm view` 的最新版本：@types/react、@types/react-dom 19.3.0，@tanstack/react-router 1.170.46，@tanstack/react-query 5.104.5，openapi-fetch 0.17.0，openapi-typescript 7.13.0，eslint 10.13.0，typescript-eslint 8.72.0，eslint-plugin-react-hooks 7.1.1，eslint-plugin-jsdoc 65.4.1，prettier 3.9.10，vitest 5.0.5，@testing-library/react 16.3.3，jsdom 30.1.3。PyPI：fastapi 0.161.1，uvicorn 0.54.0，httpx 0.28.1。安装时以当时的版本为准。
  - fastapi、uvicorn、httpx 和前端主要依赖已在 03 号票「M0 首批依赖清单」里批准，不用再申请。
  - 本机在监听的端口有 80、8080、8088、3306、6379、5173（原型的开发服务器）；8000、8600 空着。
  - `.gitignore` 已经有 `dist/`，还没有 `node_modules/`。
