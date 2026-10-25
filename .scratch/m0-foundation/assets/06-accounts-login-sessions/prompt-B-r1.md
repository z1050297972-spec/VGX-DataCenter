评审第 1 轮打回。整体通过：`make check` 我复跑全绿，标准、规格、安全三路评审都没有发现代码缺陷，25 个变异里 23 个被抓住。只改下面五处，别处不动，规则照 prompt-B.md（只改 `src/`、`tests/`，不暂存不提交，不安装不联网）。

**必须改的**
1. **测试缺口：等待过期后从零计数**。`service.login` 的契约写了"已过期的等待从零重新计数"，但把 `_sessions.wrong_password` 第一行改成 `count = row.failed_attempts`（不清零）以后，没有测试失败。补一条测试：连错 5 次进入等待，时钟走过 60 秒后再错一次，应当是 401，不是 429；再连错 3 次仍是 401，第 5 次才 429。改自己口令那条路径如果共用同一段逻辑，一条测试即可，在 docstring 写明。
2. **测试缺口：业务事务里的空闲过期**。`_sessions.authorize` 里 `now - saved.last_seen_at >= SESSION_IDLE_TIMEOUT` 改成 `> SESSION_IDLE_TIMEOUT * 2` 以后没有测试失败。补一条领域测试：拿一个会话身份，在空闲超时整点（恰好等于）和之后调用一个需要授权的服务方法（例如 `list_accounts` 或 `create_account`），得到认证失败（401 类），且没有写入。
3. **S1 同步表**：工单 S1 要求同步 `rdp.api.errors` 模块 docstring 里的状态码表。现在"404、405 由 Starlette 直接返回"已经不对，502 也缺"口令哈希资源繁忙、排队超时"。按 `docs/standards/CODING_STANDARDS.md` 6.2（主仓库版本）改，最好只留简表并注明以 6.2 为准。

**顺手改的**
4. `tests/test_account_api.py` 的 `test_reset_account_password_failure`：docstring 写了"成员 403"，测试里没有这条断言。补上断言。
5. `test_argon2_capacity_response`：`workers` 在 `try` 里赋值、`finally` 之后使用，`submit` 抛异常时会被 `NameError` 掩盖。把赋值挪到 `try` 前面，或者改成不会掩盖原异常的写法。

新测试照旧先红后绿：先用变异（临时改实现）看到它失败，再恢复。第 1、2 条在最终回复里写明你用的变异和失败输出的一行。

最终回复四块：1. 逐条处理结果；2. `make check` 末尾输出原样（pytest、Vitest passed/skipped 看得出）；3. 契约变更申请：没有就写"无"；4. 拿不准的地方。
