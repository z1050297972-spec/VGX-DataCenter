# Web 骨架与前端检查链

Status: done

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
- 2026-10-23，负责人批准本票（"批准"；三个问题都按推荐答案记下）：
  - **T1**：批准 `@testing-library/dom`（10.x）、`@types/node`（22.x，实测不需要就不装）、`@eslint-community/eslint-plugin-eslint-comments`（4.x），都是开发依赖。
  - **T2**：TypeScript 用 5.9.3。
  - **T3**：`vite build` 不进 `make check`，只在演示（验收第 10 条）和部署时跑。
  - Status 改成 `ready-for-agent`，由执行线的后台 agent 按「Claude 的步骤」推进，做到骨架关卡后交回主会话。
- 2026-10-23，第 2 步开票（执行线）。扫过 `.scratch/m*/issues/*.md` 的 `Status:` 行，只有 01（done）和本票，没有别的实现票在进行中；没有在跑的 `codex exec`。Status 改成 `in-progress`。`git worktree add -b t/m0-02-web-skeleton-frontend-check-chain ~/桌面/robot-data-platform.wt/m0-02-web-skeleton-frontend-check-chain main`，在 `5e6c34f`。`uv sync --frozen` 后基线 `make check` 六步全绿，`61 passed`，用时 4.6 秒；`git status --porcelain --untracked-files=all` 为空；`core.hooksPath` 是 `.githooks`。还没有 `src/web/`，`pnpm install` 跳过。
- 2026-10-23 14:23（+08:00），第 3 步派工 A1。
  - 提示 `assets/02-web-skeleton-frontend-check-chain/prompt-A1.md`（派工 A 模板，交付只有 `src/web/package.json`：只写 `name`、`private`、`type`、`scripts`，没有依赖表、`packageManager`、`engines`；scripts 只放 dev、build、preview，检查命令以 Makefile 为准）。
  - 快照 `refs/rdp/m0-02/A1`（`dfb998e`）。会话 `01a1676d-9d88-7950-947f-7e51ac8d54a1`。
  - 命令：在工作目录里 `timeout 60m codex exec -C <工作目录> -s workspace-write -m gpt-6-astra -c 'model_reasoning_effort="high"' --json -o assets/…/out-A1.md - < prompt-A1.md`。运行日志 `<执行线临时目录>/m0-02/ev-A1.jsonl`、`err-A1.txt`。
  - 派工前：node v22.23.2、pnpm 11.22.0、codex-cli 0.163.0；网关 `10.1.179.3:8088` 直连 200。
- 2026-10-23 14:26，第 4 步审 A1：通过。
  - Codex 退出码 0，运行日志最后一条 `turn.completed`，`out-A1.md` 在 assets；stderr 为空，开头一条 `disable_response_storage` 的 `error` 是已知现象。
  - 文件归属：工作目录只有 `?? src/web/package.json`，四个字段（`name: "rdp-web"`、`private`、`type: "module"`、`scripts` 里 dev/build/preview），没有依赖表。主仓库目录非规划文件为空。
  - 运行日志：10 条命令（读规划文件、enterprise-coding 的 SKILL.md、`git status`、`rg --files`），没有碰两个旧项目和 `/mnt`（JSONL 全文有 2 处命中，都在 `cat AGENTS.md` 的输出里）。记一笔：Codex 读的是工作目录里的规划文件副本（相对路径），A2 的提示里再强调读主仓库目录的版本。
- 2026-10-23 14:30，第 5–7 步装依赖（执行线）。
  - 第 5 步核实（`npm view`、PyPI JSON，输出在 `<执行线临时目录>/m0-02/step5-*.txt`）：所有包都没有 deprecated 标记；许可证都是 MIT，除了 typescript Apache-2.0、eslint-plugin-jsdoc BSD-3-Clause、uvicorn/httpx/starlette BSD-3-Clause。engines：jsdom 30 和 eslint-plugin-jsdoc 65 要 Node `^22.22.2`，vitest 5 要 `^22.12.0`，本机 v22.23.2 满足。直接依赖里带 `prepare` 的（antd、eslint-plugin-jsdoc、jsdom）只在开发它们的仓库里跑，从 registry 装时不跑。fastapi 0.161.1 带进 starlette 1.9.0、opentelemetry-api 1.45.1（Apache-2.0，纯 Python 的 API 包）、annotated-doc、typing-inspection，没有重型包。
  - 第 6 步：`uv add fastapi uvicorn pydantic` 装 13 个包；`uv add --dev httpx` 装 4 个（httpx 0.28.1、httpcore 1.0.9、certifi、anyio 已在）。
  - 第 7 步：在 `src/web/` 里 `pnpm add react@19.3.1 react-dom@19.3.1 @tanstack/react-router @tanstack/react-query antd openapi-fetch`，再 `pnpm add -D vite @vitejs/plugin-react typescript@5.9.3 openapi-typescript eslint typescript-eslint eslint-plugin-react-hooks eslint-plugin-jsdoc @eslint-community/eslint-plugin-eslint-comments prettier vitest @testing-library/react @testing-library/dom jsdom @types/react@~19.3.0 @types/react-dom@~19.3.0`。
    - **两个包比起草时查到的最新版低一个补丁号**：@tanstack/react-router 1.170.45（1.170.46 发布于 10 小时前）、eslint-plugin-jsdoc 65.4.0（65.4.1 发布于 15 小时前）。pnpm 11 默认不选发布不满一天的版本，用户和项目配置里都没改这个默认值。没有手动指定新版本。
    - 没有 peer 依赖告警。依赖树 347 个包，没有一个带 preinstall/install/postinstall 脚本（逐个查了 `node_modules/.pnpm/*/node_modules/**/package.json`），所以**不需要 `pnpm-workspace.yaml`**，也没有放行任何构建脚本。原生二进制（rolldown、lightningcss 的 linux-x64-gnu 包）是 optionalDependencies 预编译好的，不用构建。`pnpm licenses list`：MIT 273、Apache-2.0 18、ISC 12、BSD-2 11、BSD-3 5，另有 MPL-2.0、CC-BY、CC0、BlueOak、Unlicense、MIT-0 若干，都是宽松许可证。
    - 删掉 `node_modules` 后 `pnpm install --frozen-lockfile --offline` 0.6 秒装齐：store（`~/.local/share/pnpm/store/v11`）里已经全了，合并时可以离线装。
  - **@types/node 不装**（T1"实测不需要就不装"）。执行线在临时目录里用一份最小的 `vite.config.ts`（`vitest/config` 的 `defineConfig`、react 插件、`/api` 转发、jsdom、`pool: "threads"`）实测：`skipLibCheck: true`（Vite 模板的默认）时 tsc 5.9.3 通过；`false` 时报依赖自带的 `.d.ts` 缺 `node:util`、`URLSearchParams` 等。所以 A2 用 `skipLibCheck: true`，在 tsconfig 里写理由。
- 2026-10-23 14:33，第 8 步核对并做依赖提交。
  - 版本：`uv tree --depth 1` 是 fastapi 0.161.1、pydantic 2.14.1、uvicorn 0.54.0、httpx 0.28.1（dev），其余同第 1 张。`node_modules/.bin/tsc --version` 是 `Version 5.9.3`；eslint v10.13.0、vitest 5.0.5、prettier 3.9.10、openapi-typescript v7.13.0。`pnpm list --depth 0` 存在 `<执行线临时目录>/m0-02/step8-pnpm-list.txt`。
  - 依赖提交 `261a373 依赖：fastapi、uvicorn 和前端依赖（Web 骨架与前端检查链）`，含 `pyproject.toml`、`uv.lock`、`src/web/package.json`、`src/web/pnpm-lock.yaml`，经过钩子（六步全绿，`61 passed`），正文注明附带了 A1 的 `package.json`。
  - **和 5.1"一律 `git add -A`"的偏差**：这次只 `git add` 了上面四个文件，因为 `.gitignore` 还没有 `node_modules/`（A2 由 Codex 加），`-A` 会把 `node_modules` 提交进去。钩子查的是工作目录，`node_modules` 不影响后端六步（ruff 默认排除 `node_modules`，里面那个 `flatted.py` 没被查到），所以提交前后检查的是同一份代码。提交后 `git status` 只有 `?? src/web/node_modules/`。
- 2026-10-23 14:31，第 9 步派工 A2（续接）。
  - 提示 `assets/…/prompt-A2.md`：派工 A 模板，交付见「派工分段」的 A2；附第 8 步的版本，以及工单要求的三处提醒（`make check` 不调 pnpm；Vitest 起不来先试 `pool: "threads"`，还不行就停下报告；TSDoc 各项靠哪条规则写进最终回复）。另外写明：规划文件用绝对路径读主仓库目录的版本；没装 `@types/node`（用 `skipLibCheck: true`）、`jiti`（ESLint 配置用 `.js`）、`@eslint/js`、`globals`、jest-dom、user-event；A2 里 `openapi.json` 可以按工单定的接口手写成契约草稿、`schema.d.ts` 用 openapi-typescript 从它生成，B 用真正的导出重新生成；步骤编号按最终十一步写。最终回复六块（模板四块 + 检查配置要点 + TSDoc 规则与 Vitest 池）。
  - 快照 `refs/rdp/m0-02/A2`（`7d97e43`，和依赖提交 `261a373` 的树相同；拍快照时用 `':!src/web/node_modules'` 把还没被忽略的 `node_modules` 排除在临时索引外）。
  - 先 `cd <工作目录>`，再 `timeout 60m codex exec resume -m gpt-6-astra -c 'model_reasoning_effort="high"' -c 'sandbox_mode="workspace-write"' --json -o assets/…/out-A2.md 01a1676d-9d88-7950-947f-7e51ac8d54a1 - < prompt-A2.md`。运行日志 `<执行线临时目录>/m0-02/ev-A2.jsonl`、`err-A2.txt`。网关直连 200。
- 2026-10-23 14:48，派工 A2 交回，第 10 步审骨架（`codex-workflow.md` 3.3）。
  - 运行：14:31–14:47，退出码 0，最后一条 `turn.completed`，`out-A2.md` 在 assets。没有网关断开；stderr 只有一条 `apply_patch verification failed`（Codex 自己的补丁没对上，随后重试成功），不影响结果。
  - **重跑**：工作目录 `make check` 退出码 0，用时 6.9 秒，十步 `[1/11]`…`[6/11]`、`[8/11]`…`[11/11]`：后端六步（basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`；契约检查 `问题总数: 0`；pytest `61 passed, 34 skipped`），tsc、ESLint 无输出（即通过），Prettier `All matched files use Prettier code style!`，Vitest `6 skipped (6)` 个文件、`19 skipped (19)` 个测试。`[7/11]` 过期检查按约定用注释占位。跑之前和之后 `git status --porcelain --untracked-files=all` 相同（验收第 11 条）。
  - **沙箱里能跑（验收第 4 条，A2 这一半）**：运行日志第 67 行，Codex 在沙箱中跑 `make check` 退出码 0，tsc、ESLint、Prettier、Vitest 都跑完，Vitest 用 `pool: "threads"` 真正起来了（19 skipped）。不需要退路。
  - **文件归属**：工作目录只有 ` M .gitignore`（只加 `node_modules/`）、`Makefile`、`pyproject.toml`（只改 `[tool.importlinter]`：`include_external_packages = true` 和 forbidden 合约；ruff、basedpyright 没动；依赖表没动）、`scripts/check_contracts.py`（只改 `check_file` 的 docstring）、`src/rdp/api/__init__.py`；新文件都在 `src/rdp/api/`、`src/web/`、`tests/` 下。`package.json`、`pnpm-lock.yaml`、`uv.lock` 和依赖提交相同；没有 `pnpm-workspace.yaml`；`.githooks/pre-commit` 没改。主仓库目录 `-- src tests` 为空，非规划文件为空（只有本票文件和 assets）。
  - **运行日志**：23 条命令，读规划文件这次都用了主仓库目录的绝对路径；没有碰两个旧项目和 `/mnt`；没有在 `/tmp` 留文件（TSDoc 试验用 ESLint 的 `lintText` 在内存里跑）。命令清单在 `<执行线临时目录>/m0-02/A2-commands.txt`。
  - **审骨架**：Python 的 `create_app`、`get_health`、`export_openapi`、`main` 六项齐全，`HealthResponse` 有 `Attributes:`；TS 的 `mountWeb`、`createHealthClient`、`fetchHealth`、`useHealth`、`HealthPage` 六项齐全，`HEALTH_TIMEOUT_MS`、`HEALTH_STALE_TIME_MS` 是带单位的具名常量；失败 Alert 的权宜写了去掉的条件。测试清单 pytest 34 个（接口和托管 17、导出 11、W3 6）、Vitest 19 个，覆盖验收第 5–7 条和每条 `Raises:`。没有工单之外的公开函数。`openapi.json` 按提示手写成契约草稿，`schema.d.ts` 由 openapi-typescript 从它生成。
  - 快照 `refs/rdp/m0-02/A2-done`（`d96d0b4`）。
- 2026-10-23 14:58，第 10 步违规试验和钩子试验。脚本 `assets/…/violation_probe.sh A2-done`，输出 `violation_probe-A2-done.txt`。
  - 第一次跑到一半就停了：探针工作目录在 tmpfs（`/tmp`）上，pnpm 11 按文件系统另找 store（`/tmp/.pnpm-store`），离线装不上。脚本改成 `--store-dir ~/.local/share/pnpm/store`，误建的 `/tmp/.pnpm-store`（12 KB）已删。**合并时要注意**：主仓库目录和 store 在同一个文件系统，不受影响。
  - 第二次（`violation_probe-A2-done-try1.txt`）30 项通过、1 项不通过，**是探针的问题**：我写的"不能失败"样例里有 `void flag;`，被 `@typescript-eslint/no-meaningless-void-operator` 报了。改成 `return flag;` 后重跑。
  - 第三次：**31 项全部通过**。基线十步全绿 7.3 秒，跑完 `git status` 不变。
    - tsc：类型错误、越界下标当成非 `undefined` 用，都报 `error TS2322`，失败在 `[8/11]`。
    - ESLint（都失败在 `[9/11]`，按规则名匹配）：`no-floating-promises`、`rules-of-hooks`、`complexity`、`max-params`、`no-console`、直接 `fetch`（`no-restricted-globals`）、导出函数和导出箭头函数没有 TSDoc（`jsdoc/require-jsdoc`）、缺 `@sideEffects`（`jsdoc/require-tags`）、`@timeSemantics` 为空（`jsdoc/match-description`，补充项）、未登记的标签（`jsdoc/check-tag-names`）、`/* eslint-disable */`（`eslint-comments/no-unlimited-disable`）、不带理由的 `eslint-disable-next-line`（`eslint-comments/require-description`）、多余的豁免（`Unused eslint-disable directive`）、`@ts-ignore` 和不带说明的 `@ts-expect-error`（`ban-ts-comment`）。
    - Prettier 失败在 `[10/11]`；Vitest 失败的断言失败在 `[11/11]`；`rdp.infra` 里 `from fastapi import FastAPI` 失败在 `[4/11]` import-linter。
    - 补充：把 `src/web/node_modules` 挪走，`make check` 在 pytest 之后、`[8/11]` 之前失败，提示 `先在 src/web 里运行 pnpm install --frozen-lockfile`，没有自动安装。
    - 不能失败的：中文注释和 TSDoc、`@throws 无`；`eslint-disable-next-line no-console -- 理由` 和带说明的 `@ts-expect-error`；`tests/` 下只写一句的 `test_*`：都全绿。
    - 过期检查和 W3（`src/rdp` 里的 `test_probe` 被报出）不在 A2：前者没接，后者实现留到 B。脚本里用 `--with-b` 开关，在 `B-done` 上跑。
  - 钩子（验收第 9 条）：普通 `git commit`（`core.hooksPath` 已在共用配置里），提交 `console.log` 违规被拒（输出里有 `no-console`）、HEAD 没变；去掉后提交成功。D2：只暂存中文文件名的规划文件时跳过检查（工作区另有未暂存的违规）；规划加代码一起暂存时跑全量并被拒；代码文件改名进 `docs/` 时跑全量。探针工作目录已删，里面的提交都是游离提交。
- 2026-10-23 15:05，**骨架关卡一页摘要**（执行线起草，交主会话转负责人）。
  1. **这张票做什么**：一个只有 `GET /api/health` 的 FastAPI 应用托管前端构建产物，前端一个页面经 openapi-fetch + TanStack Query 调它；前端检查链（tsc、ESLint、Prettier、Vitest，B 再接 OpenAPI 过期检查）接进 `make check` 和钩子；补上 FastAPI 的 import-linter 合约和契约脚本的 `test_*` 跳过范围（W3）。
  2. **函数清单**：

     | 模块 | 函数 | 职责 | 改动什么 | 什么情况下报错 |
     |---|---|---|---|---|
     | `rdp.api` | `create_app(web_dist: Path \| None) -> FastAPI` | 建应用：`/api/health`，可选托管 SPA（找不到的非 `/api/` GET 回 `index.html`；`/api` 下未知路径 404 JSON；非 GET 不回退；不许读出构建目录） | 无（只读构建目录状态，不建 socket） | **创建时**就校验：目录不存在或缺 `index.html` → `FileNotFoundError`；路径是文件 → `NotADirectoryError`；`index.html` 不是普通文件或软链接指到目录外 → `ValueError`；读状态失败 → `OSError` |
     | `rdp.api.health` | `get_health() -> HealthResponse` | 返回 `{"status": "ok"}`，只表示 Web 能响应，不探测数据库和 worker | 无 | 无 |
     | `rdp.api.openapi_export` | `export_openapi(output_path) -> None` | 把 `create_app(None).openapi()` 写成确定的 JSON（键排序、2 空格、UTF-8、末尾换行） | 写一个文件；**写到一半失败可能留下截断文件**（见问题 3） | 父目录不存在、目标是目录、写失败 → `OSError`；不能序列化 → `TypeError`；非有限数 → `ValueError` |
     | `rdp.api.openapi_export` | `main(argv) -> 0/1/2` | 命令行入口 `python -m rdp.api.openapi_export <输出路径>` | 同上 | 返回码 0 成功或帮助、1 导出失败、2 参数错误；stdout/stderr 写失败抛 `OSError` |
     | `scripts/check_contracts.py` | `check_file`（只改 docstring，W3） | `test_` 开头的函数只在文件位于仓库根 `tests/` 下时跳过，按解析后的绝对路径判断 | 无 | 同原契约 |
     | `src/web/src/api/client.ts` | `createHealthClient(fetchImpl?)` | 建 openapi-fetch 客户端，基地址为空（相对路径 `/api/...`），`fetch` 可注入 | 无（只建对象） | 无；传输错误由请求的 Promise 拒绝 |
     | `src/web/src/api/health.ts` | `fetchHealth(client, signal?)` | 发一次 `GET /api/health`，只接受 `status: "ok"` | 一次请求 | 请求失败、非 2xx、载荷不符、取消、超过 `HEALTH_TIMEOUT_MS`（5000 ms）→ Promise 拒绝，不重试 |
     | `src/web/src/useHealth.ts` | `useHealth(client)` | TanStack Query 管加载、缓存、失败 | 请求、更新查询缓存 | 无；错误放在返回值的 `error` 里。缓存 `HEALTH_STALE_TIME_MS`（1000 ms），不轮询、不自动重试、聚焦不刷新 |
     | `src/web/src/HealthPage.tsx` | `HealthPage(props)` | 显示"后端正常"或失败的 Ant Design `Alert`（权宜，诊断组件那张票替换） | 经 useHealth 请求 | 无 |
     | `src/web/src/main.tsx` | `mountWeb(container)` | 挂载 React、QueryClientProvider、RouterProvider | 建 React 根 | `container` 为 null → `Error` |

     另有 `HealthResponse`（pydantic，`status: Literal["ok"]`）、代码式路由树（一个根路由 `/`，私有的 `getRootRoute`）、`index.html`，以及手写的 `openapi.json` 草稿和从它生成的 `schema.d.ts`（B 用真正的导出重新生成）。
  3. **测试清单**（pytest 用 `pytest.skip`，Vitest 用 `it.skip`，B 逐个实现）：
     - `tests/test_web_app.py` 17 个：health 200 和 `{"status":"ok"}`、响应模型进 OpenAPI；`web_dist=None` 时 `/` 404；`/` 和嵌套前端路由回 `index.html`；静态文件原样返回；`/api` 和 `/api/不存在` 404 JSON；非 GET 不回退；路径穿越和越界软链接读不到目录外；目录不存在、是文件、缺 `index.html`、`index.html` 是目录、软链接越界、读状态出错（`OSError`）；相对路径；多个应用互不影响、创建不写文件不建 socket。
     - `tests/test_openapi_export.py` 11 个：两次导出逐字节相同（排序、缩进、换行）；和 `create_app(None).openapi()` 一致；只覆盖指定文件；输出路径不合格报 `OSError`；`TypeError`/`ValueError` 时原文件不变；命令行成功、帮助、参数错误退出 2、导出失败退出 1、stdout/stderr 写失败、`argv=None` 读 `sys.argv`。
     - `tests/test_contract_scope.py` 6 个（W3）：`src/`、`scripts/` 下的 `test_*` 照查；只有仓库根 `tests/` 下跳过；别处叫 `tests` 的目录不豁免；和当前工作目录无关；按解析后的路径判断、软链接不能扩大豁免。
     - Vitest 19 个：客户端 2（不发请求、不改全局 `fetch`；注入的 `fetch` 收到相对路径 `/api/health`）、fetchHealth 5（成功；非 2xx、无响应、载荷不符拒绝；传输异常不伪装成 ok；超时中止不重试；取消）、useHealth 5（加载/成功/失败；缓存期内不重复请求；不同客户端不共享缓存；不重试不轮询；取消传给请求）、HealthPage 4（成功显示"后端正常"；失败显示 `Alert` 且没有成功提示；加载中；默认客户端稳定、不改 URL）、路由 1、挂载 2。
  4. **检查配置要点**：
     - `make check` 十一步：后端六步不变 → `[7/11]` 过期检查（A2 用注释占位，B 接上：导出和生成都写到临时目录，逐字节比较，不一致提示 `make api-types`）→ `[8/11]` tsc → `[9/11]` ESLint（`--max-warnings 0`）→ `[10/11]` Prettier `--check` → `[11/11]` Vitest `run`。前端工具都从 `src/web/node_modules/.bin/` 调，没有 `pnpm`；没有 `node_modules` 时在 `[8/11]` 之前失败并提示 `pnpm install --frozen-lockfile`。新增 `make api-types`；`make fmt` 加了 `eslint --fix`、`prettier --write`。现在全程约 7 秒。
     - tsconfig：`strict`、`noUncheckedIndexedAccess`、`isolatedModules`、`verbatimModuleSyntax`，没关 `noImplicitAny`；`noEmit`、`incremental: false`（不留 `.tsbuildinfo`）；`skipLibCheck: true`，理由写在配置里（依赖自带的 `.d.ts` 引用 Node 类型，没装 `@types/node`）。
     - ESLint：typescript-eslint `strictTypeChecked`、react-hooks flat recommended；`complexity` ≤ 10（注释写明它兜底后端的"分支 ≤ 12"）、`max-params` ≤ 5、`max-statements` ≤ 40；`no-console`；`no-restricted-globals` 禁 `fetch`，连 `window.fetch`、`self.fetch`、`globalThis.fetch` 也禁。
     - 豁免：`reportUnusedDisableDirectives: "error"`；`eslint-comments/no-unlimited-disable`、`require-description`；`ban-ts-comment` 禁 `@ts-ignore`、`@ts-nocheck`，`@ts-expect-error` 要至少 3 个字的说明。代码里的豁免：客户端工厂读全局 `fetch` 的那一处（`no-restricted-globals`），加上 5 个骨架桩各一条 `no-unused-vars`（参数还没用到），B 实现后必须删掉，不删的话"多余豁免"那条会报。
     - **TSDoc 各项靠哪条规则**（都是 eslint-plugin-jsdoc 65.4.0，执行线用违规试验核过"缺"和"空"两种）：

       | 项 | 必须出现 | 不能为空 |
       |---|---|---|
       | 首行职责 | `require-jsdoc`（导出的函数、箭头函数、函数表达式；组件也是函数）+ `require-description` | `require-description` + `match-description`（`\S`） |
       | `@param` | `require-tags` 每个函数都要有；`require-param` 核对每个真实参数 | `require-param-description` + `match-description` |
       | `@returns`、`@throws`、`@sideEffects`、`@timeSemantics` | `require-tags`（按函数查，不是按文件） | `match-description` |

       `check-tag-names` 登记了 `sideEffects`、`timeSemantics` 两个标签。**做不到的**：内容合不合格（单位、取值范围写全没有）仍是〔审〕；而且为了让无参函数能写 `@param 无 - 无参数。`，Codex 没开 `check-param-names`，所以 `@param` 写了一个不存在的参数名不会报（见问题 2）。
     - Prettier：行宽 100、2 空格、分号、双引号、尾逗号、LF。生成的 `schema.d.ts` 不过 ESLint 和 Prettier；`openapi.json`、`pnpm-lock.yaml` 也不过 Prettier（格式由导出器定，避免和逐字节比较冲突），旁边都写了理由。
     - import-linter：`include_external_packages = true`；新 forbidden 合约"基础层不得依赖 Web 框架"：`rdp.infra` 不 import `fastapi`、`starlette`、`uvicorn`，领域包登记的位置用注释留着。ruff、basedpyright 没改。钩子没改。
     - **沙箱里**：tsc、ESLint、Prettier、Vitest 都在 Codex 的沙箱里跑完；Vitest 用 `pool: "threads"` 起得来，不需要退路。basedpyright 照旧能跑。
  5. **要负责人拍板的**：
     1. **两个时间常量**：健康请求超时 `HEALTH_TIMEOUT_MS = 5000`，缓存 `HEALTH_STALE_TIME_MS = 1000`；失败不自动重试、不轮询、窗口聚焦不刷新。工单只要求"写成具名常量"，没定数值，是 Codex 定的。建议：采纳。另外缓存常量的注释引了 ADR 0001 的"约 1 秒轮询"，但健康检查不轮询，B 里改成写真实理由。
     2. **无参函数的 `@param`**：现在要求无参函数也写 `@param 无 - 无参数。`（对应后端的 `Args: 无`），代价是关掉了 `check-param-names`，写错参数名查不出来。建议：改成"有参数才写 `@param`"：从 `require-tags` 里去掉 `param`（`require-param` 已经保证每个真实参数都有说明），打开 `check-param-names`。只改 ESLint 配置和一处私有函数的注释，不改任何函数的含义，放进派工 B 做。
     3. **`export_openapi` 写到一半失败可能留下截断文件**。建议：改成同目录临时文件加 `os.replace`（标准库，CODING_STANDARDS 2.6），失败时原文件不变。这改了 `Side Effects:` 的含义，所以要你点头；B 里实现，测试加一条。
  6. **结论：建议通过**（问题 2、3 按建议在派工 B 里改）。检查都由执行线重跑过：`make check` 十步 6.9 秒全绿，跑完不留痕迹；tsc、ESLint、Vitest 在沙箱里真正跑完；违规试验和钩子试验 31 项全过；文件归属干净；没打回（0 轮）。给 B 的提醒，不用负责人拍板：`main.tsx` 在模块顶层就调 `mountWeb`，`main.test.tsx` 一 import 就会挂载，B 要拆开；`router.tsx` 里那个会抛"未实现"的 `getRootRoute` 改成普通箭头函数。负责人说"通过"以后，做契约提交 `契约：Web 骨架与前端检查链`，Status 改回 `in-progress`。
- 2026-10-23，骨架关卡（主会话）：负责人"全部通过"。
  - 主会话先独立重跑：`make check` 十一步（第 7 步按 A2 约定空着）退出码 0，约 7 秒，61 passed、34 skipped，Vitest 19 skipped；工作目录的改动都在 `src/`、`tests/` 和本票允许的受保护文件内；主仓库目录规划文件以外没有改动。
  - **G1** 接受 `HEALTH_TIMEOUT_MS` 5000、`HEALTH_STALE_TIME_MS` 1000，不重试、不轮询、不在切回页面时刷新；派工 B 改正 staleTime 注释里错引的 ADR 0001 轮询频率。
  - **G2** 没有参数的函数不写 `@param`：`require-tags` 去掉 `param`，打开 `check-param-names`（只改配置，派工 B 做）。
  - **G3** `export_openapi` 改成同目录临时文件加 `os.replace`（CODING_STANDARDS 2.6），改 `Side Effects:`，派工 B 加一个测试。负责人已批准这处契约含义变化。
  - 第 11 步：契约提交 `1b2e3ed 契约：Web 骨架与前端检查链`，经过钩子，全绿；`node_modules` 没进提交（`.gitignore` 第 33 行）。Status 改回 `in-progress`，执行线从第 12 步继续。
- 2026-10-23 15:16，第 12 步派工 B（续接，执行线）。
  - 提示 `assets/…/prompt-B.md`：派工 B 模板（先红后绿要逐个测试单独跑，pytest 和 Vitest 的单独运行命令都写明，评审会在日志里核对），加上 G1（只改 staleTime 注释）、G2（`require-tags` 去掉 `param`，开 `check-param-names`，删掉 `@param 无`）、G3（临时文件加 `os.replace`，改 `Side Effects:`，加一个测试），评审提醒（`mountWeb` 挪到单独模块、`main.tsx` 只留入口；`getRootRoute` 改成箭头函数；删掉 5 个桩上的 `no-unused-vars` 豁免；改 `.prettierignore` 里"手写草稿"那句），接上 `[7/11]` 过期检查和 `make api-types`、用真正的导出重新生成两个入库文件，实现 W3。最终回复六块（模板四块 + 先红后绿 + 检查配置的变化）。
  - 快照 `refs/rdp/m0-02/B`（`b82ffcf`，基于契约提交 `1b2e3ed`，工作目录干净）。
  - 会话 `01a1676d-9d88-7950-947f-7e51ac8d54a1`，先 `cd <工作目录>` 再 `timeout 60m codex exec resume -m gpt-6-astra -c 'model_reasoning_effort="high"' -c 'sandbox_mode="workspace-write"' --json -o assets/…/out-B.md <会话> - < prompt-B.md`。运行日志 `<执行线临时目录>/m0-02/ev-B.jsonl`、`err-B.txt`。网关直连 200。
- 2026-10-23 15:40，**派工 B 被沙箱挡住，停下等负责人决定**（执行线）。
  - 运行：15:16–15:23，退出码 0，最后一条 `turn.completed`，`out-B.md` 在 assets，没有网关断开。Codex 只做了第一个测试：`test_health_response` 先红（`create_app` 抛 `NotImplementedError`），补上最小实现后卡在 `TestClient.__enter__`，限时重跑超时（退出码 124），没有变绿。其余 33 个后端、19 个前端测试和 G1–G3 都没开始。工作区留着三处改动（`src/rdp/api/__init__.py`、`health.py`、`tests/test_web_app.py`，含一条 `# pyright: ignore[reportUnknownMemberType]`），快照 `refs/rdp/m0-02/B-blocked`（`5d84bd3`）。
  - **执行线复现的原因**（`codex sandbox -c 'sandbox_mode="workspace-write"' -- .venv/bin/python -I …`，和 Codex 派工的沙箱相同）：
    - `socket.socketpair()` 能建，但 `send` 报 `PermissionError: Operation not permitted`；对同一个 socket 用 `os.write` 能写，管道也能写。被挡的是 socket 的发送调用（seccomp）。
    - asyncio 从别的线程唤醒事件循环（`call_soon_threadsafe`）靠的就是往 socketpair 里 `send` 一个字节，所以 `asyncio.run` 里 `await loop.run_in_executor(...)` 会一直挂住；不带线程的 `asyncio.run` 正常。
    - **影响比 TestClient 大**：Starlette 把同步的接口函数、`StaticFiles` 的文件读取都放进线程池跑，所以换成 `httpx.ASGITransport` 在同一线程里调也一样挂（实测）。沙箱里没法测 FastAPI 的托管，`make check` 的 pytest 一步在沙箱里会挂住，验收第 4 条做不到。以后每张带接口测试的票都会碰到。
    - 加 `-c 'sandbox_workspace_write.network_access=true'` 后 `send` 成功、`run_in_executor` 返回 3。codex-cli 0.163.0 的二进制里还有更窄的权限配置项（`allow_unix_sockets`、`allow_local_binding` 一类），具体写法没核实。
    - 收尾：Codex 说已经终止的那个挂住的 pytest 其实还在跑，执行线自己 `timeout` 的两个诊断进程也没退出（`timeout` 只杀了外层），都已手动结束，现在没有残留进程；诊断脚本在临时目录里，已删。
  - 不算打回轮次（没有发修复清单）。Status 保持 `in-progress`。
  - **要负责人选的**（执行线的建议是 1，不行再 2）：
    1. 由执行线先试 codex 自带的"只放开本地 unix socket、不放开外网"的权限配置。要是能做到 `socketpair` 能 `send`、`curl` 外网仍然失败，就按这个配置派工，写进 `docs/brief` 和 `codex-workflow.md` 第 4 节。
    2. 本票的派工加 `sandbox_workspace_write.network_access=true`（实测能解决）。代价：Codex 的命令能联网。靠提示里"不安装、不联网"，加上评审时查运行日志里有没有 `pnpm`/`uv`/`pip`/`curl`/`npx` 来兜底。
    3. 沙箱不动：用线程池的后端测试只由 Claude 在沙箱外跑，Codex 写了也跑不了。这样这些测试在日志里没有先红后绿的证据，`make check` 在沙箱里也跑不完。不建议。
- 2026-10-23，主会话复核阻塞：
  - 用 `codex sandbox -c 'sandbox_mode="workspace-write"'` 跑一段只做 `socketpair().send` 和 `asyncio` `run_in_executor` 的脚本：`send` 报 `[Errno 1] Operation not permitted`，`run_in_executor` 一直不返回（`timeout` 退出码 124）。加 `-c 'sandbox_workspace_write.network_access=true'` 后两者都正常，同时 `curl https://pypi.org/` 返回 200，即真的能上网。
  - 试过 `network.allow_local_binding=true`、`sandbox_workspace_write.allow_local_binding=true`，都还是 `Operation not permitted`。codex 二进制里的 `allow_unix_sockets` 属于网络代理的按路径放行，管不到 `socketpair`。执行线的选项 1 实际上走不通。
  - 复现脚本留下的挂起进程已清理。等负责人决定。
- 2026-10-23，负责人选 B（"先试B"）：只在测试里绕开，沙箱不放开。主会话在默认的 `workspace-write` 沙箱里用独立脚本验证（脚本在主会话 scratchpad 的 `sbx/`，不进仓库）：
  - 把 `asyncio.selector_events.BaseSelectorEventLoop._write_to_self` 里的 `csock.send(b"\0")` 换成 `os.write(csock.fileno(), b"\0")` 以后：`socketpair` 的 `recv` 正常；`run_in_executor` 返回；FastAPI `TestClient` 调同步接口返回 `{"ok": true}`；`StaticFiles` 返回 200 和页面内容。
  - 不打补丁时，同样的 `TestClient` 脚本超时（退出码 124），和执行线看到的一致。
  - 做法：派工 B 续接时，让 Codex 在 `tests/conftest.py` 里加这个补丁，按规则 5 写明这是权宜、为什么（沙箱的 seccomp 禁止 socket 的 send 系列调用，`write` 不受限）、什么时候可以去掉（Codex 沙箱放开本进程内的 socket 发送，或者 asyncio 改用别的唤醒方式）。补丁只在测试进程里生效，生产不在沙箱里跑，不受影响。
  - 顺带发现：starlette 1.9.0 导入 `TestClient` 时报 `StarletteDeprecationWarning`，说 `httpx` 用法已弃用、建议改装 `httpx2`。现在只是警告，不影响测试；以后升级 starlette 时要处理，记为风险。
- 2026-10-23 16:05，派工 B 继续（B2，执行线）。不是打回轮。提示 `assets/…/prompt-B2.md`：先在 `tests/conftest.py` 加 `_write_to_self` 的权宜补丁（按规则 5 写为什么、什么时候去掉，只在测试进程生效）和一条先红后绿的契约测试，pytest 一律套 `timeout`；然后照 `prompt-B.md` 从停下的地方继续；StarletteDeprecationWarning 只记不改。从快照 `B-blocked`（`5d84bd3`）的工作区状态续接同一会话 `01a1676d-9d88-7950-947f-7e51ac8d54a1`，先 `cd <工作目录>`，参数同派工 B，没有 `network_access`。运行日志 `ev-B2.jsonl`、`err-B2.txt`，最终回复 `out-B2.md`。
- 2026-10-23 18:30，B2 交回：**Codex 拒绝打补丁，停下等决定**（执行线）。
  - 运行：16:05–18:25，退出码 0，最后一条 `turn.completed`，`out-B2.md` 在 assets，没有网关断开。运行日志只有 6 行：一条回复，没有执行任何命令、没有改文件（耗时长不是 Codex 在干活）。工作区仍是 `B-blocked` 的三处改动；没有残留进程。
  - Codex 原话："这一步不能照做：把 seccomp 禁止的 `socket.send` 改为对同一 socket 调用 `os.write`，是在绕过沙箱安全控制，即使补丁仅用于测试。……可行的续接方式是由 Claude 在正常环境运行 `TestClient` 测试，或批准不依赖受限 socket 通信的测试方案；相应需要调整'全部在当前沙箱内通过'的验收要求。"
  - 执行线没有自行加压续接，也不能自己写 `tests/conftest.py`（CLAUDE.md：Claude 不在 `tests/` 下写代码）。不算打回轮次。Status 保持 `in-progress`。
  - 可选的处理（交负责人）：
    1. 续接一次，把背景讲清楚：负责人批准；`socketpair` 是本进程内的一对 fd，`write(2)` 是沙箱明确允许的，补丁不带来任何联网能力，也不碰沙箱配置。Codex 仍拒绝就不再试。
    2. 接受 Codex 提的方案：用线程池的后端接口测试照常由 Codex 写，但只在沙箱外由 Claude 跑；先红后绿的证据由 Claude 在沙箱外跑出来补进 assets；验收第 4 条改成"沙箱里除这些测试外全绿"。`make check` 在沙箱里会挂在 pytest，Codex 只能跑 `pytest --deselect`/`-k` 的子集。
    3. 回到选项 2（只给本票的派工放开 `network_access`），负责人之前没选。
- 2026-10-23，主会话向负责人说明：Codex 拒绝得有道理，B 方案实际上是绕开安全控制，主会话推荐时考虑不周；不再续接去劝。负责人选 **N1**：
  - 实现票的派工（含本票续接）加 `-c 'sandbox_workspace_write.network_access=true'`，这是负责人授权的正式设置；沙箱能写的范围不变，只读任务不联网。
  - 三道防线：提示写明不安装、不联网；评审按 `codex-workflow.md` 3.5 第 5 项查运行日志里的安装和联网命令，有一条整轮打回；照常核对依赖表和锁文件。
  - 写进 `docs/brief/0012-环境事实更新-沙箱socket与联网授权.md`、`codex-workflow.md` 第 4、7、9 节和 3.5 第 5 项、`CLAUDE.md`。
  - 本票从快照 `B-blocked`（`5d84bd3`）的工作区状态续接同一会话，照 `prompt-B.md` 继续；`tests/conftest.py` 不加 `_write_to_self` 补丁。验收第 4 条不变（全部在沙箱里通过）。
- 2026-10-23，派工 B 继续（B3，执行线，按负责人 N1）。不是打回轮。开工前确认：工作区的树和 `B-blocked`（`5d84bd3`）相同（`f7dd120`），没有残留的 `codex exec`、pytest、vitest 进程。提示 `assets/…/prompt-B3.md`：说明网络权限已正式打开、不打任何 `send`/`write` 补丁；照 `prompt-B.md` 从停下的地方继续，pytest 和 `make check` 一律套 `timeout`；"边界"用 `codex-workflow.md` 第 7 节新版原样。先 `cd <工作目录>`，按第 4 节续接模板（加 `-c 'sandbox_workspace_write.network_access=true'`），会话 `01a1676d-9d88-7950-947f-7e51ac8d54a1`，运行日志 `ev-B3.jsonl`、`err-B3.txt`，最终回复 `out-B3.md`。
- 2026-10-23 22:40，派工 B3 交回，第 13 步评审（`codex-workflow.md` 3.5）。
  - 运行：21:11–22:03，退出码 0，最后一条 `turn.completed`，`out-B3.md` 在 assets，stderr 为空，没有网关断开，没有残留进程。
  - **1 重跑**：工作目录 `timeout 600 make check` 退出码 0，用时 10.2 秒，十一步 `[1/11]`…`[11/11]` 全绿：basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`；契约检查 `问题总数: 0`；pytest `100 passed, 1 warning`（就是 StarletteDeprecationWarning）；`[7/11]` `OpenAPI 与生成类型均未过期`；tsc、ESLint 通过；Prettier 通过；Vitest `6 passed`、`19 passed`。`pytest -rs` 没有跳过。跑之前和之后 `git status` 相同（验收第 11 条）。
  - **2 文件归属**：工作目录改动都在 `src/`、`tests/`，加上 `Makefile`、`scripts/check_contracts.py`、`src/web/eslint.config.js`、`vite.config.ts`、`.prettierignore`（都在允许表里）。`pyproject.toml`、`uv.lock`、`package.json`、`pnpm-lock.yaml`、`.githooks/`、`.gitignore` 相对契约提交没变；没有 `pnpm-workspace.yaml`。主仓库目录 `-- src tests` 为空；非规划文件里只有根目录一个 `Read_First_What're_Files_Meaning?.md`（16:19 写入，不在任何 Codex 运行日志里，内容是负责人自己的目录导读），不是 Codex 写的，执行线没动它，交主会话确认。
  - **3 对比契约**：用 `ast` 比 `create_app`、`get_health`、`HealthResponse`、`export_openapi`、`main`、`check_file` 的签名和 docstring，只有 `export_openapi` 的 `Raises:`、`Side Effects:` 变了（G3，已获批）；两个模块 docstring 只去掉了"A2/B"阶段的字样。TS 五个导出函数的 TSDoc 和签名不变（`mountWeb` 挪到 `mountWeb.tsx`），只有 `HEALTH_STALE_TIME_MS` 的注释按 G1 改了。
  - **4 先红后绿**：从 `ev-B.jsonl`、`ev-B3.jsonl` 里逐个找每个测试的第一次单独运行（结果存在 `<执行线临时目录>/m0-02/red-first-check.txt`），和 Codex 的表一致：每个测试都有单独运行。pytest 41 个里 26 个先红；15 个第一次就绿，都写了原因（例如 FastAPI 默认首页 404、StaticFiles 已挡住越界、W3 第一个测试的实现已覆盖其余五个）。Vitest 19 个里 17 个先红，2 个先绿有原因（Promise 拒绝自然透传；空容器那条桩本来就抛错，下一条再区分）。G3 的 `test_atomic_failure[write/replace]` 先红。
  - **5 运行日志**：124 条命令。安装和联网的 grep（3.5 第 5 项）没有命中；两个旧项目只在 Codex 读提示时的输出里出现；没有 `/mnt`；唯一碰 `/tmp` 的命令是删掉它自己失败运行留下的两个 `pytest-of-shawn` 目录。没有 `send`/`write` 补丁；`tests/` 里两处 `patch("socket.socket", side_effect=AssertionError)` 是断言"不建 socket"，不是绕开沙箱。
  - **6 两轴评审**：快照 `refs/rdp/m0-02/B-done`（`9190f83`），探针工作目录检出它，`/code-review`（基准 `5e6c34f`，即和 main 的合并基点），两轴结论：
    - 两轴都报了同一个硬问题：`create_app` 用 `app.add_exception_handler(404, _spa_fallback)` 接管**所有** 404，不看路径。现在 `/api` 下的未知路径由兜底路由直接回 JSON，所以没暴露；但以后任何 `/api` 的 GET 接口抛 `HTTPException(404)`（M1 的"数据集不存在"就是），都会拿到 `index.html` 和 200。违反它自己的 `Returns:`（"`/api/` 下……绝不返回 index.html"）和 CODING_STANDARDS 3.3.2。执行线读代码确认。
    - Standards 轴另报：`noqa: PTH105` 可以用 `Path.replace`（就是 `os.replace`）消掉；`tests/test_web_app.py:27` 的 `pyright: ignore` 可以用文件里已有的 `_request()` 消掉，那个测试还有一个没用的 `tmp_path`；`router.test.tsx` 改了模块单例 `router` 没恢复（7.5）；`create_app` 里 `web_dist` 已 resolve 又 resolve 一次，"禁用 StaticFiles 的 404.html"那句注释说的其实是默认值；`health.ts` 自己拼超时，没写为什么不用 `AbortSignal.timeout`（9.1）；非 GET 的非 `/api` 路径回的是"API 不存在"的 JSON，名不副实。判断题不改：测试 helper 重复、`useHealth` 的 WeakMap、Makefile 两种调用写法。执行线不采纳的一条：`test_export_matches_app` 和 `create_app(None).openapi()` 比，契约本来就规定导出等于它，不违反 7.2。
    - Spec 轴另报（不改，记风险）：`/api/{unknown:path}` 兜底收了所有方法，所以 `POST /api/health` 回 404 不是 405；`node_modules` 检查在 `[7/11]` 标题之前失败，看不出属于哪一步（提示文字是对的）；`.prettierignore` 里 openapi.json 有两行重叠的理由。
  - **7 违规试验**：`violation_probe.sh B-done --with-b`，输出 `violation_probe-B-done.txt`：**34 项全部通过**。第一次（`-try1.txt`）过期检查那项不通过，是探针的问题：给响应模型加字段会改变 `/api/health` 的返回，pytest 在 `[6/11]` 先失败（这是对的）。改成两项：(a) 只给 `status` 加 `description`（schema 变、返回不变），`make check` 失败在 `[7/11]` 并提示 `make api-types`；(b) 按验收原话加字段，直接跑 `make check-api-types`（`[7/11]` 调的目标），失败并提示 `make api-types`。W3：`src/rdp` 里只写一句的 `test_probe` 失败在 `[5/11]`。A2 那 31 项照样通过，基线 10 秒左右。
  - **验收第 10 条演示**（执行线，沙箱外）：`vite build`（576 KB 的包，Vite 提示超过 500 KB，见风险）；在临时目录写一个无参工厂，`uvicorn --factory --app-dir <临时目录> rdp_demo_factory:app --host 127.0.0.1 --port 8600`。`curl`：`/` 200 `index.html`、`/api/health` 200 `{"status":"ok"}`、`/datasets/x` 200 `index.html`、`/api/nonexistent` 404 `{"detail":"Not Found"}`。无头 Chrome 打开 `http://127.0.0.1:8600/` 显示"后端正常"。输出和截图：`demo-B-done-curl.txt`、`demo-B-done-page.png`、`demo-B-done-uvicorn.log`。服务已停，8600 已释放，`dist/` 已删。
  - **结论：打回第 1 轮（r1）**。Status 改成 `changes-requested`，发出修复轮时改回 `in-progress`。修复清单（契约不改）：
    1. 问题：SPA 回退接管所有 404。位置：`src/rdp/api/__init__.py` 的 `_spa_fallback` 和 `add_exception_handler(404, …)`。期望：只有路径不在 `/api` 下（不是 `/api`，也不以 `/api/` 开头）、方法是 GET 的 404 才回 `index.html`；`/api` 下的 404 一律原样回 JSON（保留原来的 `detail`）。加测试：测试里给应用加一个 GET `/api/...` 接口抛 `HTTPException(404)`，带 `web_dist` 时拿到 404 JSON，不是 `index.html`。这个测试先红后绿。
    2. 问题：非 GET 的非 `/api` 路径回的是"API 不存在"的处理函数。位置：同上。期望：改成一个名副其实的通用 404 JSON（名字和注释说清楚），或者原样回 StaticFiles 的 404；行为照契约"非 GET 请求不使用 SPA 回退"。
    3. 问题：`noqa: PTH105`。位置：`src/rdp/api/openapi_export.py`。期望：用 `Path.replace`（底层就是 `os.replace`，G3 的语义不变），删掉豁免；docstring 里的 `os.replace` 字样保留。
    4. 问题：可以消掉的 `pyright: ignore[reportUnknownMemberType]` 和没用的 `tmp_path`。位置：`tests/test_web_app.py:27` 一带的 `test_health_response`。期望：改用文件里已有的 `_request()`，删掉豁免和多余参数。
    5. 问题：`router.test.tsx` 用 `router.update(...)` 改了模块单例，没恢复，测试之间可能互相影响（CODING_STANDARDS 7.5）。期望：测试结束后恢复，或者在测试里新建一个独立的 router。
    6. 问题：几处小问题。位置：`create_app` 里重复的 `web_dist.resolve()`；"禁用 StaticFiles 的 404.html 与目录首页优先逻辑"这句注释（实际是 `html=False` 的默认行为）；`src/web/.prettierignore` 里 openapi.json 两行重叠的理由；`src/web/src/api/health.ts` 自己拼超时，没写为什么不用 `AbortSignal.timeout`。期望：去掉重复的 resolve；注释写准；`.prettierignore` 合成一行理由；`health.ts` 要么改用 `AbortSignal.timeout`（测试照样能用假时钟验证），要么注释写明为什么不用（9.1）。
- 2026-10-23 22:27，派工 r1（续接）。提示 `assets/…/prompt-r1.md`（修复轮模板，就是上面 6 条；"边界"用第 7 节新版），快照 `refs/rdp/m0-02/r1`，Status 改成 `in-progress`。会话 `01a1676d-9d88-7950-947f-7e51ac8d54a1`，先 `cd <工作目录>`，按第 4 节续接模板（带 `network_access=true`）；运行日志 `ev-r1.jsonl`、`err-r1.txt`。两轴评审用的探针工作目录已删。
- 2026-10-23 22:45，r1 交回并评审：**通过**。
  - 运行：22:27–22:34，退出码 0，最后一条 `turn.completed`，`out-r1.md` 在 assets，stderr 为空，没有残留进程。
  - 重跑：`make check` 十一步全绿，10.3 秒，`101 passed`（多了 r1 的回归测试）、Vitest 19 passed；跑之前和之后 `git status` 相同。
  - 文件归属：这一轮只动了 `src/rdp/api/__init__.py`、`openapi_export.py`、`src/web/.prettierignore`、`health.ts`、`router.test.tsx`、`tests/test_web_app.py`；受保护文件和锁文件相对契约提交没变；主仓库目录非规划文件仍只有那个负责人的导读文件。
  - 契约：这一轮没有改任何 docstring 或 TSDoc（`git diff r1 r1-done` 核过）。
  - 先红后绿：`test_api_404_preserves_detail` 第一次单独运行失败（运行日志第 17 行，`assert 200 == 404`，即 `/api` 下抛 404 的 GET 拿到了 `index.html`），修好后同一命令通过（第 22 行）。
  - 运行日志：13 条命令，安装和联网的 grep 没有命中；没有旧项目、`/mnt`；唯一碰 `/tmp` 的是删掉它自己的回归测试样例。
  - 6 条逐条核对：SPA 回退只接管非 `/api` 的 GET 404，`/api` 下保留原 `detail` 和响应头；非 GET 回通用 404 JSON；`Path.replace` 替掉了 `os.replace`、豁免删掉了；`test_health_response` 用 `_request()`、豁免和 `tmp_path` 删掉了；路由测试新建独立 router，并断言单例没变；重复 resolve、注释、`.prettierignore` 改好了，`health.ts` 写明了不用 `AbortSignal.timeout` 的理由（它没法提前清掉计时器）。
  - 违规试验：快照 `refs/rdp/m0-02/r1-done`（`c18af3a`），`violation_probe-r1-done.txt`，34 项全部通过。
  - 演示（r1-done，沙箱外）：`/` 和 `/datasets/x` 200 `index.html`，`/api/health` 200 `{"status":"ok"}`，`/api/nonexistent` 404 JSON，`POST /datasets/x` 405（不走 SPA 回退）；无头 Chrome 显示"后端正常"。`demo-r1-done-curl.txt`、`demo-r1-done-page.png`、`demo-r1-done-uvicorn.log`。服务已停，`dist/` 已删。打回共 1 轮。
- 2026-10-23 22:50，第 14 步：实现提交 `b79cce0 实现：Web 骨架与前端检查链`，经过钩子（十一步全绿，`101 passed`、Vitest 19 passed），提交后工作目录干净。Status 改成 `in-review`，等负责人说"合并"（主会话按 `codex-workflow.md` 3.7 做；第 3 步记得在主仓库目录的 `src/web/` 里 `pnpm install --frozen-lockfile`）。
- 2026-10-23，**完工汇报**（执行线起草）。
  - **改了什么**（分支 `t/m0-02-web-skeleton-frontend-check-chain`，三个提交）：
    - `261a373` 依赖：fastapi 0.161.1、uvicorn 0.54.0、pydantic 2.14.1、httpx 0.28.1（dev），前端 22 个包，`uv.lock`、`pnpm-lock.yaml`。
    - `1b2e3ed` 契约：检查配置（tsconfig、ESLint、Prettier、Vitest）、Makefile 十一步（第 7 步占位）、import-linter forbidden 合约、W3 的 docstring、后端和前端的契约骨架、53 个跳过的测试。
    - `b79cce0` 实现：`create_app`、`get_health`、`export_openapi`（临时文件加原子替换）、命令行入口；前端客户端、`fetchHealth`、`useHealth`、`HealthPage`、`mountWeb`、路由；`[7/11]` 过期检查和 `make api-types`；G1–G3；W3；真正导出的 `openapi.json`、`schema.d.ts`；测试环境适配 `testSetup.ts`（jsdom 下补浏览器 `Request` 对相对 URL 的处理和 `scrollTo`，不碰 `fetch`）。
  - **测试**：pytest 101 个（原有 61，加接口和托管 20、导出 14、W3 6），Vitest 19 个，全部通过，没有跳过。`make check` 十一步约 10 秒（第 1 张是 3.5–4.5 秒）。违规试验：A2-done 31 项、B-done 34 项、r1-done 34 项，全部通过。
  - **十二条验收**：
    1. 环境：通过。`tsc --version` 是 5.9.3（T2）；`pnpm-lock.yaml`、`uv.lock` 在依赖提交里入库；契约和实现两个提交里依赖表、锁文件都没变。
    2. 骨架阶段全绿：通过。契约提交 `1b2e3ed` 经过钩子，十步全绿，pytest 34 个、Vitest 19 个跳过（主会话做的提交，执行线在 A2-done 上重跑过）。
    3. 实现后全绿：通过。十一步退出码 0，没有跳过；用时约 10 秒，超过 03 号票"约 1 分钟"的线还远，暂不拆快慢两档。
    4. 沙箱里能跑：通过，但有前提。A2 的日志里 tsc、ESLint、Vitest（threads 池）在沙箱里跑完；B3 和 r1 的日志里 `make check` 十一步在沙箱里退出码 0。B 阶段要靠负责人授权打开沙箱网络权限（N1，`docs/brief/0012`），不打开时 FastAPI 的测试会挂住。
    5. 接口和托管：通过。`/api/health` 200 和 `{"status":"ok"}`；`/`、嵌套前端路由回 `index.html`；静态文件原样返回；`/api` 和 `/api/不存在` 404 JSON；`web_dist=None` 时 `/` 404；四种不合格的构建目录在创建时按契约报错；另加 `/api` 下接口自己抛的 404 不回 `index.html`（r1）。
    6. 导出确定：通过。两次导出逐字节相同的测试；`make api-types` 之后过期检查通过；违规试验里改了 schema 不重新生成，`[7/11]` 失败并提示 `make api-types`。
    7. 前端：通过。成功显示"后端正常"、失败显示 `Alert`；注入的 `fetch` 收到相对路径 `/api/health`。
    8. 违规会失败：通过。每种都失败在对应的那一步（按规则名匹配），去掉后恢复全绿；"不能失败"的三种都全绿。过期检查的"加字段"按原话做时会先在 pytest 失败（加字段改变了接口返回，这是对的），所以探针拆成 (a) 只改 schema 的 `make check` 和 (b) 加字段直接跑过期检查目标，两项都通过。
    9. 钩子：通过。前端 `console.log` 违规提交被拒、HEAD 没变，去掉后提交成功；D2 的三种情况照旧。钩子没改。
    10. 能演示：通过。沙箱外 `vite build`，`uvicorn --factory` 在 `127.0.0.1:8600`，`curl` 首页拿到 `index.html`、`/api/health` 拿到 JSON，无头 Chrome 显示"后端正常"（截图在 assets）。工单写的是"浏览器打开"，这里用的是无头 Chrome 截图。
    11. 不留痕迹：通过。每次跑 `make check` 前后 `git status` 都相同。
    12. 文件归属与契约：通过。工作目录只动了 `src/`、`tests/` 和允许表里的文件；主仓库目录规划文件以外只有负责人自己的导读文件；运行日志没碰两个旧项目，安装和联网的 grep 没有命中；先红后绿每个测试都有单独运行，先绿的都有原因；Standards 轴的硬问题（404 回退）在 r1 修好。
  - **风险**：
    - starlette 1.9.0 导入 `TestClient` 时报 `StarletteDeprecationWarning`（建议改用 `httpx2`）。现在只是警告；以后升级 starlette 时要处理，可能要申请 `httpx2`。
    - 实现派工要开沙箱网络权限（N1）。安全靠提示和评审时的日志 grep，这张票三轮日志都没有命中。
    - `/api/{unknown:path}` 兜底收了所有方法，所以 `POST /api/health` 回 404，不是 405。等接口变多、统一异常处理那张票（04）时再看。
    - 前端包 576 KB，`vite build` 提示超过 500 KB（antd 整包）。按路由拆包本来就不在本票，留给 M1。
    - `node_modules` 检查在 `[7/11]` 标题之前失败，提示文字是对的，但看不出属于哪一步。
    - 判断题没改：测试 helper 有重复；`useHealth` 用 WeakMap 按客户端区分缓存（只为测试注入）；Makefile 两种调用前端工具的写法混用。
    - pnpm 的 store 按文件系统区分：探针工作目录在 tmpfs 上时要 `--store-dir`。主仓库目录不受影响。
  - **和工单的偏差**：`@types/node` 实测不需要，没装（用 `skipLibCheck: true`）；router、jsdoc 比最新版低一个补丁号（pnpm 11 的发布时间门槛）；派工 B 中途因沙箱阻塞续接了三次（B2 被 Codex 拒绝、B3 按 N1 打开网络），都不算打回；验收第 8 条过期检查按上面拆成两项；新增测试比骨架清单多 7 个（`/api` 各方法、自带 `404.html` 不覆盖 SPA、帮助参数不掩盖未知参数、W3 的回归断言、G3 的两种失败、r1 的回归）。
  - **合并后（第 15、16 步，主会话）**：主仓库目录 `uv sync --frozen` 加 `src/web/` 里 `pnpm install --frozen-lockfile`；按实测补全 `CODING_STANDARDS.md` 3.1（W3）、3.5（TSDoc 规则表，见骨架摘要第 4 块和 G2）、8.1（前端豁免检查）、10.1 改成〔机〕。
  - **下一张**：M0 第 3 张「配置、状态目录与运行日志」。
- 2026-10-23，主会话复核后合并（负责人事先授权："just merge it"，条件是评审通过）。
  - 复核：工作目录 `make check` 十一步全绿（约 10 秒，pytest 101 passed，Vitest 19 passed）；工作目录干净；`src/`、`tests/` 以外的改动只有 `Makefile`、`scripts/check_contracts.py`（都在允许表里），锁文件没变；B3、r1 运行日志的安装和联网 grep 没有命中；违规试验 r1-done 34/34。
  - 3.7：暂存区空 → `git merge --no-ff --no-commit` → `uv sync --frozen`、`pnpm install --frozen-lockfile` → `git commit`，钩子在合并结果上跑 `make check` 全绿 → `f925329 合并：Web 骨架与前端检查链`。
  - 收尾：工作目录、分支 `t/m0-02-web-skeleton-frontend-check-chain`、快照 `refs/rdp/m0-02/*` 已删除。Status 改成 `done`。
  - 待办（主会话）：第 16 步补 CODING_STANDARDS 前端部分（3.1、3.5、8.1、10.1）；`codex-workflow.md` 加"前端依赖提交前先补 `.gitignore` 的 `node_modules/`"。
