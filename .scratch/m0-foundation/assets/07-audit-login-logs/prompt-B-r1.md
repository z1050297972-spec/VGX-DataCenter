评审第 1 轮打回。整体很好：`make check` 我复跑全绿，标准、规格、安全三路评审都没有发现代码缺陷，15 个变异抓住 14 个，真实浏览器里两个页面、筛选表单、成员 403 都正常。只改下面几处，别处不动，规则照 prompt-B.md（先读 7.1；只改 `src/`、`tests/`，不暂存不提交，不安装不联网）。

**必须改的**
1. **筛选参数在真实浏览器里会让页面崩掉。** 直接打开 `/audit/operations?target_account_id=2`（手输或分享的链接，数字不带引号）时，TanStack Router 把 `2` 解析成数字，`validateSearch` 只认字符串而抛错，整页显示"请求失败，请检查网络或稍后重试"；`/audit/logins?account_id=abc` 也一样。契约写的是参数不合法时显示"日志筛选参数不合法"。期望：
   - 编号参数接受数字形式的安全整数（`Number.isSafeInteger` 且为正），转成十进制字符串；超出安全整数范围的数字已经丢了精度，按不合法处理（写进 TSDoc）。字符串形式照旧。
   - 不合法的参数不让路由崩溃：页面照常渲染，显示"日志筛选参数不合法"，不发日志请求。
   - 补测试，先红后绿：用真实的 router（内存 history）分别打开 `?account_id=2`、`?target_account_id=2`、`?account_id=abc`，断言前两个按编号查询、第三个显示提示且没有请求。只测 `validateSearch` 函数本身不够，这次的问题就出在路由层。
2. **测试缺口**：`src/rdp/accounts/_login.py` 的 `attempt` 里，`state.known_missing` 为真时异常退出、补记 `ACCOUNT_MISSING` 的那条路径（约 77 行），删掉这次调用后没有测试失败。补一条测试：不存在的登录名在假哈希阶段出错（例如 Argon2 名额排队超时），原错误照常返回，同时留下一条"账号不存在"的登录日志，不含输入的登录名。先用删掉调用的变异看到红。
3. **具名常量（7.1）**：
   - `accounts/service.py` 的 `set_log_retention` 写了字面量 `7 <= days <= 365`，改用 `audit/policy.py` 的 `MIN_RETENTION_DAYS`、`MAX_RETENTION_DAYS`。
   - `"运维"` 在 `service.py` 出现 6 次（`ActorRef(None, "运维")`），`audit/_validation.py` 里又比较一次。收成一个具名常量（放在 `rdp.infra.actors`，例如 `OPS_ACTOR`），各处引用它。

**顺手改的**
4. `report_audit_append_failure`：登录日志补记失败时也记"操作日志补记失败"，文案按日志种类区分。`api/audit.py` 和 `ops/audit.py` 里这个函数逐字相同，只留一份。
5. `api/account_auth.py` 两处函数内 `from rdp.api.audit import request_audit_context`：写一行注释说明为什么放在函数内（避开循环 import）；能挪到模块顶部就挪。

第 1、2 条在最终回复里写明你用的变异或失败输出的一行。最终回复四块：1. 逐条处理结果；2. `make check` 末尾输出原样；3. 契约变更申请：没有就写"无"（第 1 条要改 `search.ts` 的 TSDoc，列出改了哪几句）；4. 拿不准的地方。
