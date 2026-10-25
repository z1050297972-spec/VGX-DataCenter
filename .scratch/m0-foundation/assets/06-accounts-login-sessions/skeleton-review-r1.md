# 第 6 张骨架复核（r1，只读）

范围：工作区 `robot-data-platform.wt/m0-06-accounts-login-sessions`。已确认工作区和 `refs/rdp/m0-06/A-r1-done` 一致：`git diff` 里的 23 个"删除"都是未跟踪文件，逐个和 ref 内容比对过，全部相同。本轮改动的依据是 `git diff A-r1 A-r1-done`（27 个文件，+670/−525）。没有重跑 `make check`，以 out-A-r1 报的结果为准：pytest 557 passed / 274 skipped，Vitest 77 passed / 47 skipped。

## 1. 逐条落实情况

| 项 | 落实 | 位置 |
|---|---|---|
| 决定 1 方案甲 | 已落实。全局预算、1024 桶、`LoginThrottleRow` 表和对应测试都删了，grep 查不到残留。未知名或停用账号做一次假哈希，返回统一 401，不计数、不建行。Argon2 共享名额 2 个，排队 1 秒，超时 502 | policy.py:183-186；security.py:5-11、57、79、104；service.py:73、81、85；accounts.py:64；models.py（LoginThrottleRow 已删）；tests/test_accounts.py:504-539、:613；test_account_api.py:391；test_account_ops.py:91 |
| 决定 2 新建账号必须先改口令 | 已落实。管理员建号置 must_change_password=True；首号为 False，由运维创建 | service.py:243、257、417、428；accounts.py:232；test_accounts.py:321、436；test_account_api.py:296 |
| 决定 3 缺 Origin 一律 403 | 已落实，并写明脚本要自己带 Origin | account_auth.py:87、137；test_account_api.py:351 |
| 1 不套模板 | 大体落实。十个路由的 Raises 各写各的；who_am_i、logout、改自己口令不再列 PasswordChangeRequiredError；login 不再列角色不足、重复登录名；list_accounts 全程只读，Raises 和 Side Effects 一致。还剩的问题见 A1、A2 和 B1 | accounts.py:57-65、91-98、121-127、160-168、199-207；service.py:212-228 |
| 2 时钟回拨 | 已落实。负经过时长按 0，存时刻取 max；把 409 当期望的测试已改掉 | service.py:91-93、130-131；test_accounts.py:211、499、544-554 |
| 3 判定顺序 | 已落实，但缺 6.2 新表里的"角色"这一步，见 A2 | account_auth.py:86-94；test_account_api.py:146、351-366 |
| 4 Argon2 并发上限 | 已落实，但 Argon2 在写锁里面跑，见 A3 | security.py:5-11 |
| 5 删 clear_expired_sessions | 已落实，函数、测试和参数化项都删了 | test_accounts.py:478 附近 |
| 6 测试缺口 | 已落实：ErrorBoundary 清 cookie（api:371）；认证阶段全路由脱敏（api:376、381；errors.py sanitize_account_error）；管理员动自己（api:386，test_accounts.py:584-594）；refetchOnWindowFocus（Pages.tsx:46、59-60，navigation.test.ts:44，Pages.test.tsx:64）；非法状态码换 418（test_api_errors.py:169） | 同左 |
| 7 刷新尽力而为 | 已落实，只对获锁时的 BUSY/LOCKED 豁免 | service.py:114-127；test_accounts.py:559 及以后 |
| 8 cookie 续期 | 已落实。新增 `activity_refreshed`，没提交刷新就不续 cookie | types.py SessionIdentity；account_auth.py:22、108、219；test_account_api.py:396 |
| 9 关闭文档路由 | 已落实，create_app 无条件关闭；离线导出照旧可用 | api/__init__.py create_app；test_api_database.py:203；test_web_app.py:46 |

## A 阻塞问题

**A1 改自己口令时旧口令输错返回 401，会把用户登出**
- 位置：`accounts.py:162`、`service.py:178`、`service.py:189`。
- 和这几条叠加：
  - 6.2 新表规定 401 要"同时清掉会话 cookie"（errors.py 的 account_error_headers 也是这样做的）。
  - 本轮第 6 条又定了前端"任何接口 401 统一跳登录"（accounts.ts:65）。
- 结果：用户在改口令页把当前口令输错一次，cookie 被删，页面被踢到登录页；服务端会话其实还有效。这也和 Pages.test.tsx:20"旧口令 401 可展示"矛盾。
- 改法：旧口令错误改用不带清 cookie 语义的状态码，例如 400 或 422 的 AccountInputError（"当前口令不正确"）。G2 照样计数，第五次照样 429。如果用 403，要先在 6.2 表里补一行。

**A2 判定顺序缺 6.2 新表里的"角色（403）"**
- 6.2 规定的顺序是 Origin→白名单→认证→强制改密→角色→路由。
- 契约 `account_auth.py:86-94` 只有五步，并且写明"管理员限制由相应业务依赖再核验"，角色实际在 service 里查（service.py:215、248 等）。
- 按这个写法，成员调用管理接口会出现两种和新表不符的结果：
  - 方法写错，例如 PUT /api/accounts，得到 405，不是 403；
  - body 或路径参数不合格，FastAPI 先返回 422，根本走不到角色检查。
- 两种改法，二选一：
  - (a) 加一个管理员依赖，例如 `get_admin_context`，在参数校验之前返回 403；service 在事务里照样再核验一次。这要在契约里加一个函数。
  - (b) 把 6.2 那一行改成"角色（403，仅已匹配的操作，在参数校验之后）"。
- 我倾向 (a)。不管选哪个，契约和规范要一致，再补一条测试："成员带错误 body 或方法调用管理接口"。

**A3 Argon2，包括最多 1 秒的排队，都在 BEGIN IMMEDIATE 写锁里面执行**
- 位置：
  - `service.py:82-86`（login：先 BEGIN IMMEDIATE，再核验、再保存）
  - `:186-188`（change_password：同一写事务里核验旧口令）
  - `:256-258`（create_account）
  - `:365`（reset_password）
  - `:427`、`:459`（运维）
- 本轮加了信号量，于是持有 SQLite 写锁的线程可能要先排队最多 1 秒，再做一次 Argon2（默认参数约几十到几百毫秒）。这段时间里，worker、活动刷新和其他写入都在等这把锁，busy_timeout 约 5 秒。几次登录排起来，别的写入就会出现 409。运维函数自己都规定了"输入期间不持锁"，这里是同一个道理。
- 改法：在契约里写死"不在写事务里申请名额或做 Argon2"。
  - 新口令哈希（建号、重置、运维、改密的新哈希）先在事务外算好。
  - 核验口令：先用只读事务读出哈希和 G2 状态，在事务外 verify，再 BEGIN IMMEDIATE 重读三样：口令哈希没变、账号仍启用、G2 状态。三样都对才提交计数或会话。哈希被并发改掉时，按失败安全处理（401，不计数）。
  - 并发错口令要防止计数超过 5：事务里重读后发现已经在等待，就不再加计数。
- 测试补一条："Argon2 执行和排队期间，别的连接能拿到写锁"。

## B 非阻塞建议

1. **服务器时钟无效被写成 422。** 各路由的 Raises 都有"AccountInputError：请求时钟无效，422"（如 accounts.py:58、94、123；account_auth.py:100、159、188）。注入的时钟出错是平台自己的问题，按 6.2 应该是 500（DefectError）。建议在入口把 service 因 `now` 不合格抛出的 AccountInputError 当缺陷处理，路由 Raises 改成 DefectError。service 层保留 AccountInputError，供运维等直接调用方使用。
2. **活动刷新拿锁会白等约 5 秒**（account_auth.py:116、service.py:132）。既然拿不到锁就跳过，刷新事务的 busy 等待应该设成很短，例如 0 到 100 毫秒，或者直接不等。否则 worker 写库时，每个 GET 都会先卡 5 秒再放行，尽力而为就失去意义了。
3. **残留的模板句和重复测试。**
   - 十个路由的 Side Effects 都有同一句"不记录或报告口令、cookie、令牌、哈希；中间层不打日志……"，可以挪到模块 docstring 里说一次。
   - `test_install_docs`（test_account_api.py:36）和 `test_documentation_routes_disabled`（:406）测的是同一件事，合并成一条。
   - 领域层的 security.py:7 写了"HTTP 502"，领域层不该知道 HTTP 状态码，删掉，只留 ExternalError。
4. **上一轮的 B1、B2 本轮没采纳，可以保留但要留个记录。**
   - B1：查库后还用 `hmac.compare_digest` 复核摘要（security.py:155、service.py:120）。
   - B2：改角色时撤销该账号全部会话（service.py:294）。这会让被提升为管理员的成员也被踢下线。
   - 两条都请负责人在提交说明里点一句"保留"。
5. **6.2 表的 502 那一行补一个例子**，写上"Argon2 哈希资源繁忙（第 6 张）"，让表继续是唯一的事实来源。现在那一行只写了"依赖的外部东西出错"，和哈希资源繁忙对不上。

## 4. Argon2 排队 1 秒超时返回 502

**有条件认可。**

- **为什么可以选 502**：可选的几个都不合适。
  - 503 不在 6.2 表里。
  - 429 已经专门给 G2 用，前端会显示等待倒计时，用户会误以为自己被限制了。
  - 409 的意思是和当前状态冲突，对不上。
  - 让请求无限等，会占满 FastAPI 线程池（约 40 个线程）。
  - 502 至少不会被当成"口令错误"：不计 G2，不清 cookie，前端单独显示"资源繁忙"（accounts.test.ts:72）。
- **1 秒是合理的**：按 argon2-cffi 默认参数（t=3，64 MiB，并行度 4），2 个名额 1 秒内能处理几十次核验。内部工具正常使用时几乎碰不到这个超时；被洪泛时只是登录暂时失败，不会留下锁死状态。
- **前提条件**：
  1. 排队和运算不能在写锁里（A3）；
  2. 6.2 表的 502 行补上这个用途（B5）；
  3. 诊断写"哈希资源繁忙，请稍后重试"，不带 Retry-After，前端不自动重试（契约里已经写了）。
- **接受的代价**：攻击者用乱输的登录名洪泛，能让正常登录暂时拿到 502。这正是方案甲接受的取舍，负责人已经知道。

## 本轮有无引入新问题

- **安全**：没有发现新漏洞。改密页 401 的问题（A1）早就存在，是本轮"前端 401 统一跳登录"把它变成了必然发生。
- **范围**：没有蔓延。`activity_refreshed`、四个跳过的测试文件、create_app 关闭文档路由，都对应修复清单里的条目。create_app 这一处改的是现有函数的真实代码（`docs_url=None` 等三项），属于第 9 条批准的范围，相关旧测试也同步改了（test_api_errors.py:730、test_web_app.py:46、test_api_database.py:203）。
- **分层**：没有问题。`rdp.accounts` 只用到标准库的 threading，没有 import fastapi。唯一的例外是 security.py:7 文字里提到了 HTTP 状态码（B3）。

## C 结论

**需要再改。** A1 到 A3 都只改契约文字和跳过测试清单，改动面小。改完可以直接契约提交，不需要再全面复审，只核对这三处即可。
