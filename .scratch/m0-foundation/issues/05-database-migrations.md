# 数据库与迁移

Status: done

## 依据

- M0 spec 第 05 张；S1 状态目录。
- ADR 0002（SQLite + 同步写法的 SQLAlchemy 2 + Alembic）；0003 第六节 (9)：WAL、打开外键、时间用 UTC、改表结构一律走迁移、不存密码。
- ADR 0005：Web 和 worker 两个进程只通过 SQLite 里的作业表联系，所以两个进程会同时读写同一个数据库文件。
- ADR 0006：数据库只放能重建的数据集索引，加上机器人、采集任务、工具、作业记录、账号、日志。
- 第 4 张 E2：报错表。依赖：第 4 张合并以后开工。
- 已批准的依赖：sqlalchemy、alembic（03 号票 M0 首批清单）。

## 目标

平台有一个数据库，两个进程都能安全地同时用它；表结构只通过迁移改；存进去的时间一定是 UTC。

## 范围

**连接**（`rdp.infra.db`）
- 数据库文件是状态目录里的 `rdp.sqlite3`，路径从第 3 张的状态目录取。
- 每个连接打开时设置：WAL 模式、`foreign_keys=ON`、`busy_timeout` 5 秒（另一个进程正在写时最多等 5 秒，再等不到就按"冲突"报错）。
- 同步写法的 SQLAlchemy 2：一个建引擎的函数，一个"一次工作单元一个会话"的上下文管理器，正常退出提交、异常退出回滚。Web 每个请求用一个会话，以 FastAPI 依赖的方式提供。
- **UTC 列类型**：一个自定义列类型，写入时拒绝不带时区的时刻，换算成 UTC 后存成 ISO 8601 文本（例如 `2026-10-23T02:00:00.123456Z`）；读出来是带时区的 UTC 时刻。换算直接用第 1 张的 `ensure_utc`。所有时间列一律用它。

**迁移**
- Alembic 的迁移脚本放在 `src/rdp/infra/db/migrations/`，由 Codex 写，和别的代码一样过检查链和评审。
- 第一个迁移只建报错表（第 4 张 E2）：错误编号、发生时间（UTC）、类别、一句话、完整的异常链和 traceback、来源（请求或作业）。另加一个按时间清除过期记录的函数，保留天数来自配置，默认 30；谁按时调用它，放在第 9 张「作业调度资源」的定时作业。
- 运维命令先做成一个函数 `migrate`（升级到最新），第 11 张再接进命令入口。
- 迁移规则见「待负责人确认」第 1、2 条。

**报错表接上第 4 张**：接口的统一异常处理里，程序缺陷除了写运行日志，还按错误编号写进报错表；页面按编号点开看的接口也在本票做。

**手册**：运维手册加一节：数据库在哪、怎么升级、升级前的自动备份在哪、出问题怎么恢复。

## 不在本票

- 账号、日志、作业的表（第 6–8 张各自建）。
- 定期备份（M0 第 12 张，等「备份方案」）。

## 允许改的受保护文件

| 文件 | 允许做什么 |
|---|---|
| `pyproject.toml` | 加 `[tool.alembic]` 或 Alembic 需要的配置；依赖表只由 Claude 用 `uv add` 写 |

依赖：`uv add sqlalchemy alembic`（已批准），由 Claude 在派工 A 之前装好并做依赖提交。

## 验收

1. **连接设置**：新连接上 `PRAGMA journal_mode` 是 `wal`，`foreign_keys` 是 1，`busy_timeout` 是 5000。
2. **两个进程**：测试里用两个进程同时写同一个临时数据库，都成功；一个进程长时间持有写事务时，另一个在约 5 秒后以"冲突"失败，不是挂住不动。
3. **UTC**：写入不带时区的时刻被拒绝；写入 +08:00 的时刻，读出来是同一时刻的 UTC；微秒不丢。
4. **会话**：异常退出时回滚，数据库里没有半条记录。
5. **迁移**：空数据库 `migrate` 后到最新版本；再跑一次什么都不改；Alembic 的自动对比（模型和数据库）没有差异。
6. **升级前备份**：`migrate` 有待执行的迁移时，先备份一份数据库，备份能打开、内容一致；没有待执行的迁移时不备份。
7. **版本不对拒绝启动**：数据库版本落后于代码时，建应用的函数报错，提示先运行 `migrate`。
8. **报错表**：一个意外异常经接口返回 500 后，用响应头里的编号能查到完整报错；超过保留天数的记录被清除函数删掉。
9. **先红后绿、文件归属、契约**：同第 2 张的验收第 12 条。
10. **能演示**：Claude 在临时状态目录里跑 `migrate`，起应用，触发一个演示用的程序缺陷，在页面上按错误编号点开完整报错。

## Claude 的步骤

按 `codex-workflow.md` 3.1–3.7 走：开票 → 装依赖并做依赖提交 → 派工 A → 骨架关卡交负责人 → 契约提交 → 派工 B → 评审 → 负责人"合并"。违规试验加一项：一个时间列没用 UTC 列类型，评审能发现（这项是〔审〕，靠 `/code-review` 的 Standards 轴）。

## 风险

- **SQLite 的写锁是整个数据库一把**：Web 和 worker 同时写时，后来的要等。M0 的写入量很小，没问题；M1 的重新扫描每 10 分钟写一次索引，要控制成一个短事务，在 M1 的工单里实测。
- **WAL 文件和备份**：开了 WAL 以后，数据库是三个文件（`.sqlite3`、`-wal`、`-shm`），直接复制可能复制到不一致的状态。所以备份一律用 SQLite 自己的备份接口，本票的"升级前备份"就这样做，第 12 张的定期备份也照这样做。
- **数据库放在系统盘上**：系统盘还剩约 330 GB（2026-10-23 `df -h /`），M0 的数据量可以忽略。备份方案定了以后，再看要不要把备份放到 NAS。

## 待负责人确认

1. **迁移只往前，不写降级脚本；升级前自动备份？**
   - 升级出问题时，用升级前的备份恢复，而不是跑降级脚本。降级脚本很少有人测，真要用时多半也是坏的。
   - `migrate` 每次真正升级前，用 SQLite 的备份接口复制一份到状态目录的 `backups/` 下，文件名带时间和版本，只留最近 5 份。
   - 建议：是。
2. **不自动升级：版本不对就拒绝启动，由人运行 `migrate`？**
   - Web 和 worker 启动时只检查数据库版本，落后就拒绝启动，并提示先运行 `migrate`；不在启动时自动升级。
   - 理由：两个进程同时启动、同时去升级会互相踩；升级是一个应该有人看着的动作。第 11 张会把它写进升级步骤。
   - 建议：是。
3. **时间存成 ISO 8601 文本，不存成整数时间戳？** 用 `sqlite3` 命令行直接查数据库时能看懂，按文本排序也就是按时间排序（统一用 UTC 和固定位数）。
   - 建议：是。

## Comments

- 2026-10-23，起草（主会话）。等负责人过目，回答「待负责人确认」后改成 `ready-for-agent`；第 4 张合并以后才能开票。
- 2026-10-23，负责人批准本票（"都按推荐来"）：
  - **F1**：迁移只往前，不写降级脚本；`migrate` 真正升级前用 SQLite 备份接口备份到 `backups/`，只留最近 5 份。
  - **F2**：启动时只检查数据库版本，落后就拒绝启动并提示运行 `migrate`，不自动升级。
  - **F3**：时间存 ISO 8601 UTC 文本，固定位数。
  - Status 改成 `ready-for-agent`。等第 4 张合并以后再开票。

- 2026-10-24 18:25（+08:00），第 1 步开票（执行线）。扫过 `.scratch/m*/issues/*.md` 的 `Status:` 行：01–04 是 done，其余都是 `ready-for-agent`，没有别的实现票在进行中；没有在跑的 `codex exec`。Status 改成 `in-progress`。`git worktree add -b t/m0-05-database-migrations ~/桌面/robot-data-platform.wt/m0-05-database-migrations main`，在 `d1d1091`。`uv sync --frozen`、`src/web/` 里 `pnpm install --frozen-lockfile --offline` 后，基线 `make check` 十一步全绿：ruff 通过；basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`；契约检查 `问题总数: 0`；pytest `329 passed, 1 warning`（warning 同第 2 张起的 starlette 弃用警告）；OpenAPI 过期检查"均未过期"；Vitest `55 passed`；用时 13.9 秒。跑前跑后 `git status --porcelain --untracked-files=all` 都为空；`core.hooksPath` 是 `.githooks`。输出 `<执行线临时目录>/m0-05/baseline-check.txt`。
- 2026-10-24 18:27（+08:00），**依赖提交**（执行线，已批准的 sqlalchemy、alembic）。在工作目录里 `uv add sqlalchemy alembic`：装上 **sqlalchemy 2.1.6**、**alembic 1.20.1**，传递依赖 mako 1.4.3、markupsafe 3.0.4（typing-extensions 已有）；没有 greenlet。PyPI 上核对过：两者都是当前最新版（sqlalchemy 2.1.6 发布于 2026-10-21，alembic 1.20.1 发布于 2026-10-22），MIT 许可，`Production/Stable`。`pyproject.toml` 的依赖表加了 `alembic>=1.20.1`、`sqlalchemy>=2.1.6`，`uv.lock` +75 行，别的没动。本机 Python 内置 sqlite 3.53.1。普通 `git commit`：`c188444 依赖：sqlalchemy、alembic（数据库与迁移）`，经过钩子，十一步全绿（pytest `329 passed`，Vitest `55 passed`）；提交后工作目录干净。
- 2026-10-24 18:30（+08:00），第 2 步派工 A（新会话）。
  - 提示 `assets/05-database-migrations/prompt-A.md`：派工 A 模板，交付 `rdp.infra.db`（建引擎、每个连接的 WAL/外键/`busy_timeout` 5000、一次工作单元一个会话、UTC 列类型、共用 `MetaData` 和约束命名、报错表模型、写/查/清除报错三个函数、Alembic `env.py` 和第一个迁移、`migrate`、版本检查）、`rdp.api` 的会话依赖、程序缺陷写报错表、按编号查报错的接口、前端把查报错接到 `DiagnosticCard` 的 `loadDetails`，以及跳过的测试清单。要 Codex 在契约里定下并说明的：SQLite 延迟事务升级时立刻 `SQLITE_BUSY` 的坑怎么处理、等锁超时怎么转成 `ConflictError`；UTC 列类型拒绝无时区值时抛什么、读到坏文本怎么办；报错表的主键、来源（请求编号是 uuid hex、作业编号是整数）、traceback 长度上限；清除函数"恰好等于保留天数"的边界；保留天数的配置项放哪、叫什么（改第 3 张的 `PlatformConfig`）；`downgrade()` 写成什么；`env.py` 不碰全局日志、`render_as_batch`；`migrate` 不依赖仓库的 `pyproject.toml`/`alembic.ini`；空库要不要备份、`backups/` 权限和位置（是否改 `StatePaths`）、失败时留下什么、两个 `migrate` 同时跑；版本落后/没有版本表/比代码新各报什么；`create_app` 怎么拿到数据库（改已获批签名，交骨架关卡）和引擎生命周期；报错表在哪一层写、异步中间件里怎么调同步写入、写失败不能掩盖 500；查报错接口本票不鉴权（第 6 张加）；会话依赖的提交时机（核对 fastapi 0.161.1 源码）。允许改的受保护文件只有 `pyproject.toml` 的 `[tool.alembic]`；import-linter 要改就停下报告。
  - 快照 `refs/rdp/m0-05/A`（`fd749ae`，树和 `c188444` 相同）。会话 `01a16d74-8900-7312-a1f4-e90e3315009f`。
  - 命令：在工作目录里 `timeout 60m codex exec -C <工作目录> -s workspace-write -c 'sandbox_workspace_write.network_access=true' -m gpt-6-astra -c 'model_reasoning_effort="high"' --json -o assets/…/out-A.md - < prompt-A.md`。运行日志 `<执行线临时目录>/m0-05/ev-A.jsonl`、`err-A.txt`。
  - 派工前：codex-cli 0.163.0；`~/.codex/config.toml` 的 `base_url` 现在是本机 `127.0.0.1:15721/v1`（不再是手册第 9 节写的 `10.1.179.3:8088`），直连有 HTTP 响应（404）；旧网关 `10.1.179.3:8088` 直连 200。手册第 9 节的网关地址要更新，报主会话。
- 2026-10-24 18:50（+08:00），派工 A 交回，第 3 步审骨架（`codex-workflow.md` 3.3）。
  - 运行：本机时间 04:28–04:48（−06:00），退出码 0，最后一条 `turn.completed`，`out-A.md` 在 assets；stderr 为空，开头两条 `disable_response_storage` 的 `error` 是已知现象；没有网关断开（运行日志里匹配到的 "stream disconnected" 在 `cat` 工单的输出里）。
  - **重跑**：工作目录 `make check` 退出码 0，十一步全绿，用时 14.2 秒：basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`；契约检查 `问题总数: 0`；pytest `329 passed, 172 skipped, 1 warning`（warning 同基线）；OpenAPI 过期检查"均未过期"；Vitest `55 passed | 22 skipped`。跑前跑后 `git status --porcelain --untracked-files=all` 相同。输出 `<执行线临时目录>/m0-05/A-done-check.txt`。
  - **文件归属**：工作目录 27 个改动，全在 `src/`、`tests/` 下：改了 `src/rdp/api/{__init__,errors}.py`、`src/rdp/infra/config.py`、`src/web/src/HealthPage{,.test}.tsx`、`src/web/src/api/{openapi.json,schema.d.ts}`（`make api-types` 生成）；新文件 `src/rdp/infra/db/{__init__,connection,utc,models,records,migration}.py`、`src/rdp/infra/db/migrations/{__init__,env}.py`、`…/versions/{__init__,v0001_error_reports}.py`、`src/rdp/api/{database,error_details}.py`、`src/web/src/api/errorDetails{,.test}.ts`、`tests/test_db_{config,connection,utc,records,migration}.py`、`tests/test_api_database.py`。受保护文件对依赖提交 `c188444` 的 diff 为空（Codex 认为不需要 `[tool.alembic]`，没加）。主仓库目录 `-- src tests` 为空，非规划文件只有负责人的 `Read_First_What're_Files_Meaning?.md`。**通过。**
  - **运行日志**：30 条命令（读规划文件用主仓库绝对路径；读 sqlalchemy `sqlite/base.py` 的 `sqlite_transactions`、fastapi 依赖退出时机、alembic `script/base.py` 的源码；`make api-types` 2 次；`make check` 5 次，前 3 次失败后修好）；文件用 apply_patch 写（32 次）。两个旧项目的命中只在 `cat AGENTS.md`、brief 的输出里，没有命令碰它们或 `/mnt`；安装、联网命令的 grep 无结果；没有碰 `.git/info/exclude`、真实的 `~/.local/share/rdp`、`~/.config/rdp`。命令清单 `<执行线临时目录>/m0-05/A-commands.txt`。**通过。**
  - **审骨架**：公开的 `create_database_engine`、`session_scope`、`translate_database_error`、`UTCDateTime.process_bind_param`/`process_result_value`、`write_error`、`find_error`、`clear_expired_errors`、`migration_config`、`check_database_version`、`migrate`、`run_migrations`、`upgrade`、`downgrade`、`configure_database`、`get_session`、`get_read_session`、`get_error_details`、`report_error_with_database` 六项齐全，内容合格；`ErrorReportRow`、`ErrorRecord`、`MigrationResult`、`UTCDateTime`、`ErrorRetentionConfig`、两个 404/422 子类都有 `Attributes:`；TS 的 `fetchErrorDetails`、`createErrorDetailsLoader` 的 TSDoc 六项齐全。测试 172 + 22 个跳过，对着每条 `Raises:` 和验收第 1–8 条都找得到（验收 1 `test_pragmas`；验收 2 `test_process_success`/`test_process_timeout`（4–10 秒上下界）/`test_process_cleanup`；验收 3 `test_bind_offset`/`test_roundtrip`；验收 4 `test_session_rollback`；验收 5 `test_migrate_new`/`test_migrate_noop`/`test_compare_metadata`；验收 6 `test_backup_contents`/`test_migrate_noop`；验收 7 `test_configure_version`；验收 8 `test_report_unknown`/`test_clear_boundary`）。新增豁免只有 5 条骨架期的 `eslint-disable-next-line @typescript-eslint/no-unused-vars`，写了理由，B 必须删。没有新依赖，没有受保护文件申请。
  - **Codex 定下的要点**：驱动不自动开事务，写会话进入时就 `BEGIN IMMEDIATE`（避开 WAL 下先读后写立刻 `SQLITE_BUSY`），只读会话 `BEGIN` 加 `query_only`；`NullPool`；锁等待超时、约束冲突归冲突，库损坏归输入或数据问题，磁盘、权限、I/O 归外部失败，其余归程序缺陷，数据库层不打日志。UTC 文本固定 27 个字符。报错表主键就是错误编号（请求是 uuid4 hex，作业是规范整数文本），来源种类单独一列，同一编号不覆盖。清除"严格早于 now − 保留天数"的记录，恰好等于的保留。`downgrade()` 显式拒绝。备份放 `root/backups`（在 db 模块里算，不改 `StatePaths`），新目录 0700、备份文件 0600，按文件名里的 UTC 时间只留最新 5 份，只删平台自己命名的文件；两个 `migrate` 同时跑，后一个立刻以冲突失败（状态目录上的 `flock`）。版本落后、没有版本表、比代码新、未知版本都抛输入或数据问题，提示先运行 `migrate`。程序缺陷用独立事务在线程里写报错表，最多等 6 秒，写失败只多记一条 ERROR，不掩盖原来的 500。会话依赖用 `scope="function"`，核对过 fastapi 0.161.1：响应发出前提交。
  - **契约变更申请**（改已获批的第 3、4 张契约，进骨架关卡）：① `create_app(web_dist, *, database: Engine | None = None)`；② `PlatformConfig` 加 `[errors] retention_days`（默认 30，1–3650，单位 UTC 24 小时）；③ `format_exception_report` 加 262144 字符上限，超了截断并加标记（改了 D2"完整"的承诺）；④ `handle_error`/`ErrorBoundary` 改为共用 `report_error_with_database`；⑤ `HealthPage` 把取详情回调传给卡片。②④⑤是本票范围本来就要的，按工单办；①③进摘要问负责人。
  - **评审意见，B 里处理，不用负责人拍板**：
    - 删 5 条骨架期 `eslint-disable`；两个 `yield` 依赖的 docstring 把 `Returns:` 改成 `Yields:`（Codex 已说明）；删掉 `create_app`、`handle_error`、`ErrorBoundary`、`format_exception_report`、`HealthPage`、`env.py` 里"工单 05 提案""骨架阶段"一类说法，只写现在的行为。
    - 版本不对抛输入或数据问题（不是冲突），按 Codex 的定。
    - 未知异常的 500 先发出、报错随后才写进表，立刻查可能短暂 404；页面是人点开才查，可以接受。
    - 演示（验收 10）由执行线做：临时状态目录里 `migrate`，起应用，用 `tests/diagnostics_demo.py` 触发程序缺陷，页面上点开完整报错并截图。
    - 违规试验加工单规定的一项：一个时间列不用 UTC 列类型，看 `/code-review` 的 Standards 轴能不能抓到。
    - 手册归 Claude：运维手册加"数据库"一节（位置、`migrate`、`backups/`、恢复步骤、升级前先停服务），配置文件一节加 `[errors] retention_days`。
  - **报主会话**（不属于本票，执行线没改）：
    - `GLOSSARY.md` 没有"平台状态目录""请求编号""作业编号"的独立条目（Codex 读的时候发现的）。
    - 手册第 9 节写的网关 `10.1.179.3:8088` 已经过期，现在 `~/.codex/config.toml` 的 `base_url` 是本机 `127.0.0.1:15721/v1`。
    - 记给后面的票：第 6 张给 `GET /api/errors/{error_id}` 加登录（所有登录账号都能看）；第 9 张定时调用 `clear_expired_errors`；第 11 张的启动入口必须把数据库引擎传给 `create_app`，关闭引擎前要等在途的报错写入线程。
  - 快照 `refs/rdp/m0-05/A-done`（`d468a9e`）。
- 2026-10-24 18:55（+08:00），**骨架关卡一页摘要**（执行线起草，交主会话转负责人）。
  1. **这张票做什么**：平台有了一个 SQLite 数据库，Web 和 worker 能同时安全地用；表结构只通过迁移改，升级前自动备份；时间一律存 UTC；程序缺陷的完整报错按错误编号存进数据库，页面上点开就能看。
  2. **函数清单**：

     | 模块 | 函数 | 职责 | 改动什么 | 什么情况下报错 |
     |---|---|---|---|---|
     | `rdp.infra.db.connection` | `create_database_engine(database)` | 建引擎；每个连接设 WAL、外键、等锁 5 秒 | 第一次连接时可能新建空库文件 | 路径不合法（输入）；目录、软链接、权限（外部） |
     | 同上 | `session_scope(engine, *, read_only=False)` | 一次工作单元一个会话：正常提交，异常回滚 | 提交或回滚 | 等锁 5 秒超时、约束冲突（冲突）；库损坏（输入）；磁盘、I/O（外部）；其余（缺陷） |
     | 同上 | `translate_database_error(...)` | 把底层数据库错误归到四类，带诊断 | 无 | 无 |
     | `rdp.infra.db.utc` | `UTCDateTime`（列类型） | 存成 `2026-10-23T02:00:00.123456Z`，读出是 UTC 时刻 | 无 | 写入不带时区的时刻、读到格式不对的文本（输入） |
     | `rdp.infra.db.models` | `metadata`、`Base`、`ErrorReportRow` | 所有表共用一套约束命名；报错表：编号、时间、类别、一句话、完整报错、来源 | 无 | 无 |
     | `rdp.infra.db.records` | `write_error` / `find_error` / `clear_expired_errors(*, now, retention_days)` | 写一条、按编号查一条、删掉过保留期的 | 报错表 | 编号重复（冲突）；参数不合法（输入）；同上四类 |
     | `rdp.infra.db.migration` | `check_database_version(database)` | 启动时比较数据库版本和代码版本 | 无（只读） | 落后、没迁移过、比代码新（输入，提示先运行 `migrate`） |
     | 同上 | `migrate(paths, *, now)` | 升级到最新；真正升级前先备份到 `backups/`，只留 5 份 | 数据库、`backups/` | 另一个 `migrate` 在跑（冲突）；备份失败（外部，不升级）；版本未知（输入） |
     | `…/migrations/versions/v0001_error_reports` | `upgrade()` / `downgrade()` | 第一个迁移只建报错表；降级一律拒绝 | 数据库 | 降级（输入） |
     | `rdp.api.database` | `configure_database`、`get_session`、`get_read_session` | 建应用时查版本；每个请求一个会话，响应发出前提交 | 无 | 版本不对，建应用失败 |
     | `rdp.api.error_details` | `GET /api/errors/{error_id}` | 按编号看完整报错（本票不鉴权，第 6 张加登录） | 无 | 查不到 404；编号格式不对 422 |
     | `rdp.api.errors` | `report_error_with_database(...)` | 程序缺陷写日志的同时写报错表，一次请求一条 | 报错表 | 写表失败不影响原来的 500，只多记一条日志 |
     | `rdp.infra.config` | `[errors] retention_days` | 报错保留天数，默认 30，1–3650 | 无 | 超范围拒绝启动 |
     | 前端 | `fetchErrorDetails`、`createErrorDetailsLoader` | 缺陷卡片"点开"时去查完整报错 | 无 | 查不到、失败、超时显示固定提示 |

  3. **测试清单**（194 个，都先跳过）：连接 32（三项连接设置、写事务先拿锁、提交和回滚、四类错误、两进程同时写都成功、一个进程占着写锁另一个约 5 秒后以冲突失败（量 4–10 秒）、子进程一定回收）；UTC 13（+08:00 读出同一时刻的 UTC、微秒不丢、拒绝不带时区、坏文本、按文本排序就是按时间排序）；报错表 31（编号格式、写/查/清除、"恰好等于保留天数"的边界、超长报告）；迁移 50（空库升级到最新、再跑一次什么都不改、模型和数据库自动对比无差异、备份能打开且内容一致、没有待执行迁移不备份、只留 5 份、备份失败不升级、两个 `migrate` 同时跑、降级被拒、不依赖仓库里的配置文件）；配置 5；接口 41（版本落后时建应用失败、会话提交时机、按编号查报错 200/404/422、500 之后能用响应头里的编号查到完整报错、写表失败不掩盖 500、日志和表里的报错逐字一致、不泄露口令）；前端 22。
  4. **要负责人拍板的**：
     1. **建应用的函数加一个"数据库"参数，可以不传？**
        - 传了：启动时检查数据库版本，不对就拒绝启动；程序缺陷存进报错表。
        - 不传：只给导出接口文档和旧测试用；报错只写日志，查报错接口返回 502。
        - 风险：真正启动时忘了传，报错就不进表。第 11 张做启动入口时必须传，并在那张的验收里加一条。
        - 建议：同意。
     2. **完整报错设一个上限：26 万字符（约 1 MB），超了截掉后面并标明"已截断"？**
        - 第 4 张定的是"完整保留"。没有上限的话，一个异常组或很深的递归能把一条报错撑到很大，日志和数据库都跟着变大（CODING_STANDARDS 2.7）。
        - 正常报错只有几 KB，远到不了上限。日志里和数据库里的是同一份截断结果。
        - 建议：同意。
     3. **升级数据库前先停 Web 和 worker，`migrate` 不替你检查？**
        - `migrate` 只防两个 `migrate` 同时跑，不检查 Web、worker 是不是还开着。
        - 服务开着时升级，正在跑的服务会用旧表结构读写新库。
        - 建议：同意。运维手册写明"先停服务再 `migrate`"，第 11 张的升级步骤照这样写；第 8 张有了 worker 单实例锁以后，再看要不要让 `migrate` 检查它。
  5. **结论：建议通过**（三条都按建议办，派工 B 里不用改契约）。检查都由执行线重跑过：`make check` 十一步 14.2 秒全绿，跑完不留痕迹；文件归属干净，受保护文件没动；运行日志没有碰旧项目、`/mnt`，没有安装和联网命令；没有新依赖；没打回（0 轮）。负责人说"通过"以后，做契约提交 `契约：数据库与迁移`，Status 改回 `in-progress`，派工 B。
  - Status 改成 `in-review`，交回主会话。
- 2026-10-24，骨架关卡：负责人回复"Agree"，按通过处理。
  - **B1**：`create_app` 的 `database` 参数**去掉默认值**（主会话在执行线建议上收紧）：每个调用方必须写明，只有导出接口文档和不需要数据库的旧测试显式写 `database=None`。签名变化属于获批的契约变更，派工 B 改，并把现有调用处都改成显式传参。第 11 张验收加"启动入口传入数据库引擎"。
  - **B2**：完整报错上限约 1 MB（26 万字符），超出截掉后面并标明"已截断"；日志和数据库存同一份。改第 4 张"完整保留"的含义，已获批。
  - **B3**：升级数据库前先停 Web 和 worker，`migrate` 不检查服务是否在跑；运维手册和第 11 张的升级步骤照此写；第 8 张有单实例锁后再议。
  - 执行线列的"B 里处理"各项照办。手册"数据库"一节和配置项 `[errors] retention_days` 由主会话在合并后写。
- 2026-10-24 19:50（+08:00），第 4 步契约提交（执行线）。先核对工作目录的树和快照 `A-done` 相同（`861ff0d`），再 `git add -A`，普通 `git commit`：`d36a888 契约：数据库与迁移`，经过钩子，十一步全绿（pytest `329 passed, 172 skipped`，Vitest `55 passed | 22 skipped`）；提交后工作目录干净。B1、B2 留给派工 B 改，契约提交用的是 `A-done` 的原样。Status 改回 `in-progress`。
- 2026-10-24 19:52（+08:00），第 5 步派工 B（续接）。
  - 提示 `assets/05-database-migrations/prompt-B.md`：派工 B 模板（逐个测试单独跑、先红后绿，pytest 和 Vitest 都写了单独运行的命令），加上 B1（`create_app(web_dist, *, database)` 去掉默认值，`openapi_export`、`tests/`、`tests/diagnostics_demo.py` 全部显式传 `database=None` 或临时库引擎，补"不传就 `TypeError`"的测试）、B2（262144 字符上限、尾部截断标记、日志和表同一份）、B3（契约不变）；评审意见（删 5 条 `eslint-disable`、`yield` 依赖改 `Yields:`、删掉所有"提案""骨架"说法、`env.py` 被 Alembic 加载时真正跑迁移但单独 import 不跑、首个迁移冻结不用 `create_all`、`compare_metadata` 真比、等待有上限且回收子进程和线程、不依赖本机时区、`HealthPage` 接上取详情、演示由执行线做）。最终回复五块。
  - 快照 `refs/rdp/m0-05/B`（`95fc407`，树和 `d36a888` 相同，工作目录干净）。
  - 会话 `01a16d74-8900-7312-a1f4-e90e3315009f`，先 `cd <工作目录>` 再 `timeout 60m codex exec resume -m gpt-6-astra -c 'model_reasoning_effort="high"' -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true' --json -o assets/…/out-B.md <会话> - < prompt-B.md`。运行日志 `<执行线临时目录>/m0-05/ev-B.jsonl`、`err-B.txt`。网关 `base_url` `127.0.0.1:15721/v1` 有响应。
- 2026-10-24 21:20（+08:00），派工 B 交回，第 6 步评审（`codex-workflow.md` 3.5），逐项结论：
  - **运行**：本机时间 05:48–06:48（−06:00），**`timeout 60m` 到时，退出码 124**。运行日志最后一条是 `make fmt && make check` 的 `item.completed`，没有 `turn.completed`，`out-B.md` 没写出来；stderr 为空，没有网关断开。按 6.3，**超时算一轮**，这一轮记为第 1 轮。Codex 当时已经去掉了全部跳过、正在跑最后的检查链，评审照常在超时时的工作区上做。快照 `refs/rdp/m0-05/B-done`（`86412ee`）。
  1. **重跑**：工作目录 `make check` 十一步全绿，33.4 秒；pytest `502 passed, 1 warning`（warning 同基线），Vitest `77 passed`，都没有跳过；跑前跑后 `git status` 相同。输出 `<执行线临时目录>/m0-05/B-done-check.txt`。**通过。**
  2. **文件归属**：30 个改动全在 `src/`、`tests/` 下（新文件 `src/rdp/infra/db/_validation.py`、`tests/db_support.py`）；受保护文件对契约提交的 diff 为空。主仓库目录 `-- src tests` 为空，非规划文件只有负责人的那个文件。**通过。**
  3. **对比契约**（对 `d36a888`，脚本 `<执行线临时目录>/m0-05/contract_diff.py`，输出 `B-contract-diff.txt`）：签名只有 `create_app` 去掉了 `database` 的默认值（B1）。docstring 的改动只有 B1（`create_app`、`openapi_export`、`mount_diagnostic_demo` 改成显式 `database=None`）、B2（`format_exception_report`）、评审意见要求的 `Yields:` 和删掉"提案""骨架"的说法。本票改过的文件里搜"提案""骨架""派工"，没有结果。**通过。**
  4. **先红后绿**：执行线用脚本 `<执行线临时目录>/m0-05/redgreen.py` 从运行日志解析每个测试第一次单独运行的结果（`B-redgreen.txt`）。后端新增的 173 个测试里 63 个先红、109 个一开始就绿（有 1 个被脚本误判，是一条 python 命令）；前端 22 个里 5 个先红、17 个先绿。每个测试都单独跑过。一开始就绿的比例高（约 63%），而说明理由的最终回复因超时没有写出来，所以加做**变异抽查**（`assets/…/mutation_probe.py`，输出 `mutation_probe-B-done.txt`）：20 个变异，抓到 15 个，漏 5 个。
     - 漏掉的里有 4 个是测试真的有缺口：只读会话不设 `query_only`（`test_read_exception` 的写入断言放在 `except` 分支里，写入成功时根本不断言）；旧备份清理不认文件名（`test_backup_foreign` 只有一份备份，清理根本没触发）；备份文件名去掉随机后缀（`test_backup_filename` 两次备份的 revision 不同，文件名本来就不会撞）；非缺陷也写进报错表（`test_report_nondefect` 只测了 404、422，而且写入会被 `report or ""` 的空串校验悄悄吞掉）。
     - 另 1 个是等价变异：`gcTime` 改大不影响，因为加载器结束后会显式删掉查询。
     - **不通过**，进修复清单。
  5. **运行日志**：510 条命令；没有一条碰两个旧项目或 `/mnt`；安装、联网命令的 grep 无结果；`/tmp` 下只有一条删除 pytest 自己临时目录里残留文件的命令；没有碰真实状态目录和 `.git/info/exclude`。命令清单 `<执行线临时目录>/m0-05/B-commands.txt`。**通过。**
  6. **两轴评审**：在探针工作目录里跑 `/code-review`（基点 `c188444`），原文整理在 `assets/…/code-review-B-done.md`。执行线复核了里面的关键结论。
     - Standards 轴：`test_backup_filename` 名不副实（docstring 说非 UTC，实际只传 UTC）。判断题有：
       - 诊断文案写死"5000 毫秒"、"1 至 3650"，没有引用常量；`ERROR_PERSIST_TIMEOUT_S` 没从 `BUSY_TIMEOUT_MS` 推导；
       - 2^63−1 是裸魔数；备份连接没传超时；
       - 新增一条 `eslint-disable … no-deprecated`（TanStack Query 5.104.5 弃用了 `fetchQuery`，提示改用 `queryClient.query`）；
       - 入口层 import 了私有模块 `rdp.infra.db._validation`；
       - 前端参数名还带骨架期的 `_` 前缀；`report or ""` 是死代码；
       - 几处重复：编号正则、只读写入判断、UTC 文本格式化、测试里的 `_reap`。
     - Spec 轴：
       - `test_configure_version` 只测了"库缺失"一种；
       - `test_process_success` 两个写事务没有真正重叠；
       - B2 截断以后"日志和表同一份"没有端到端测；
       - Alembic 自动对比不看 CHECK 约束，模型和迁移各抄一份 CHECK，会漂移。
     - 本票不是同步、录制、转换模块，不跑 `algorithm-code-review`。**不通过**，进修复清单。
  7. **违规试验**：`assets/…/violation_probe.sh`（照第 4 张，加了"`rdp.infra.db` 里 import fastapi"），输出 `violation_probe-B-done.txt`：基线全绿、跑完不留痕迹；13 种违规各失败在对应那一步（4 条 import-linter 都被拦住）；带理由的豁免照常全绿；普通 `git commit` 带 print 的代码被钩子拒绝。**16 项全部通过。**
     - 工单规定的〔审〕项"一个时间列不用 UTC 列类型"：在 `B-done` 上拍了一个探针提交 `refs/rdp/m0-05/probe-utc`（`41f878a`，加一张用 `DateTime(timezone=True)` 的表），让 Standards 轴的子 agent 只读看这个 diff，提示里不提 UTC。它第一条硬性违规就报了"CODING_STANDARDS 5.2：没有用 `UTCDateTime()`"。**通过。** 记录在 `assets/…/review_probe_utc-B-done.md`。
  8. **演示**：等修复轮交回后在最终快照上做。
  - **报负责人知道、执行线不改的**（会写进完工汇报）：
    - `BACKUP_TIMEOUT_S = 5.0` 是整个备份的总时长上限（已获批的契约就是这样写的），M1 库变大以后 `migrate` 可能超时；要改成只限制等锁时长，属于改含义，要回关卡。
    - 显式抛出的程序缺陷要等报错写进表（最多约 6 秒）才返回 500。
    - 没有 WAL 文件时用 `immutable=1` 读版本，依赖 B3"先停服务"。
- 2026-10-24 21:25（+08:00），**修复清单（r1）**。Status 改成 `changes-requested`。轮数：B 的超时是第 1 轮，r1 是第 2 轮。
  1. `test_backup_filename` 传 +08:00 和 −06:00 的时刻，断言文件名里是换算后的 UTC；再造"同一时刻、同一 revision"的两次备份，断言文件名不同、两个文件都在。（`tests/test_db_migration.py`）
  2. `test_backup_foreign` 先放至少 6 份平台命名的备份，加上人工文件、软链接和 `.partial`，跑 `migrate`；断言只删掉最旧的平台备份，其余原样。
  3. `test_read_exception` 的写入用 `pytest.raises` 直接断言失败（只读会话写入必须失败），不要放在 `except` 分支里。
  4. `test_report_nondefect` 照 docstring 覆盖输入（400、404）、冲突、外部失败、参数校验和"没有引擎"几种，都走真实应用；断言表里没有行，日志里也没有"完整报错持久化失败"。删掉 `report or ""` 的兜底，缺陷路径的报告不能是空的。
  5. `test_configure_version` 经 `create_app(..., database=engine)` 覆盖缺失、没有版本表、落后、领先或未知四种，每种都断言 `InputError` 和"先运行 migrate"。
  6. `test_process_success` 让两个写事务真正重叠：一个子进程持有写事务，另一个开始等锁，在 5 秒内放开；断言两个都成功、第二个确实等过（用 monotonic 量）。
  7. B2 端到端：报告超过上限时，日志里的报告段和表里的 `report` 逐字相同，都以截断标记结尾，长度不超过上限；`tests/test_api_database.py` 的 `test_report_bound` 照 docstring 测 N−1、N、N+1 三档。
  8. 加一个测试：迁移后的 `error_reports` 建表 SQL（`sqlite_master.sql`）和用模型 `MetaData` 在另一个空库里建出来的一致（规范化空白后比较），这样模型和迁移里两份 CHECK 漂移能被发现。
  9. 常量：诊断文案里的"5000 毫秒"用 `BUSY_TIMEOUT_MS`；`ERROR_PERSIST_TIMEOUT_S` 由 `BUSY_TIMEOUT_MS` 加 1 秒余量算出；`records.py` 的"1 至 3650"用 `MAX_RETENTION_DAYS`；2^63−1 在 Python、TS 各定义一个具名常量，注明"SQLite 有符号 64 位整数上限"。值都不变。
  10. 备份用的两个 `sqlite3.connect` 传 `timeout=BUSY_TIMEOUT_MS / 1000`。
  11. 前端：`fetchQuery` 换成 `queryClient.query(options)`，删掉 `no-deprecated` 的豁免，TSDoc 里的方法名跟着改（语义不变，措辞变更，执行线批准）；参数名去掉 `_` 前缀（`@param` 跟着改）；`boundedText` 的计数写清楚。
  12. 去重：`rdp.api` 不 import 私有的 `_validation`，改成公开模块或从包里导出；"只读会话写入 → DefectError（带诊断）"只留一处实现，`records.py` 那处不能抛不带诊断的 `DefectError()`；备份文件名的 UTC 格式化复用 `utc.py` 的写法；`test_db_migration.py` 复用 `_reap`；Python 侧的编号格式只留一处（迁移脚本里冻结的 CHECK 和前端那份除外）。
  13. 补交 B 因超时没写出来的最终回复（五块），第 5 块"先红后绿"要逐个说明一开始就通过的测试为什么通过；可以按文件分组写，但每个测试都要点到。
- 2026-10-24 21:30（+08:00），派工 r1（续接，第 2 轮）。提示 `assets/…/prompt-r1.md`（修复轮模板，十三条，加上"每条只跑相关测试、最后只跑一次 `make check`"以免再超时）；快照 `refs/rdp/m0-05/r1`（树和 `B-done` 相同）；会话 `01a16d74-…`，先 `cd <工作目录>` 再续接，命令同派工 B，`-o assets/…/out-r1.md`。运行日志 `<执行线临时目录>/m0-05/ev-r1.jsonl`、`err-r1.txt`。Status 改回 `in-progress`。
- 2026-10-25（+08:00），**负责人重启电脑**后接手。r1 已在重启前跑完（`out-r1.md` 写出，五块齐全）；工作目录里 r1 的改动完好。执行线的临时目录在 `/tmp` 下，重启后清空：`ev-r1.jsonl`、`B-done-check.txt`、`B-commands.txt`、`redgreen.py`、`contract_diff.py` 都没了，两个探针工作树已 `prune`。r1 的命令改从 Codex 自己的会话记录 `~/.codex/sessions/2026/10/24/rollout-2026-10-24T04-28-36-01a16d74-….jsonl` 里取（第 1594 行以后是 r1）。新的执行线临时目录：`/tmp/claude-1001/-mnt-datasets/72897f16-…/scratchpad/m0-05/`。负责人要求加快速度。
- 2026-10-25，r1 交回，第 6 步评审。快照 `refs/rdp/m0-05/r1-done`（`8bf1ad9`）。
  1. **重跑**：工作目录 `make check` 十一步全绿，35 秒；pytest `505 passed, 1 warning`，Vitest `77 passed`，没有跳过；跑前跑后 `git status` 相同。**通过。**
  2. **文件归属**：工作目录的改动全在 `src/`、`tests/` 下；主仓库目录非规划文件只有负责人的那个文件。**通过。**
  3. **对比契约**（对 `B-done`，签名和 docstring 用 ast 比）：docstring 没有变化；签名只有 `get_error_details` 的 `max_length=32`、编号正则改成引用 `REQUEST_ID_HEX_LENGTH`（32）和 `ERROR_ID_PATTERN`，值不变，OpenAPI 过期检查也通过。新增的是第 12 条要求的公开模块 `validation.py`、`_errors.py`、`utc.format_utc_text`。**通过。**
  4. **先红后绿**：`out-r1.md` 第 5 块逐个说明了 r1 的 10 个测试和 B 的全部测试。r1 是加强已有测试，实现本来就对，一开始就绿是预期的；用变异抽查验证（`mutation_probe-r1-done.txt`）：20 个变异抓到 19 个，B-done 时漏的 4 个全部抓到；剩下 1 个是 `gcTime` 等价变异。"详情查询重试"一项因 r1 改了缩进，脚本找不到变异点，手工跑过，抓到。**通过。**
  5. **运行日志**（从会话记录取，23 次工具调用）：没有碰两个旧项目和 `/mnt`；没有安装、联网命令；没碰 `.git/info/exclude` 和真实状态目录。读过一次执行线临时目录里的 `B-redgreen.txt`，只读，用来写第 5 块。**通过。**
  6. **两轴评审**（`code-review-r1-done.md`）：13 条全部落实，没有回归，Spec 轴没有缺失。剩下的：
     - 6.1：`_errors.py` 的只读写入诊断错误码写死 `0`，规则借用通用文案；`connection.py` 路径非法那处同样借用 `database_problem(..., 0)`，和 docstring 不一致。
     - 6.2：`errors.py` 新增 `raise RuntimeError("程序缺陷报告不能为空")`，不属于四类；遗留的 `raise DefectError()` 不带诊断。
     - docstring 和注释里还写死"5000 毫秒""5 秒"。
     - 不阻塞、记进完工汇报的遗留事项：请求编号规则放在 `rdp.infra.db.validation`，`rdp.infra.logging` 因此依赖数据库包，留到第 6 张前定；`format_utc_text` 和 `validation.py` 三个公开函数只有间接覆盖；`BUSY_TIMEOUT_MS / 1000` 出现 4 次；前端编号正则两份；`staleTime`、`gcTime` 未具名。
     **不通过**（前三项），进修复清单。
  7. **违规试验**：`violation_probe-r1-done.txt`，16 项全部通过。
  8. **演示**：在 r2 交回后做。
- 2026-10-25，**修复清单（r2）**，第 3 轮，也是最后一轮：只读写入和路径非法的诊断如实写；去掉 `RuntimeError` 分支，`raise DefectError()` 带诊断；docstring 和注释点出常量名（措辞变更，执行线批准）。提示 `assets/…/prompt-r2.md`；快照 `refs/rdp/m0-05/r2`（`c062bb7`）；会话 `01a16d74-…`，续接命令同前，`-o assets/…/out-r2.md`。运行日志 `<执行线临时目录>/m0-05/ev-r2.jsonl`、`err-r2.txt`。Status `in-progress`。
- 2026-10-25，r2 交回，第 6 步评审（按 2026-10-25 修订后的 3.5）。快照 `refs/rdp/m0-05/r2-done`（`cfd592d`）。Codex 退出码 0，运行日志最后一条 `turn.completed`，`out-r2.md` 五块齐全；自述 `make check` 跑了 2 次（第一次停在类型检查），偏离"只跑一次"，不影响结果。
  1. **重跑**：`make check` 全绿，34 秒；pytest `506 passed`，Vitest `77 passed`，没有跳过；跑前跑后 `git status` 相同。**通过。**
  2. **文件归属**：7 个文件，全在 `src/`、`tests/`；主仓库目录同前。**通过。**
  3. **对比契约**（对 `r2`）：docstring 改动是 r2 第 3 条批准的措辞（点出 `BUSY_TIMEOUT_MS`），加上 `report_error_with_database.Raises` 补一句"格式化报告为空时 `DefectError`"。这一句是 r1 删掉 `report or ""` 之后的缺陷路径，r2 第 2 条要求改成 `DefectError`，不改对外含义，执行线批准。`database_problem` 改成泛型（去掉 `cast`），私有函数。新增私有 `database_path_error`。**通过。**
  4. **先红后绿**：Codex 报 4 个新增或加强的测试都先红。变异抽查：r1 的脚本 18 个后端变异全部抓到（前端未改，沿用 r1 结论）；另对 r2 的 4 处行为各做一个变异（只读码写回 0、路径诊断换回通用诊断、编号不符不带诊断、空报告改回 `RuntimeError`），4 个全部抓到。**通过。**
  5. **运行日志** `ev-r2.jsonl`：没有安装、联网命令；出现的旧项目名和 `/mnt` 都只在读 `AGENTS.md`、工单时的输出里，没有命令访问。**通过。**
  6. **两轴评审**：本轮 diff 181 行，执行线直接读：三条都已落实，诊断如实，没有引入新的四类以外异常，没有新的硬性违规。**通过。**
  7. **违规试验**：本轮没改检查链，按修订后的 3.5 不做（r1-done 上 16 项全过）。
  8. **演示**（验收第 10 条）：在 `r2-done` 的探针目录里，临时状态目录 `migrate`（`0001_error_reports`，新库不备份），`DEMO_HEALTH=defect` 起应用，`/api/health` 返回 500 和错误编号；`/api/errors/<编号>` 返回完整报错，`occurred_at` 是 UTC；无头 Chrome 打开页面、点「完整报错」，显示发生时间、类别、来源和完整 traceback。截图 `assets/…/demo-r2-done.png`。发现长行撑出卡片边框，记进 `followups.md`。**通过。**
  - 八项通过。实现提交 `3000e66 实现：数据库与迁移`，经过钩子，十一步全绿；提交的树和 `r2-done` 相同，工作目录干净。探针工作目录已删。Status 改成 `in-review`，等负责人说"合并"。
- 2026-10-25，负责人说"合并"（原话"合并，挪"，"挪"指把请求编号规则移出 `rdp.infra.db`，作为第 6 张的前置）。主仓库目录 `merge --no-ff --no-commit`、`uv sync --frozen`、`pnpm install --frozen-lockfile`，`e5620f9 合并：数据库与迁移`，钩子十一步全绿（pytest `506 passed`，Vitest `77 passed`）。工作目录、分支、快照已删。Status `done`。
