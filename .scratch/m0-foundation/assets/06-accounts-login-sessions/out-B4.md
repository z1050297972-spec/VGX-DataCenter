整票实现完成。最终仅运行一次 `make check`，十一步全绿：**pytest 877 passed，Vitest 127 passed，均为 0 skipped**。改动留在工作区，未暂存、未提交。

**1. 改动清单**

累计改动，每个文件一行：

```text
src/rdp/accounts/errors.py：实现 G2 等待异常校验。
src/rdp/accounts/models.py：激活账号、会话两表，共用 MetaData。
src/rdp/accounts/security.py：实现 Argon2、并发限额、令牌及摘要。
src/rdp/accounts/service.py：实现账号和会话事务，接入安全异常出口。
src/rdp/accounts/_boundary.py：清除可能含秘密的底层异常链，保留安全诊断和定位。
src/rdp/accounts/_inputs.py：集中校验口令输入。
src/rdp/accounts/_issues.py：构造安全领域诊断。
src/rdp/accounts/_records.py：实现输入校验、账号快照和管理员不变量。
src/rdp/accounts/_sessions.py：实现 G2、会话签发、撤销及事务内复核。
src/rdp/api/__init__.py：接通全局鉴权和可控时钟。
src/rdp/api/account_auth.py：实现 Origin、鉴权顺序、cookie 和 404/405。
src/rdp/api/account_schemas.py：转换安全响应，保留编号精度。
src/rdp/api/accounts.py：实现十个账号接口。
src/rdp/api/error_details.py：更新已生效的登录访问说明。
src/rdp/api/errors.py：接通脱敏、Retry-After、401 清 cookie 和唯一报告。
src/rdp/api/_account_middleware.py：请求体解析前鉴权，仅提交刷新后续 cookie。
src/rdp/infra/db/connection.py：实现独立连接的短锁等待。
src/rdp/infra/db/migrations/pending/__init__.py：删除。
src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py：移出 pending。
src/rdp/infra/db/migrations/versions/v0002_accounts_sessions.py：实现并启用 0002。
src/rdp/ops/accounts.py：实现无回显双次输入、首号创建及运维重置。
src/web/src/accounts/Pages.tsx：实现登录、改密、账号管理、菜单及保护布局。
src/web/src/accounts/Pages.test.tsx：启用全部页面测试。
src/web/src/accounts/navigation.ts：实现安全回跳、守卫和统一退出。
src/web/src/accounts/navigation.test.ts：启用全部导航测试。
src/web/src/accounts/runtime.tsx：提供客户端及窗口聚焦身份查询。
src/web/src/accounts/testSupport.ts：提供独立安全响应样本。
src/web/src/api/accounts.ts：实现 HTTP 请求、取消和超时。
src/web/src/api/accounts.test.ts：启用全部请求层测试。
src/web/src/api/client.ts：导出统一默认传输供应用装配。
src/web/src/api/problems.ts：安全保留有界 Retry-After。
src/web/src/api/openapi.json：通过 make api-types 重新生成。
src/web/src/api/schema.d.ts：通过 make api-types 重新生成。
src/web/src/main.test.tsx：适配先查询身份的启动流程。
src/web/src/mountWeb.tsx：绑定账号应用缓存及路由。
src/web/src/router.test.tsx：验证登录后的首页路由。
src/web/src/router.tsx：接通默认登录守卫和统一客户端。
tests/diagnostics_demo.py：明确演示请求的临时认证前置条件。
tests/test_account_api.py：完成全部 94 条 API 测试。
tests/test_account_ops.py：完成全部 19 条运维测试。
tests/test_accounts.py：完成全部 194 个领域用例，清除剩余跳过。
tests/test_accounts_migration.py：验证新表、升级、回滚及备份。
tests/test_api_database.py：补真实登录；更新未来迁移样本，原断言不变。
tests/test_api_errors.py：补真实登录和 Origin，原断言不变。
tests/test_db_connection.py：验证短锁等待和连接隔离。
tests/test_db_migration.py：适配 0002 当前版本。
tests/test_diagnostics_demo.py：补真实登录，原断言不变。
tests/test_web_app.py：补真实登录和 Origin，原断言不变。
tests/account_api_support.py：提供临时数据库、固定时钟及 ASGI 客户端。
tests/accounts_support.py：提供有界并发、竞争调度和提交失败测试工具。
tests/auth_support.py：提供请求结束即删除的独立临时认证库。
```

`/tmp/rdp-accounts-tdd` **已删除**。14 条 TS 未使用参数豁免已删除；S105 正则豁免保留。改动文件中无“骨架／提案／派工／桩”残留。

**2. `make check`**

最后一次命令：

```text
make check
```

末尾输出原样：

```text
======================= 877 passed, 1 warning in 58.90s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.ksWdOmAa80/openapi.json → /tmp/tmp.ksWdOmAa80/schema.d.ts [37.1ms]
OpenAPI 与生成类型均未过期
[8/11] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/11] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-06-accounts-login-sessions/src/web


 Test Files  12 passed (12)
      Tests  127 passed (127)
   Start at  13:07:15
   Duration  4.37s (tests 45%, environment 33%, import 20%, transform 1%, setup 1%)
```

两边均无 skipped。

运行前 `git status --porcelain --untracked-files=all`：

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
 M tests/diagnostics_demo.py
 M tests/test_account_api.py
 M tests/test_account_ops.py
 M tests/test_accounts.py
 M tests/test_accounts_migration.py
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_db_connection.py
 M tests/test_db_migration.py
 M tests/test_diagnostics_demo.py
 M tests/test_web_app.py
?? src/rdp/accounts/_boundary.py
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
?? tests/auth_support.py
```

运行后：

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
 M tests/diagnostics_demo.py
 M tests/test_account_api.py
 M tests/test_account_ops.py
 M tests/test_accounts.py
 M tests/test_accounts_migration.py
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_db_connection.py
 M tests/test_db_migration.py
 M tests/test_diagnostics_demo.py
 M tests/test_web_app.py
?? src/rdp/accounts/_boundary.py
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
?? tests/auth_support.py
```

前后逐字一致。

**3. 契约变更申请、依赖申请**

契约变更申请：**无**。依赖申请：**无**。没有改受保护文件。

本轮文档补充：

- `get_error_details`：说明 HTTP 请求通过“第 06 张的全局登录与强制改密检查”，保持所有合格登录账号可查看。
- `mount_diagnostic_demo`：说明演示请求须先建立测试登录，认证和报错存储只使用临时数据库或独立临时认证服务。

累计已批准的说明修正：

- 模型模块、`create_app`、鉴权安装及错误处理函数：删除未接线说明，改写为已生效行为。
- `create_app`：补充默认编码器及假哈希初始化副作用。
- cookie 函数：明确对象及响应头校验；发送前调用由调用方保证。
- `api/accounts.ts`：HTTP 函数只负责请求、超时和信号；表单清理、缓存、导航、查询配置和旧分页取消归页面、布局及菜单。
- `createProblemFetch`、`toFailureView`：说明仅保留合法的 1–60 整数秒 `Retry-After`。
- 五个页面组件、`mountWeb`：改为实际视图、身份查询和保护布局的行为说明。
- `_begin_transaction`：将短锁等待说明改为已生效行为。

已批准的公开函数签名、HTTP 状态码、路径、字段和数据库表结构未改变。

**4. 拿不准、需要评审决定的地方**

无。

旧 HTTP 测试**没有修改任何断言**：四个文件的 341 条断言经 AST 比较全部保持。

相关前置调整：

- 注入真实临时账号服务和真实会话，仍经过全局鉴权。
- 写请求携带正确 Origin。
- 敏感 cookie 测试保留原测试 cookie，同时携带有效会话 cookie。
- 未来迁移样本从 0001 后的另一个分支，改为接在 0002 后面的 0003，避免双 head；断言未改。
- 临时认证库与被测业务库分开，避免干扰原有事务、故障注入和持久化断言。

**5. 本轮首次运行记录**

- **P**：一开始就通过（实现先于测试）。
- **R**：首次失败，原因如下；现已通过。
- 本轮没有 R0。

`tests/test_accounts.py`：

```text
test_login_failures：P
test_authenticate_revoked：P
test_current_password_error_type：P
test_password_change_mismatch_keeps_session：P
test_clock_wait_rollback：P
test_clock_session_rollback：P
test_clock_mutation_rollback：P
test_concurrent_request_time_order：P
test_admin_disable_self：P
test_admin_delete_self：P
test_admin_demote_self：P
test_set_role_errors：P
test_set_status_errors：P
test_reset_password_errors：P
test_delete_account_errors：P
test_authenticate_read_session：P
test_list_accounts_readonly：P
test_authenticate_failure：P
test_login_rollback：P
test_logout_failure：P
test_change_password_rollback：P
test_reset_password_rollback：P
test_delete_account_rollback：P
test_login_rehash_commit：P
test_service_failure_secrets：R，数据库原始异常链仍将秘密带入完整报告；新增安全出口后通过
test_service_failure_cleanup：P
test_set_role_concurrent：P
test_set_status_concurrent：P
test_delete_account_concurrent：P
test_first_admin_concurrent：P
test_login_hash_changed_after_verify：P
test_login_g2_changed_after_verify：P
test_login_disabled_after_verify：P
test_login_expired_g2_snapshot：P
test_password_change_hash_changed：P
test_password_change_session_revoked：P
test_password_change_g2_changed：P
test_creation_rechecks_authority：P
test_first_admin_rechecks_after_hash：P
test_ops_reset_recreated_name：P
test_authenticate_touch_busy：P
test_authenticate_touch_other_failure：P
test_authenticate_expired_delete_busy：P
test_authenticate_concurrent_touch：P
test_authenticate_repeated_busy_expiry：P
test_login_unknown_no_state：P
test_login_wait_skips_capacity：P
test_login_capacity_no_counter：P
test_service_argon2_capacity_failure：6 个参数例全部 P
test_argon2_outside_database_transactions：12 个参数例全部 P
test_rehash_calculated_before_write：2 个参数例全部 P
```

旧 HTTP 测试以下 **R401** 均表示首次因缺少登录前置，被全局鉴权返回 401，未进入原来要验证的业务路径；补真实登录后通过。

`tests/test_web_app.py`：

```text
test_unknown_api：R401
test_api_404_preserves_detail：R401
test_api_namespace_all_methods：R401，并补写请求 Origin
test_response_and_log_id_match：R401
test_concurrent_request_ids：R401
test_request_ids_on_all_response_statuses：R401
test_streaming_and_background_context：R401
```

`tests/test_api_errors.py`：

```text
test_handler_mappings_and_media：R401
test_boundary_server_error_rethrow_once：R401
test_boundary_stream_failure_once：R401
test_boundary_background_failure_once：R401
test_boundary_exception_group_once：R401
test_preserve_framework_http_errors：R401
test_representative_platform_defect：R401
test_explicit_defect_diagnostics_and_cause：R401
test_validation_log_field_locations_without_values：R，缺 Origin 先返回 403；补 Origin 和登录后恢复原 422 断言
```

`tests/test_api_database.py`：

```text
test_configure_version：R，旧未来迁移样本形成双 head；修正样本后通过
test_factory_compat：R401
test_factory_lifecycle：P，原健康接口已有实现，新增认证前置不改变断言
test_session_cached：R401
test_session_commit_before_send：R401
test_session_route_exception：R401
test_session_serialization_exception：R401
test_session_database_errors：R401
test_session_thread：R401
test_read_session：R401
test_details_request：R401
test_details_job：R401
test_details_not_found：R401
test_details_invalid：R401
test_details_corrupt：R401
test_details_busy：R401
test_details_external：R401
test_details_defect：R401
test_details_auth：R401
test_report_unknown：R401
test_report_explicit：R401
test_report_same_text：R401
test_report_nondefect：R401
test_report_independent：R401
test_report_failure：R401
test_report_stream：R401
test_report_truncated_same_text：R401
test_report_sensitive：R401
```

`tests/test_diagnostics_demo.py`：

```text
test_demo_five_errors：R401
test_demo_no_external_effects：R401
```