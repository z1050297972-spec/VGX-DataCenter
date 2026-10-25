你在工单「账号、登录与会话」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-06-accounts-login-sessions（git worktree，分支 t/m0-06-accounts-login-sessions）里工作。

这一步是本票的前置重构（派工 A0），**行为完全不变**，只挪位置。负责人已批准（2026-10-25"挪"）。做完以后才写本票的契约骨架，那是下一次派工的事，这一步不要碰账号相关的任何东西。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- 背景：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/followups.md 第 5 张一节的头两条和"正则靠切片去锚点"一条

**问题**：请求编号、作业编号、错误编号的格式规则放在 `rdp.infra.db.validation`，`rdp.infra.logging` 为了校验请求编号要 import 数据库包。日志不该依赖数据库。

**要做的**：
1. 新建 `src/rdp/infra/ids.py`（基础层的编号规则模块），把下面这些从 `rdp.infra.db.validation` 原样搬过去：`MAX_SQLITE_INTEGER`、`REQUEST_ID_HEX_LENGTH`、`REQUEST_ID_PATTERN`、`JOB_ID_PATTERN`、`ERROR_ID_PATTERN`、`is_request_id`、`error_source_kind`。值、签名和函数 docstring 一字不改（模块 docstring 照实重写）。`ids.py` 只依赖标准库，不 import `rdp.infra.db`、`rdp.infra.logging`。
2. `rdp.infra.db.validation` 只留数据库自己的东西：`ERROR_SOURCE_CHECK_SQL`、`invalid_field`，所需常量从 `rdp.infra.ids` 引入。不要在 `validation` 里留转发别名，所有调用方直接改成从 `rdp.infra.ids` 引入（`logging.py`、`api/errors.py`、`api/error_details.py`、`db/models.py`、`db/records.py`、`db/migration.py`，以及 `tests/` 里用到的地方）。
3. 去掉靠切片去锚点的写法：在 `ids.py` 里定义不带锚点的核心正则（例如 `REQUEST_ID_CORE`），`REQUEST_ID_PATTERN`、`ERROR_ID_PATTERN` 由它拼出来，值和现在逐字相同。代码里不再出现 `[1:-1]` 切正则。
4. `db/migration.py` 里匹配备份文件名的正则现在借用了请求编号规则来匹配文件名里的 uuid 后缀，这是两个不相关的概念。在 `migration.py` 里给备份后缀单独定义一个具名的正则常量（uuid4 hex），不再引用请求编号规则；能匹配的文件名集合和现在完全相同。
5. 在 `pyproject.toml` 的 import-linter 里加一条 `forbidden` 合同："基础层的日志不得依赖数据库包"，`source_modules = ["rdp.infra.logging", "rdp.infra.ids"]`，`forbidden_modules = ["rdp.infra.db"]`，写一行注释说明理由（M0 工单 06 前置，负责人 2026-10-25 批准）。这是本步唯一允许改的受保护文件，只加这一条合同，别的段不动。
6. 测试：新建 `tests/test_ids.py`，给 `is_request_id`、`error_source_kind` 写直接测试，覆盖 docstring 写的每种情况（合法 uuid4 hex、大写、版本位或 variant 位不对、长度不对、非字符串、None；作业编号 1、上限、上限加一、前导零、0、负数、空串、带空白），再加一条"`ERROR_ID_PATTERN` 的值和改动前逐字相同"的测试（把改动前的字面量写进测试）。备份文件名正则加一条测试：平台生成的备份名能匹配，把 uuid 后缀换成大写或少一位就不匹配。原有测试只改 import 路径，断言不动。
   - 这是纯搬移，实现本来就对，新测试一开始就通过是预期的；在最终回复里说明即可，不用为了看红故意写错实现。

`make check` 要全绿。每改完一块只跑相关测试，最后只跑一次 `make check`。不要用 `make fmt` 改动本步以外的文件。

边界：
- 只改 `src/`、`tests/`。本步允许改的受保护文件：`pyproject.toml`（只加上面第 5 条那一条 import-linter 合同）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。列出改了哪些 docstring（应当只有模块 docstring）。
4. 拿不准、需要评审决定的地方（没有就写"无"）。
5. 新测试每个一行，写第一次单独运行的结果。
