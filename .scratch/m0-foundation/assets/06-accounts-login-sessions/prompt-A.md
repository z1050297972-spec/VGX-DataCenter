前置重构（派工 A0）已经提交。现在在同一个工作目录里写本票「账号、登录与会话」的契约骨架。

先读下面这些。规划文件一律用绝对路径读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件（比如工单的 Comments）。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md（尤其第 1、2、3 条（含 3.5 TSDoc）、5.1–5.5、第 6 条全部（6.2 状态码表、6.3 只在边界报告、6.10 敏感信息）、第 7 条（7.5 可控时钟）、9.1 的表）
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/06-accounts-login-sessions.md：「范围」「验收」「风险」「允许改的受保护文件」，以及 Comments 里负责人批准的 G1–G3、第 4 张定的状态码表补 401/403、S1（`/api/{path}` 分清 404 和 405）、第 5 张定的"`GET /api/errors/{id}` 本票加登录，所有登录账号都能看"
- 第 5 张工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/05-database-migrations.md 的「范围」和 Comments 里"Codex 定下的要点"（`session_scope`、`BEGIN IMMEDIATE`、只读会话、UTC 列类型、共用 `MetaData` 和约束命名、迁移只往前、`migrate` 前备份）
- /home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/02-interaction-frontend.md 的 Answer 里"访问范围与账号"和"HTTPS"
- /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/spec.md 的 S2 和第 06 张那一行
- /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里的账号、角色、管理员、成员等术语
- 工作目录里已有的代码：`src/rdp/infra/db/`（连接、会话、UTC 列类型、`models.py` 的 `MetaData`、迁移 `migrations/versions/`）、`src/rdp/infra/ids.py`、`src/rdp/infra/diagnostics.py`（四类异常、`ALLOWED_HTTP_STATUSES`）、`src/rdp/infra/timeutil.py`、`src/rdp/api/`（`create_app`、`database.py` 的会话依赖、`errors.py`、`error_details.py`）、`src/rdp/ops/`、`src/web/src/`（`router.tsx`、`api/client.ts`、`problems.ts`、`DiagnosticCard.tsx`）、`pyproject.toml` 的 import-linter 合同
- 已装好的依赖：argon2-cffi 25.1.0（依赖提交已做，负责人已批准）。前端已有 @tanstack/react-router、@tanstack/react-query、antd、openapi-fetch，不加新的。

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和完整契约文档写全：Python 是六项 docstring（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条），函数体只写 `raise NotImplementedError`；pydantic 模型、dataclass、枚举、SQLAlchemy 表模型写 `Attributes:`，每个字段（列）写含义、单位、取值范围、可空、默认值。TypeScript 是 TSDoc（3.5），函数体只写 `throw new Error("未实现")`；React 组件写 TSDoc，渲染体可以先返回占位。
2. 测试清单写成跳过的测试：pytest 用 `pytest.skip`，docstring 写明它验证哪条契约行为；Vitest 用 `it.skip`，标题写明。对着每个函数 docstring 里的每条 `Raises:`、每种返回情况、每项副作用（包括失败时留下什么），逐条都有测试（7.1），并覆盖工单「验收」第 1–9 条、S1 的那条验收。
3. `make check` 全绿（十一步）。已有接口的行为在骨架阶段不变；新路由或 OpenAPI 改动用 `make api-types` 重新生成，不手改生成文件。新迁移脚本 `0002_...` 骨架阶段可以先写成 `raise NotImplementedError`，但要保证现有迁移和建表 SQL 一致性测试仍然全绿（例如新表模型先不注册进共用的 `MetaData`，或者相关测试先跳过；你定，写进第 4 块）。

本次交付（模块路径按工单）：
- **领域模块 `rdp.accounts`**（新包，领域层，和 `rdp.jobs` 同层；不 import fastapi、starlette）：
  - 账号表、会话表、登录失败记录（G2 需要的计数和等待截止时间存在哪，表还是账号表的列，你定）的 SQLAlchemy 模型，共用第 5 张的 `MetaData`，时间列一律用 UTC 列类型。迁移脚本 `0002`（只往前）。
  - 账号：内部编号（自增，永不复用：SQLite 用 `AUTOINCREMENT`，写明为什么）、登录名（唯一；大小写、首尾空白、允许字符、长度上限，定下来）、显示名、角色（管理员、成员）、状态（启用、停用）、口令哈希、"下次登录必须改口令"标记（G3）、创建和修改的时间与人（"人"用编号加当时的名字，见下面的值对象；首个管理员由运维命令创建时"人"写什么，定下来）。
  - 口令：Argon2id，库的默认参数（`argon2.PasswordHasher()`）；登录成功时 `check_needs_rehash` 为真就重新哈希。G3：至少 10 个字符，上限多少（防止超长口令拖慢哈希）、按什么计数，定下来；不要求字符组合。口令只在内存里出现，不进日志、诊断、异常消息、报错表（6.10）。
  - 不变量：至少一个启用的管理员。停用、删除、降级最后一个启用的管理员，以 `ConflictError` 拒绝。并发下怎么保证（第 5 张写会话是 `BEGIN IMMEDIATE`，写锁串行），写进契约。
  - 会话：服务端会话表存会话编号的哈希（用什么哈希，例如 SHA-256，写明为什么不用 Argon2）、账号编号、创建时间、最后活动时间。cookie 只放 `secrets.token_urlsafe` 的原文。G1：最后活动时间起连续 7 天不用就过期，不设绝对上限；每次请求刷新最后活动时间——刷新会让每个请求都写库，定一个刷新的最小间隔（具名常量）来减少写入，写明对过期判断的影响。过期会话什么时候删（访问时顺手删，还是由第 9 张定时清理，或者两者），定下来。
  - 账号被停用、删除，或口令被重置时，它的全部会话在同一事务里删除。
  - G2：同一账号连续输错 5 次，要等 1 分钟才能再试，不锁死账号；等待中的登录直接拒绝，提示还要等多久（不做口令校验）。登录名不存在时怎么处理（既不能泄露"账号存在与否"，也要防止对不存在的登录名无限尝试；耗时上是否也要对齐，比如对不存在的账号也做一次哈希），定下来。成功登录清零。等待中返回什么状态码（看 6.2 的表，429 是否在 `ALLOWED_HTTP_STATUSES` 里；不在就停下，写进第 3 块）。
  - "记录存名字"的值对象（验收 9）：例如 `ActorRef(account_id, name)`，第 7、8 张用；写明 `name` 取登录名还是显示名、为什么。
  - 所有用到"现在"的函数都把时刻作为参数传入，或者注入时钟（7.5），测试用固定时钟。
- **运维函数** `create_first_admin(...)`：放在 `rdp.ops` 下。交互式输入口令（`getpass`，两次一致），只在还没有任何管理员时可用，否则 `ConflictError`。为了可测，把"读口令"作为可注入的参数。第 11 张接进命令入口，本票只做函数。另外给一个重置口令的运维函数（运维手册"忘记了唯一管理员的口令怎么办"要用），重置后同样删会话、置"下次登录必须改口令"。
- **接口**（`rdp.api`）：
  - 登录、登出、"我是谁"、改自己的口令；管理员：列出、新建、改角色、停用和启用、重置口令、删除账号。路径、请求和响应模型、状态码逐个写清，进 OpenAPI。响应里永远不出现口令哈希和会话编号。
  - 鉴权依赖：除了登录和健康检查，所有 `/api/*` 都要登录（包括 `GET /api/errors/{id}`，所有登录账号都能看）；管理员接口还要管理员角色。没登录或会话过期 401，角色不够 403，都用第 4 张的错误格式（`ProblemResponse`），带诊断。"下次登录必须改口令"的账号，在改口令之前除了改口令、登出、"我是谁"，其他接口返回什么，定下来。
  - 怎么保证"除了白名单都要登录"不会漏：例如在应用层统一挂、白名单显式列出，再加一个测试遍历所有已注册的 `/api/*` 路由，确认每个都要求登录（白名单除外）。
  - cookie：名字、`HttpOnly`、`SameSite=Lax`、`Path=/`，不加 `Secure`（只走 HTTP，代码注释写明是权宜，M5 上 HTTPS 时加）；过期时间（`Max-Age`）和 G1 怎么配合，定下来。
  - 跨站：非 GET（以及 HEAD、OPTIONS 以外）的请求检查 `Origin` 和本站一致；没有 `Origin` 头时怎么办（有的客户端不发），定下来并说明风险。"本站"怎么判断（`Host` 头，还是配置），定下来。拒绝时 403 带诊断。
  - S1：`/api/{path}` 兜底路由分清"路径不存在"（404）和"路径存在但方法不对"（405，带 `Allow` 头）。
  - 状态码表：本票新增 401、403（以及 G2 等待中的状态码）的用法，`rdp.api.errors` 模块 docstring 里的表同步改。`CODING_STANDARDS.md` 和手册由 Claude 改，你不用写。
- **前端**（`src/web/src/` 下）：登录页；右上角当前账号和登出；改口令页（必须改口令时登录后直接进这一页）；管理员的账号管理页（列表、新建、改角色、停用和启用、重置口令、删除，删除和停用要二次确认）。没登录时任何页面都跳到登录页，登录后回到原来的页面（回跳地址只允许站内路径，防止开放重定向）。任何接口返回 401 时统一跳登录页。用 @tanstack/react-router 和 antd，类型用生成的 OpenAPI 类型。每个组件和函数写 TSDoc，Vitest 测试清单覆盖跳转、回跳、401 处理和各页面的错误显示。
- **import-linter**：登记 `rdp.accounts` 为领域模块（工单允许改的受保护文件）。只改 import-linter 段；依赖表不动。
- **测试**：只用 `tmp_path` 和临时数据库，不碰真实的 `~/.local/share/rdp`、`~/.config/rdp`。时间用固定时钟。测试里的 Argon2 太慢可以用更低的参数，但要有至少一条测试用默认参数，写明。

要特别注意的地方：
- 安全是本票的重点，评审会加跑 `/security-review`。口令、会话编号原文、cookie 不进日志、诊断、报错表、异常消息、OpenAPI 示例（6.10）；用 `hmac.compare_digest` 之类的常量时间比较；登录失败的提示不区分"账号不存在"和"口令错"。
- 中间层不打日志（6.3）；领域层把错误转成四类异常往上抛。登录日志和操作日志是第 7 张的事，本票不记。
- 不要写 `.git/info/exclude`。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 import-linter：登记 `rdp.accounts`；依赖表不动，别的段不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 那步要能看出 passed 和 skipped 的数目，Vitest 那步要能看出 skipped 的数目）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请（对已获批的第 3–5 张契约的改动，例如 `create_app`、`ProblemResponse`、`ALLOWED_HTTP_STATUSES`、状态码表）、依赖申请、受保护文件申请：没有就写"无"。
4. 拿不准、需要评审决定的地方，包括上面要你"定下来"的每一处：你定的是什么、为什么。
