评审打回第 1 轮（小）。执行线在探针目录复跑：`make check` 全绿（pytest 1946 passed / 0 skipped，Vitest 250），三轮日志审计 0 条；变异抽查 Python 12/12、脚本 7/7 被抓。临时 HOME 冒烟也通过（迁移前 web 拒绝启动、migrate、create-admin、web+worker、登录、/api/version、worker 在线、无访问日志、SIGTERM 0.5 秒内退出）。只改下面三条，其余不要动。

动手前用绝对路径重读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。第 1 条先写会失败的测试、单独运行看到红，再实现（$tdd）。

1. **worker 启停不写日志**（冒烟实测：`rdp worker --no-stderr` 起来、SIGTERM 停下，`worker.log` 只有一行"读取配置"）。手册"排查 worker 没在运行"要靠日志看它什么时候起、什么时候停、为什么停。要求：worker 入口在开始运行时写一条 INFO（平台版本、pid、实例号或等价标识），结束时写一条（退出码及其含义：正常停止、锁被占、失败等；失败时 ERROR）。Web 入口在 uvicorn 启动前写一条 INFO 带平台版本，结束时写一条带退出码。只用现有 logger，不改日志格式。测试断言日志内容和级别。
2. **`rdp --help` 太简**：子命令列表没有说明，`status` 的三个选项没有帮助文字。给每个子命令加 `help=`/`description=`（一句话说做什么），`status` 三个选项写清检查什么、各退出码含义（0、3 等，与 `status` 契约一致）。测试至少断言 `rdp --help` 列出每个子命令的说明、`rdp status --help` 写明退出码。
3. `src/rdp/api/production.py` 约 106 行 `UvicornRunner` Protocol 方法体的 `raise NotImplementedError` 改成 `...`（Protocol 声明，不是骨架残留）。

边界和交付同前几轮（只改 `src/`、`tests/`；不安装、不联网；不碰 `/mnt`、真实 systemd/配置目录；不 `git add`）。30 分钟内交付；最后跑一次 `make check`（0 skipped）。最终回复五块：1 改动清单；2 `make check` 末尾原样输出及前后 `git status --porcelain --untracked-files=all`；3 契约补充/docstring 改动；4 拿不准的地方；5 先红后绿。
