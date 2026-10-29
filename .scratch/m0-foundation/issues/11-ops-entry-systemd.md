# 运维入口与 systemd 服务

Status: in-progress

## 依据

- M0 spec 第 11 张，也是 M0 的验收：按手册从零装起，跑通 spec「目标」里的全过程。
- 「交互形态与前端路线」：最小的运维命令入口，只有启动 Web 和 worker、数据库迁移、重建索引、创建首个管理员，不放业务功能。重建索引要有数据集索引，留到 M1 加。
- ADR 0005：Web 和 worker 各是一个 systemd 用户服务，开机自启、崩溃自动重启；systemd 下只写日志文件，不往 stderr 输出；升级重启 worker 按中断处理。
- 第 5 张 F2：版本不对拒绝启动，升级时由人运行 `migrate`。第 6 张：创建首个管理员、重置唯一管理员的口令。
- 本机事实（2026-10-23）：systemd 259；`loginctl` 显示 `Linger=yes`，用户服务不用登录也会开机启动；`~/.config/systemd/user/` 里已有一个无关的 `egopro-restore.service`，不动它。
- 依赖：第 10 张合并以后开工。不需要新依赖。

## 目标

平台以两个后台服务的形式跑在这台机器上，开机自启、崩溃自动重启；装、升级、排查都有手册可照着做。

## 范围

**运维命令 `rdp`**（`rdp.ops`）
- 在 `pyproject.toml` 里登记成命令行入口，用标准库 `argparse`。子命令：
  - `rdp web`：起 Web（uvicorn，单进程，地址和端口来自配置）。
  - `rdp worker`：起 worker。
  - `rdp migrate`：升级数据库（第 5 张）。
  - `rdp create-admin`：创建首个管理员（第 6 张）。
  - `rdp reset-password <登录名>`：在终端里重置一个账号的口令，用于唯一的管理员忘了口令。写一条操作日志，操作人记为"运维"（沿用第 6 张，负责人 2026-10-28 定）。
  - `rdp --version`：见「待负责人确认」第 2 条。
- `web`、`worker` 带一个 `--no-stderr` 开关，systemd 单元里用它（ADR 0005）。
- `rdp web` 调 uvicorn 时传 `log_config=None, access_log=False`：不传的话 uvicorn 会覆盖第 3 张配好的日志格式，访问日志也会回来（第 3 张评审）。
- **启动时补归档**（第 3 张 R1，负责人 2026-10-23 批准，改第 3 张 `configure_logging` 的契约含义）：启动时，活动日志文件（`web.log`、`worker.log`）的修改日期早于今天，就先按那个日期归档，再开新文件。否则服务停几天再启动，停机前的内容会归档成重启当天的日期。
- 要碰导航层的运维命令，在 worker 运行时拒绝执行（「作业模型」）。M0 还没有这样的命令，先把检查函数做好、写测试，M1 的"重建索引"直接用。

**systemd 单元**
- 两个用户服务单元的模板：`rdp-web.service`、`rdp-worker.service`。`Restart=on-failure`，`WantedBy=default.target`，`ExecStart` 指向部署目录里的 `.venv/bin/rdp`。
- 单元模板放在仓库里，由安装步骤复制到 `~/.config/systemd/user/`。worker 的单元给 `TimeoutStopSec` 留够时间，让外部工具能在 10 秒内收到 SIGTERM 再被结束（「作业模型」的取消规则）。

**部署目录与升级**（见「待负责人确认」第 1 条）
- 一个安装脚本和一个升级脚本，放在 `scripts/` 下：建部署目录、`uv sync --frozen`、`pnpm install --frozen-lockfile` 加 `vite build`、`rdp migrate`、装单元、启动。
- 升级脚本先检查有没有运行中的作业，有就停下来提示（v1 没有"等作业跑完再停"，「作业模型」的风险）；确认后再停服务、更新、迁移、启动。

**一键部署脚本**（负责人 2026-10-28 加，合并前做完）
- `scripts/setup.sh`：别人在另一台机器上拿到仓库副本（`git clone`）后运行一次，就能装好并启动。不负责取代码；取代码的办法写进运维手册。
- 顺序：
  1. 检查环境：git、uv、pnpm、Node、`systemctl --user`、linger。缺 uv、pnpm、Node 时，逐个问过再自动装到用户目录（不用 sudo，版本固定且和 `uv.lock`、`package.json` 一致，下载后校验）；git、systemd 缺失只提示。linger 关着时说明后果，问过再 `loginctl enable-linger`，失败就打印要管理员执行的命令。
  2. 生成配置：已有 `~/.config/rdp/config.toml`（或 `RDP_CONFIG`）就沿用，不覆盖。没有就问答生成：监听地址（默认 0.0.0.0，说明明文 HTTP 的风险）、端口（默认 8600）、导航层目录、存储根（列出已挂载的盘和 UUID，标出是否只读，让人选）、GPU（有 `nvidia-smi` 就列出，没有就空）。写完用平台自己的配置校验检查一遍。
  3. 调用 `scripts/install.sh`（参数透传）。
  4. 建第一个管理员（终端输入口令）；已有管理员就跳过。
  5. 健康检查 `/api/health`，打印可访问地址（本机各网卡 IP）。
- 重复运行：已安装就不重装，打印状态和升级命令。
- 非交互：`--config <文件>`、`--yes`、`--no-systemd` 等，没有终端时缺什么就报错退出，不卡住。
- 测试照安装脚本的做法：假命令放 PATH 前面、临时 HOME；不联网、不调用真实 systemctl/loginctl/nvidia-smi/findmnt。
- 验收 9：Claude 在临时 HOME 下用一键脚本从零装起（`--no-systemd`，含一次在临时目录里自动装 uv、pnpm、Node 的联网演练），跑通验收 5 的全过程。验收 6 的真实安装改用一键脚本做。

**手册**：把 M0 各票写的手册整理成两份：
- `docs/manual/使用手册.md`：登录、账号、看日志、作业、看报错、存储根。
- `docs/manual/运维手册.md`：从零安装、配置文件、状态目录、升级、备份（先写"待 M0 第 12 张"）、排查（worker 没在运行、存储根离线、数据库版本不对、忘了管理员口令）。

## 允许改的受保护文件

| 文件 | 允许做什么 |
|---|---|
| `pyproject.toml` | 加 `[project.scripts]` 里的 `rdp` 入口 |
| `scripts/` | 新建安装脚本、升级脚本、一键部署脚本 `setup.sh` 和 systemd 单元模板；不改 `check_contracts.py` |
| `Makefile` | 只在需要把安装脚本的检查（例如 shellcheck 式的语法检查）接进来时改；没有就不改 |

## 验收

1. **命令**：每个子命令的 `--help` 能用；参数错误退出码 2；`web`、`worker` 在数据库版本落后时拒绝启动并提示 `rdp migrate`。
2. **`--no-stderr`**：开着时 stderr 没有日志输出，日志只进文件。
2a. **日志接管**：`rdp web` 起来以后，`web.log` 里 uvicorn 的启动行是统一格式，请求不产生访问日志。
2b. **启动时补归档**：活动日志文件的修改时间设成三天前，启动后它被归档成那一天的日期，新内容写进新的 `web.log`；修改时间是今天时不归档（测试里用可控的时钟）。
3. **worker 运行时拒绝**：检查函数在 worker 拿着单实例锁时返回"拒绝"，测试覆盖。
4. **reset-password**：重置后旧会话失效，下次登录必须先改口令（第 6 张 G3），有一条操作日志。
5. **从零安装**（M0 验收）：Claude 在沙箱外，用一个临时的 `HOME`（不碰真实的 `~/.config`、`~/.local/share/rdp`）按运维手册从零装起，跑通：迁移 → 创建管理员 → 起两个服务 → 登录 → 建一个成员 → 提交示例作业并看着它完成 → 管理员看到操作日志和登录日志 → 存储根页面两块盘在线。每一步的命令和输出放进 assets。
6. **真实安装**：负责人同意后，按手册装到真实的部署目录，两个服务以 systemd 用户服务运行；`systemctl --user restart rdp-worker` 后，正在跑的示例作业变成"已中断"；重启机器后两个服务自动起来（负责人方便时做）。
7. **升级**：有运行中的作业时，升级脚本停下来提示；没有时，升级后版本号变了，数据库迁移到最新。
8. **先红后绿、文件归属、契约**：同第 2 张的验收第 12 条。

## Claude 的步骤

按 `codex-workflow.md` 3.1–3.7 走，不用拆段，没有新依赖。验收第 5、6 条由 Claude 在沙箱外做；第 6 条要负责人同意并在场（会动真实的 `~/.config/systemd/user/`）。合并以后，M0 结束：在原会话里跑 `/retro`（`CLAUDE.md`「管理」）。

## 风险

- **部署目录和开发目录分开以后，要记得升级**：开发目录的 main 前进了，跑着的服务不会变，要跑升级脚本。手册里写清楚。
- **端口 8600 被占**：安装前检查一次，被占就提示改配置。

## 待负责人确认

1. **服务从单独的部署目录运行，不从开发用的仓库目录运行？** 部署目录是仓库在某个提交上的一份检出（例如 `~/.local/opt/rdp`，由安装脚本用 `git worktree` 建）。这样在开发目录里改代码、切分支、跑测试，都不会影响正在跑的服务；升级就是把部署目录移到新的提交上。
   - 建议：是。
2. **`rdp --version` 和网页底部显示版本号加 git 提交号？** 例如 `0.1.0 (82907a1)`。作业记录里也记下当时平台的版本，以后排查"这个作业是哪个版本的平台跑的"就有据可查。
   - 建议：是。
3. **命令行用标准库 `argparse`，不加 click 或 typer？** 子命令只有五六个、参数很少，标准库够用（规则 7）。
   - 建议：是。

## Comments

- 2026-10-23，起草（主会话）。等负责人过目，回答「待负责人确认」后改成 `ready-for-agent`；第 10 张合并以后才能开票。
- 2026-10-23，负责人批准本票（"都按推荐来"）：
  - **M1**：服务从单独的部署目录（例如 `~/.local/opt/rdp`，用 `git worktree` 建）运行，不从开发目录运行。
  - **M2**：`rdp --version` 和网页底部显示"版本号 + git 提交号"；作业记录里记下平台版本。
  - **M3**：命令行用标准库 `argparse`。
  - Status 改成 `ready-for-agent`。等第 10 张合并以后再开票。
- 2026-10-23，按第 3 张评审补范围：`rdp web` 传 `log_config=None, access_log=False`；启动时按活动日志文件的修改日期补归档（R1，负责人批准）。验收加 2a、2b。
- 2026-10-24，第 5 张定（B1、B3）：启动入口必须把数据库引擎传给 `create_app`（验收加一条）；关闭引擎前等写报错表的线程结束；升级步骤先停 Web 和 worker 再 `migrate`。
- 2026-10-26，第 8 张合并时补充（执行线）：worker 的外部程序在自己的进程组里运行（`start_new_session`），worker 被 SIGKILL 时不会跟着结束；第 8 张不在 worker 里清理孤儿，依赖本票的服务单元。验收补一条：worker 单元 `KillMode=control-group`、`TimeoutStopSec` 不少于 30 秒（第 8 张 `WORKER_STOP_TIMEOUT_S`）；测试或演示里 `systemctl --user kill -s KILL` worker 后，残留的外部程序随单元一起被清掉。入口必须 `sys.exit(result.code)`，失败码交 systemd 重启（见 `rdp.ops.worker.run_worker` docstring）。
- 2026-10-27（执行线，来自第 9 张评审）：第 9 张没有生产入口装配调度。worker 入口要构造 `WorkerScheduling(SchedulingCatalog(resolve_scheduling(config.jobs, registry), production_schedules(registry), local_timezone(Path("/etc/localtime"))), nvidia_smi=<配置卡非空时的绝对路径>, error_retention_days=config.errors.retention_days)` 传给 `run_worker(..., scheduling=...)`；Web 入口 `configure_jobs(..., scheduling=<同一 SchedulingCatalog>)`。参照 `.scratch/m0-foundation/assets/09-job-scheduling-resources/demo09.py`。
- 2026-10-27（执行线，来自第 10 张评审）：第 10 张也没有生产入口装配。Web 入口要 `configure_storage(app, inspector=MountInspector(config.storage_roots, LinuxMountSource().read_mountinfo, LinuxMountSource().resolve_uuid_device, <UTC 时钟>))`；worker 入口要构造 `StorageAccessChecker(mounts=<同上>, options=config.storage, access=read_storage_root)` 放进 `ExecutorDependencies(storage=...)`，并在全部类型登记后调用 `registry.validate_storage_roots(roots=config.storage_roots)`。参照 `.scratch/m0-foundation/assets/10-storage-roots-fake-nav/demo10.py`。
- 2026-10-28 开票（执行线）：第 10 张已合并（363a8f7）。负责人："合并，然后开始第 11 张"。Status 改为 `in-progress`。工作目录 `~/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd`，分支 `t/m0-11-ops-entry-systemd`，基点 66f0de0；基线 make check 全绿（pytest 1811、Vitest 243）。派工 A（新会话），提示 `assets/11-ops-entry-systemd/prompt-A.md`，快照 `refs/rdp/m0-11/A`。
  - 派工 A 会话编号 `01a18128-6a69-7a72-ba76-edfe518e3789`。
- 2026-10-28 00:17、00:20 派工 A 两次都没开始工作：第一次上游 429 Too Many Requests（超出重试上限），第二次本机 CC Switch 代理（127.0.0.1:15721）转发 gpt-6-astra 返回 503 Service Unavailable。工作区未改动。等负责人确认 Codex 服务恢复后重派同一 `prompt-A.md`（新会话）。
- 2026-10-28 负责人说 Codex 已恢复，重派 A（新会话 `01a181dc-0f44-7062-80e5-ed93b0effbea`）：仍是 CC Switch 代理转发 gpt-6-astra 时上游 HTTP 503（重连 5 次后 turn.failed），没开始工作，工作区未改动。
- 2026-10-28 机器 05:27 重启后 CC Switch 未起，又一次派工连不上代理（已停）。负责人打开 CC Switch 后重派 A，新会话 `01a1824e-e4b2-7dc1-9c9d-d7eb3faf78b2`，已开始工作。
- 2026-10-28 上一会话只跑了约 4 分钟（读文件、基线检查，05:43 后停住），机器 06:53 又重启，工作区未改动。新会话重派 A：`01a18294-af03-70b1-81ef-4fd5b748815f`，运行日志改放 `~/.cache/rdp-dispatch/m0-11/`（`/tmp` 重启会清空）。
- 2026-10-28 负责人要求改用 Codex fast 模式（`-c service_tier="fast"`）重跑：停掉会话 `01a18294-…`（只读了文件，工作区未改动），新会话 `01a18298-a530-7210-ae88-874e082c1564`，约 07:00 开始。用时记下来与以往派工对比；能否经 CC Switch 生效未经证实。
- 2026-10-28 07:52 骨架 A 交回（fast 模式，用时约 52 分钟），快照 `refs/rdp/m0-11/A-out`。执行线复跑 make check 全绿（pytest 1811 passed / 115 skipped；Vitest 243 passed / 7 skipped），日志审计 0 条。等负责人过骨架关卡。待负责人定：reset-password 操作人沿用第 6 张已有的"运维"，还是改成工单写的"运维命令"（后者要改身份校验和数据库约束）。
- 2026-10-28 负责人过骨架关卡："按照你的建议，我通过，请用fast实现"。决定：reset-password 操作人沿用第 6 张的"运维"，不新增"运维命令"（范围已改）。骨架第 3 块的只加参数/字段（`create_app.platform_version`、`run_worker.log_time`、`ExecutorDependencies.platform_version`、`JobRecord`/`JobResponse.platform_version`）和第 4 块的设计选择一并认可。派工 B 用 fast 模式。
- 2026-10-28 契约提交 `22bdb4d`（`契约：运维入口与 systemd 服务`，钩子 make check 全绿）。派工 B（fast 模式，新会话 `01a182d5-6622-7d83-886c-6314bcbc43c4`），提示 `assets/11-ops-entry-systemd/prompt-B.md`，快照 `refs/rdp/m0-11/B`。
- 2026-10-28 08:36 执行线会话结束，派工 B 被中断（已跑约 30 分钟：版本、0006、启动补归档、前端页脚完成；cli/runtime/web 生命周期/worker 入口/部署脚本 82 个测试仍跳过）。日志审计干净，快照 `refs/rdp/m0-11/B-cut`。08:56 续跑同一会话（fast），提示 `prompt-B-resume.md`。
- 2026-10-28 09:10 负责人另有安排，要求无人值守跑完、最后直接验收。执行线自主推进到：B 完成 → 3.5 评审（变异抽查、日志审计、打回最多 3 轮）→ `实现：` 提交 → 验收 5（临时 HOME 从零安装，assets 存全部命令和输出）。**然后停下**：验收 6（真实安装，动真实 `~/.config/systemd/user/`）要负责人同意并在场；合并要负责人说"合并"。中断恢复：派工日志在 `~/.cache/rdp-dispatch/m0-11/`，快照在 `refs/rdp/m0-11/`，以本 Comments 的最后一条为准。Codex 改用 `setsid` 派工，不随执行线会话退出而被杀；执行线会话放进 `screen -S rdp`。
- 2026-10-28 09:14 派工 B 挪到独立会话（`setsid`，进程组长 PID 见 `~/.cache/rdp-dispatch/m0-11/pid-B.txt`，退出码写 `exit-B.txt`），提示 `prompt-B-resume2.md`，快照 `refs/rdp/m0-11/B-cut2`。执行线恢复后先看 `exit-B.txt` 是否存在：在则读 `out-B.md` 评审；不在则用 Monitor 等 `ev-B.jsonl` 出现 `turn.completed`/`turn.failed`。
- 2026-10-28 10:06 B 交检查点（部署脚本 22 项未做），快照 `refs/rdp/m0-11/B-out`；同会话续做脚本（setsid、fast，提示 `prompt-B-scripts.md`）。执行线在探针目录复跑检查点：make check 全绿（pytest 1906 passed / 22 skipped，Vitest 250），日志审计 0 条，变异 12/12 被抓（`assets/.../mutation_probe-B.txt`）。临时 HOME 冒烟：web 迁移前拒绝启动（exit 1、提示 rdp migrate）→ migrate → create-admin（只接受终端输入口令，用 pty）→ web+worker 起来，登录、`/api/version` "0.1.0 (未知)"、worker 在线，web.log 无访问日志、stderr 空 → SIGTERM 0.5 秒内两者都退出。待打回：worker 启停不写 worker.log；子命令和 status 选项没有帮助说明。
- 2026-10-28 11:05 脚本交付，快照 `refs/rdp/m0-11/B-out2`。执行线探针复跑 make check 全绿（pytest 1946 passed / 0 skipped，Vitest 250），日志审计 0 条，脚本变异 7/7 被抓（`mutation_probe-B-scripts.txt`）。打回第 1 轮（小，`prompt-B-r1.md`）：worker/Web 启停写日志；`rdp --help` 子命令与 status 选项说明；Protocol 方法体改 `...`。同会话 setsid、fast。
- 2026-10-28 11:37 第 1 轮交付（worker/Web 启停日志、帮助文字、Protocol `...`），日志审计 0 条，快照 `refs/rdp/m0-11/B-r1-out`。评审通过。实现提交 `b7c9f4c`（`实现：运维入口与 systemd 服务`，钩子 make check 全绿：pytest 1953 passed、Vitest 250）。下一步验收 5（临时 HOME 从零安装演练）。
- 2026-10-28 11:43 验收 5 演练（`assets/11-ops-entry-systemd/drill11.sh`、`drill11.mjs`，输出 `drill11-run.log`、`drill/*.png`）：临时 HOME、`install.sh --commit t/m0-11-ops-entry-systemd --no-systemd` 从零安装 → `rdp --version` 为 `0.1.0 (b7c9f4c)` → create-admin → 前台起 web/worker → 浏览器：admin 登录、页脚版本、建成员、成员首登改口令、成员提交"示例：数数"走 queued→running→completed（作业记录 platform_version 正确）、操作日志与登录日志、存储根两块盘只读在线 → DRILL PASS；web.log 无访问日志；worker SIGTERM 退出 0、开始/结束日志齐。**缺陷**：web SIGTERM 退出 143、无"Web结束运行"——uvicorn 0.54 `capture_signals` 关闭后重抛信号，`start_web` 收尾（排空报错线程、释放引擎）在生产停服务路径上不执行。打回第 2 轮（`prompt-B-r2.md`）。另记（非本票）：登录页未登录时的 401 在 web.log 记为 ERROR（每次打开登录页 2–3 条），可在后续票调成 INFO/不记。
- 2026-10-28 12:09 第 2 轮交付（自有 `uvicorn.Server` 子类取消关闭后的信号重抛；真实进程 SIGTERM 测试），日志审计 0 条。提交 `2c76e60`（钩子全绿：pytest 1958、Vitest 250）。重跑验收 5：DRILL PASS，web/worker SIGTERM 均退出 0，开始/结束日志齐（`drill11-run.log`，前一次在 `drill11-run-b7c9f4c.log`）。
- 2026-10-28 12:15 验收 7 升级演练（`drill11-upgrade.sh b7c9f4c 2c76e60`，输出 `drill11-upgrade-run.log`）：第一次运行（执行线脚本把作业号写死成 1）已证实"有运行中作业时 upgrade.sh 停下、版本不变"；第二次运行升级成功 `0.1.0 (b7c9f4c)` → `0.1.0 (2c76e60)`、`rdp-build.json` 更新、数据库在 0006，但暴露**缺陷**：web 与 worker 同时启动时 web 退出 1，`[Errno 17] File exists: .../logs/示例：写锁`——`infra/state.py` `_create_directory` 先查后建的竞争（第 3 张起就有，单进程演示未暴露；systemd enable --now 和开机同时起两个服务会触发）。打回第 3 轮（最后一轮，`prompt-B-r3.md`）。
- 2026-10-28 12:37 第 3 轮交付（`_create_directory` 在 mkdir 撞 FileExistsError 时复核为目录即按已有处理；确定性与真实并发测试；装配路径其余创建点结论：日志分文件追加、锁原子 O_CREAT、数据库只读检查，无同类竞争），日志审计 0 条。提交 `b3a1b7b`（钩子全绿：pytest 1967、Vitest 250）。执行线核验：
  - 验收 5 重跑 DRILL PASS（`drill11-run.log`，版本 `0.1.0 (b3a1b7b)`，web/worker SIGTERM 均 0、开始/结束日志齐、无访问日志）。
  - 验收 7 重跑（`drill11-upgrade.sh 2c76e60 b3a1b7b` → `drill11-upgrade-run.log`）：有运行中作业时升级停下、版本不变；取消并停服务后升级成功，`0.1.0 (2c76e60)` → `0.1.0 (b3a1b7b)`，数据库在 0006；旧作业保留 platform_version `0.1.0 (2c76e60)`。
  - 同时启动 web+worker 压力 8/8 次干净（全新状态目录）。
  - 把第 2、3 轮修复各自撤回，新增测试分别 8 个、3 个失败（测试确能抓到缺陷）。
  - **到此执行线自主部分完成，停下等负责人**：验收 6 真实安装（要负责人同意并在场），然后"合并"。合并时整理两份手册。
- 2026-10-28 负责人要一键部署脚本（"其他人运行即可完成所有配置启动服务"），决定：并进第 11 张、合并前做完；缺 uv/pnpm/Node 时问过再自动装；用在别的机器上从零部署。范围加「一键部署脚本」、验收 9。按新的一段走骨架 → 负责人关卡 → B → 评审（本段打回上限另算 3 轮）。负责人另问能否监听 0.0.0.0：可以（本就是默认值），风险是局域网明文 HTTP，见对话。
- 2026-10-28 负责人预批一键脚本骨架关卡："可以"（骨架按执行线建议直接过，不停下等）。执行线复查骨架后，按建议处理 Codex 第 4 块的待决项、写进本条之后的 Comment，直接做契约提交并派 B；真实安装和"合并"仍等负责人。
- 2026-10-28 18:58 一键脚本骨架交回（快照 `refs/rdp/m0-11/C-A-out`）：`scripts/setup.sh` 24 个阶段函数、`src/rdp/ops/setup_queries.py` 6 个只读查询、65 项跳过测试；Codex 自报 make check 全绿（1967 passed / 65 skipped，Vitest 250）。执行线按预批过关卡，采纳 Codex 第 4 块：配置校验用 `git archive` 目标提交 + 临时 `uv sync --frozen --no-dev` 环境跑 `setup_queries validate-config`（不改 install.sh）；固定 uv 0.13.5 / Node 22.23.2 / pnpm 11.22.0，pnpm 用官方独立二进制；Node 用同源 SHASUMS256.txt、uv/pnpm 用 GitHub release asset digest 校验，缺摘要即停；`--no-systemd` 时 setup 前台监管两个服务；加 `--skip-admin`，不提供口令参数；存储根平台写许可默认否、`--yes` 不代答。下载源能否访问由验收 9 联网演练核实。
- 2026-10-28 18:56 契约提交 `51288e7`（`契约：一键部署脚本`，钩子全绿 1967 passed / 65 skipped）；派工 C-B（setsid、fast，同会话，提示 `prompt-C-B.md`，日志 `~/.cache/rdp-dispatch/m0-11/ev-C-B.jsonl`，退出码 `exit-C-B.txt`）。
- 2026-10-28 19:36 负责人要求先完成真实安装（"能否启用子agent，先帮我完成安装"）。验收 6 开始：子 agent 用 `install.sh --commit b3a1b7b` 装到 `~/.local/opt/rdp`，配置写在 `~/.config/rdp/config.toml`（监听 0.0.0.0:8600，nav_root /mnt/datasets，两块盘只读，gpus [0,1]），启用 systemd 用户服务；运行记录写到 `assets/11-ops-entry-systemd/real-install-run.log`。管理员由负责人在终端里建。一键脚本 C-B 同时在跑，互不影响。
- 2026-10-28 19:37 验收 6 真实安装失败，停在"启用并启动服务"（`real-install-run.log`）。构建、迁移（0006）和 enable 都成功了，start 失败：单元里 `WorkingDirectory="…"` 带了引号，systemd 报 "path is not absolute"，单元处于 bad-setting 状态。执行线用 `systemd-analyze --user verify` 复现了。根因：install.sh 替换时给 WorkingDirectory 加了引号；`tests/test_ops_deploy_scripts.py:516` 断言的就是错的带引号形式，测试和实现错在一起；--no-systemd 演练不装单元，所以没发现。修法：WorkingDirectory 不加引号（systemd 按整行字面取值，空格不用转义），`%` 写成 `%%`；测试改成断言不带引号，并加一项用 systemd-analyze verify 检查生成的单元（离线运行，不调用 systemctl）。等 C-B 交回后作为一轮修复派给 Codex。现场保留：配置、状态目录、部署目录、两个单元文件、两个 wants 链接；egopro-restore 没动，Linger=yes。7.1 待补一条：单元模板的测试要过 systemd 自己的解析，不能只做文本比对。
- 2026-10-28 19:39 负责人选"1"：执行线手修已装的两个单元，去掉 WorkingDirectory 的引号（原文件备份在 `~/.cache/rdp-dispatch/m0-11/rdp-*.service.orig`），`systemd-analyze --user verify` 通过，daemon-reload 后启动。两个服务 active、enabled；127.0.0.1 和 100.82.81.44 的 /api/health 都是 ok；版本 `0.1.0 (b3a1b7b)`；监听 0.0.0.0:8600；日志没有 ERROR；egopro-restore 没动。这只是临时修补：验收 6 要等脚本修好后用新脚本在真实环境重装一次再算。下一步：负责人建管理员，然后验"重启 worker 时作业变成已中断"。
- 2026-10-28 20:30 C-B 交付（20:09，快照 `refs/rdp/m0-11/C-B-out`，包括未跟踪的 `tests/setup_support.py`）。日志审计 0 条。评审打回第 1 轮（本段第 1/3 轮，提示 `prompt-C-r1.md`）：(1) 已安装时重复运行，setup.sh 调用不带参数的 `rdp status`，真实 CLI 返回 2；假 rdp 接受了这组参数，所以测试没发现，要求假命令的参数规则和真实解析器一致。(2) 一并修 install.sh 的 WorkingDirectory 引号缺陷，加 systemd-analyze verify 测试。
- 2026-10-28 20:31 负责人对五条提速办法回复"都采用"，已写进 `docs/agents/codex-workflow.md` 3.0（从 M1 起生效），7.1 补了本段的两条教训。pytest-xdist 依赖已批准，M0 合并后的第一张票顺带做。
- 2026-10-28 20:41 执行线在探针目录复跑 C-B 快照的 make check：全绿，pytest 2038 passed / 0 skipped，Vitest 250。变异抽查 8 处，7 处被测试发现（`assets/…/mutation_probe-C-B.txt`）。没被发现的是"非 Linux 平台检查"：测试只覆盖了不支持的 CPU 和非 glibc。非 Linux 本来也没有 systemd，不阻塞，记为待补；如果后面还有修复轮就顺带补上。
- 2026-10-28 21:10 第 1 轮交付（快照 `refs/rdp/m0-11/C-r1-out`），日志审计 0 条。重复运行改用合法的 status 参数；假 rdp 改用真实 `parse_command` 解析参数；WorkingDirectory 去掉引号、`%` 写成 `%%`；新增安装、升级 × 三种路径的 `systemd-analyze verify` 测试。评审通过。实现提交 `9d90249`（`实现：一键部署脚本（含单元 WorkingDirectory 引号修复）`，钩子全绿：pytest 2055 passed / 0 skipped，Vitest 250）。下一步验收 9 演练（`drill9.sh 9d90249`）。
- 2026-10-28 21:50 验收 9 演练（`drill9.sh 9d90249`，日志 `drill9-run.log`）失败。Node 22.23.2 下载、校验、安装成功；uv 和 pnpm 没装上。执行线只读核实了原因：(1) api.github.com 的 TLS 握手偶发失败，curl --retry 不重试连接错误；(2) GitHub 未认证限流 403，出口 IP 是共用的；(3) pnpm 11 的 asset 是 `pnpm-linux-<arch>.tar.gz`，不是独立二进制；(4) uv 自检要求整行等于 `uv 0.13.5`，真实输出带 `(x86_64-unknown-linux-gnu)`；(5) 没有终端、没有配置时，先下载工具才报错，退出码也不是 2。打回第 2 轮（本段 2/3，`prompt-C-r2.md`）。负责人中途拒绝了执行线在 scratchpad 里下载 uv/pnpm 包的操作，所以改为只读查看 GitHub 发布页 HTML，确认 asset 名字。
- 2026-10-28 22:32 第 2 轮交付（快照 `refs/rdp/m0-11/C-r2-out`），日志审计 0 条（也查了 github.com，没有出现）。提交 `d1fc95e`（钩子全绿）。重跑验收 9 演练。
- 2026-10-28 22:35 在 `d1fc95e` 上重跑验收 9（`drill9-run.log`）。工具自动安装全部成功：Node 22.23.2、uv 0.13.5、pnpm 11.22.0。问答失败在挂载快照：binfmt_misc 有 autofs 和 binfmt_misc 两层叠加挂载，代码把"挂载点重复"当成非法，拒绝了整份快照。执行线用事先写好的配置跑后半段（`drill9-existing-config-*.log`、`drill9/*.png`）：install、建管理员、健康检查、DRILL PASS、Ctrl+C 退出码 0、重复运行只报告状态（退出码 0），全部通过。真实 `ip -j` 快照生成地址列表正常。打回第 3 轮（本段 3/3，`prompt-C-r3.md`）：叠加挂载改为逐行标"stacked_mount"、不可选，不再拒绝整份快照（执行线按预批改这条契约的含义）。
- 2026-10-28 23:13 第 3 轮交付（快照 `refs/rdp/m0-11/C-r3-out`），日志审计 0 条。提交 `67271a2`（钩子全绿：pytest 2095 passed / 0 skipped）。重跑完整的验收 9 演练（含问答）。
- 2026-10-28 23:36 在 `67271a2` 上跑验收 9。两次完整运行（`drill9-run-67271a2-ratelimited*.log`）都停在 GitHub 未认证限流：脚本按第 2 轮的设计给出了限流提示和可重试时间，没有跳过校验。出口 IP 由 Clash 轮换，有的 IP 额度已经用完。第一次卡住是执行线的驱动脚本没去掉颜色码，已修。问答段改用本机已有的固定版本工具跑（`drill9q.sh` → `drill9q-run.log`、`drill9q/*.png`），通过：问答选中 dataset1、dataset2（编号 8、9），生成的配置是 0600、内容正确，安装、建管理员、健康检查都通过，DRILL PASS，Ctrl+C 退出码 0，重复运行只报告状态（退出码 0），无终端、无配置时退出码 2。工具自动安装已在 `d1fc95e` 那次运行中真实走通（Node、uv、pnpm 都装上并通过自检）。**遗留问题：GitHub API 限流会让别的机器第一次安装失败**，建议把 uv、pnpm 的 sha256 按架构固定在脚本里，改从 github.com/…/releases/download 下载，不再调用 API。本段打回已满 3 轮，按 6.3 交负责人决定。
- 2026-10-28 23:48 负责人："你来做决定好不好，我没精力处理了"。执行线据此决定：(1) 本段加第 4 轮，把 uv、pnpm 的 sha256 固定在脚本里，改从 releases/download 下载，避开 API 限流；(2) 修好后用 upgrade.sh 把真实部署升级到最终提交，账号和数据保留，并验证单元在真实 systemd 下能启动、重启 worker 时运行中的作业会被中断。合并仍等负责人一句"合并"。
- 2026-10-28 23:49 派第 4 轮（`prompt-C-r4.md`）：uv、pnpm 的 sha256 固定在脚本里（执行线从官方 release asset digest 读取，核对过两次），改从 releases/download 下载，不再调用 api.github.com。
- 2026-10-29 00:28 第 4 轮交付（快照 `refs/rdp/m0-11/C-r4-out`），日志审计 0 条，四个固定摘要和执行线给出的一致。提交 `b556311`（钩子全绿，pytest 2103 passed / 0 skipped）。重跑完整的验收 9。
- 2026-10-29 00:37 验收 9 在 `b556311` 上全部通过（`drill9-run.log`、`drill9/*.png`）：真实联网自动装上 Node 22.23.2、uv 0.13.5、pnpm 11.22.0（不再调用 GitHub API）；问答选中两块盘，生成 0600 配置；安装、建管理员、健康检查、DRILL PASS 全部通过；Ctrl+C 退出码 0；重复运行只报告状态（0）；无终端时退出码 2。验收 6：用 `upgrade.sh --commit b556311 --yes` 升级真实部署（`real-upgrade-run.log`），升级前把手修过的单元备份到 `~/.cache/rdp-dispatch/m0-11/*.hotfix`。升级后版本 `0.1.0 (b556311)`；单元由修好的模板重新生成，WorkingDirectory 不带引号，systemd-analyze verify 通过；两个服务 active、enabled；127.0.0.1 和局域网 10.1.179.3 的 health 都是 ok；起停日志齐全，退出码 0；账号数据保留；egopro-restore 没动。本机访问自己的 Tailscale 地址 100.82.81.44 超时（连 22 端口也超时，问题不在平台），早先 19:39 时是通的，记为环境现象。还剩"重启 worker 时运行中作业变成已中断"：需要负责人登录后提交一个长作业。
- 2026-10-29 02:30 负责人："合并，接着做"。执行线按 3.7 合并。"重启 worker 时作业变成已中断"这一项等负责人下次登录后提交长作业再补验。
