骨架已获批（负责人"全部通过"），契约提交是 `1b2e3ed`（`契约：Web 骨架与前端检查链`）。工作目录现在是干净的。现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding。

先用绝对路径重读主仓库目录里的工单：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/02-web-skeleton-frontend-check-chain.md 。末尾 Comments 里有骨架关卡的摘要和负责人的决定 G1–G3。

1. 每次去掉一个测试的跳过，先单独运行它，看到它失败，再写实现让它通过。
   - pytest：`.venv/bin/pytest <文件>::<测试名>`。
   - Vitest：`cd src/web && node_modules/.bin/vitest run <文件> -t "<it 标题>"`。
   - 去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因（例如前一个测试的实现已经覆盖了它）。
   - 评审会在运行日志里逐个核对"实现前有一次失败的运行"（CODING_STANDARDS 7.10），所以单独运行这一步不要省，也不要把多个测试合在一次运行里先红。
2. 已获批的签名、类型和 docstring/TSDoc 不改，下面"负责人已批准的改动"除外。别处确实要改时停下，在最终回复里写契约变更申请：哪个函数、改什么、为什么。
3. 最后 `make check` 十一步全绿，测试里不留骨架阶段的跳过（`pytest.skip`、`it.skip` 都去掉）。

**负责人已批准的改动（骨架关卡 G1–G3）和评审提醒，一并做：**
- **G1**：`HEALTH_TIMEOUT_MS = 5000`、`HEALTH_STALE_TIME_MS = 1000`，不重试、不轮询、窗口聚焦不刷新，都照契约。只改 `HEALTH_STALE_TIME_MS` 的注释：现在引了 ADR 0001 的"约 1 秒轮询"，但健康检查不轮询，改成写这个数值的真实理由。
- **G2**：没有参数的函数不写 `@param`。ESLint 配置里从 `jsdoc/require-tags` 去掉 `param`（每个真实参数仍由 `jsdoc/require-param` 要求），打开 `jsdoc/check-param-names`；把现有的 `@param 无 - 无参数。` 删掉。
- **G3**：`export_openapi` 改成先写同目录的临时文件，再用 `os.replace` 替换目标（CODING_STANDARDS 2.6，用标准库 `tempfile`）。失败时目标文件保持原样，临时文件删掉。按这个含义改它的 `Side Effects:`（负责人已批准这处契约含义变化，`main` 的 `Side Effects:` 里"失败产物语义同 export_openapi"如有需要也跟着改措辞），`Raises:` 如有变化一并写准。加一个测试：写入或替换失败时，原有的目标文件内容不变，目录里没有留下临时文件。
- **`main.tsx`**：现在模块顶层就调 `mountWeb(...)`，测试一 import 就会挂载。把 `mountWeb` 挪到单独的模块（签名和 TSDoc 不变），`main.tsx` 只剩调用它的一行入口；`main.test.tsx` 改为测那个模块。
- **`router.tsx`**：私有的 `getRootRoute` 去掉，改成 `getParentRoute: () => rootRoute`。
- 5 个骨架桩上的 `// eslint-disable-next-line @typescript-eslint/no-unused-vars -- A2 契约桩…` 豁免在实现后全部删掉（不删的话"多余豁免"那条会报）。
- `.prettierignore` 里 `openapi.json` 旁边"A2 暂为手写草稿"那句注释，在换成真正的导出后改掉。

**本次另外要接上的：**
- **`[7/11]` OpenAPI 过期检查**（工单「范围 / 检查链」）：导出 OpenAPI、用 openapi-typescript 生成类型，都写到临时目录（用完删掉，失败也删），再和入库的 `src/web/src/api/openapi.json`、`schema.d.ts` 逐字节比较；不一致就失败，提示运行 `make api-types`。它放在 `node_modules` 检查之后、`[8/11] tsc` 之前。
- **`make api-types`** 必须能跑，并用它重新生成两个入库文件（替换 A2 的手写草稿）。过期检查和 `make api-types` 用同一套生成命令，免得两边产物不同。生成后立刻再跑一次过期检查，必须通过；同样的代码导出两次逐字节相同（验收第 6 条）。
- **W3**：`scripts/check_contracts.py` 按已改好的 docstring 实现（`test_` 开头的函数只在文件位于仓库根的 `tests/` 下时跳过），`tests/test_contract_scope.py` 的 6 个测试照上面的先红后绿做。实现后 `make check` 的契约检查一步仍要 `问题总数: 0`。
- 验收第 5、7 条是测试要证明的行为：`/api/health` 200 和 `{"status":"ok"}`；`/`、`/datasets/x` 这类前端路由返回 `index.html`；存在的静态文件原样返回；`/api/不存在` 404 JSON；`web_dist` 为 `None` 时 `/` 404；`web_dist` 不合格时按契约报错；页面成功显示"后端正常"、失败显示 `Alert`；请求经注入的 `fetch` 发到相对路径 `/api/health`。
- 静态托管用 `fastapi.staticfiles.StaticFiles`，不直接 import starlette（CODING_STANDARDS 9.2）。测试用 `fastapi.testclient.TestClient`，静态目录用 `tmp_path`。前端测试不碰全局 `fetch`，用注入的替身。
- 跑完 `make check` 以后，`git status --porcelain --untracked-files=all` 要和跑之前相同（验收第 11 条）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`Makefile`（接上 `[7/11]` 过期检查；`make api-types`、`make fmt`；后端六步不动）、`pyproject.toml`（只改 `[tool.importlinter]`，以及 FastAPI 带来的 ruff、basedpyright 配置调整，每条写理由；依赖表不动）、`scripts/check_contracts.py`（只改 `test_*` 的跳过范围和对应 docstring）、`src/web/package.json`（只改 `name`、`private`、`type`、`scripts`；依赖表不动）、`src/web/tsconfig*.json`、`src/web/eslint.config.*`、`src/web/vite.config.*`、Prettier 配置和 `.prettierignore`、`.gitignore`（只追加前端产物）、`.githooks/pre-commit`（只在实测必须改时改，改了在最终回复里说明）。`pnpm-lock.yaml`、`uv.lock`、`pnpm-workspace.yaml` 不改也不建。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。不要写 `.git/info/exclude`。
- 沙箱不能联网，不要尝试安装任何东西（不跑 `pnpm install`、`pnpm add`、`uv add`、`npx`）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分六块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出，包括过期检查、tsc、ESLint、Vitest 几步的输出和 pytest、Vitest 的通过数。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。另外贴出 `make api-types` 之后紧接着过期检查通过的输出。
3. 契约变更申请、依赖申请：没有就写"无"。G3 改了哪几处 docstring，原样贴出改后的 `Side Effects:`、`Raises:`。
4. 拿不准、需要评审决定的地方。
5. 先红后绿：每个测试一行，写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
6. 检查配置的变化：G2 之后 TSDoc 各项靠哪条规则（"必须出现""不能为空"分开写）；过期检查的实现方式（临时目录、比较方式、失败提示）。
