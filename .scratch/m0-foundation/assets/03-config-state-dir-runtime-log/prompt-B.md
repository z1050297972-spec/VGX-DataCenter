骨架已获批，契约提交是 `cb86a80`（`契约：配置、状态目录与运行日志`），内容就是你派工 A 交的骨架。工作目录现在是干净的。

动手前先用绝对路径重读主仓库目录里的工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/03-config-state-dir-runtime-log.md，Comments 的最后两条是评审意见和负责人的决定（P1–P4）。

现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（`.venv/bin/pytest tests/<文件>::<测试名>`），看到它失败，再写实现让它通过。评审会在运行日志里逐个核对每个测试都有一次实现前的失败运行。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因（例如前一个测试的实现已经覆盖了它）。
2. 已获批的签名、类型和 docstring 不改，下面"已获批的契约变更"列的几处除外。还有别的地方确实要改时停下，在最终回复里写契约变更申请：哪个函数、改什么、为什么。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过。

已获批的契约变更（负责人 2026-10-23 在骨架关卡批准，按下面改契约，并先改测试、后改实现）：
- **P2 日志格式化不因字段内容报错**：`RuntimeFormatter.format` 遇到 `str`/`int`/`float`/`bool`/`None` 以外的字段值，先 `str()` 再按字符串规则输出（需要时加 JSON 引号）。理由：标准库在 handler 里遇到格式化异常只会经 `handleError` 丢掉这一行，`raiseExceptions = False` 时连提示都没有，最容易丢的是报错路径上的 ERROR 日志。同理，键名不合规、用了保留键、`fields` 不是映射、非有限浮点数，也不要让整行丢掉：选一种确定的输出办法（例如不合规的键加引号照常输出、保留键改名或丢弃该字段但保留整行、`NaN` 按字符串输出），写进 `Returns:`，并从 `Raises:` 里删掉对应的 `ValueError`。时钟和时区注入错误（naive 时刻等）属于配置错误，仍可在 `configure_logging` 时报出；`format` 里要不要保留，由你定，在第 4 块说明。改 `Raises:`、`Returns:` 和 `test_invalid_fields`（改成验证"照常输出、不丢行"），需要的话加测试；`str()` 本身抛异常的对象也不能让整行丢掉。
- **P3 验收第 9 条**改成：两次 `curl /api/health` 拿到两个不同的 `X-Request-ID`；`web.log` 里有统一格式的启动行、没有访问日志。"响应头和日志里的编号一致"由测试证明：`test_response_and_log_id_match` 在测试里临时加一个写日志的路由（只在测试里，不进 `src/`）。演示由 Claude 在沙箱外做，你不用起服务器。
- **P4 已存在的状态目录权限宽于 0700 时记一条警告**：路径和现在的权限（八进制，例如 `0755`），不改权限。适用于 `root`、`logs` 和每个作业日志目录里已经存在的那些（`mode & 0o077 != 0`）；本次新建的不算。注意顺序：启动时 `initialize_state` 在 `configure_logging` 之前运行，这时直接打日志进不了 `web.log`/`worker.log`。所以警告要在日志配置好之后才发出，并且确实落在本进程的日志文件里。建议做法（可以按你的判断换一种，第 4 块说明）：`initialize_state` 返回一个不可变的"宽权限目录"清单（路径、权限），由 `rdp.infra.logging` 里一个和 `log_config_source` 同样在启动边界调用的函数记 WARNING（消息写清后果：数据库里以后有口令哈希，其他用户可能读到）。相应地改 `initialize_state` 的 `Returns:`、`Side Effects:`，补测试：宽权限目录被列出、权限不变、第二次调用仍不写任何东西、警告落进日志文件且格式正确、0700 的不报。
- 这些变化只在本票范围内；验收第 2 条"第二次调用不改动任何东西"仍然成立。

评审意见（不改含义，照做）：
- **中间件**：`_RequestContextApp` 覆盖 Starlette 的 `build_middleware_stack`，把 `RequestIdMiddleware` 包在整个框架栈外，让框架生成的 500 也带 `X-Request-ID`。用测试钉住这件事（`test_request_ids_on_all_response_statuses` 里的框架 500），并在注释里写明：这依赖 Starlette 的这个方法，升级 FastAPI/Starlette 时要重看。不要直接 import `starlette`（CODING_STANDARDS 9.2）。
- **`logging.raiseExceptions = False`**：是进程级的全局设置，在设置它的地方用注释写明理由（ADR 0005：systemd 下只写文件、不往 stderr 输出，日志自身故障也不例外）和代价（日志写失败时没有提示）。
- **删掉两条 `reportUnusedClass` 豁免**（`_DailyFileHandler`、`_RequestContextApp`），接上以后它们就不是未使用的了；`S104` 那条保留。
- `create_app` 接入中间件以后，删掉函数体里"工单 03 当前只交契约……"那两行注释。
- 测试里不改进程的全局时区、不真等一天（CODING_STANDARDS 7.5）；时间都用 `LogTime` 注入。本机时区现在是 `America/Cambridge_Bay`（−06:00），负责人决定保持现状（P1，`docs/brief/0013`），测试不能依赖本机时区。
- 测试结束后恢复全局 logging 状态（root 和 uvicorn 三个 logger 的 handler、级别、传播、`raiseExceptions`），不让测试互相影响、不依赖执行顺序；`configure_logging` 打开的文件 handler 要关掉。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整配置，每条写理由；依赖表不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不写 `.git/info/exclude`。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 那步要能看出 passed 和 skipped 的数目，应当没有 skipped）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。另外逐条列出你按 P2、P4 改了哪些 docstring 的哪几句。
4. 拿不准、需要评审决定的地方。
5. 先红后绿：每个测试一行，写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
