# M0 遗留事项

两轴评审里不打回的判断题和坏味道（`docs/agents/codex-workflow.md` 3.5「什么算不通过」）。里程碑结束前由 `/retro` 处理：改进编码规范，或者单开一张整理票。

## 第 5 张 数据库与迁移（r1-done 评审）

- **请求编号规则的归属**：规则放在 `rdp.infra.db.validation`，`rdp.infra.logging` 因此依赖数据库包。应移到 `rdp.infra` 下一个中立的模块。第 6 张开工前定。
- **公开辅助函数只有间接覆盖**：`utc.format_utc_text`、`validation.py` 的三个公开函数，docstring 写的拒绝条件没有直接用例（7.1 判定偏宽）。
- **重复**：`BUSY_TIMEOUT_MS / 1000` 出现 4 次，可以定义 `BUSY_TIMEOUT_S`；`Path(url.database or "未知数据库")` 有 5 处。
- **正则靠切片去锚点**：`REQUEST_ID_PATTERN[1:-1]`；`migration.py` 拿请求编号的规则去匹配备份文件名里的 uuid 后缀，两个概念绑在了一起。
- **前端**：`errorDetails.ts` 和 `problems.ts` 各写一份请求编号正则；`{0,18}` 没有从 `MAX_SQLITE_INTEGER` 推出来；`staleTime`、`gcTime` 没写成具名常量。
- **遗留写法**：`migration.py` 用字符串 `"清理旧备份"` 决定后果文案（Repeated Switch）；`migration_config` 和 `ScriptDirectory.from_config` 重复构造；`is_request_id` 可以改成返回 `TypeIs`。
- **报负责人、要改含义的**：`BACKUP_TIMEOUT_S = 5.0` 是整个备份的总时长上限，M1 库变大以后可能超时；显式抛出的程序缺陷最多等约 6 秒才返回 500；没有 WAL 文件时用 `immutable=1` 读版本，依赖"先停服务"（B3）。
- **页面**：完整报错的 traceback 长行撑出 `DiagnosticCard` 边框（`demo-r2-done.png`），`<pre>` 需要横向滚动或换行。
- **数据库文件权限**：`rdp.sqlite3` 新建为 0644（随 umask），里面有完整报错。状态目录根是 0700 时外人进不去，但工单没写库文件的权限，第 11 张部署时确认。

## 第 6 张 账号、登录与会话（B4、r1 评审）

- **安全 LOW，报负责人**：Argon2 名额等待（最多 1 秒）阻塞在 AnyIO 公共线程池里。局域网内未登录客户端保持约 40 个以上并发登录，就能占满线程池，已登录用户的所有接口都要排队。登录名不存在也会做一次假哈希。修复方向：在协程里异步等名额（`anyio.CapacityLimiter`），或者给登录单独开一个小线程池。建议 M5 部署加固时处理。
- **前端真实浏览器冒烟**：`defaultFetch` 的 Illegal invocation 是演示才抓到的，Vitest 全用替身传输。第 11 张接入口以后，`make check` 之外应当有一条无头浏览器冒烟（打开首页 → 跳登录页）。演示脚本在 `assets/06-…/demo06.{py,mjs}`。
- **时间显示**：账号表的时间用浏览器默认 locale（`toLocaleString()`，无头 Chrome 显示 "10/25/2026, 1:19:40 PM"）。全平台应统一成中文 locale 和明确的时区标注。
- **阈值硬编码**：`_sessions.wait_error` 的 `min(60, …)`，以及 `errors.account_error_headers`、`LoginWaitError` 里的 `1 <= … <= 60`，应从 `LOGIN_WAIT` 推出；`service._begin_was_busy` 的 `range(8)`、`& 0xFF` 没有说明；`Pages.tsx` 倒计时的 1000 毫秒没有具名。
- **重复**：
  - "ensure_utc + 加 `LOGIN_WAIT` 试溢出"有三份（`_records.utc`、`account_auth.get_account_now`、`ops.accounts._moment`）。
  - traceback 定位取最后 20 帧有两份（`_boundary._safe_error`、`errors.sanitize_account_error`）。
  - `reset_password` 和 `reset_password_from_ops` 的重置块几乎一样。
  - 编号校验有三处。
  - `ActorRef(actor.account_id, actor.display_name)` 写了 5 次。
- **冗余防御**：管理员角色在中间件、`get_admin_context`、领域层三处检查。变异抽查确认，只删 `get_admin_context` 那处时没有测试失败（等价）。领域层那处有必要；入口的两处可以合并。
- **前端 search params**：`Pages.tsx` 用 `URLSearchParams` 读 `permission`，没走 TanStack Router 的类型化 search（10.6）。
- **`errors.py` 模块 docstring 的状态码简表**：r1 已同步并注明以 6.2 为准。以后改 6.2 时还要记得改这里，可以考虑删掉这份副本。
- **规格之外、已在评审中认可的行为**（汇报负责人）：
  - 每账号最多 32 个会话，超出时淘汰最旧的。
  - 登录名格式 `^[a-z][a-z0-9_.-]{2,31}$`，口令最长 128。
  - 改自己口令输错旧口令也计入 G2。
  - 改角色时撤销会话。
  - 运维重置也置"必须改口令"。
  - 活动时间每 60 秒最多落库一次，抢不到锁就跳过（空闲超时可能提前不到 60 秒）。

## 第 7 张 操作日志与登录日志（B3 评审）

- **安全 MEDIUM，报负责人**：G2 等待期内的登录尝试不走 Argon2，也没有限流，每次都写一条 `waiting` 登录日志，外加一次短写事务。知道登录名的人可以先错 5 次，再在等待期内高速刷，淹没登录日志、抢 SQLite 写锁；等待结束后再错 5 次就能续期。工单要求"记每次登录尝试"，所以没有去重。可选做法：同一账号在一个等待期内只记一条（附计数），或者纳入入场限制。和第 6 张的线程池 LOW 同类（局域网未登录洪泛），建议 M5 一起处理。
- **易用性**：账号筛选要手输内部编号（操作人、对象、登录账号），表格里也不显示编号。应改成按账号选择，或至少在表格里显示编号。
- **明细列**：直接显示原始 JSON，含值为 null 的字段。应只显示有变化的字段，例如"改自己的口令：必须改口令 是 → 否"。
- **重复与命名**（标准评审）：
  - 编号长度 19 写了两份。
  - `ObjectRef("audit_settings", …)` 有三处。
  - 四类异常回退到 DEFECT 的判断写了两份。
  - `make_event` 参数组每个方法调两次。
  - 两个日志页面主体几乎一样；`query_operations`、`query_logins` 尾段相同。
  - `set_status` 的操作码判断写了两遍。
  - `_login` 模块的 `event`/`attempt`/`apply`/`reject` 名字太泛；`result` 变量其实是 `SessionGrant`。
  - TS 的 `_search` 已经在用，下划线前缀会误导。
  - `service.py` 直接 import `rdp.audit` 的私有模块。
  - `ObjectRef.kind` 用裸字符串。
- **前端文案**：`Pages.tsx` 自己拼"日志筛选参数不合法""保留期须为…天"，没走统一诊断（10.5）。
- **查询性能**：稀疏筛选可能全表扫描，量小，M1 实测。
