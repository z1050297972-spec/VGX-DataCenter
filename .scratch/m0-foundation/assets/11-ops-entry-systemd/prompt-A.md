你在工单「运维入口与 systemd 服务」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd（git worktree，分支 t/m0-11-ops-entry-systemd）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」：这些写法以前被打回过，一开始就避免
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/11-ops-entry-systemd.md，**特别是 Comments**：负责人决定 M1–M3；第 3 张补的 `log_config=None, access_log=False` 和启动时补归档（R1，已批准改 `configure_logging` 的契约含义）；第 5 张的 B1、B3（引擎传给 `create_app`、关引擎前等报错写入线程、先停服务再 migrate）；第 8 张的 `KillMode=control-group`、`TimeoutStopSec` ≥ 30 秒、`sys.exit(result.code)`；第 9、10 张列出的生产入口装配清单（调度、存储根）。
- 它引用的 ADR 0005、`.scratch/m0-foundation/spec.md` 第 11 张和「目标」，`docs/manual/运维手册.md`、`docs/manual/使用手册.md` 的现状。
- 第 9、10 张执行线的演示启动脚本，是生产装配的现成参照（只读）：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/demo09.py、/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/10-storage-roots-fake-nav/demo10.py。

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。shell 脚本和 systemd 单元模板在骨架阶段写出结构和注释（每段做什么、失败怎么停），可执行逻辑留到派工 B；它们的测试同样写成跳过的测试。
2. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。
3. `make check` 跑到全绿。

**执行线给的设计方向**（你可以改，改了在第 4 块写理由；不确定的列进第 4 块）

命令入口（`rdp.ops`）
- `pyproject.toml` 的 `[project.scripts]` 登记 `rdp = "rdp.ops.cli:main"`（模块名你定）。`main(argv: Sequence[str] | None = None) -> int`，标准库 argparse（M3）；入口包装里 `sys.exit(main())`。子命令：`web`、`worker`、`migrate`、`create-admin`、`reset-password <登录名>`，以及 `--version`。参数错误退出码 2（argparse 默认）。
- 装配（composition root）放在 `rdp.ops` 里一个专门的模块：读配置（`load_config`）→ 初始化/检查状态目录 → 配日志（`LoggingSettings`，`--no-stderr` 时 stderr=False）→ 记配置来源和目录警告 → 建引擎 → `production_registry()` → `validate_storage_roots` → 调度目录（`resolve_scheduling`、`production_schedules`、`local_timezone(Path("/etc/localtime"))`）→ 存储根 `MountInspector`/`StorageAccessChecker`。Web 一侧 `create_app(dist, database=engine)` + `configure_jobs(..., scheduling=...)` + `configure_storage(..., inspector=...)`，然后 `uvicorn.run(app, host, port, log_config=None, access_log=False)`，单进程；worker 一侧 `run_worker(ExecutorDependencies(..., storage=...), stop, logging_settings, scheduling=WorkerScheduling(...))`，SIGTERM/SIGINT 设置 stop，进程退出码就是 `result.code`。可注入的东西（环境、home、时钟、信号安装、uvicorn 运行函数、`nvidia-smi` 查找）作为参数，测试不起真实服务、不装真实信号处理器到测试进程以外。
- `web`、`worker` 在数据库版本落后时拒绝启动，提示运行 `rdp migrate`（复用 `check_database_version`），退出码非 0。
- `nvidia-smi` 路径：配置了卡（`[jobs] gpus` 非空）时需要一个绝对路径。建议启动时用 `shutil.which("nvidia-smi")` 找，找不到就拒绝启动并说明（或者你提出更好的做法，例如配置项）；配置为空列表时传 None。
- 前端 dist 的位置：部署目录里 `src/web/dist`（安装脚本 `vite build` 产出）。从包位置推导还是配置项，由你提出；不能依赖当前工作目录。
- `create-admin`、`reset-password` 复用 `rdp.ops.accounts` 已有函数；`reset-password` 的操作日志操作人记"运维命令"（确认第 6/7 张已有的行为是否已经满足验收 4：旧会话失效、下次登录先改口令、一条操作日志；不满足的列进第 4 块）。
- **版本号（M2）**：`rdp --version` 输出例如 `0.1.0 (82907a1)`；网页底部显示同样的文字；作业记录里记下运行该作业的平台版本。建议：版本号来自包元数据；提交号由安装/升级脚本写进部署目录的一个构建信息文件，运行时读取，读不到显示"未知"，运行时不调用 git。作业记录加一列需要迁移 `0006`（照第 8、9 张的迁移做法：骨架阶段放 `pending/`，派工 B 激活），由 worker 领取时写入；Web 提供一个只读接口或在现有健康/会话接口里带版本，你定。
- **启动时补归档**（R1，已批准）：活动日志文件（`web.log`、`worker.log`）的修改日期早于今天（按 `configure_logging` 现有的本地日历规则），先按那个日期归档再开新文件；时钟可注入，测试不改全局时区、不 sleep。
- **worker 运行时拒绝**：一个检查函数，判断 worker 单实例锁（`worker.lock`）此刻是否被持有（非阻塞尝试加锁后立刻释放，或复用第 8 张已有的锁工具），持有时返回"拒绝"及原因；M0 只有测试使用，M1 的"重建索引"直接用。
- 升级脚本要知道"有没有运行中的作业"：建议加一个只读的运维子命令（例如 `rdp jobs --active` 或 `rdp status`，只读数据库、退出码表示有无），或者由脚本调用 `python -m` 一个只读入口，你选一种并说明理由；这超出工单列的子命令，只能是只读状态查询，不放业务功能。

systemd 单元与脚本（`scripts/`）
- `scripts/systemd/rdp-web.service`、`rdp-worker.service` 模板：`ExecStart=<部署目录>/.venv/bin/rdp web --no-stderr`（worker 同理），部署目录由安装脚本替换；`Restart=on-failure`；`WantedBy=default.target`；worker 加 `KillMode=control-group`、`TimeoutStopSec`（≥ 30 秒，留出外部工具 10 秒内收到 SIGTERM 的余量，取值写理由）。不写死用户名或 `/home/...`。
- `scripts/install.sh`、`scripts/upgrade.sh`（bash，`set -euo pipefail`）：
  - 安装：参数给部署目录（默认 `~/.local/opt/rdp`，M1）和要部署的提交（默认当前 main）；`git worktree add --detach` 建部署目录；`uv sync --frozen`；`pnpm install --frozen-lockfile` + `vite build`；写构建信息文件；`rdp migrate`；检查 8600（或配置的端口）是否被占，被占就停下提示改配置；复制单元到 `~/.config/systemd/user/`（不碰已有的无关单元，例如 `egopro-restore.service`），`systemctl --user daemon-reload`、`enable --now`。
  - 必须有一个不装 systemd 单元的模式（例如 `--no-systemd`），供临时 `HOME` 下从零安装演练（验收 5）：那时用 `rdp web`、`rdp worker` 直接前台运行。
  - 升级：先查有没有运行中的作业，有就停下提示（v1 不等作业跑完）；确认后先停 Web 和 worker，再把部署目录移到新提交、`uv sync`、前端构建、写构建信息、`rdp migrate`，最后启动；也要支持 `--no-systemd`。
  - 脚本测试：至少语法检查（`bash -n`）接进 `make check`（Makefile 只为这个改，允许）；再用假的 `uv`、`pnpm`、`systemctl`、`git` 放在 PATH 前面，在临时目录里验证步骤顺序、端口被占时停下、有运行中作业时升级停下、`--no-systemd` 不碰 systemctl。测试绝不调用真实 `systemctl`，不写真实 `~/.config/systemd/user/`。
- 手册整理（使用手册、运维手册两份）由执行线在合并时做，你不改 `docs/`；但安装/升级脚本的用法要在脚本 `--help` 里写清，执行线照着写手册。

**测试清单至少覆盖**：验收 1（每个子命令 `--help`；参数错误退出码 2；数据库版本落后时 web/worker 拒绝并提示 `rdp migrate`）、2（`--no-stderr` 时 stderr 无日志）、2a（uvicorn 启动行走统一格式、无访问日志；用注入的 uvicorn 运行函数或进程内小应用测，不占真实端口以外的资源）、2b（修改时间三天前 → 归档成那天；今天 → 不归档）、3（worker 持锁时检查返回拒绝）、4（reset-password：旧会话失效、必须改口令、一条操作日志、操作人"运维命令"）、7（升级脚本：有运行中作业停下；没有时步骤按顺序、迁移到最新）、版本号（`--version` 格式、构建信息文件缺失显示未知、作业记录写入版本、网页底部显示）、worker 入口返回码、SIGTERM 停止、装配校验（存储根名字未登记拒绝启动、配置了卡但找不到 `nvidia-smi` 的处理）、systemd 单元模板内容（关键指令都在、无写死路径）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只加 `[project.scripts]` 里的 `rdp` 入口）；`scripts/`（新建安装脚本、升级脚本和 systemd 单元模板，不改 `check_contracts.py`）；`Makefile`（只为把脚本语法检查接进 `make check`）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 不运行真实 `systemctl`、`loginctl`，不碰真实 `~/.config/systemd/user/`、`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/`；不起占用真实端口的服务；不运行安装或升级脚本本身（只在测试里配假命令运行）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已获批契约的含义（R1 对 `configure_logging` 的改动已获批；只加参数或字段的改动可以先做再在第 3 块申请）。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方（包括你对上面设计方向的改动和理由；需要负责人决定的单独标出）。
