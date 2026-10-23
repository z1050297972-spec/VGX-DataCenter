这是派工 B 的继续（不是打回轮）。

负责人已经正式打开了这次派工的沙箱网络权限（`sandbox_workspace_write.network_access=true`，见 /home/shawn/桌面/robot-data-platform/docs/brief/0012-环境事实更新-沙箱socket与联网授权.md）。现在沙箱里 socket 能正常发送，`TestClient`、Starlette 的线程池和 `StaticFiles` 都能在沙箱里跑。上一轮提到的在测试里改 asyncio 唤醒方式的做法已经作废：**不要在 `tests/conftest.py` 或别处打任何 `send`/`write` 相关的补丁**，测试照常写。

工作区里还是你在派工 B 第一次留下的三处改动（`src/rdp/api/__init__.py`、`src/rdp/api/health.py`、`tests/test_web_app.py`），接着用。

先用绝对路径重读：
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/02-web-skeleton-frontend-check-chain.md（末尾 Comments 里有骨架关卡的决定 G1–G3 和这次阻塞的经过）
- 上一份提示 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/02-web-skeleton-frontend-check-chain/prompt-B.md

然后照 prompt-B.md 从停下的地方继续，要求全部照旧：
1. 先让 `test_health_response` 变绿（它在实现之前已经红过一次，日志里有）。
2. 剩下的每个测试逐个先红后绿：去掉一个跳过，先单独运行看到它失败，再写实现让它通过（CODING_STANDARDS 7.10，评审会在运行日志里逐个核对）。
   - pytest 一律套 `timeout`，例如 `timeout 120s .venv/bin/pytest <文件>::<测试名>`；`make check` 也套 `timeout 600s`。交付前确认没有挂住的进程（`pgrep -af pytest` 为空）。
   - Vitest：`cd src/web && timeout 120s node_modules/.bin/vitest run <文件> -t "<it 标题>"`。
3. 做完 G1–G3 和评审提醒（`main.tsx` 拆开、`getRootRoute` 改成箭头函数、删掉 5 个桩上的豁免、改 `.prettierignore` 里"手写草稿"那句），G3 的新测试同样先红后绿。
4. 接上 `[7/11]` 过期检查和 `make api-types`，用真正的导出重新生成 `openapi.json` 和 `schema.d.ts`；实现 W3。
5. 最后 `make check` 十一步在沙箱里全绿，跑完 `git status --porcelain --untracked-files=all` 和跑之前相同，测试里不留骨架阶段的跳过。

starlette 1.9.0 导入 `TestClient` 时会报 `StarletteDeprecationWarning`（建议改用 `httpx2`）。现在只是警告，不要为它改依赖或配置，在最终回复第 4 块里提一句。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`Makefile`（接上 `[7/11]` 过期检查；`make api-types`、`make fmt`；后端六步不动）、`pyproject.toml`（只改 `[tool.importlinter]`，以及 FastAPI 带来的 ruff、basedpyright 配置调整，每条写理由；依赖表不动）、`scripts/check_contracts.py`（只改 `test_*` 的跳过范围和对应 docstring）、`src/web/package.json`（只改 `name`、`private`、`type`、`scripts`；依赖表不动）、`src/web/tsconfig*.json`、`src/web/eslint.config.*`、`src/web/vite.config.*`、Prettier 配置和 `.prettierignore`、`.gitignore`（只追加前端产物）、`.githooks/pre-commit`（只在实测必须改时改，改了在最终回复里说明）。`pnpm-lock.yaml`、`uv.lock`、`pnpm-workspace.yaml` 不改也不建。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复：同 prompt-B.md 的六块。第 5 块"先红后绿"每个测试一行，包括 `test_health_response` 和 G3 的新测试。
