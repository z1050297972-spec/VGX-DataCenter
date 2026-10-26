骨架已获批，契约提交是 `c2e2898`（`契约：作业框架与 worker`），内容就是你最后一轮交的骨架。工作目录现在是干净的。

动手前先用绝对路径重读：主仓库目录里的工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/08-job-framework-worker.md（Comments 里负责人的决定 J1–J3 和骨架关卡的回答）、/home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」。

现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（Python 用 `.venv/bin/pytest tests/<文件>::<测试名>`，前端在 `src/web/` 里用 `node_modules/.bin/vitest run <文件> -t "<标题>"`），看到它失败，再写实现让它通过。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因。评审会用变异抽查验证测试能区分对错。
2. 已获批的签名、类型和 docstring 不改。确实要改含义时停下来写进最终回复的契约变更申请；只是措辞、补充说明的，照改并在第 3 块列出。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过（pytest 和 Vitest 都没有 skipped）。

要做的：
- 激活骨架里暂时隔离的部分：作业表、心跳表的 ORM 模型去掉 `__abstract__` 并注册进共用 `MetaData`；迁移 `0004` 从 `pending/` 移进 `versions/`，删掉 `pending/` 目录；操作日志的 `job` 对象类型 CHECK 一起激活；建表 SQL 一致性测试和 `compare_metadata` 测试要覆盖新表和重建后的 `operation_logs`。
- 把 `WorkerStatusBanner` 挂进 `AccountLayout`，所有登录账号的页面顶部都能看到。
- 删掉所有骨架期的说法（"骨架""桩""实现阶段""尚未接线""留待实现"等），只写现在的行为。交付前在本票改过的文件里搜"骨架""提案""派工""桩""实现阶段""留待"，不留。
- 真实子进程的测试（SIGKILL 恢复、忽略 SIGTERM、锁不被继承、超时保锁）：所有等待有上限，子进程和线程在嵌套的 `finally` 里回收，孤儿进程按进程组清掉；测试不依赖本机时区（−06:00），不改全局时区；结束后恢复全局 logging 状态和 contextvars。验收 4 那条测试本身要等约 10 秒，可以接受，但不要再加别的长等待；用测试专用的短间隔参数。
- 前端页面用 antd，类型用生成的 OpenAPI 类型；OpenAPI 有变化用 `make api-types` 重新生成，不手改生成文件。作业页面的 search 参数经真实 router 测（7.1）。
- 演示由执行线在沙箱外做（起 Web 和 worker，真实浏览器里走验收 11），你不用起服务器，也不要建真实的状态目录。

为了不超时：每个测试单独先红后绿，每改完一个文件只跑相关测试文件；最后只跑一次 `make check`。不要用 `make fmt` 改动本票以外的文件。这张票很大：预计 80 分钟内做不完时，停在 `make check` 全绿的位置交检查点（已完成的测试去掉跳过、没做的保留跳过），第 4 块写清还剩哪些测试，执行线会续接。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 import-linter：`rdp.jobs` → `rdp.audit`、`rdp.accounts` 的依赖方向；依赖表和别的段不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已获批契约的含义。其余拿不准的照你的判断做，列进第 4 块。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。列出改了哪些 docstring/TSDoc 的哪几句。
4. 拿不准、需要评审决定的地方；交检查点时写清还剩什么。
5. 先红后绿：每个测试一行（可以按文件分组），写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
