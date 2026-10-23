# 0012 环境事实更新：沙箱的 socket 限制与实现派工的联网授权

> 类别：输入（只追加，不改写）。记录日期：2026-10-23。
> 本文补充 0006、0009、0011，来自 M0 第 2 张「Web 骨架与前端检查链」派工 B 的阻塞。复核记录在该工单的 Comments 里。

## 事实

- **`workspace-write` 沙箱禁止 socket 的发送调用**（codex-cli 0.163.0，seccomp）：
  - `socket.socketpair()` 能建，但 `send` 报 `PermissionError: [Errno 1] Operation not permitted`。
  - 对同一个 socket 用 `os.write`、`recv` 都正常，管道也正常。
- **后果：沙箱里测不了 FastAPI**。asyncio 从别的线程唤醒事件循环（`call_soon_threadsafe`），靠的是往 socketpair 里 `send` 一个字节。Starlette 把同步接口函数、`StaticFiles` 的文件读取都放进线程池，所以 `TestClient` 和 `httpx.ASGITransport` 都会一直挂住。不带线程的 `asyncio.run` 正常。0011 记的"`pnpm build` 报 Failed to create stream fd""本地 HTTP 服务起不来"，是同一个限制。
- **能解决的设置**：`-c 'sandbox_workspace_write.network_access=true'`。打开后 `send` 正常，`TestClient` 测试能跑完；但 Codex 的命令也真的能上网了（`curl https://pypi.org/` 返回 200）。
- **试过但没用的**：`network.allow_local_binding=true`、`sandbox_workspace_write.allow_local_binding=true`，打开后 `send` 仍然被挡。二进制里的 `allow_unix_sockets` 属于网络代理的按路径放行，管不到 `socketpair`。
- **测试里绕开的做法被 Codex 拒绝**：在测试进程里把 `_write_to_self` 的 `send` 换成 `os.write`，技术上能用，但 Codex 认为这是在绕过沙箱的安全控制，拒绝执行。主会话也认同这个判断，不再走这条路。

## 负责人的决定（2026-10-23，N1）

- **实现票的派工**（派工 A、派工 B、修复轮）都加上 `-c 'sandbox_workspace_write.network_access=true'`。这是沙箱的正式设置，由负责人明确授权，不算 CLAUDE.md 说的"绕过沙箱的参数"。
- 沙箱能写的范围不变，仍然只有该票的工作目录。
- **只读的任务不联网**：调研、盘点这类非代码任务仍然按 `codex-workflow.md` 第 8 节用 `-s read-only`。
- **三道防线**：
  1. 派工提示的"边界"里写明不安装、不联网。
  2. 评审时查运行日志里的命令：出现 `pip`、`uv add`/`uv pip`、`pnpm add`/`pnpm install`（不带 `--frozen-lockfile`）、`npm`、`npx`、`curl`、`wget`、`git clone`、`git fetch` 这类安装或联网的命令，就整轮打回。
  3. 评审时照常核对依赖表和锁文件有没有变化。
