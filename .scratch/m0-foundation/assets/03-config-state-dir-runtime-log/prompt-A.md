你在工单「配置、状态目录与运行日志」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log（git worktree，分支 t/m0-03-config-state-dir-runtime-log）里写契约骨架。

先读下面这些。规划文件一律用绝对路径读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件（比如工单的 Comments）。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md（尤其第 3 条、5.1、5.3、5.4、6.4、6.5、6.10、第 7 条、9.1 的表）
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/03-config-state-dir-runtime-log.md（「范围」「验收」「风险」，以及 Comments 里负责人批准的 C1–C3）
- 它引用的：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/spec.md（S1 状态目录、S3 端口）、/home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/09-observability.md 的 Answer（"运行日志"一节）、/home/shawn/桌面/robot-data-platform/docs/adr/ 下的 0005（systemd 下只写文件，不写 stderr；作业日志目录 `logs/<作业类型>/`；worker 单实例锁）
- /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里的术语（平台状态目录、运行日志、作业日志等）
- 工作目录里已有的代码：`src/rdp/api/__init__.py` 的 `create_app`（第 2 张），`src/rdp/infra/timeutil.py`（基础层的写法样例），`tests/test_web_app.py`（TestClient 的用法）

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。pydantic 模型、dataclass 写 `Attributes:`，每个字段写含义、单位、取值范围、默认值。
2. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。对着每个函数 docstring 里的每条 `Raises:`、每种返回情况、每项副作用，逐条都有测试（CODING_STANDARDS 7.1），并覆盖工单「验收」第 1–7 条。
3. `make check` 跑到全绿（十一步）。

本次交付（模块路径按工单）：
- **`rdp.infra.config`**：配置模型（不可变），读配置的函数。配置文件位置的规则：`RDP_CONFIG` 有值就读它指向的文件（这时文件不存在算错误还是用默认值，由你在契约里定下来，并在最终回复第 4 块说明理由）；没有 `RDP_CONFIG` 就读 `~/.config/rdp/config.toml`，不存在时全部用默认值（C1）。只有 `RDP_CONFIG` 这一个环境变量，不支持用环境变量覆盖单个配置项（C2）。报错要指明文件、项名、实际值和期望（验收第 1 条），报错用什么异常类、怎么从 pydantic 的 `ValidationError` 转出来，在契约里写清楚。为了测试不碰真实的 home 和环境变量，环境和 home 目录的取法要能注入（例如显式参数），写进签名。"使用默认配置"那一行日志由谁、在什么时候写，在契约里定下来。
- **`rdp.infra.state`**：一个函数根据配置给出状态目录里所有路径（数据库文件、`logs/`、`logs/<作业类型>/`、worker 单实例锁），返回不可变对象；一个函数在第一次启动时建目录（`0700`），已存在时不改动任何东西（包括不改已有目录的权限，还是会纠正权限，由你定并写进契约和第 4 块）。数据库文件名、锁文件名是具名常量，注释写来源。作业类型是参数（作业类型的清单在第 8 张，本票不定）。
- **`rdp.infra.logging`**：
  - 日志格式化器（行格式逐字按工单：`时间 级别 模块 中文消息 key=value…`，时间是带时区的本地时间到毫秒，例如 `2026-10-21 16:15:02.123+08:00`）；多行消息（诊断明细）的缩进写法。key=value 里值含空格、等号、换行时怎么写，在契约里定下来。
  - 一个配置函数：进程名（`web` 或 `worker`）、日志目录、要不要同时写 stderr、级别、保留天数。写 `logs/web.log` 或 `logs/worker.log`，每天零点切分，保留 `retention_days` 天。用 `logging.handlers.TimedRotatingFileHandler`（CODING_STANDARDS 9.1），在模块注释里写明"单进程写一个文件"的前提（工单「风险」）。重复调用时怎么处理（例如测试里配两次）写进契约。
  - 作业编号、请求编号的 contextvars，和设置它们的上下文管理器（退出时恢复原值，嵌套时也对）。
  - 时钟和时区要能注入，满足验收第 3、5 条（固定时钟和时区、跨零点切分、删旧文件），测试不真等一天，也不改进程的全局时区（CODING_STANDARDS 7.5）。怎么注入（参数、子类、工厂）由你定，写进签名。
  - 注意 ruff 的 `PLR0913`（最多 5 个参数）：参数多时用一个设置对象或关键字参数归组，不要加豁免。
- **Web**：`create_app` 加一个中间件：每个请求生成一个请求编号，放进上下文，响应头 `X-Request-ID` 返回。请求编号的格式（例如 uuid4 的十六进制）写进契约；客户端自己带了 `X-Request-ID` 时用不用它，由你定并写进第 4 块。`create_app` 已获批的签名不改；它的 docstring 需要补"加了中间件"时，补充说明，并在第 4 块列出你改了 docstring 的哪几句。uvicorn 的访问日志怎么关、uvicorn 自己的启动和报错日志怎么走同一套格式：本票不写启动命令（第 11 张），所以要在 `rdp.infra.logging` 或 `rdp.api` 里给出第 11 张能直接用的东西（例如 uvicorn 用的 `log_config` 字典，或者在配置函数里接管 `uvicorn`、`uvicorn.error`、`uvicorn.access` 这几个 logger），写进契约。**`rdp.infra` 不能 import `uvicorn`、`fastapi`、`starlette`**（import-linter 的 forbidden 合约）；按 logger 名字配置是可以的。
- **worker**：本票没有 worker 进程，"worker 只写 `worker.log`"由配置函数的 `process` 参数保证，测试里用 `worker` 配一次即可。不建 worker 的入口。
- **测试**：放在 `tests/` 下，每个模块一个测试文件。临时目录用 `tmp_path`。

要特别注意的地方：
- 用标准库 `tomllib` 读 TOML，pydantic 校验（pydantic 已是直接依赖）。不需要新依赖；要是觉得需要，停下来写依赖申请。
- 配置项只有工单列的三组：`state_dir`、`[web]` 的 `host`/`port`、`[log]` 的 `level`/`retention_days`。每项的类型和取值范围（端口范围、级别可选值、保留天数下限上限、`state_dir` 能不能是相对路径、`~` 展不展开）写进 `Attributes:`，拿不准的列进第 4 块。
- 日志不写口令、令牌（CODING_STANDARDS 6.10）；本票不涉及，但配置报错里要回显"实际值"，想一想以后加了口令类配置项时会不会把它打出来，写进第 4 块。
- 基础层不 import 入口层，`rdp.infra` 的三个模块之间的依赖方向（例如 `state` 依赖 `config`）写在模块注释里。
- 不要写 `.git/info/exclude`（所有工作目录共用）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整配置，每条写理由；依赖表不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 那步要能看出 passed 和 skipped 的数目）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方，包括上面要你"定下来并说明"的每一处：你定的是什么、为什么。
