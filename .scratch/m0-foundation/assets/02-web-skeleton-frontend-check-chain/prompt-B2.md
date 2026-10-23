这是派工 B 的继续（不是打回轮）。上一次你停在 `test_health_response`：`TestClient.__enter__` 在沙箱里挂住。原因已经查清，负责人选了"只在测试里绕开，沙箱不放开"。工作区里你上一次留下的三处改动（`src/rdp/api/__init__.py`、`src/rdp/api/health.py`、`tests/test_web_app.py`）都还在，接着用。

先用绝对路径重读工单末尾的 Comments：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/02-web-skeleton-frontend-check-chain.md （"派工 B 被沙箱挡住"和"负责人选 B"两条）。

**原因**：沙箱的 seccomp 禁止 socket 的 send 系列调用，`write(2)` 不受限。asyncio 从别的线程唤醒事件循环时，`asyncio.selector_events.BaseSelectorEventLoop._write_to_self` 用 `csock.send(b"\0")` 往 self-pipe 的 socketpair 里写一个字节，于是 `run_in_executor`、Starlette 的线程池（同步接口、`StaticFiles`）和 `TestClient` 都会挂住。主会话在同一个沙箱里验证过：把这一句换成 `os.write(csock.fileno(), b"\0")` 以后，`run_in_executor` 返回，`TestClient` 调同步接口、`StaticFiles` 都返回 200；不换就超时。

**第 1 步：测试里的权宜补丁**
1. 在 `tests/conftest.py`（新建）里，模块导入时就把 `BaseSelectorEventLoop._write_to_self` 换成等价的版本：保留 `csock is None` 时直接返回、`except OSError: pass`（原版在 debug 时记一条日志，可以照留），只把 `csock.send(b"\0")` 换成 `os.write(csock.fileno(), b"\0")`。
2. 按 AGENTS.md 规则 5 写中文注释，写明：这是权宜做法；为什么（沙箱的 seccomp 禁止 socket 的 send 系列调用，asyncio 的跨线程唤醒用的是 `socket.send`，所以 Starlette 的线程池和 `TestClient` 会挂住；`write(2)` 不受限）；什么时候可以去掉（Codex 沙箱放开本进程内的 socket 发送，或者 asyncio 改了唤醒方式）；只在测试进程里生效，生产代码不受影响（生产不在沙箱里跑）。
3. 补丁只放在 `tests/` 下，`src/` 里不要有任何相关代码。basedpyright 对私有属性的报错用带理由的单条豁免（`# pyright: ignore[<规则名>]  # 理由：…`）。
4. 加一个测试记录这条契约：打了补丁以后，`asyncio.run` 里 `await loop.run_in_executor(None, …)` 在一个很短的超时内（例如 `asyncio.wait_for` 5 秒）返回预期值。这个测试同样先单独跑一次：在补丁写好之前先写测试，看到它失败（超时或挂住时用 `timeout 20s .venv/bin/pytest …` 跑，免得卡死），再写补丁让它通过。
5. 跑 pytest 时一律套 `timeout`（例如 `timeout 120s`），挂住的进程交付前确认已经结束（`pgrep -af pytest` 为空）。

**第 2 步：从停下的地方继续派工 B**
上一份提示 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/02-web-skeleton-frontend-check-chain/prompt-B.md 的要求全部照旧：剩下的每个测试逐个先红后绿（单独运行、在日志里看得到），G1–G3，`main.tsx` 拆开、`getRootRoute` 改成箭头函数，删掉 5 个桩上的豁免，接上 `[7/11]` 过期检查和 `make api-types`，用真正的导出重新生成 `openapi.json` 和 `schema.d.ts`，实现 W3。最后 `make check` 十一步在沙箱里全绿，跑完 `git status` 不变。

依赖不动：starlette 1.9.0 导入 `TestClient` 时会报 `StarletteDeprecationWarning`（建议改用 `httpx2`），现在只是警告，不要为它改依赖或配置；在最终回复第 4 块里提一句它在输出里的样子。

边界：同 prompt-B.md 的"边界"一节（只改 `src/`、`tests/` 和本票允许的受保护文件；不 `git add`、不提交；不读两个旧项目、不碰 `/mnt`；不联网、不安装；`/tmp` 里的试验文件交付前删掉）。

最终回复：同 prompt-B.md 的六块。第 5 块"先红后绿"包括上一次的 `test_health_response` 和这次新加的补丁测试。
