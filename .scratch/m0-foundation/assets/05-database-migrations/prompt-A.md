你在工单「数据库与迁移」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-05-database-migrations（git worktree，分支 t/m0-05-database-migrations）里写契约骨架。

先读下面这些。规划文件一律用绝对路径读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件（比如工单的 Comments）。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md（尤其第 1、2、3 条（含 3.5 TSDoc）、5.1–5.5、第 6 条全部（6.2 状态码表、6.3 只在边界报告、6.10 敏感信息）、第 7 条、9.1 的表）
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/05-database-migrations.md（「范围」「验收」「风险」「允许改的受保护文件」，以及 Comments 里负责人批准的 F1–F3）
- 第 4 张工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/04-diagnostics-error-framework.md 的 Comments 里 E2、D1、D2 和完工汇报的"风险"（报错表、错误编号、`loadDetails` 回调、`ProblemResponse.error_id` 只收 uuid4 hex）
- 它引用的：/home/shawn/桌面/robot-data-platform/docs/adr/0002-技术栈.md、0005、0006；/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/spec.md 的 S1 和第 05 张那一行；/home/shawn/桌面/robot-data-platform/docs/brief/0013-环境事实更新-本机时区.md（本机时区 −06:00，数据库存 UTC）
- /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里相关的术语（平台状态目录、作业、作业编号、请求编号等）
- 工作目录里已有的代码：`src/rdp/infra/timeutil.py`（`ensure_utc`）、`src/rdp/infra/config.py`（`PlatformConfig`，未知项拒绝启动 C1）、`src/rdp/infra/state.py`（`StatePaths`、`DATABASE_FILENAME`、`STATE_DIRECTORY_MODE`）、`src/rdp/infra/logging.py`、`src/rdp/infra/diagnostics.py`（四类异常、`ALLOWED_HTTP_STATUSES`）、`src/rdp/api/__init__.py`（`create_app`、`_RequestContextApp`）、`src/rdp/api/errors.py`（`ErrorBoundary`、`_report_error`、`format_exception_report`）、`src/rdp/api/openapi_export.py`、`tests/diagnostics_demo.py`、`src/web/src/DiagnosticCard.tsx`（`loadDetails` 回调）、`src/web/src/api/`、`Makefile`、`pyproject.toml`
- 已装好的依赖：sqlalchemy 2.1.6、alembic 1.20.1（依赖提交 `c188444`，已批准）。本机 Python 内置 sqlite 3.53.1，fastapi 0.161.1，starlette 1.9.0。

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和完整契约文档写全：Python 是六项 docstring（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条），函数体只写 `raise NotImplementedError`；pydantic 模型、dataclass、枚举、SQLAlchemy 表模型写 `Attributes:`，每个字段（列）写含义、单位、取值范围、可空、默认值。TypeScript 是 TSDoc（CODING_STANDARDS 3.5），函数体只写 `throw new Error("未实现")`。
2. 测试清单写成跳过的测试：pytest 用 `pytest.skip`，测试的 docstring 写明它验证哪条契约行为；Vitest 用 `it.skip`，标题写明它验证哪条契约行为。对着每个函数 docstring 里的每条 `Raises:`、每种返回情况、每项副作用（包括失败时留下什么），逐条都有测试（CODING_STANDARDS 7.1），并覆盖工单「验收」第 1–8 条。
3. `make check` 跑到全绿（十一步）。骨架阶段已有接口的行为不变；如果骨架登记了新路由或改了 OpenAPI，用 `make api-types` 重新生成，不要手改生成文件。

本次交付（模块路径按工单）：
- **`rdp.infra.db`**（基础层的包；内部怎么分模块由你定）：
  - **连接**：建引擎的函数（输入是数据库文件路径，取自第 3 张的 `StatePaths.database`），每个新连接设置 WAL、`foreign_keys=ON`、`busy_timeout` 5000 毫秒（具名常量，注释写单位和出处）。"一次工作单元一个会话"的上下文管理器：正常退出提交、异常退出回滚，异常原样传播。Web 每个请求一个会话的 FastAPI 依赖放在入口层（`rdp.api` 下），基础层不 import fastapi。
  - **SQLite 事务的已知坑，请对着本地源码核对后在契约里定下办法**：Python `sqlite3` 驱动默认的"延迟开始事务"和 SQLAlchemy 的配合，见本地 `sqlalchemy/dialects/sqlite/base.py` 的 `sqlite_transactions` 一节；WAL 下一个先读后写的延迟事务升级成写事务时，可能立刻得到 `SQLITE_BUSY`、不等 `busy_timeout`。验收 2 要求"另一个进程正在写时最多等约 5 秒，再等不到就按'冲突'报错"。写明：事务怎么开始（例如写事务用 `BEGIN IMMEDIATE`，或者别的办法）、`journal_mode` 在哪一步设置（不能在事务里设）、等锁超时由哪一层、怎样转成第 4 张的 `ConflictError`（带诊断：对象、规则、实际、期望、后果、下一步），其他数据库错误归哪一类。
  - **UTC 列类型**：自定义列类型（SQLAlchemy `TypeDecorator`），写入时拒绝不带时区的时刻，用第 1 张的 `ensure_utc` 换算成 UTC，存成固定位数的 ISO 8601 文本（F3，例如 `2026-10-23T02:00:00.123456Z`：微秒总是 6 位、结尾 `Z`）；读出来是 `tzinfo=UTC` 的时刻，微秒不丢。读到格式不对的文本怎么办，定下来。拒绝时抛什么、SQLAlchemy 会不会把它包一层，写进 `Raises:`。
  - **表模型**：SQLAlchemy 2 的声明式写法，所有表共用一个 `MetaData`，约束命名规则（`naming_convention`）在这里定，以后第 6–8 张的表都用它。
  - **报错表**（第 4 张 E2）：错误编号、发生时间（UTC 列类型）、类别、一句话、完整的异常链和 traceback（就是 `format_exception_report` 的输出）、来源（请求或作业）。主键是什么、来源怎么表示（例如来源种类加编号；请求编号是 32 位 uuid4 hex，作业编号是整数，E2 说作业的错误编号就是作业编号）、同一个编号能不能有多条、traceback 文本有没有长度上限（CODING_STANDARDS 2.7，超长怎么截、截了怎么标明），定下来。
  - **写报错、按编号查报错、清除过期报错**三个函数。清除函数的输入包括"现在"这个时刻（作为参数传入，测试传固定时钟，7.5）和保留天数，返回删了几条；边界（恰好等于保留天数的那条删不删）写清。谁按时调用它是第 9 张的事，本票不做定时。
  - **保留天数来自配置，默认 30**（工单「范围」）：第 3 张的配置文件不认识的项会拒绝启动（C1），所以要在 `PlatformConfig` 里加一项。放在哪一节、叫什么名字、取值范围（参照 `LogConfig.retention_days` 的 1–3650 和 `MAX_RETENTION_DAYS`）、单位（UTC 的 24 小时，还是日历天），定下来。这是对第 3 张已获批契约的改动，写进第 3 块。运维手册由 Claude 改，你不用写。
  - **迁移**：Alembic 的 `env.py`、`script.py.mako`（如果需要）和迁移脚本放在 `src/rdp/infra/db/migrations/`。迁移脚本由你手写，和别的代码一样过 ruff、basedpyright 和契约检查（`upgrade()` 也是公开函数）。F1：只往前，不写降级脚本——`downgrade()` 写成什么（不定义，还是显式拒绝），定下来。第一个迁移只建报错表。
    - `env.py` 不要调用 `logging.config.fileConfig`，也不要改全局日志配置（第 3 张的运行日志由入口配置）。SQLite 改表要用 `render_as_batch`，定下来。
    - 运行时不依赖仓库里的 `pyproject.toml` 或 `alembic.ini`（装好的包里没有它们）：`migrate` 用代码构造 Alembic 的 `Config`，脚本位置指向包内目录。本票允许在 `pyproject.toml` 里加 `[tool.alembic]`，只在开发时手工跑 `alembic` 命令需要时才加，不需要就不加。
  - **`migrate`**（运维命令，先做成函数，第 11 张接进命令入口）：升级到最新。F1：有待执行的迁移时，先用 SQLite 的备份接口（`sqlite3.Connection.backup`，不直接复制文件，因为 WAL 下是三个文件）备份到状态目录的 `backups/`，文件名带 UTC 时间和升级前的版本，只留最近 5 份（具名常量）；没有待执行的迁移时不备份、不改任何东西。写明：空数据库（还没有文件）算不算"有待执行的迁移"、要不要备份一个空库；`backups/` 目录的权限（第 3 张新建目录是 0700，因为以后数据库里有口令哈希）；`backups/` 这个位置是加进第 3 张的 `StatePaths`（这会改已获批的契约，算契约变更，写进第 3 块）还是在 db 模块里算；备份或升级失败时留下什么（2.6）；"只留最近 5 份"按文件名还是按修改时间排序、只删平台自己命名的文件；两个 `migrate` 同时跑会怎样。
  - **版本检查**（F2）：一个函数比较数据库当前版本和代码里的最新版本。数据库落后、没有版本表（从没迁移过）、数据库版本比代码新或者代码里没有这个版本（降级了代码），各怎么报错，提示里写"先运行 migrate"；抛哪一类异常（四类之一），定下来并说明。
- **接到 Web 应用**（`rdp.api`）：
  - 验收 7："数据库版本落后于代码时，建应用的函数报错"。现在 `create_app(web_dist)` 不知道数据库在哪；`openapi_export` 和大量现有测试调用 `create_app(None)`。请提一个改法：例如加一个仅限关键字的参数（数据库引擎还是路径；能不能为 `None`，`None` 时报错表和查报错接口怎么办，生产入口会不会因此漏传），引擎的生命周期（谁创建、谁 `dispose`）。改 `create_app` 已获批的签名、Returns、Raises、Side Effects 属于改变含义的契约变更，写进第 3 块，交负责人在骨架关卡拍板；骨架里先按你的方案写好，现有测试的调用要能继续跑通。
  - **写报错表**：第 4 张的统一异常处理里，程序缺陷（未知异常和 `DefectError`）在写运行日志之外，再按错误编号写进报错表，一次请求只写一条。写明：在哪一层写（`handle_error` 还是 `ErrorBoundary`，或者 `_report_error`）；`ErrorBoundary` 是异步 ASGI 中间件，同步的数据库写入怎么调用（例如 `anyio.to_thread` / starlette 的 `run_in_threadpool`，不要阻塞事件循环）；写报错表本身失败时（数据库锁住、磁盘满）怎么办——不能掩盖原来的 500、不能让请求挂住，失败本身记进运行日志，记几次、什么级别，定下来；和请求的业务会话是什么关系（业务会话回滚了，报错记录也不能丢）。
  - **按编号查报错的接口**：例如 `GET /api/errors/{error_id}`，返回完整报错（时间、类别、一句话、异常链和 traceback、来源）。查不到返回 404（用输入或数据问题的 404 子类，带诊断，CODING_STANDARDS 6.2），编号格式不对返回 422。谁能看：第 4 张定的是"所有登录账号都能看"，登录在第 6 张才有，本票先不鉴权，在接口的 docstring 里写明，第 6 张加上。响应模型要进 OpenAPI，前端类型用 `make api-types` 生成。
  - **会话依赖**：Web 每个请求一个会话（FastAPI `yield` 依赖）。核对 fastapi 0.161.1 的源码：路由抛异常时依赖的 `yield` 之后能不能看到异常并回滚、提交发生在响应发出之前还是之后，按核对结果写契约。
- **前端**（`src/web/src/` 下）：把查报错接口接到第 4 张 `DiagnosticCard` 的 `loadDetails` 回调上（例如在 `src/web/src/api/` 里加一个用生成类型的取详情函数，`HealthPage` 把它传给卡片），这样程序缺陷卡片"点开"就显示完整报错。查不到、请求失败时卡片显示什么，契约写清。现有的 5 秒超时沿用。
- **测试**：放在 `tests/` 下，按模块分文件。只用 `tmp_path`，绝不碰真实的 `~/.local/share/rdp`、`~/.config/rdp`。
  - 验收 2 的两进程测试：用标准库 `multiprocessing`（`spawn` 上下文）在临时数据库上做，一个进程持有写事务，另一个约 5 秒后以"冲突"失败；用 `time.monotonic()` 量时长，断言一个上下界（例如 4–10 秒），超时保护要有，不能让 pytest 挂住；测完子进程都回收。
  - 验收 5 的"自动对比没有差异"用 Alembic 的 `compare_metadata`（或等价 API），对象是迁移后的临时数据库和表模型的 `MetaData`。
  - 验收 6 的备份测试要验证备份文件能打开、内容一致。

要特别注意的地方：
- 依赖只有 sqlalchemy、alembic（已装）。要是觉得还需要别的（例如 aiosqlite），停下来写依赖申请，不要绕。
- 日志、报错表、接口响应里不写口令、令牌、cookie、私钥，也不把整份请求体写进去（6.10）；报错表里的 traceback 和运行日志里的保持一致（D2），不额外加东西。
- 中间层不打日志（6.3）；数据库层把错误转成四类异常往上抛，不自己记日志。
- 本票允许改的受保护文件只有 `pyproject.toml` 的 `[tool.alembic]`。如果你发现 import-linter 合约需要改（例如登记 `rdp.infra.db` 的位置），或者别的受保护文件要改，停下，写进第 3 块，不要改。
- 不要写 `.git/info/exclude`（所有工作目录共用）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只允许加 `[tool.alembic]` 或 Alembic 需要的配置；依赖表不动，别的段不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 那步要能看出 passed 和 skipped 的数目，Vitest 那步要能看出 skipped 的数目）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请（对已获批的第 3、4 张契约的改动，例如 `create_app`、`StatePaths`、`PlatformConfig`）、依赖申请、受保护文件申请：没有就写"无"。
4. 拿不准、需要评审决定的地方，包括上面要你"定下来"的每一处：你定的是什么、为什么。
