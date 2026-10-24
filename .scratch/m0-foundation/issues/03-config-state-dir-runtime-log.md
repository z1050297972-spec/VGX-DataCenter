# 配置、状态目录与运行日志

Status: in-review

## 依据

- M0 spec（`.scratch/m0-foundation/spec.md`）第 03 张；S1 状态目录、S3 端口。
- 「可观测性与报错规范」（`.scratch/platform-v1/issues/09-observability.md`）Answer 的"运行日志"一节：格式、级别、两个文件、按天切分保留 30 天、关掉 uvicorn 访问日志。`CODING_STANDARDS.md` 6.4。
- ADR 0005：systemd 下只写文件，不往 stderr 输出。
- 流程：`docs/agents/codex-workflow.md`。依赖：第 2 张工单合并以后开工（要用它的 `create_app`）。

## 目标

1. 平台有一份配置：从哪里读、有哪些项、写错了怎么报。
2. 平台状态目录在第一次启动时建好，里面每样东西的路径只在一处定义。
3. Web 和 worker 都按「可观测性」定的格式写运行日志；作业编号、请求编号自动带上，不在函数之间手工传。

## 范围

**配置**（`rdp.infra.config`）
- 文件是 TOML，默认在 `~/.config/rdp/config.toml`；环境变量 `RDP_CONFIG` 可以指向别的文件（测试用临时文件）。用标准库 `tomllib` 读，pydantic 模型校验，读出来的配置对象不可变。
- 本票只放三组项，后面的票各自加自己的：
  - `state_dir`：默认 `~/.local/share/rdp`（S1）。
  - `[web]`：`host` 默认 `0.0.0.0`，`port` 默认 8600（S3）。
  - `[log]`：`level` 默认 `INFO`；`retention_days` 默认 30。
- 规则见「待负责人确认」第 1、2 条。

**状态目录**（`rdp.infra.state`）
- 一个函数根据配置给出所有路径：数据库文件、`logs/`、`logs/<作业类型>/`、worker 的单实例锁。后面的票只从这里取路径，不自己拼。
- 第一次启动时建目录，权限 `0700`，因为以后数据库里有口令哈希。目录已存在但不是目录、或者不可写，报错并说明是哪个路径。

**运行日志**（`rdp.infra.logging`）
- 标准库 logging，不加依赖。每条一行：`时间 级别 模块 中文消息 key=value…`；时间是带时区的本地时间，精确到毫秒，例如 `2026-10-21 16:15:02.123+08:00`。诊断的明细行缩进跟在后面（诊断对象在第 4 张，本票只留好多行消息的写法）。
- 一个配置函数，参数是进程名（`web` 或 `worker`）、日志目录、要不要同时写 stderr、级别。写 `logs/web.log` 或 `logs/worker.log`，每天零点切分，保留 `retention_days` 天。
- 上下文：作业编号、请求编号放在 contextvars 里，日志配置自动把它们加到每条的 key=value 后面。提供一个上下文管理器设置它们，退出时恢复原值。
- Web：`create_app` 加一个中间件，每个请求生成一个请求编号，放进上下文，并在响应头 `X-Request-ID` 里返回。uvicorn 的访问日志关掉，uvicorn 自己的启动和报错日志走同一套格式。
- 本票不写启动 Web 和 worker 的运维命令（第 11 张），所以"要不要写 stderr"是参数，由第 11 张的命令和 systemd 单元来传。

**手册**：在 `docs/manual/` 新建「运维手册」的第一节：配置文件在哪、每项的含义和默认值、状态目录里有什么、日志在哪、怎么看。由 Claude 按实现写。

## 不在本票

- 诊断对象、四类异常、接口的统一异常处理（第 4 张）。
- 作业日志的写法（第 8 张）；本票只给出它的目录。
- 启动命令和 systemd 单元（第 11 张）。

## 允许改的受保护文件

| 文件 | 允许做什么 |
|---|---|
| `pyproject.toml` | 只在 ruff、basedpyright 需要时调整配置，每条写理由；依赖表不动 |

本票不需要新依赖：pydantic 已在 03 号票批准，第一次直接 import 时由 Claude 声明为直接依赖（`CODING_STANDARDS.md` 9.2）；如果第 2 张已经声明了，就什么都不用装。

## 验收

1. **配置**：没有配置文件时用默认值；`RDP_CONFIG` 指向的文件生效；写错类型、写了不认识的项、端口越界，各报一条错，指明文件、项名、实际值和期望。
2. **状态目录**：临时目录里第一次调用就建好全部子目录，权限 `0700`；路径被一个普通文件占着时报错；第二次调用不改动任何东西。
3. **日志格式**：一条日志的时间、级别、模块、消息、key=value 和上面的格式逐字一致（测试里固定时钟和时区，`CODING_STANDARDS.md` 7.5）。
4. **上下文**：在上下文管理器里写的日志带上作业编号；退出后不再带；两个并发的请求各自带自己的请求编号，不串。
5. **切分**：跨过零点后写到新文件；超过保留天数的旧文件被删掉（测试里用可控的时钟，不真的等一天）。
6. **两个进程**：Web 只写 `web.log`，worker 只写 `worker.log`；"不写 stderr"时 stderr 没有输出。
7. **请求编号**：每个响应带 `X-Request-ID`，和这次请求的日志里记的一致；`/api/health` 不产生访问日志。
8. **先红后绿、文件归属、契约**：同第 2 张的验收第 12 条。
9. **能演示**：Claude 用一份临时配置起应用，`curl /api/health` 两次，`web.log` 里有两条带不同请求编号的行，和响应头一致。

## Claude 的步骤

按 `codex-workflow.md` 3.1–3.7 走，不用拆段（没有新依赖）：开票 → 派工 A → 骨架关卡交负责人 → 契约提交 → 派工 B → 评审 → 负责人"合并"。违规试验这次只需要确认已有的检查链照常工作，不新增检查。

## 风险

- **按天切分和多进程**：标准库的 `TimedRotatingFileHandler` 只在一个进程写一个文件时可靠。Web 和 worker 各写各的文件，所以没问题；但 uvicorn 如果以后开多个 worker 进程，就会出错。v1 的 Web 只跑一个进程，在模块注释里写明这个前提。
- **切分时机**：标准库是在"零点之后的第一条日志"时才切分，不是准点。夜里没有日志时，文件名上的日期会晚一些，不影响按天保留。
- **时区**：本机时区以后改了，日志里的时间偏移会跟着变。数据库照旧存 UTC，不受影响。

## 待负责人确认

1. **配置文件可以没有，写了不认识的项就拒绝启动？** 没有配置文件时全部用默认值，启动时在日志里记一行"使用默认配置"；文件里出现不认识的项（多半是拼错了）、类型不对，就拒绝启动并说明哪一项错了，不默默忽略。
   - 建议：是。
2. **只用一个环境变量 `RDP_CONFIG`，不支持用环境变量覆盖单个配置项？** 所有配置都写在文件里，查问题时只看一个地方。
   - 建议：是。
3. **运行日志的保留天数写在配置文件里，网页上不能改？** 「交互形态」说操作日志和登录日志的保留期管理员能在网页上调；运行日志是给维护的人看的，改它要改配置文件、重启服务。
   - 建议：是。

## Comments

- 2026-10-23，起草（主会话）。等负责人过目，回答「待负责人确认」后改成 `ready-for-agent`；第 2 张合并以后才能开票。
- 2026-10-23，负责人批准本票（"都按推荐来"）：
  - **C1**：没有配置文件时全部用默认值，日志里记一行"使用默认配置"；不认识的项、类型不对，拒绝启动并说明哪一项错了。
  - **C2**：只用 `RDP_CONFIG` 指定配置文件位置，不支持用环境变量覆盖单个配置项。
  - **C3**：运行日志的保留天数只在配置文件里改，网页上不能改。
  - Status 改成 `ready-for-agent`。按"一次只做一张实现票"，等第 2 张合并以后再开票。

- 2026-10-23 23:05（+08:00），第 1 步开票（执行线）。扫过 `.scratch/m*/issues/*.md` 的 `Status:` 行：01、02 是 done，其余都是 `ready-for-agent`，没有别的实现票在进行中；没有在跑的 `codex exec`。Status 改成 `in-progress`。`git worktree add -b t/m0-03-config-state-dir-runtime-log ~/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log main`，在 `ae0d338`。`uv sync --frozen`、`src/web/` 里 `pnpm install --frozen-lockfile --offline`（0.6 秒）后，基线 `make check` 十一步全绿：pytest `101 passed, 1 warning`，OpenAPI 过期检查"均未过期"，Vitest `19 passed`，用时 11.0 秒；跑前跑后 `git status --porcelain --untracked-files=all` 都为空；`core.hooksPath` 是 `.githooks`。输出在 `<执行线临时目录>/m0-03/baseline-check.txt`。
  - 那 1 条 warning 是第 2 张就有的：starlette 的 `StarletteDeprecationWarning`（"Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead"），不是本票引入的，记一笔。
  - **环境事实，和本票有关**：`timedatectl` 显示本机时区是 `America/Cambridge_Bay (MDT, -0600)`，`/etc/timezone` 却写着 `Asia/Shanghai`。运行日志写本地时间，按现在的设置会写成 `-06:00`，不是工单例子里的 `+08:00`。见骨架摘要的问题。本条和以后各条的时刻按 +08:00 写，和前两张一致。
- 2026-10-23 23:07（+08:00），第 2 步派工 A（新会话）。
  - 提示 `assets/03-config-state-dir-runtime-log/prompt-A.md`：派工 A 模板，交付 `rdp.infra.config`、`rdp.infra.state`、`rdp.infra.logging` 的契约骨架、`create_app` 加请求编号中间件的契约、跳过的测试清单。要 Codex 在契约里定下并在最终回复里说明的：`RDP_CONFIG` 指向的文件不存在时怎么办；报错的异常类；"使用默认配置"那行由谁写；已存在目录的权限纠不纠正；key=value 的值里有空格、换行时怎么写；重复配置日志；时钟和时区怎么注入；客户端带来的 `X-Request-ID` 用不用；uvicorn 访问日志怎么关（`rdp.infra` 不能 import uvicorn）。允许改的受保护文件只有 `pyproject.toml` 的 ruff、basedpyright 配置。
  - 快照 `refs/rdp/m0-03/A`（`5b11b75`，树和 `ae0d338` 相同）。会话 `01a1694d-6710-75a1-839e-baf3833aa19c`。
  - 命令：在工作目录里 `timeout 60m codex exec -C <工作目录> -s workspace-write -c 'sandbox_workspace_write.network_access=true' -m gpt-6-astra -c 'model_reasoning_effort="high"' --json -o assets/…/out-A.md - < prompt-A.md`。运行日志 `<执行线临时目录>/m0-03/ev-A.jsonl`、`err-A.txt`。
  - 派工前：codex-cli 0.163.0；网关 `10.1.179.3:8088` 直连 200。
- 2026-10-23 23:30（+08:00），派工 A 交回，第 3 步审骨架（`codex-workflow.md` 3.3）。
  - 运行：23:07–23:25，退出码 0，最后一条 `turn.completed`，`out-A.md` 在 assets；stderr 为空，开头两条 `disable_response_storage` 的 `error` 是已知现象。没有网关断开。
  - **重跑**：工作目录 `make check` 退出码 0，十一步全绿，用时 10.4 秒：basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`（`rdp.infra` 没有 import uvicorn、fastapi、starlette）；契约检查 `问题总数: 0`；pytest `101 passed, 114 skipped, 1 warning`（warning 同基线）；OpenAPI 过期检查"均未过期"；Vitest `19 passed`。跑前跑后 `git status --porcelain --untracked-files=all` 相同。
  - **文件归属**：工作目录只有 ` M src/rdp/api/__init__.py`、` M tests/test_web_app.py`，新文件 `src/rdp/infra/{config,state,logging}.py`、`tests/test_{config,state,logging}.py`。`pyproject.toml`、`Makefile`、`scripts/`、`.githooks/`、锁文件都没动（对快照 `A` 的 diff 为空）。主仓库目录 `-- src tests` 为空；非规划文件只有负责人自己的 `Read_First_What're_Files_Meaning?.md`（开票前就在，不是 Codex 写的）。
  - **运行日志**：27 条命令（读规划文件都用主仓库目录的绝对路径；读 fastapi/starlette 的源码确认中间件栈；用 heredoc 和 python 写文件；跑三次 `make check`，前两次失败后修好）。没有一条命令碰两个旧项目或 `/mnt`（JSONL 里的命中都在 `cat AGENTS.md`、brief 的输出里）；安装、联网命令的 grep 无结果；没有在 `/tmp` 留文件。命令清单在 `<执行线临时目录>/m0-03/A-commands.txt`。
  - **审骨架**：公开函数和方法 `load_config`、`PlatformConfig.validate_state_dir`、`state_paths`、`initialize_state`、`RuntimeFormatter.__init__`/`format`、`configure_logging`、`log_context`、`log_config_source`、`RequestIdMiddleware.__init__`/`__call__` 六项齐全，内容合格（单位、取值范围、失败时留下什么、时间语义都写了）；`WebConfig`、`LogConfig`、`PlatformConfig`、`LoadedConfig`、`StatePaths`、`LogTime`、`LoggingSettings` 都有 `Attributes:`。`create_app` 签名没改，docstring 只在 Returns、Side Effects、Time Semantics 各加一句，原文没删。测试 114 个跳过（配置 24、状态目录 17、日志 58、中间件 15），对着每条 `Raises:` 和验收第 1–7 条都找得到。新增豁免 3 条，都针对单条规则、写了理由：`S104`（工单定的 `0.0.0.0`）；两条 `reportUnusedClass`（`_DailyFileHandler`、`_RequestContextApp` 骨架期还没接上，B 接上后必须删，不删 basedpyright 会报多余豁免）。没有新依赖。
  - **评审意见，B 里处理，不用负责人拍板**：
    - 中间件是纯 ASGI 写的，通过子类覆盖 `build_middleware_stack` 包在整个框架栈外面，这样框架生成的 500 也带 `X-Request-ID`（第 4 张的错误编号要用到）。代价是依赖 Starlette 这个方法的行为；B 要有测试钉住，并在注释里写明升级 FastAPI 时要重看。没有直接 import starlette，ASGI 类型是自己写的别名（9.2），可以接受。
    - `configure_logging` 设 `logging.raiseExceptions = False`，是全局设置；理由（systemd 下日志自身故障不写 stderr，ADR 0005）成立，B 在注释里写明。
    - 已存在的状态目录不纠正权限（例如负责人手工建成 0755 也照留），新建的才是 0700。符合工单字面（"第一次启动时建目录，权限 0700"；验收 2"第二次调用不改动任何东西"），暂按 Codex 的定。
    - 数据库文件名 `rdp.sqlite3`、锁文件名 `worker.lock`、保留天数上限 3650、`state_dir` 不接受相对路径和软链接：Codex 的提案，执行线认为合理。
  - 快照 `refs/rdp/m0-03/A-done`（`9b5b214`）。
- 2026-10-23 23:35（+08:00），**骨架关卡一页摘要**（执行线起草，交主会话转负责人）。
  1. **这张票做什么**：平台的配置文件（读、校验、报错）、状态目录（路径只在一处定义、第一次启动建好）、运行日志（统一格式、按天切分、作业编号和请求编号自动带上），以及 Web 每个请求带 `X-Request-ID`。
  2. **函数清单**：

     | 模块 | 函数 | 职责 | 改动什么 | 什么情况下报错 |
     |---|---|---|---|---|
     | `rdp.infra.config` | `load_config(*, environ, home) -> LoadedConfig` | 读唯一的配置文件，校验后返回不可变配置和来源 | 无（只读文件） | `RDP_CONFIG` 指的文件不存在 → `FileNotFoundError`（不回退默认值）；TOML 坏、类型错、未知项、越界 → `ValueError`，逐项写文件、项名、实际值、期望；读不了 → `OSError` |
     | `rdp.infra.state` | `state_paths(config, job_types) -> StatePaths` | 算出数据库 `rdp.sqlite3`、`logs/`、`logs/<作业类型>/`、`worker.lock` 的路径 | 无 | 作业类型名非法或重复 → `ValueError` |
     | `rdp.infra.state` | `initialize_state(paths) -> None` | 补建缺的目录，新建的权限 0700 | 建目录；失败时留下已建的空目录，可重试 | 被普通文件占着 → `NotADirectoryError`；是软链接 → `ValueError`；不可写 → `PermissionError`；其他 → `OSError` |
     | `rdp.infra.logging` | `RuntimeFormatter.format(record)` | 一条日志排成 `时间 级别 模块 中文消息 key=value…`，明细行缩进 4 格；值有空格、等号、换行时加 JSON 引号 | 无 | 字段不合规（见问题 2）、时钟无时区 → `ValueError` 等 |
     | `rdp.infra.logging` | `configure_logging(settings, *, time_source)` | 进程 `web`/`worker` 只写自己的文件，可选 stderr，零点后第一条日志时切分，按日历天删旧文件；接管 uvicorn 的日志，关掉访问日志 | 建或追加日志文件，改 root 和 uvicorn 三个 logger | 进程名、目录不对 → `ValueError`、`FileNotFoundError`、`NotADirectoryError`；打不开 → `OSError`；失败时原配置不变 |
     | `rdp.infra.logging` | `log_context(*, job_id, request_id)` | 上下文管理器，临时设置作业编号、请求编号，退出恢复 | 只改当前 contextvars | 编号格式不对 → `ValueError` |
     | `rdp.infra.logging` | `log_config_source(loaded)` | 用默认配置时记一行 INFO"使用默认配置"（C1） | 无（只写日志） | 无 |
     | `rdp.api` | `RequestIdMiddleware`（`create_app` 里接上） | 每个请求新生成 uuid4 编号，放进上下文，响应头 `X-Request-ID` 返回；不用客户端带来的编号 | 无 | 下游异常原样传出，上下文照样恢复 |

     时钟和时区通过 `LogTime` 注入，测试不改进程时区、不真等一天。第 11 张起 uvicorn 时要传 `log_config=None, access_log=False`，已写进契约。
  3. **测试清单**（114 个，都先跳过）：
     - 配置 24：默认值、`RDP_CONFIG` 生效、只认这一个环境变量、类型错、未知项、端口 0/1/65535/65536、级别、保留天数 0/1/3650/3651、`~` 展开、坏 TOML、坏 UTF-8、报错不回显口令类的值。
     - 状态目录 17：第一次全部建成 0700、第二次什么都不改、被文件占着、软链接、不可写、中途失败可重试。
     - 日志 58：逐字比对一行的格式（固定时钟和 +08:00）、毫秒截断、引号转义、多行明细、web 只写 `web.log`、worker 只写 `worker.log`、不写 stderr、跨零点切分、保留期边界日、夏令时、时钟回拨、重复配置不重复写、上下文嵌套和并发不串号、"使用默认配置"那一行。
     - 中间件 15：每个响应带编号且互不相同、和请求内日志的编号一致、并发两个请求不串、500 也带、`/api/health` 不产生访问日志、异常和取消后上下文恢复。
  4. **要负责人拍板的**：
     1. **本机时区是 −06:00，不是 +08:00**。`/etc/localtime` 在 10 月 11 日被改成 `America/Cambridge_Bay`（加拿大山地时间），`/etc/timezone` 还写着 `Asia/Shanghai`。运行日志写本地时间，现在会写成 `09:27:39.531-06:00`。
        - 建议：负责人确认后用 `sudo timedatectl set-timezone Asia/Shanghai` 改回来；代码不用改，日志按系统时区写。不改的话日志照样对，只是偏移是 −06:00。
     2. **日志字段写错时会悄悄丢掉整行**。契约规定字段值只能是字符串、数字、布尔、空，传了别的（例如一个 `Path`）`format` 会报错；而标准库在写日志时遇到报错只会丢掉这一行，systemd 下连提示都没有。最容易出事的是报错路径上的那条 ERROR 日志。
        - 建议：`format` 不因字段内容报错：别的类型先 `str()` 再按字符串规则输出（需要时加引号）；键名不合规也照样输出。错误写法靠测试和评审抓，不靠运行时丢日志。这改了 `format` 的 `Raises:`，所以要你点头。
     3. **验收第 7 条和第 9 条打架**。第 7 条要求 `/api/health` 不产生访问日志；第 9 条的演示却要"`curl /api/health` 两次，`web.log` 里有两条带不同请求编号的行"。现在的平台没有别的接口会写日志。
        - 建议：第 9 条改成：两次 `curl` 拿到两个不同的 `X-Request-ID`；`web.log` 里有统一格式的启动行、没有访问日志。"响应头和日志里的编号一致"由测试证明（测试里临时加一个会写日志的路由，已在测试清单里）。不为了演示加一条访问日志。
  5. **结论：建议通过**（问题 2、3 按建议在派工 B 里改）。检查都由执行线重跑过：`make check` 十一步 10.4 秒全绿，跑完不留痕迹；文件归属干净；运行日志没有碰旧项目、`/mnt`，没有安装和联网命令；没有新依赖；没打回（0 轮）。负责人说"通过"以后，做契约提交 `契约：配置、状态目录与运行日志`，Status 改回 `in-progress`，派工 B。
  - Status 改成 `in-review`，交回主会话。
- 2026-10-23，骨架关卡：负责人回复"Q1不要改，保持现状；其他按照你说的来"，主会话按通过处理。
  - **P1**：不改系统时区，保持 `America/Cambridge_Bay`（−06:00）；运行日志照本机时区写，代码不改。记进 `docs/brief/0013-环境事实更新-本机时区.md`。
  - **P2**：日志格式化不因字段内容报错；字符串、数字、布尔、空以外的值先转成字符串再输出。改 `format` 的 `Raises:`（契约变更，已获批）。
  - **P3**：验收第 9 条改成：两次 `curl /api/health` 拿到两个不同的 `X-Request-ID`；`web.log` 里有统一格式的启动行、没有访问日志。"响应头和日志里的编号一致"由测试证明（测试里临时加一个写日志的路由）。
  - **P4**：状态目录已存在且权限宽于 `0700` 时，启动时记一条警告（路径和现在的权限），不自动改权限。契约里相应的 `Side Effects:` 和测试由派工 B 补上。
  - 评审里列的"B 里处理"各项照执行线的意见办（纯 ASGI 中间件用测试钉住并注明升级时重看；`logging.raiseExceptions = False` 注明理由；删掉两条 `reportUnusedClass` 豁免）。
- 2026-10-24 09:17（+08:00），第 4 步契约提交（执行线）。先核对工作目录的树和快照 `A-done` 相同，再 `git add -A`，普通 `git commit`：`cb86a80 契约：配置、状态目录与运行日志`，经过钩子，十一步全绿；提交后工作目录干净。P2、P4 的契约补充按主会话的安排留给派工 B 改，契约提交用的是 `A-done` 的原样。Status 改回 `in-progress`。
- 2026-10-24 09:20（+08:00），第 5 步派工 B（续接）。
  - 提示 `assets/03-config-state-dir-runtime-log/prompt-B.md`：派工 B 模板（逐个测试单独跑、先红后绿），加上已获批的契约变更 P2（`format` 不因字段内容报错，别的类型先 `str()`；键名、保留键、非映射、非有限浮点也不丢整行，改 `Returns:`、`Raises:` 和 `test_invalid_fields`）、P3（`test_response_and_log_id_match` 在测试里临时加写日志的路由；演示由执行线在沙箱外做）、P4（已存在且 `mode & 0o077 != 0` 的状态目录记 WARNING，不改权限；因为 `initialize_state` 在 `configure_logging` 之前跑，建议 `initialize_state` 返回宽权限清单，由日志模块里的启动边界函数在日志配好以后记警告）；评审意见（钉住覆盖 `build_middleware_stack` 的做法并注明升级要重看；`raiseExceptions = False` 写理由和代价；删两条 `reportUnusedClass`；删 `create_app` 里的骨架期注释；测试不依赖本机时区（P1）；测试后恢复全局 logging 状态）。最终回复五块。
  - 快照 `refs/rdp/m0-03/B`（`e466af1`，基于契约提交 `cb86a80`，工作目录干净）。
  - 会话 `01a1694d-6710-75a1-839e-baf3833aa19c`，先 `cd <工作目录>` 再 `timeout 60m codex exec resume -m gpt-6-astra -c 'model_reasoning_effort="high"' -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true' --json -o assets/…/out-B.md <会话> - < prompt-B.md`。运行日志 `<执行线临时目录>/m0-03/ev-B.jsonl`、`err-B.txt`。网关直连 200。
- 2026-10-24 09:50（+08:00），派工 B 交回，第 6 步评审（`codex-workflow.md` 3.5），逐项结论：
  1. **重跑**：运行 09:20–09:48，退出码 0，最后一条 `turn.completed`，stderr 为空，没有网关断开。工作目录 `make check` 十一步全绿，10.7 秒；pytest `221 passed, 1 warning`（warning 同基线），没有跳过；跑前跑后 `git status` 相同。**通过。**
  2. **文件归属**：工作目录只有 `src/rdp/api/__init__.py`、`src/rdp/infra/{config,state,logging}.py`、`tests/test_{config,state,logging,web_app}.py` 的改动和新文件 `tests/conftest.py`；受保护文件和锁文件都没动。主仓库目录 `-- src tests` 为空，非规划文件只有负责人的 `Read_First_What're_Files_Meaning?.md`。**通过。**
  3. **对比契约**（对 `cb86a80` 逐个比签名和 docstring）：改了的只有已获批的 P2（`RuntimeFormatter.format` 的 Args/Returns/Raises）和 P4（`initialize_state` 返回 `tuple[DirectoryPermissionWarning, ...]`，改 Returns、Side Effects；新增公开的 `DirectoryPermissionWarning`、`log_state_warnings`，六项齐全）。其余都是新增的私有辅助函数。**通过。**
  4. **先红后绿**：Codex 用一个 `/tmp/rdp_m003_tdd.py` 辅助脚本逐个去掉跳过、单独跑 `.venv/bin/pytest <文件>::<测试>`，每次的命令和输出都打印在运行日志里（脚本和它的证据文件交付前已删）。执行线从运行日志解析出 120 个测试各自的第一次运行：48 个先红，72 个一开始就绿，和 Codex 自报的表逐个一致（`<执行线临时目录>/m0-03/B-redgreen.txt`）。一开始就绿的比例高，所以执行线另做了**变异抽查**（`assets/…/mutation_probe.py`，输出 `mutation_probe-B-done.txt`）：对 10 处行为各做一个能区分对错的变异（用客户端带来的编号、中间件挂到错误处理之内、`log_context` 不恢复、零点按 86400 秒算、访问日志没关、报错回显所有值、已有目录也 chmod、时钟回拨重算边界、同名归档覆盖、请求编号放进进程全局），覆盖 18 个一开始就绿的测试，**10 个变异全部被抓到**。第一次写的"进程全局"变异写错了（仍然设了 contextvar），已改正重跑。**通过。**
  5. **运行日志**：78 条命令；没有一条碰两个旧项目或 `/mnt`（JSONL 里唯一一处命中在 `cat` 工单的输出里）；安装、联网命令的 grep 无结果；`/tmp` 下只建过那两个辅助文件，已删（`ls` 确认不在）。命令清单 `<执行线临时目录>/m0-03/B-commands.txt`。**通过。**
  6. **两轴评审**：快照 `refs/rdp/m0-03/B-done`（`9dce202`），在探针工作目录里跑 `/code-review main`，原文整理在 `assets/…/code-review-B-done.md`。本票不是同步、录制、转换模块，不跑 `algorithm-code-review`。另外执行线自己审代码时用一个试验（`assets/…/exp-B-done-unlink.py`）证实了一个缺陷：**有一个过期归档删不掉时，之后的每一条日志都会丢**（跨零点前后 6 条记录，`web.log` 是空的），因为 `shouldRollover`/`doRollover` 里的删除报错，每条记录都走 `handleError` 被丢掉，`rolloverAt` 也不前进。**不通过**，进修复清单。
  7. **违规试验**（工单："只需要确认已有的检查链照常工作"）：脚本 `assets/…/violation_probe.sh`，输出 `violation_probe-B-done.txt`。基线十一步全绿 11.4 秒，跑完不留痕迹；print、不带时区的 `datetime.now()`、不带规则码的 noqa、类型错误、`rdp.infra` 里 import uvicorn、缺 `Time Semantics:`、失败的断言、格式不合、ESLint `no-console` 各失败在对应那一步；带规则码和理由的豁免、中文全角标点照常全绿；普通 `git commit` 带 print 的代码被钩子拒绝。**12 项全部通过。** 前两次试跑失败都是探针自己的问题（`try1` 是 bash 引号吃掉了样例里的引号；更早一次 A-done 试跑是"不能失败"样例里有未用的 import），已改脚本。
  8. **演示**（新的验收第 9 条，P3）：执行线在沙箱外按第 11 张将来的启动顺序写了 `assets/…/demo.py`（`load_config` → `state_paths` → `initialize_state` → `configure_logging(stderr=False)` → `log_config_source` → `log_state_warnings` → `uvicorn.run(..., log_config=None, access_log=False)`），用临时配置（`127.0.0.1:8600`，状态目录在执行线临时目录）起应用，`curl /api/health` 两次：两个响应的 `X-Request-ID` 分别是 `85b80199…`、`1bbe3650…`，互不相同；`web.log` 里是统一格式的 uvicorn 启动、关闭行（`2026-10-23 19:53:59.284-06:00 INFO uvicorn.error Started server process […]`，偏移 −06:00，符合 P1），没有访问日志；stdout、stderr 都是 0 字节；状态目录和 `logs/` 是 0700。证据 `assets/…/demo-B-done-{curl.txt,web.log,misc.txt}`。**通过。**（第一次演示时我 `kill` 错了进程，杀的是外层 shell，服务器多跑了一会儿，后来用 SIGINT 正常停掉，不影响结论。）
- 2026-10-24 09:55（+08:00），**修复清单（r1）**。Status 改成 `changes-requested`。
  1. **过期归档删不掉时之后的日志全丢**。位置：`src/rdp/infra/logging.py` 的 `shouldRollover`（启动清理）、`doRollover`、`getFilesToDelete` 附近。期望：删单个过期归档报 `OSError`（含 `PermissionError`、列目录和删除之间已被删掉的 `FileNotFoundError`）时跳过这个文件，当条和之后的记录照常写进活动文件；切分照常完成（`rolloverAt` 前进、活动文件重开）；删不掉的归档留着，下一次切分或下一次启动再试。补测试：持续删不掉时跨零点前后多条记录都在；竞态时当条不丢。`configure_logging` 的 Side Effects 补一句"删不掉的过期归档跳过并留下"——属于补充说明，执行线批准（6.2），汇报时告诉负责人。
  2. **重复实现**（AGENTS 规则 7、CODING_STANDARDS 9.1）。位置：`logging.py` `_local_time`。期望：改用 `rdp.infra.timeutil.ensure_utc`，再 `.astimezone(zone)`；行为不变，现有测试照过。
  3. **从异常文本解析 TOML 的行列没写理由**（4.2）。位置：`src/rdp/infra/config.py` 约 164 行。期望：注释写明 Python 3.12 的 `TOMLDecodeError` 没有 `lineno`/`colno`（3.14 才有），所以从文案里取；文案变了取不到时输出什么（确认此时仍是一条合格的 `ValueError`，加一个测试或说明现有测试已覆盖）。
  4. **过时注释**。位置：`config.py` 约 21 行"待骨架评审确认"。期望：改成定下来的理由（骨架关卡已通过，上限 3650 天）。
  5. **验收 4 的测试没看日志**。位置：`tests/test_web_app.py` `test_concurrent_request_ids`。期望：两个交错的并发请求各自在请求里写业务日志，断言写进日志文件（或 handler 收到）的行里带的 `request_id` 和各自响应头一致、不串；docstring 和断言一致。
  6. **测试没恢复模块状态**（7.5）。位置：`tests/conftest.py`。期望：一并恢复 `rdp.infra.logging._installed_handlers`，测试之间不留已关闭的 handler 引用。
  7. **具名常量**（4.6）。期望：`config.py` 里重复的 `home / ".local/share/rdp"` 和默认配置相对路径提成具名常量并注明出处（S1、工单「范围」）；`logging.py` 里请求编号、字段键、归档日期后缀的正则提成具名常量，请求编号那条注明对应 `api/__init__.py` 的 `uuid4().hex`。
  8. **默认时区每条记录读一次 `/etc/localtime`**。位置：`logging.py` `_local_timezone`。期望：不改行为（契约定的"系统时区修改在下条记录生效"），只在注释里写明代价（每条日志两三次小文件读取）和为什么接受（v1 日志量小），以及不看 `TZ` 环境变量的理由（P1 按本机时区；第 11 张的 systemd 单元不设 `TZ`）。
  - 记下、不改的（需要的话汇报时交负责人）：未知项的实际值显示 `<已隐藏>`（防口令泄露，和验收 1 字面不完全一致）；pydantic 的"期望"是英文原文；缺失的祖先目录也建成 0700；P4 警告不受日志级别约束；`retention_days=30` 留 30 个日期归档加当天的活动文件；**重启后活动文件里前几天的内容会在下一次零点整体归档成重启当天的日期**（契约里写明了"不按 mtime 回溯切分"，负责人已批准；要改是契约含义变化，交主会话问负责人）；`_DailyFileHandler` 绕过父类 `__init__`（模块注释写了理由）；第 11 张必须传 `log_config=None, access_log=False`（演示已证实这样能用，建议写进第 11 张的验收）。
- 2026-10-24 09:58（+08:00），第 7 步派工 r1（修复轮第 1 轮，续接）。提示 `assets/…/prompt-r1.md`（修复轮模板，八条照上面的修复清单；第 1、3 条先写测试看到失败再改）。快照 `refs/rdp/m0-03/r1`（`7695b44`，树和 `B-done` 相同）。Status 改回 `in-progress`。会话 `01a1694d-6710-75a1-839e-baf3833aa19c`，先 `cd <工作目录>` 再按第 4 节续接命令（带 `network_access=true`），`-o assets/…/out-r1.md`。运行日志 `<执行线临时目录>/m0-03/ev-r1.jsonl`、`err-r1.txt`。网关直连 200。
- 2026-10-24 10:15（+08:00），r1 交回，复评（3.5）。
  1. 重跑：`make check` 十一步全绿，10.7 秒，`226 passed`，跑前跑后 `git status` 相同。**通过。**
  2. 文件归属：改动仍只在 `src/rdp/infra/{config,logging}.py`、`tests/{conftest,test_config,test_logging,test_web_app}.py`；主仓库目录非规划文件只有负责人的那个文件。**通过。**
  3. 契约：公开签名和 docstring 只多了获批的那一句（`configure_logging` 的 Side Effects："删不掉的过期归档跳过并留下，下次切分或启动再试"）。**通过。**
  4. 先红后绿：运行日志里新测试 `test_expired_archive_delete_errors_preserve_records`（四个参数组合）第一次 `4 failed`，`test_toml_error_without_position_has_safe_fallback` 第一次 `1 failed`，修后通过；`test_concurrent_request_ids` 是只改测试，一开始就绿，Codex 已说明。执行线的删除失败试验（`exp-r1-done-unlink.txt`）：零点后 3 条都在活动文件里，删不掉的归档留着。变异抽查 10/10 仍被抓到（`mutation_probe-r1-done.txt`）。**通过。**
  5. 运行日志：21 条命令，没碰旧项目和 `/mnt`，没有安装、联网命令，`/tmp` 下没留文件。**通过。**
  6. 两轴复评（探针工作目录检出快照 `r1-done` = `5bfdff2`，只读子 agent）：八条都已落实，没有新豁免。**还有一条同形态的缺陷**：`getFilesToDelete` 里的 `iterdir()` 出错没被兜住，启动清理时异常在 `_startup_cleanup = False` 之前抛出，之后每条日志都被丢掉（复评 agent 实测跨零点 6 条全丢；执行线读代码确认路径成立）。另两条判断项：`DEFAULT_STATE_DIR_RELATIVE`、`DEFAULT_CONFIG_FILE_RELATIVE` 成了公开名；同名归档追加合并中途失败会在重试时重复追加（不丢日志，记为风险，不改）。`rotate()` 本身失败时持续丢日志，和标准库行为一致，在获批契约"切分失败遵循 handleError"之内，记为风险。**不通过。**
  7. 违规试验：`violation_probe-r1-done.txt`，12 项全部通过。**通过。**
  8. 演示：r1 没动 Web 和启动路径，沿用 `B-done` 的演示结论。
- 2026-10-24 10:18（+08:00），**修复清单（r2）**。Status 改成 `changes-requested`。
  1. 问题：过期归档清理时列目录失败，之后的日志全丢。位置：`src/rdp/infra/logging.py` `_delete_expired` / `getFilesToDelete`。期望：列目录（`iterdir`、`is_file`、`is_symlink` 等）报 `OSError` 时同样跳过这次清理，当条和之后的记录照常写入；启动清理只试一次就清掉 `_startup_cleanup`（失败也清，下次切分再试）；切分时 `rolloverAt` 照常前进、活动文件照常重开。先写测试看到失败：启动阶段和切分阶段各一种。`getFilesToDelete` 自己的契约（返回过期归档列表）不变。
  2. 问题：两个默认路径常量是公开名，多出了模块的对外接口（2.9）。位置：`src/rdp/infra/config.py` 的 `DEFAULT_STATE_DIR_RELATIVE`、`DEFAULT_CONFIG_FILE_RELATIVE`。期望：改成 `_` 开头的私有名；没有别处引用。
- 2026-10-24 10:20（+08:00），第 8 步派工 r2（修复轮第 2 轮，续接）。提示 `assets/…/prompt-r2.md`。快照 `refs/rdp/m0-03/r2`（`c257c37`，树和 `r1-done` 相同）。Status 改回 `in-progress`。会话同上，先 `cd <工作目录>` 再续接（带 `network_access=true`），`-o assets/…/out-r2.md`。运行日志 `<执行线临时目录>/m0-03/ev-r2.jsonl`、`err-r2.txt`。网关直连 200。
- 2026-10-24 10:40（+08:00），r2 交回，复评（3.5）。
  1. 重跑：`make check` 十一步全绿，`232 passed`，跑前跑后 `git status` 相同。**通过。**
  2. 文件归属：这一轮只改了 `src/rdp/infra/{config,logging}.py`、`tests/test_logging.py`；主仓库目录非规划文件只有负责人的那个文件。**通过。**
  3. 契约：公开签名和 docstring 没变；`getFilesToDelete` 的契约不变，兜底放在调用处 `_delete_expired`。**通过。**
  4. 先红后绿：新测试 `test_expired_archive_query_errors_preserve_records`（启动/切分 × `iterdir`/`is_file`/`is_symlink` 六种）第一次 `6 failed`，修后 `6 passed`。变异抽查 10/10（`mutation_probe-r2-done.txt`），删除失败试验三条记录都在。**通过。**
  5. 运行日志：9 条命令，没碰旧项目和 `/mnt`，没有安装、联网命令。**通过。**
  6. 两轴评审：这一轮的改动只有 `_delete_expired` 外面包一层 `try/except OSError` 和两个常量改名，执行线自己逐行审过，没有再跑子 agent；上一轮两轴提出的两条都已解决。**通过。**
  7. 违规试验：`violation_probe-r2-done.txt`，12 项全部通过。**通过。**
  8. 演示：在 `r2-done` 上重做一次（`demo-r2-done-*`）：两个 `X-Request-ID`（`3393adf5…`、`231ade49…`）不同；`web.log` 8 行，都是统一格式的 uvicorn 启动、关闭行，没有访问日志；stdout、stderr 0 字节；目录 0700。**通过。**
  - 快照 `refs/rdp/m0-03/r2-done`（`dc50018`）。打回 2 轮（r1、r2），在 3 轮以内。
- 2026-10-24 10:45（+08:00），实现提交 `62191ba 实现：配置、状态目录与运行日志`（`git add -A`，树和 `r2-done` 相同），经过钩子，十一步全绿，`232 passed`；提交后工作目录干净。探针工作目录都已删除，没有残留的 codex、pytest、演示进程。Status 改成 `in-review`，交回主会话等负责人"合并"。
- 2026-10-24 10:45（+08:00），**完工汇报**（执行线起草）。
  - **改了什么**：`rdp.infra.config`（读唯一的 TOML 配置：`RDP_CONFIG` 或 `~/.config/rdp/config.toml`，没有就用默认值；pydantic 严格校验，报错逐项写文件、项名、实际值、期望）；`rdp.infra.state`（状态目录里所有路径只在 `state_paths` 一处算：`rdp.sqlite3`、`logs/`、`logs/<作业类型>/`、`worker.lock`；`initialize_state` 新建的目录 0700，已存在的不改，宽于 0700 的返回清单）；`rdp.infra.logging`（统一行格式、作业编号和请求编号经 contextvars 自动带上、`web.log`/`worker.log` 每天零点后切分并按日历天删旧文件、可选 stderr、接管 uvicorn 日志并关掉访问日志、"使用默认配置"和宽权限警告两条启动日志）；`rdp.api` 的 `create_app` 加了请求编号中间件（`X-Request-ID`，框架的 500 也带）。
  - **测试**：pytest 232 个（本票新增 131 个），全绿，没有跳过；`make check` 约 11 秒。先红后绿按运行日志逐个核对过；一开始就绿的 72 个用 10 个变异抽查，全部抓到。违规试验 12 项、演示都通过。
  - **契约变化**（负责人已批准）：P2 `format` 不因字段内容报错；P4 `initialize_state` 改返回宽权限清单，新增 `DirectoryPermissionWarning`、`log_state_warnings`。执行线批准的补充说明一处：`configure_logging` 的 Side Effects 加"删不掉的过期归档跳过并留下，下次切分或启动再试"。
  - **风险和要负责人知道的**：
    1. **重启后归档日期不准**：服务停了几天再启动，`web.log` 里前几天的内容会在下一次零点整体归档成重启当天的日期（契约写明了"不按 mtime 回溯切分"，骨架关卡批准过）。按日期找日志可能找错文件，旧内容也会多留几天。要改就是契约含义变化，建议另开一个小票或在第 11 张前处理：启动时活动文件的修改日期早于今天，就先按那个日期归档。
    2. **第 11 张必须**用 `uvicorn.run(..., log_config=None, access_log=False)`，否则 uvicorn 会覆盖日志配置、访问日志又会出现。演示已按这个方式跑通，建议写进第 11 张的验收。
    3. 配置报错里，未知项的实际值显示 `<已隐藏>`（防止把以后的口令类配置打出来），"期望"部分是 pydantic 的英文原文。
    4. 默认时区每条日志读两三次 `/etc/localtime`，不看 `TZ`（P1）；v1 日志量小，可以接受。
    5. 日志写失败时（磁盘满、切分时 rename 失败）会丢记录且没有提示（`raiseExceptions = False`，ADR 0005）；同名归档追加合并中途失败、重试时会重复追加一段（不丢）。
    6. 缺失的祖先目录（例如 `~/.local/share`）也会建成 0700；P4 警告不受日志级别限制，ERROR 级别下照样写。
  - **下一张**：第 4 张「诊断与报错框架」（依赖本票）。
