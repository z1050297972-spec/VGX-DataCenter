本轮按约定交检查点，**整票尚未完成，未运行最终 `make check`**。API、运维和前端已完成；领域层还剩 51 个测试函数、68 个参数用例待补。改动均未暂存、未提交。

**1. 改动清单**

以下包含前次超时后保留的累计改动，每个文件一行：

```text
src/rdp/accounts/errors.py：实现 G2 等待异常校验。
src/rdp/accounts/models.py：激活账号、会话两表，注册共用 MetaData。
src/rdp/accounts/security.py：实现 Argon2、并发名额、令牌生成及摘要。
src/rdp/accounts/service.py：实现账号、登录、会话和权限事务。
src/rdp/accounts/_inputs.py：集中校验口令输入。
src/rdp/accounts/_issues.py：构造不含秘密的领域诊断。
src/rdp/accounts/_records.py：实现账号校验、快照及管理员不变量。
src/rdp/accounts/_sessions.py：实现 G2、会话签发、撤销和事务内复核。
src/rdp/api/__init__.py：安装全局鉴权与可控时钟。
src/rdp/api/account_auth.py：实现 Origin、鉴权顺序、角色检查、cookie 和 404/405。
src/rdp/api/account_schemas.py：实现安全响应转换。
src/rdp/api/accounts.py：实现十个账号接口。
src/rdp/api/error_details.py：更新已生效的登录访问说明。
src/rdp/api/errors.py：接通脱敏、Retry-After、401 清 cookie 和唯一报告。
src/rdp/api/_account_middleware.py：在解析请求体前鉴权，仅提交活动刷新后续 cookie。
src/rdp/infra/db/connection.py：实现独立连接的短锁等待。
src/rdp/infra/db/migrations/pending/__init__.py：删除。
src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py：移出 pending。
src/rdp/infra/db/migrations/versions/v0002_accounts_sessions.py：实现并启用 0002 迁移。
src/rdp/ops/accounts.py：实现双次无回显输入、首号创建和运维重置。
src/web/src/accounts/Pages.tsx：实现登录、改密、账号管理、当前账号菜单和保护布局。
src/web/src/accounts/Pages.test.tsx：启用全部 20 条页面测试。
src/web/src/accounts/navigation.ts：实现安全回跳、守卫和统一未登录导航。
src/web/src/accounts/navigation.test.ts：启用全部 11 条导航测试。
src/web/src/accounts/runtime.tsx：提供应用客户端及窗口聚焦身份查询。
src/web/src/accounts/testSupport.ts：提供独立的安全响应样本。
src/web/src/api/accounts.ts：实现十个 HTTP 函数、取消及超时，修正职责说明。
src/web/src/api/accounts.test.ts：启用全部 19 条请求层测试。
src/web/src/api/client.ts：导出统一默认传输供应用装配。
src/web/src/api/problems.ts：安全保留 429 的有界 Retry-After。
src/web/src/api/openapi.json：通过 make api-types 重新生成。
src/web/src/api/schema.d.ts：通过 make api-types 重新生成。
src/web/src/main.test.tsx：适配先查询身份的启动流程。
src/web/src/mountWeb.tsx：绑定账号应用的查询缓存和路由。
src/web/src/router.test.tsx：使用隔离路由工厂验证登录后的首页。
src/web/src/router.tsx：接通页面守卫、统一客户端和登录导航。
tests/test_account_api.py：全部 94 条测试启用并通过。
tests/test_account_ops.py：全部 19 条测试启用并通过。
tests/test_accounts.py：累计 126 个用例通过；新增数据库故障矩阵 48 例。
tests/test_accounts_migration.py：验证新表、迁移、回滚和升级前备份。
tests/test_db_connection.py：增加短锁等待及隔离测试。
tests/test_db_migration.py：适配 0002 为当前迁移版本。
tests/account_api_support.py：提供临时数据库、固定时钟和真实 ASGI 客户端。
tests/accounts_support.py：提供临时库及有界 Argon2 并发测试工具。
```

`/tmp/rdp-accounts-tdd` **已删除**。14 条 TS 未使用参数豁免已删除；S105 正则豁免保留，因为它是令牌格式规则，不是凭据。改动文件搜索“骨架／提案／派工／桩”无命中。

**2. 检查结果**

最终 `make check` 尚未运行，保留到全部剩余测试完成后运行一次。

已通过：Ruff、全量 basedpyright、契约检查、三个 import-linter 合同、OpenAPI 过期检查，以及前端全量 TypeScript、ESLint、Prettier 检查。

API：94 passed；运维：19 passed，均无 skipped。最后领域文件运行：

```text
.venv/bin/pytest tests/test_accounts.py -q

SKIPPED [12] tests/test_accounts.py:1546: 工单 06 尚待补齐的契约测试
SKIPPED [2] tests/test_accounts.py:1552: 工单 06 尚待补齐的契约测试
126 passed, 68 skipped in 5.47s
```

前端最后运行：

```text
cd src/web && node_modules/.bin/vitest run && node_modules/.bin/tsc --noEmit && node_modules/.bin/eslint . --max-warnings 0 && node_modules/.bin/prettier --check .

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-06-accounts-login-sessions/src/web


 Test Files  12 passed (12)
      Tests  127 passed (127)
   Start at  12:38:13
   Duration  4.50s (tests 45%, environment 32%, import 20%, transform 2%)

Checking formatting...
All matched files use Prettier code style!
```

Vitest 全量 **0 skipped**。

最后一组相关检查前，`git status --porcelain --untracked-files=all`：

```text
 M src/rdp/accounts/errors.py
 M src/rdp/accounts/models.py
 M src/rdp/accounts/security.py
 M src/rdp/accounts/service.py
 M src/rdp/api/__init__.py
 M src/rdp/api/account_auth.py
 M src/rdp/api/account_schemas.py
 M src/rdp/api/accounts.py
 M src/rdp/api/error_details.py
 M src/rdp/api/errors.py
 M src/rdp/infra/db/connection.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py
 M src/rdp/ops/accounts.py
 M src/web/src/accounts/Pages.test.tsx
 M src/web/src/accounts/Pages.tsx
 M src/web/src/accounts/navigation.test.ts
 M src/web/src/accounts/navigation.ts
 M src/web/src/api/accounts.test.ts
 M src/web/src/api/accounts.ts
 M src/web/src/api/client.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/main.test.tsx
 M src/web/src/mountWeb.tsx
 M src/web/src/router.test.tsx
 M src/web/src/router.tsx
 M tests/test_account_api.py
 M tests/test_account_ops.py
 M tests/test_accounts.py
 M tests/test_accounts_migration.py
 M tests/test_db_connection.py
 M tests/test_db_migration.py
?? src/rdp/accounts/_inputs.py
?? src/rdp/accounts/_issues.py
?? src/rdp/accounts/_records.py
?? src/rdp/accounts/_sessions.py
?? src/rdp/api/_account_middleware.py
?? src/rdp/infra/db/migrations/versions/v0002_accounts_sessions.py
?? src/web/src/accounts/runtime.tsx
?? src/web/src/accounts/testSupport.ts
?? tests/account_api_support.py
?? tests/accounts_support.py
```

检查后：

```text
 M src/rdp/accounts/errors.py
 M src/rdp/accounts/models.py
 M src/rdp/accounts/security.py
 M src/rdp/accounts/service.py
 M src/rdp/api/__init__.py
 M src/rdp/api/account_auth.py
 M src/rdp/api/account_schemas.py
 M src/rdp/api/accounts.py
 M src/rdp/api/error_details.py
 M src/rdp/api/errors.py
 M src/rdp/infra/db/connection.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py
 M src/rdp/ops/accounts.py
 M src/web/src/accounts/Pages.test.tsx
 M src/web/src/accounts/Pages.tsx
 M src/web/src/accounts/navigation.test.ts
 M src/web/src/accounts/navigation.ts
 M src/web/src/api/accounts.test.ts
 M src/web/src/api/accounts.ts
 M src/web/src/api/client.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/main.test.tsx
 M src/web/src/mountWeb.tsx
 M src/web/src/router.test.tsx
 M src/web/src/router.tsx
 M tests/test_account_api.py
 M tests/test_account_ops.py
 M tests/test_accounts.py
 M tests/test_accounts_migration.py
 M tests/test_db_connection.py
 M tests/test_db_migration.py
?? src/rdp/accounts/_inputs.py
?? src/rdp/accounts/_issues.py
?? src/rdp/accounts/_records.py
?? src/rdp/accounts/_sessions.py
?? src/rdp/api/_account_middleware.py
?? src/rdp/infra/db/migrations/versions/v0002_accounts_sessions.py
?? src/web/src/accounts/runtime.tsx
?? src/web/src/accounts/testSupport.ts
?? tests/account_api_support.py
?? tests/accounts_support.py
```

**3. 契约变更申请、依赖申请**

新增契约变更申请：**无**。依赖申请：**无**。未改受保护文件。

按已批准范围修正的文档：

- `accounts/models.py` 模块说明：改为两表已注册。
- `create_app`：删除未接线说明，说明统一鉴权已生效；补充编码器和假哈希初始化副作用。
- `account_auth.py` 模块、`install_account_security`：删除未安装阶段说明。
- `set_session_cookie`、`clear_session_cookie`：明确检查对象类型及头可修改性；“发送前调用”由调用方保证。
- `api/accounts.py` 模块：说明路由和鉴权已生效。
- `error_details.py` 模块及 `get_error_details`：说明 HTTP 全局边界要求登录和完成强制改密，成员也可查看。
- `handle_error`、`ErrorBoundary.__call__`、`account_error_headers`、`sanitize_account_error`：删除尚未接线说明。
- `_begin_transaction`：删除短锁等待尚未接线说明。
- `api/accounts.ts`：按批准将表单清理、缓存、导航、分页取消、查询配置移交页面、布局和菜单；HTTP 函数保留请求、超时和传入信号职责。
- `problems.ts` 的 `createProblemFetch`、`toFailureView`：补充仅保留合法 1–60 整数秒 `Retry-After`。
- `Pages.tsx` 五个组件：将占位返回说明改为实际表单、状态和诊断视图；根布局保护已生效。
- `mountWeb`：说明绑定应用查询缓存，页面先确认身份再请求业务数据。

**4. 尚未完成／需要评审决定**

无新增需求决定。本轮是续接检查点，下一轮仍需：

1. 完成 `tests/test_accounts.py` 以下 51 个函数，共 68 个参数用例。
2. 适配并复核旧 Python HTTP 测试的登录前置条件，包括 `test_web_app.py`、`test_api_errors.py`、`test_api_database.py` 和诊断演示相关测试。
3. 全部无 skipped 后，运行最终唯一一次 `make check`。

剩余领域测试：

```text
test_login_failures
test_login_rehash_commit
test_login_rollback
test_authenticate_revoked
test_authenticate_read_session
test_authenticate_failure
test_logout_failure
test_change_password_rollback
test_list_accounts_readonly
test_set_role_concurrent
test_set_role_errors
test_set_status_concurrent
test_set_status_errors
test_reset_password_errors
test_reset_password_rollback
test_delete_account_concurrent
test_delete_account_errors
test_delete_account_rollback
test_first_admin_concurrent
test_service_failure_cleanup
test_service_failure_secrets
test_concurrent_request_time_order
test_login_unknown_no_state
test_login_wait_skips_capacity
test_login_capacity_no_counter
test_clock_wait_rollback
test_clock_session_rollback
test_clock_mutation_rollback
test_authenticate_touch_busy
test_authenticate_touch_other_failure
test_authenticate_expired_delete_busy
test_authenticate_concurrent_touch
test_authenticate_repeated_busy_expiry
test_admin_disable_self
test_admin_delete_self
test_admin_demote_self
test_service_argon2_capacity_failure
test_current_password_error_type
test_login_hash_changed_after_verify
test_login_g2_changed_after_verify
test_login_disabled_after_verify
test_login_expired_g2_snapshot
test_password_change_hash_changed
test_password_change_session_revoked
test_password_change_g2_changed
test_password_change_mismatch_keeps_session
test_creation_rechecks_authority
test_first_admin_rechecks_after_hash
test_ops_reset_recreated_name
test_argon2_outside_database_transactions
test_rehash_calculated_before_write
```

**5. 首次运行记录**

以下每行一个测试函数或已批准合跑的同函数参数组。

- **P**＝一开始就通过（实现先于测试）。
- **R**＝首次失败，原因写在该行；现已通过。
- **R0**＝前次恢复记录为首次失败且后来通过，但恢复摘要未保留具体失败原因；这里不补造原因。

`tests/test_accounts.py`：

```text
test_codec_init_default：R0
test_codec_init_injected：P
test_codec_init_dummy：P
test_codec_init_failure：R0
test_password_hash_salt：R0
test_password_hash_bounds：R0
test_password_hash_unicode：R0
test_password_hash_invalid：R0
test_password_hash_failure：R0
test_password_verify_match：R0
test_password_verify_mismatch：R0
test_password_verify_rehash：R0
test_password_verify_invalid：R0
test_password_verify_corrupt：R0
test_password_verify_failure：R0
test_session_token_entropy：R0
test_session_token_failure：R0
test_session_digest_sha256：R0
test_session_digest_invalid：R0
test_session_digest_pure：P
test_actor_snapshot：P
test_actor_ops：P
test_actor_immutable：P
test_models_metadata：R0
test_models_utc：P
test_models_constraints：P
test_models_autoincrement：P
test_models_cascade：P
test_models_defaults：P
test_service_init_dependencies：R0
test_login_success：R0
test_login_forced：P
test_login_fixed_session：P
test_login_fifth：P
test_login_waiting：P
test_login_deadline：P
test_login_session_cap：P
test_login_invalid：P
test_login_clock：P
test_authenticate_current：R0
test_authenticate_invalid：P
test_authenticate_expiry：R0
test_authenticate_touch：P
test_authenticate_precision：P
test_logout_success：R0
test_logout_missing：P
test_change_password_success：R0
test_change_password_forced：P
test_change_password_mismatch：P
test_change_password_same：P
test_change_password_revoked：P
test_list_accounts_pages：R0
test_list_accounts_cursor：P
test_list_accounts_permissions：P
test_create_account_success：R0
test_create_account_validation：P
test_create_account_duplicate：P
test_create_account_permissions：P
test_set_role_success：R0
test_set_role_noop：P
test_set_role_last_admin：P
test_set_status_disable：R0
test_set_status_enable：P
test_set_status_noop：P
test_set_status_last_admin：P
test_reset_password_success：R0
test_delete_account_success：R0
test_delete_account_last_admin：P
test_first_admin_success：R0
test_first_admin_exists：P
test_first_admin_invalid：P
test_ops_reset_service_success：R0
test_ops_reset_service_errors：P
test_argon2_process_limit：R0
test_argon2_queue_timeout：R0
test_argon2_slot_release：P
test_argon2_rehash_capacity：P
test_argon2_running_cancellation：P
test_service_failure_database_categories：48 个参数例全部 P
```

`tests/test_account_api.py`：

```text
test_context_clock：P
test_context_login：R，未缓存登录上下文
test_context_authenticated：P
test_context_failure：P
test_install_default_deny：P
test_install_rollback：R，测试漏传必填 database；修正后实现直接通过
test_install_missing_database：P
test_access_anonymous：R，鉴权边界尚未接通
test_access_health：P
test_access_errors：P
test_access_role：P
test_access_forced：P
test_access_revocation：P
test_access_database_errors：P
test_access_order：P
test_access_thread：P
test_origin_same：P
test_origin_different：P
test_origin_missing：P
test_origin_malformed：R，显式端口 0 被错误当作默认端口
test_origin_safe_methods：P
test_origin_proxy：P
test_cookie_set：P
test_cookie_renew：R，活动刷新后缺少 Set-Cookie
test_cookie_clear：R，NotImplementedError
test_cookie_secret：P
test_cookie_failures：R，测试把秘密字面量写在 traceback 源码行；改用变量后通过
test_fallback_health_method：P
test_fallback_missing：P
test_fallback_known_method：P
test_fallback_query：P
test_fallback_broken：R，损坏路由装配被静默当作不存在
test_schema_requests：P
test_schema_secret_validation：P
test_schema_ids：P
test_schema_response：P
test_schema_bad_view：P
test_schema_list：P
test_error_contract_statuses：P
test_error_contract_wait_constructor：R0
test_error_contract_headers：R，NotImplementedError
test_error_contract_both_paths：R，缺少 Retry-After
test_error_contract_sanitize：R，NotImplementedError
test_error_contract_privacy：P
test_openapi_paths：P
test_openapi_security：P
test_openapi_generation：P
test_login_success：R0
test_login_failure：P
test_login_commit：P
test_logout_success：R，路由未实现，返回 500
test_logout_second：P
test_who_am_i_success：R，路由未实现，返回 500
test_change_password_success：R，路由未实现，返回 500
test_change_password_failures：P
test_list_accounts_success：R，路由未实现，返回 500
test_list_accounts_invalid：P
test_create_account_success：R，路由未实现，返回 500
test_create_account_failure：P
test_set_account_role_success：R，路由未实现，返回 500
test_set_account_role_failure：P
test_set_account_status_success：R，路由未实现，返回 500
test_set_account_status_failure：P
test_reset_account_password_success：R，路由未实现，返回 500
test_reset_account_password_failure：P
test_delete_account_success：R，路由未实现，返回 500
test_delete_account_failure：P
test_install_password_initialization：P
test_origin_missing_every_path：P
test_anonymous_write_with_origin：P
test_fallback_login_method：P
test_forced_before_routing：P
test_error_boundary_clear_cookie：P
test_authentication_secrets_all_routes：P
test_authentication_phase_marker：P
test_administrator_self_changes：P
test_argon2_capacity_response：P
test_cookie_no_touch_no_renewal：P
test_renewal_committed_only：P
test_documentation_routes_disabled：P
test_admin_dependency_declared：P
test_member_bad_body_precedes_validation：P
test_member_bad_method_precedes_routing：P
test_member_invalid_target_precedes_validation：P
test_access_order_all_stages：P
test_admin_context_cached：P
test_get_account_now_valid：P
test_get_account_now_invalid：P
test_get_account_now_callback_failure：P
test_clock_errors_not_user_errors：P
test_password_mismatch_response：P
test_credential_conflict_response：P
test_short_touch_timeout：R，测试重复执行 BEGIN；改用受管连接 begin 后通过
test_admin_included_router_classification：P
```

`tests/test_account_ops.py`：

```text
test_create_first_admin_success：R，NotImplementedError
test_create_first_admin_mismatch：R，NotImplementedError
test_create_first_admin_echo：R，NotImplementedError
test_create_first_admin_abort：R，NotImplementedError
test_create_first_admin_input_error：R，NotImplementedError
test_create_first_admin_domain_errors：P
test_create_first_admin_lifecycle：P
test_reset_account_password_success：R，NotImplementedError
test_reset_account_password_mismatch：P
test_reset_account_password_echo：P
test_reset_account_password_abort：P
test_reset_account_password_input_error：P
test_reset_account_password_domain_errors：P
test_reset_account_password_lifecycle：P
test_specific_first_exists：P
test_specific_reset_missing：P
test_specific_reset_atomic：P
test_argon2_capacity_failure：R，测试未创建临时库父目录；修正后通过
test_invalid_now_is_defect：R，测试误把无需计算等待截止的首号函数作为溢出入口；改测登录后通过
```

`tests/test_accounts_migration.py`：

```text
test_upgrade_new：R0
test_upgrade_existing：P
test_upgrade_noop：P
test_upgrade_failure：P
test_upgrade_utc_checks：R0
test_upgrade_gate：P
test_downgrade_refused：R0
```

`tests/test_db_connection.py` 新增测试：

```text
test_short_write_timeout_before_begin：R0
test_short_write_timeout_contention：P
test_short_write_timeout_isolation：P
test_short_write_invalid_options：P
test_short_write_transaction_lifecycle：P
test_short_write_error_categories：P
```

`src/web/src/api/accounts.test.ts`，用标题关键词标识：

```text
createAccountClient创建：R，未实现
任意接口401：P
429保留合法problem：R，未保留 Retry-After
所有操作仅用生成类型：P
login成功200：R，未实现
logout成功204：R，未实现
fetchCurrentAccount成功200：R，未实现
changePassword成功返回新身份：R，未实现
listAccounts空页：R，未实现
createAccount成功201：R，未实现
setAccountRole成功：R，未实现
setAccountStatus发送已确认状态变更：R，未实现
resetAccountPassword成功：R，未实现
deleteAccount成功204：R，未实现
每个API超时10秒：P
所有账号错误经toFailureView：P
401/403/429的problem：P
Argon2容量不足：P
changePassword的400及409：P
```

`src/web/src/accounts/navigation.test.ts`：

```text
safeReturnTo允许：R，未实现
safeReturnTo拒绝外部：R，未实现
safeReturnTo拒绝登录：R，未实现
guardAccountRoute匿名：R，未实现，未得到 redirect
guardAccountRoute强制改密：R，测试重复消费同一 Response；改为每次构造响应后通过
guardAccountRoute成员：P
guardAccountRoute的502：P
handleUnauthorized并发401：R，未实现
handleUnauthorized已在登录页：P
前端以TanStack Router和内存history执行守卫：P
身份Query保持staleTime及窗口聚焦配置：P
```

`src/web/src/accounts/Pages.test.tsx`：

```text
LoginPage登录后：R，尚无 createAppRouter 和登录表单
LoginPage必须改口令：P
LoginPage的401等错误显示：P
LoginPage展示429倒计时：P
PasswordPage强制改密：R，未实现表单；随后发现并修复旧强制改密缓存导致回跳
PasswordPage所有结束路径清理：P
AccountsPage显示安全字段：R，仍为占位页面
AccountsPage停用和删除确认：R，测试命中重复标题且 jsdom 不结束 CSS 动画；关闭测试动画后通过
AccountsPage最后管理员等错误：P
AccountsPage成功操作：P
AccountMenu右上角：R，布局未呈现菜单及受保护内容
AccountMenu登出成功或401：P
AccountLayout加载时：P
各页用户和服务端文本：P
所有页面卸载清理请求：P
成员被管理员停用后切回窗口：P
窗口聚焦身份查询遇502：P
管理员停用、删除、降级自己：P
改密页旧口令前四次400：P
改密核验后状态竞争变化409：P
```