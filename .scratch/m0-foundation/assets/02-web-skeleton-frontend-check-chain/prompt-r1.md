评审发现下面的问题，逐条修复，别处不动。已获批的签名、类型和 docstring/TSDoc 不改。沙箱的网络权限照旧开着（负责人授权，见 docs/brief/0012），测试照常写，不打任何 `send`/`write` 补丁。pytest 一律套 `timeout`（例如 `timeout 120s`），`make check` 套 `timeout 600s`，交付前 `pgrep -af pytest` 为空。

1. 问题：SPA 回退接管了所有 404，不看路径。现在 `/api` 下的未知路径由兜底路由直接回 JSON，所以没暴露；但以后任何 `/api` 的 GET 接口抛 `HTTPException(404)`，都会拿到 `index.html` 和 200，违反 `create_app` 的 `Returns:`（"`/api/` 下……绝不返回 index.html"）。位置：`src/rdp/api/__init__.py` 的 `_spa_fallback` 和 `app.add_exception_handler(404, _spa_fallback)`。期望：只有路径不在 `/api` 下（既不是 `/api`，也不以 `/api/` 开头）、并且方法是 GET 的 404 才回 `index.html`；`/api` 下的 404 一律原样回 JSON，保留原来的 `detail`。加一个测试：测试里给 `create_app(<临时构建目录>)` 返回的应用再加一个 GET `/api/...` 接口，让它抛 `HTTPException(404, detail=…)`，断言拿到 404 和那个 JSON，不是 `index.html`。这个测试先单独跑一次看到它失败，再改实现让它通过。
2. 问题：非 GET 的非 `/api` 路径，现在回的是"API 不存在"的那个处理函数，名不副实。位置：同上。期望：改成名字和注释都说得清楚的通用 404 JSON，或者原样回 StaticFiles 的 404；行为照契约"非 GET 请求不使用 SPA 回退"。现有测试照样通过。
3. 问题：`# noqa: PTH105`。位置：`src/rdp/api/openapi_export.py`。期望：用 `Path.replace`（底层就是 `os.replace`，G3 的语义不变），删掉这条豁免；docstring 里的 `os.replace` 字样保留不改。
4. 问题：可以消掉的 `# pyright: ignore[reportUnknownMemberType]`，以及没用的 `tmp_path` 参数。位置：`tests/test_web_app.py` 的 `test_health_response`（第 27 行一带）。期望：改用文件里已有的 `_request()` 辅助函数，删掉豁免和多余参数。
5. 问题：`src/web/src/router.test.tsx` 用 `router.update(...)` 改了模块单例 `router`，测试结束后没有恢复，测试之间可能互相影响（CODING_STANDARDS 7.5）。期望：测试结束后恢复原状，或者在测试里用同一棵路由树新建一个独立的 router 来测。
6. 问题：几处小问题。
   - `create_app` 里 `web_dist` 已经 resolve 过，判断入口越界时又 `web_dist.resolve()` 一次：去掉重复。
   - "禁用 StaticFiles 的 404.html 与目录首页优先逻辑"这句注释，说的其实是 `StaticFiles(html=False)` 的默认行为：按实际写准。
   - `src/web/.prettierignore` 里 `openapi.json` 有两行重叠的理由：合成一行。
   - `src/web/src/api/health.ts` 自己用 `AbortController` + `setTimeout` 拼超时，没写为什么不用 `AbortSignal.timeout`（CODING_STANDARDS 9.1）：要么改用 `AbortSignal.timeout`（超时测试照样要能用假时钟验证），要么在注释里写明为什么不用。

修完后 `make check` 十一步全绿，跑完 `git status --porcelain --untracked-files=all` 和跑之前相同。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`Makefile`、`pyproject.toml`（只改 `[tool.importlinter]` 和 FastAPI 带来的 ruff、basedpyright 配置调整）、`scripts/check_contracts.py`（只改 `test_*` 的跳过范围和对应 docstring）、`src/web/package.json`（只改 `name`、`private`、`type`、`scripts`）、`src/web/tsconfig*.json`、`src/web/eslint.config.*`、`src/web/vite.config.*`、Prettier 配置和 `.prettierignore`、`.gitignore`（只追加前端产物）、`.githooks/pre-commit`（只在实测必须改时改）。这一轮预计只需要动 `src/`、`tests/` 和 `.prettierignore`。`pnpm-lock.yaml`、`uv.lock`、`pnpm-workspace.yaml` 不改也不建。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复：逐条写处理结果；第 1 条新测试的先红后绿（第一次运行的失败原因）；`make check` 最后一次运行的命令和末尾输出，原样贴出。
