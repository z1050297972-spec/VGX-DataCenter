评审打回第 2 轮（一条缺陷）。第 1 轮三条都改到了，执行线已把它提交为 `b7c9f4c`（`实现：运维入口与 systemd 服务`），工作目录是干净的。执行线随后做了验收 5 的从零安装演练（临时 HOME、`install.sh --no-systemd`）：安装、迁移、建管理员、登录、建成员、成员改口令、提交示例作业并完成、操作/登录日志、存储根两块盘在线、页脚版本 `0.1.0 (b7c9f4c)` 全部通过。worker 收到 SIGTERM 后退出码 0，`worker.log` 有开始和结束两行。

**缺陷（先红后绿）**：`rdp web` 收到 SIGTERM 后进程退出码是 **143**，`web.log` 里没有 "Web结束运行" 这一行。uvicorn 优雅关闭是完成了的（有 Shutting down … Finished server process），但 uvicorn 0.54 的 `Server.capture_signals` 在 serve 结束时会 `signal.raise_signal(captured_signal)` 把捕获的信号重新抛出（`.venv/lib/python3.12/site-packages/uvicorn/server.py` 约 348 行），默认处理器直接结束进程。所以 `start_web` 在运行器返回之后的收尾（结束日志、等报错写入线程排空、释放引擎，第 5 张 B3）在 systemd 停服务这条生产路径上**根本没有执行**。现有测试注入了假的运行器，没覆盖到。

要求：
1. 生产的 uvicorn 运行函数在优雅关闭后不能让重新抛出的信号结束进程，让控制权回到 `start_web` 完成收尾。做法你定（例如用 `uvicorn.Config`/`Server` 自行运行并处理 capture_signals 的重抛，或在运行期间临时接管、结束后恢复），写清理由；不改 uvicorn 包本身，不加依赖。SIGTERM 和 SIGINT（前台 Ctrl+C）都要走完整收尾。正常停止的退出码按 `start_web` 契约（正常 0）；如果需要对 systemd 区分，在第 4 块说明。
2. 加一个真实进程测试：在临时 HOME 里写配置（`127.0.0.1`、测试里先绑定端口 0 取一个空闲端口）、迁移，`subprocess` 起 `python -m rdp web --no-stderr`，等健康接口就绪后发 SIGTERM，断言：有上限的时间内退出、退出码 0、`web.log` 有开始和结束两行。所有等待有上限，结束时确保子进程被收掉（超时就 kill 并让测试失败）。不占 8600，不碰真实 HOME。worker 同样补一个真实进程的 SIGTERM 测试（退出码 0、两行日志），如已有等价测试说明是哪一个。
3. 先单独运行新测试看到红（143 / 缺结束行），再改实现。

其他不动。边界和交付同前几轮（只改 `src/`、`tests/`；不安装、不联网；不碰 `/mnt`、真实 systemd 与配置目录；不 `git add`、不提交）。40 分钟内交付；最后跑一次 `make check`（0 skipped）。最终回复五块：1 改动清单；2 `make check` 末尾原样输出及前后 `git status --porcelain --untracked-files=all`；3 契约补充/docstring 改动；4 拿不准的地方；5 先红后绿。
