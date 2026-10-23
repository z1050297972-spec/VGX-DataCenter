派工 A1 已通过评审。Claude 已经装好后端和前端依赖，并在工单分支上做了依赖提交 `261a373`（`依赖：fastapi、uvicorn 和前端依赖（Web 骨架与前端检查链）`）。这个提交里有你在 A1 交的 `src/web/package.json`（`pnpm add` 已把依赖表写进去）、`src/web/pnpm-lock.yaml`、`pyproject.toml` 的依赖表和 `uv.lock`。`src/web/node_modules/` 已装好，但 `.gitignore` 里还没有它，所以现在 `git status` 会显示 `?? src/web/node_modules/`，这是你这一次要加的。除此之外工作目录是干净的。

现在做**派工 A2：契约骨架**。交付见工单「派工分段」的 A2，要求见工单「范围」和「验收」。工单在 A1 之后追加了 Comments（装依赖时核实的版本和实测），动手前重读一遍。**规划文件一律用绝对路径读主仓库目录里的版本**（A1 时你读的是工作目录里的副本，那份停在开分支的那一刻，缺了后来的 Comments）：
- /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/02-web-skeleton-frontend-check-chain.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md（尤其 3.1、3.5、8.1、8.2、第 10 条）
- /home/shawn/桌面/robot-data-platform/AGENTS.md、/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/spec.md（S3 端口）、/home/shawn/桌面/robot-data-platform/docs/adr/ 下的 0001、0002、0005
- 前端检查链的来源：/home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/03-tech-stack-standards.md 的 Answer

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和完整的契约文档写全：Python 是六项 docstring（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条），函数体只写 `raise NotImplementedError`；TypeScript 是 TSDoc 六项（CODING_STANDARDS 3.5），函数体只写 `throw new Error("未实现")`。
2. 测试清单写成跳过的测试：pytest 用 `pytest.skip`，测试的 docstring 写明它验证哪条契约行为；Vitest 用 `it.skip`，`it(...)` 的标题写明它验证哪条契约行为。
3. `make check` 跑到全绿（这一次十步，过期检查未接，见下）。

本次交付：
- **检查配置**：`src/web/` 下的 `tsconfig*.json`、`eslint.config.*`、`vite.config.ts`（Vitest 配置写在这里，不另建文件）、Prettier 配置和 `.prettierignore`；按工单「范围 / 检查链」配齐 TypeScript、ESLint、TSDoc、豁免、生成文件的忽略。
- **Makefile**：后端六步不动，后面接前端步骤，每步开头输出 `[n/11] 步骤名`；新增 `make api-types`；`make fmt` 加上 `prettier --write` 和 `eslint --fix`。**这一次 OpenAPI 过期检查那一步先不接**（导出函数还是桩），在 Makefile 里用注释标明，派工 B 接上；其余四步照常跑。步骤编号按最终的十一步写，B 接上过期检查时不用改编号。把 A1 里说的"`package.json` 的 scripts 不含检查命令、检查以 Makefile 为准"的理由写进 Makefile 注释。
- **`.gitignore`**：追加 `node_modules/` 这类前端产物（`dist/` 已经有了）。
- **`pyproject.toml`**：只改 `[tool.importlinter]`：加 forbidden 合约（`rdp.infra` 不 import `fastapi`、`starlette`、`uvicorn`，领域层的位置用注释标出），`include_external_packages = true`。FastAPI 带来的 ruff、basedpyright 调整如果需要，每条写理由。依赖表不动。
- **`scripts/check_contracts.py`**：只按 W3 改 `check_file` 的 docstring（`test_` 开头的函数只在文件位于仓库根的 `tests/` 下时跳过；`src/`、`scripts/` 下的照常查六项）。现有实现这一次不改，B 再改；新行为的测试写成跳过的测试。
- **后端契约骨架**：`rdp.api` 下的 `create_app(web_dist: Path | None) -> FastAPI` 和 `python -m rdp.api.openapi_export <输出路径>`，契约按工单「范围 / 后端」写，`web_dist` 不存在或缺 `index.html` 时报什么错、什么时候报，由你在契约里定下来。测试用 `fastapi.testclient.TestClient`（httpx 已装），静态目录用 `tmp_path`。
- **前端契约骨架**：`src/web/` 下的入口（`index.html`、`src/main.tsx` 之类）、TanStack Router 代码式路由树（一个根路由 `/`）、`src/api/` 下的 openapi-fetch 客户端工厂（`fetch` 实现可以注入，测试不碰全局 `fetch`）、一个 hook（例如 `useHealth`）、一个页面组件，以及对应的 `*.test.ts(x)`（和源码放在一起）。
  - **`openapi.json` 和 `schema.d.ts` 在 A2 怎么办**：导出函数这时是桩，生成不了真的。为了让客户端工厂、hook 的类型能写出来，这一次你可以按工单定的接口（`GET /api/health` 返回 `{"status": "ok"}`，pydantic 响应模型）手写一份 `src/web/src/api/openapi.json` 当作接口契约的草稿，再用 `src/web/node_modules/.bin/openapi-typescript` 从它生成 `schema.d.ts`（离线可以跑）。派工 B 接上过期检查时，两个文件都用真正的导出重新生成，评审会比对差异。`schema.d.ts` 不手改。

环境事实（Claude 装依赖时核实的）：
- 后端：fastapi 0.161.1（带 starlette 1.9.0）、pydantic 2.14.1、uvicorn 0.54.0；开发组 httpx 0.28.1。其余同第 1 张：`.venv/bin/python` 是 CPython 3.12.15，ruff 0.17.1、basedpyright 1.40.2、import-linter 2.15、pytest 9.1.1。
- 前端（`src/web/node_modules/.bin/` 下）：Node v22.23.2；typescript 5.9.3（T2）、eslint 10.13.0、typescript-eslint 8.72.0、eslint-plugin-react-hooks 7.1.1、eslint-plugin-jsdoc **65.4.0**、@eslint-community/eslint-plugin-eslint-comments 4.8.1、prettier 3.9.10、vitest 5.0.5、jsdom 30.1.3、@testing-library/react 16.3.3、@testing-library/dom 10.4.2、vite 8.3.5、@vitejs/plugin-react 6.1.2、openapi-typescript 7.13.0；运行时 react / react-dom 19.3.1、@types/react / @types/react-dom 19.3.0、@tanstack/react-router **1.170.45**、@tanstack/react-query 5.104.5、antd 6.6.7、openapi-fetch 0.17.0。版本以 `src/web/pnpm-lock.yaml` 为准。
- **没有装 `@types/node`**（T1：实测不需要就不装）。Claude 实测过：`skipLibCheck: true` 时，tsc 5.9.3 检查一份用 `vitest/config` 的 `defineConfig`、react 插件、`/api` 转发、jsdom 的 `vite.config.ts` 能通过；`false` 时报依赖自带的 `.d.ts` 缺 `node:util` 等。所以用 `skipLibCheck: true`，在 tsconfig 里写理由。确实要用 Node 的类型时停下，写依赖申请。
- **没有装 `jiti`**：ESLint 10 读 `eslint.config.ts` 要它，所以 ESLint 配置用 `.js`（或 `.mjs`）。
- 也没有装 `@eslint/js`、`globals`、`@testing-library/jest-dom`、`@testing-library/user-event`。ESLint 的核心规则（`complexity`、`max-params`、`no-console` 等）不用 `@eslint/js` 也能直接在 `rules` 里开。要用其中任何一个就停下，写依赖申请。
- 依赖树里没有包带安装脚本，没有 `pnpm-workspace.yaml`，也不需要。

要特别注意的地方：
- **`make check` 里不出现 `pnpm`**（pnpm 可能联网或写 store）。前端工具一律从 `src/web/node_modules/.bin/` 调用。`node_modules` 不存在时，第一个前端步骤之前就失败，提示"先在 src/web 里运行 pnpm install --frozen-lockfile"，不自动安装。
- **Vitest 在沙箱里**：沙箱不能建 socket（docs/brief/0011），Vitest 默认的 `forks` 池要用子进程通信，能不能跑没核实过。起不来时先试 `pool: "threads"`；还不行就停下，在最终回复里原样贴出报错，不要把 Vitest 从 `make check` 里拿掉（验收第 4 条）。tsc、ESLint 同理：跑不起来就原样报告。
- **TSDoc 的强制**：`@throws`、`@sideEffects`、`@timeSemantics` 必须出现、不能为空。用 eslint-plugin-jsdoc 65.4.0 实测能用哪条规则做到（例如 `jsdoc/no-missing-syntax`、`jsdoc/require-throws` 等），在最终回复里**逐项**写明：首行职责、`@param`、`@returns`、`@throws`、`@sideEffects`、`@timeSemantics` 各靠哪条规则，"必须出现"和"不能为空"分开写。插件做不到的项如实报告，不要自己写脚本补。`@throws 无` 不能报错。
- **豁免**（8.1）：`reportUnusedDisableDirectives: "error"`；不带规则名、不带 `-- 理由` 的 `eslint-disable` 用 eslint-comments 插件的 `no-unlimited-disable`、`require-description` 拦；`@ts-ignore` 和不带说明的 `@ts-expect-error` 用 `@typescript-eslint/ban-ts-comment` 拦。客户端工厂默认取全局 `fetch` 的那一处，用带理由的单条豁免。
- **不留痕迹**：跑完 `make check` 以后，`git status --porcelain --untracked-files=all` 要和跑之前相同（验收第 11 条）：tsc 不产出文件（包括 `.tsbuildinfo`），ESLint、Prettier 不在仓库里留缓存；Vite、Vitest 的缓存只能落在 `node_modules/` 下。
- **违规试验由 Claude 在探针工作目录里做**（验收第 8 条，过期检查除外），按规则名匹配。你的配置要让每种违规失败在对应的那一步，"不能失败"的几种也不能失败。你可以用临时文件自己先试，试完删掉，工作目录里不留试验文件。
- `make fmt`、`make api-types` 也要能跑（`api-types` 这一次可以因为导出是桩而失败，在最终回复里说明；B 里必须能跑）。
- 钩子 `.githooks/pre-commit` 预计不用改；你写不了 `.git`，没法用真提交试，真提交的试验由 Claude 做。
- 不要写 `.git/info/exclude`（所有工作目录共用）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`Makefile`（加前端五步、`make api-types`，`make fmt` 加前端；后端六步不动）、`pyproject.toml`（只改 `[tool.importlinter]`，以及 FastAPI 带来的 ruff、basedpyright 配置调整，每条写理由；依赖表不动）、`scripts/check_contracts.py`（只改 `test_*` 的跳过范围和对应 docstring）、`src/web/package.json`（只改 `name`、`private`、`type`、`scripts`；依赖表不动）、`src/web/tsconfig*.json`、`src/web/eslint.config.*`、`src/web/vite.config.*`、Prettier 配置和 `.prettierignore`（新建）、`.gitignore`（只追加前端产物）、`.githooks/pre-commit`（只在实测必须改时改，改了在最终回复里说明）。`pnpm-lock.yaml`、`uv.lock`、`pnpm-workspace.yaml` 不改也不建。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 沙箱不能联网，不要尝试安装任何东西（不跑 `pnpm install`、`pnpm add`、`uv add`、`npx`）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分六块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出，包括 tsc、ESLint、Vitest 三步的输出（Vitest 那步要能看出跳过的测试数）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
5. 检查配置的要点：tsconfig 的选项；ESLint 开了哪些规则集和单条规则、阈值多少、关掉或放宽了什么（每条的理由）；Prettier 的设置；忽略了哪些文件；import-linter 的新合约；ruff、basedpyright 有没有调整。
6. TSDoc 各项靠哪条 jsdoc 规则（"必须出现""不能为空"分开写），做不到的项；Vitest 用的是哪个池、在沙箱里是否真的跑起来了。
