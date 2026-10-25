骨架关卡：负责人说"改"，修一轮再进实现。负责人同时批准了：状态码表的 INPUT 加 401、403、429（429 带 `Retry-After`，秒，向上取整）；`create_app` 加可选 `clock`。逐条修复下面的问题，别处不动。这一步仍然只改契约骨架（签名、类型、docstring/TSDoc、跳过的测试清单），函数体仍是 `raise NotImplementedError` / `throw new Error("未实现")`。

评审原文在 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/06-accounts-login-sessions/skeleton-review-A-done.md，可以参考，以本提示为准。

**负责人的三个决定**
1. **登录防护（方案甲）**：删掉全平台的登录核验预算（`LOGIN_GLOBAL_ATTEMPTS`、`LOGIN_GLOBAL_WINDOW` 及相关契约、表结构和测试），也删掉给不存在的登录名分的 1024 个桶。保留：G2 按账号计数（连续 5 次错误后等 60 秒，等待中不做哈希，返回 429）；不存在或停用的登录名照样做一次假哈希，统一返回"账号或口令错误"的 401，不计数、不建行。新增：进程内 Argon2 并发上限（具名常量，取 2），拿不到名额时最多排队多久、超时后返回什么（建议 503 不在表里，那就按外部失败 502 或者等待；你定，写清楚），写进契约和测试。账号是否存在能被探测出来，负责人接受。
2. **管理员新建的账号，首次登录也必须先改口令**（和重置口令后一样，置"下次登录必须改口令"）。首个管理员由运维命令创建，口令是本人交互输入的，不置这个标记。
3. **写请求不带 `Origin` 一律 403**（包括以后的命令行脚本），负责人接受。契约里写明脚本要自己带 `Origin`。

**必须改的（评审 A1–A6）**
1. **契约不能套模板（3.2）**：`src/rdp/api/accounts.py` 十个路由的 `Raises:` 逐个只写这个路由真会出现的情况（例如 `who_am_i`、`logout`、改自己的口令在强制改密允许集合里，不写 `PasswordChangeRequiredError`；`login` 不写"角色不足""重复登录名"）。`src/rdp/accounts/service.py` 每个方法的 `Time Semantics`、`Side Effects` 按自己的实际写，不共用一段；`list_accounts` 是只读事务，`Raises` 和 `Side Effects` 要一致。改完自查所有新增公开函数，没有互相矛盾的句子。
2. **时钟回拨**：`now` 早于已存时刻时不报 `ConflictError`，按"经过时长为 0"处理：活动、修改时间取 `max(已存, now)`，等待截止和过期判断都不因回拨而延长或提前。删掉把 409 当期望的测试（`tests/test_accounts.py` 第 227、536 行附近），改成"回拨不报错、不延长等待"的测试。
3. **请求的判定顺序写死**，写进 `account_auth.py` 的契约：非安全方法先查 `Origin`（缺失、`null`、不一致 → 403）→ 公开白名单（健康检查 GET、登录 POST）→ 认证（没登录或过期 → 401）→ 强制改密（→ 403）→ 路由匹配（不存在 → 404，方法不对 → 405 带 `Allow`）。健康检查、登录路径的错误方法：带正确 `Origin` 时返回 405。测试相应改：`test_fallback_health_method` 带正确 `Origin`；另加"缺 `Origin` 的写请求在任何路径上都先 403"、"带正确 `Origin` 的匿名写请求在业务路径上 401"。
4. **Argon2 并发上限**：见决定 1。
5. **删掉 `clear_expired_sessions`**（`service.py` 第 472 行附近，工单里没有、没有调用方）及其测试。过期会话在访问时删，每账号最多 32 个会话已经给了上界。
6. **测试缺口（7.1）**，补跳过的测试：
   - `ErrorBoundary` 出口的 401 清 cookie；
   - 认证阶段的脱敏覆盖所有路由（口令、令牌、cookie 不进日志、诊断、报错表、异常）；
   - 管理员停用、删除、降级自己（不是最后一个启用的管理员时）以后，当前会话下一次请求 401 或 403，按契约；
   - 验收 11"成员立刻被踢回登录页"：前端契约写明，身份查询开 `refetchOnWindowFocus`（切回窗口时重新查身份），任何接口返回 401 时统一跳登录页；加 Vitest；
   - `tests/test_api_errors.py` 第 168 行附近原来用 403 当非法状态码，现在 403 合法了，换成 418，断言照旧有效。

**顺手改的（评审建议，执行线采纳）**
7. 60 秒一次的活动刷新拿不到写锁时尽力而为：本次请求照常通过，不因刷新失败返回 409；写进契约和测试。
8. cookie 只在登录、改口令和活动刷新落库时续期，不在每个响应都重发。
9. `create_app` 无条件关闭 FastAPI 自带的 `/docs`、`/redoc`、`/openapi.json`（它们不在 `/api` 下，全局鉴权管不到）；OpenAPI 导出照旧由 `openapi_export` 离线生成，确认 `make api-types` 和 OpenAPI 过期检查仍然可用。

改完 `make check` 全绿（跳过数会变，没关系），用 `make api-types` 重新生成，不手改生成文件。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 import-linter；依赖表不动，别的段不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络。需要新依赖时停下，写依赖申请。
- 自己建的试验文件交付前删掉。测试只用临时目录。

最终回复分四块：
1. 逐条写处理结果（决定 1–3，第 1–9 条）。
2. `make check` 最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请、受保护文件申请：没有就写"无"。
4. 拿不准、需要评审决定的地方（Argon2 排队超时后的处理要写在这里）。
