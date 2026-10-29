骨架已获批，契约提交是 `22bdb4d`（`契约：运维入口与 systemd 服务`），内容就是你交的骨架。工作目录现在是干净的。

负责人对你第 3、4 块的决定：
- 第 3 块的只加参数/字段全部认可：`create_app(platform_version=...)`、`run_worker(log_time=...)`、`ExecutorDependencies.platform_version`、`JobRecord`/`JobResponse.platform_version`。
- **reset-password 的操作人沿用第 6 张已有的"运维"**（`ActorRef(None, "运维")`），不新增"运维命令"，不改身份校验和数据库约束；工单范围已改。验收 4 按"旧会话失效、下次登录先改口令、一条操作日志、操作人'运维'"测。
- 第 4 块其余设计选择照你的方案：入口在 `rdp.cli`；dist 从包位置推导、构建信息 `rdp-build.json`；`status --active-jobs / --worker-stopped / --check-port`；认证保护的 `/api/version` 和登录后页脚；作业版本单列、恢复领取时更新；worker `TimeoutStopSec=45`、Web 360（理由写在单元注释里）；uvicorn `workers=1`。

动手前先用绝对路径重读：工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/11-ops-entry-systemd.md（含 Comments）、/home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」。

现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（Python 用 `.venv/bin/pytest tests/<文件>::<测试名>`，前端在 `src/web/` 里用 `node_modules/.bin/vitest run <文件> -t "<标题>"`），看到它失败，再写实现让它通过。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因。评审会用变异抽查验证测试能区分对错。
2. 已获批的签名、类型和 docstring 不改。确实要改含义时停下来写进最终回复的契约变更申请；只是措辞、补充说明的，照改并在第 3 块列出。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过（pytest 和 Vitest 都没有 skipped）。

要做的（除测试清单本身外）：
- 激活迁移 `0006`：照第 8、9 张的做法从 `pending/` 移到活动迁移目录、删掉 `pending/`，`version_models.py` 的列并入活动表定义（或说明为什么保留单独文件）。同时更新 `tests/test_jobs_scheduling_migration.py::test_isolated`：骨架里加的"0006 不在活动图"断言激活后会错，改成只断言 0005 的历史事实（不再要求它是 head），head 的断言放进 0006 自己的迁移测试。
- 安装/升级脚本写出可执行逻辑和 `--help`（`--help` 是执行线写手册的依据，写清每个参数、默认值、前台运行命令、失败后怎么办）。去掉骨架期的 `exit 78`。脚本测试用临时目录里的假 `git`、`uv`、`pnpm`、`systemctl`、`rdp`（放在 PATH 前面并记录调用），覆盖：步骤顺序；端口被占停下且不复制单元；有运行中作业时升级停下且不停服务；停服务后二次检查发现作业时保持停止；`--no-systemd` 全程不调用 systemctl；`HOME` 指向临时目录时单元写到临时 `HOME/.config/systemd/user/`、不碰同目录里一个假的无关单元；`@DEPLOY_DIR@` 含空格和中文时替换正确。测试绝不调用真实 `systemctl`/`loginctl`，测试进程的 `HOME` 必须是临时目录。
- systemd 单元模板测试：关键指令都在（`Restart=on-failure`、`WantedBy=default.target`、worker `KillMode=control-group` 和 `TimeoutStopSec>=30`、`--no-stderr`），没有写死用户名或 `/home/`。可以的话用 `systemd-analyze verify` 之外的纯文本解析，不依赖本机 systemd。
- Web 入口测试用注入的 uvicorn 运行函数，或在进程内用临时端口起一次真实 uvicorn 并在测试内停掉（只绑 127.0.0.1、端口 0 或临时端口），断言 `web.log` 里的启动行是统一格式、请求不产生访问日志。不占 8600。
- worker 入口测试不在测试进程里安装真实信号处理器（用注入的信号安装函数），或在子进程里测 SIGTERM；子进程必须有超时并在结束时清理。
- 删掉所有骨架期的说法（"骨架""桩""实现阶段""尚未接线""留待""待实现""11 号票""号票"等），只写现在的行为；`第 N 张`作为来源可以保留。交付前在本票改过的文件里搜这些词，不留。前端 4 条 `no-unused-vars` 豁免实现后移除。
- OpenAPI 有变化用 `make api-types`，不手改生成文件。
- 从零安装演练（验收 5）和真实安装（验收 6）由执行线在沙箱外做，你不用跑安装或升级脚本本身（只在测试里配假命令运行）。

为了不超时：每个测试单独先红后绿，每改完一个文件只跑相关测试文件；最后只跑一次 `make check`。到 75 分钟还没做完，停在 `make check` 全绿的位置交检查点（已完成的去掉跳过、没做的保留跳过），第 4 块写清还剩哪些测试。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只 `[project.scripts]`，以及 ruff、basedpyright 确实需要时的调整，每条写理由）；`scripts/`（安装、升级脚本和 systemd 单元模板，不改 `check_contracts.py`）；`Makefile`（只为脚本语法检查）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请。
- 不运行真实 `systemctl`、`loginctl`、`nvidia-smi`；不碰真实 `~/.config/systemd/user/`、`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/`；不起占用 8600 的服务。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已获批契约的含义。其余拿不准的照你的判断做，列进第 4 块。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。列出改了哪些 docstring/TSDoc 的哪几句。
4. 拿不准、需要评审决定的地方；交检查点时写清还剩什么。
5. 先红后绿：每个测试一行（可以按文件分组），写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
