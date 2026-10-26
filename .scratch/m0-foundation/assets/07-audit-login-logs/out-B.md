**1. 改动清单**

这是按 80 分钟限制交回的**检查点，整票尚未完成**。日志领域核心、迁移、上下文传递和会话过期处理已实现；其他账号日志接入、管理员接口和前端仍待完成。

改动未暂存、未提交。本轮创建的 `/tmp/rdp07-*.log` 检查日志已删除，没有遗留辅助脚本。

| 文件 | 改动 |
|---|---|
| `src/rdp/accounts/_boundary.py` | 参数绑定先于异常转译，漏传 `audit` 保留 TypeError。 |
| `src/rdp/accounts/audit_contract.py` | 删除过渡模块。 |
| `src/rdp/accounts/service.py` | 合入批准的契约和签名；实现上下文校验、账号存在性查询及过期删除日志。 |
| `src/rdp/api/account_auth.py` | 提取并传递请求审计上下文，更新过期短锁说明。 |
| `src/rdp/api/accounts.py` | 向账号服务显式传 `audit`，同步过期行为说明。 |
| `src/rdp/api/audit.py` | 实现来源 IP、请求编号提取及补记失败报告；四个业务路由仍待实现。 |
| `src/rdp/audit/__init__.py` | 登记共用 MetaData 中的日志模型。 |
| `src/rdp/audit/_context.py` | 实现请求、运维及事件上下文校验。 |
| `src/rdp/audit/_query.py` | 实现游标、筛选绑定、快照转换和存在性回调校验。 |
| `src/rdp/audit/_storage.py` | 实现受管事务检查及安全数据库异常转换。 |
| `src/rdp/audit/_validation.py` | 实现日志字段、明细白名单和事件组合校验。 |
| `src/rdp/audit/models.py` | 激活三张表，移除 `__abstract__`。 |
| `src/rdp/audit/records.py` | 实现追加、查询及共同保留期读写。 |
| `src/rdp/audit/service.py` | 实现独立失败追加和原子保留期清除。 |
| `src/rdp/infra/db/migrations/pending/__init__.py` | 删除隔离目录入口。 |
| `src/rdp/infra/db/migrations/pending/v0003_audit_login_logs.py` | 移出 pending。 |
| `src/rdp/infra/db/migrations/versions/v0003_audit_login_logs.py` | 实现冻结建表 SQL，复用拒绝降级逻辑。 |
| `src/rdp/ops/accounts.py` | 显式传入 `OPS_AUDIT_CONTEXT`。 |
| `src/rdp/ops/audit.py` | 实现安全、幂等的补记失败报告。 |
| `src/web/src/api/openapi.json` | 用 `make api-types` 重新生成。 |
| `src/web/src/api/schema.d.ts` | 用 `make api-types` 重新生成。 |
| `tests/account_api_support.py` | 补上下文参数，直接入口测试绑定并恢复请求编号。 |
| `tests/accounts_support.py` | 增加固定审计上下文，适配新签名。 |
| `tests/audit_support.py` | 增加独立的日志输入样本。 |
| `tests/auth_support.py` | 适配新签名。 |
| `tests/test_account_api.py` | 补参数；更正读锁测试说明，断言不变。 |
| `tests/test_account_ops.py` | 仅适配新签名。 |
| `tests/test_accounts.py` | 适配新签名；修改获批的过期忙锁异常断言。 |
| `tests/test_accounts_migration.py` | 用临时历史 0002 包及表视图保留原断言。 |
| `tests/test_api_database.py` | 未来版本样本改为 0004 接续 0003。 |
| `tests/test_audit_accounts.py` | 展开上下文、单服务及过期处理测试。 |
| `tests/test_audit_api.py` | 展开来源、报告边界及过期 401 测试。 |
| `tests/test_audit_migration.py` | 全部展开，验证真实迁移、DDL、约束和回滚。 |
| `tests/test_audit_records.py` | 全部展开，验证日志核心及失败边界。 |
| `tests/test_db_migration.py` | 更新当前版本预期及未来迁移样本。 |

**2. `make check`**

末次命令，退出码 `0`：

```bash
make check > /tmp/rdp07-check.log 2>&1
```

收尾检查未一次通过；类型检查、契约检查和未来版本测试样本的问题修正后重跑。末尾输出原样：

```text
=========== 1138 passed, 118 skipped, 1 warning in 62.73s (0:01:02) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.x8gI3FpwOZ/openapi.json → /tmp/tmp.x8gI3FpwOZ/schema.d.ts [51.2ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-07-audit-login-logs/src/web


 Test Files  12 passed | 2 skipped (14)
      Tests  128 passed | 39 skipped (167)
   Start at  23:28:22
   Duration  4.50s (tests 42%, environment 38%, import 19%)

```

`118` 个 pytest 跳过和 `39` 个 Vitest 跳过均为检查点剩余项，不代表完成。

**3. 契约变更申请、依赖申请**

依赖申请：**无**。额外对外行为变更申请：**无**。

内部接线变更需随检查点评审：`AccountRequestContext` 新增必填 `audit: AuditContext` 字段，用于向领域显式传参；没有增加 HTTP 请求或响应字段。

文档改动：

- 合入 `service.py` 的已批准函数 docstring 与 `68fd146` 中的契约逐项比较一致。
- `AccountRequestContext.Attributes`：增加审计上下文字段说明。
- `enforce_api_access`：将过期删除说明改为“100 毫秒入场等待，忙时不删不记、仍拒绝身份”，并注明删除和登录日志同事务。
- `get_authenticated_context`、`get_admin_context`：区分入场忙返回 401 与已获锁后的存储冲突。
- `logout`、`who_am_i`、`list_accounts`：相应收窄过期删除的冲突条件；`who_am_i` 的等待说明改为过期删除、活动刷新均为 100 毫秒。
- 私有 `_refresh_identity`：说明改为两种操作均用短锁。
- 模型、迁移模块：去掉隔离及将来激活的说法。
- 第 6 张两个读故障测试的说明收窄到实际覆盖的初始读锁，断言未改；新增测试说明与实际断言同步。

**4. 评审事项、旧测试变更、剩余测试**

迁移测试采用临时历史 0002 包和历史 MetaData 视图保留第 6 张原断言；真实 0003 另由完整迁移及 `compare_metadata` 测试验证。这项测试隔离方式请评审。

第 6 张行为断言只改一项：

| 测试 | 改前 | 改后 |
|---|---|---|
| `test_authenticate_expired_delete_busy` | 持有写锁时期待 `ConflictError` | 期待 `AuthenticationError`；原有“锁忙保留会话、释放后删除”断言保留 |

第 6 张其余 `assert` 表达式核对未变；调用只补 `audit` 参数。历史迁移测试新增 fixture，原断言未改。

剩余工作：

- **账号服务：92 个用例**，位于 `tests/test_audit_accounts.py`。尚需实现成功操作日志、执行后失败补记、登录各种结果、登出、旧口令失败与 G2 原子提交、保留期服务接入及相应权限验证。剩余测试组：
  ```text
  test_success_atomic
  test_execution_boundary
  test_rejection_not_logged
  test_failure_append_preserves_error
  test_failure_category
  test_login_outcomes
  test_login_atomic
  test_missing_login_privacy
  test_login_rejection_race
  test_logout_atomic
  test_session_rollback_clock
  test_no_fabricated_logout
  test_password_secrets
  test_own_wrong_password
  test_ops_actor
  test_actor_reexport
  test_failure_notice_survives_secret_boundary
  test_login_execution_failure
  test_failed_creation_has_no_reusable_account_id
  test_read_permissions
  test_conflict_after_admin_precheck_is_logged
  test_target_disappears_inside_write_is_logged
  test_write_reauthorization_rejection_is_not_logged
  test_own_wrong_password_transaction
  ```
- **管理员接口：26 个用例**，位于 `tests/test_audit_api.py`：
  ```text
  test_authorization_order
  test_member_denied
  test_origin_required
  test_no_single_row_mutation
  test_response_types
  test_api_errors
  test_operation_account_query_api
  test_invalid_domain_audit_returns_server_error
  ```
  四个路由、响应转换及报告器接入统一异常边界仍待实现。
- **前端：39 个用例**，`src/web/src/api/audit.test.ts` 和 `src/web/src/audit/Pages.test.tsx` 全部仍待实现，包括客户端、类型化筛选、Query、两个页面及保留期表单。

当前不能作为整票完工或演示版本。

**5. 先红后绿**

以下按测试函数列出；参数化用例结果相同的合并一行，不同的单独注明。未展开的跳过项不计入 R/P。

`tests/test_audit_records.py`

| 测试 | 首次结果及原因 |
|---|---|
| `test_append_only` | P：已批准路由声明本就没有单条修改、删除接口。 |
| `test_maintenance_engine_contract` | R：构造函数抛 NotImplementedError。 |
| `test_login_failure_category` | R：登录追加未实现。 |
| `test_independent_login_failure_storage` | R：两种独立追加函数分别未实现。 |
| `test_operation_roundtrip` | R：操作追加未实现。 |
| `test_operation_rollback` | P：已有工作单元已提供事务回滚。 |
| `test_operation_validation` | R：操作追加未实现。 |
| `test_detail_whitelist` | P：此前同一追加函数的校验实现已覆盖白名单。 |
| `test_detail_shape` | P：此前追加实现已保存版本化前后值。 |
| `test_append_storage_failure` | P：原六种情况由存取边界及已有数据库异常映射覆盖。 |
| `test_append_storage_failure[unbound_session]` | R：漏出 UnboundExecutionError，已改归 DefectError。 |
| `test_login_shape` | R：登录追加未实现。 |
| `test_query_order` | R：操作查询未实现。 |
| `test_query_intersection[operations]` | P：此前操作查询已实现交集筛选。 |
| `test_query_intersection[logins]` | R：登录查询未实现。 |
| `test_query_bounds` | R：操作查询未实现。 |
| `test_query_invalid` | R：查询及跨种类游标拒绝尚未实现。 |
| `test_query_snapshot` | R：查询未实现。 |
| `test_query_clock_rollback` | R：查询未实现。 |
| `test_query_corruption` | P：此前查询重验及存储异常边界已覆盖。 |
| `test_snapshot_identity` | P：此前按编号存在性查询及账号 AUTOINCREMENT 已满足。 |
| `test_snapshot_presence` | R：存在性适配器未实现。 |
| `test_presence_invalid` | R：存在性适配器或操作查询未实现。 |
| `test_retention_default` | R：读取保留期未实现。 |
| `test_retention_bounds` | R：修改保留期未实现。 |
| `test_retention_atomic` | R：修改保留期未实现。 |
| `test_purge_boundary` | R：清除未实现。 |
| `test_purge_rollback` | R：清除未实现。 |
| `test_purge_time` | R：清除未实现。 |
| `test_purge_invalid` | R：清除未实现。 |
| `test_short_append` | R：失败操作追加未实现。 |
| `test_purge_without_setting_uses_thirty_days` | R：清除未实现。 |
| `test_operation_account_filter_roles` | R：操作查询未实现。 |
| `test_target_account_filter_invalid` | R：操作查询未实现。 |
| `test_cursor_binds_both_account_filters` | P：此前游标已绑定完整筛选摘要。 |
| `test_audit_storage_context_defect` | P：写边界已经调用上下文校验。 |
| `test_detail_semantic_rejection` | R：未拒绝错误前后值、设置对象及成功空编号。 |
| `test_login_append_roundtrip` | R：登录追加未实现。 |
| `test_login_query_pages_and_unknown` | R：登录查询未实现。 |
| `test_login_query_invalid` | R：登录查询未实现。 |

`tests/test_audit_migration.py`

| 测试 | 首次结果及原因 |
|---|---|
| `test_active_migration` | R：head 仍为 0002。 |
| `test_upgrade_schema` | R：尚未升级至 0003。 |
| `test_upgrade_preserves` | P：已实现的新迁移与原迁移器保留旧数据和备份。 |
| `test_upgrade_rollback` | P：原迁移器已提供整个 DDL 事务回滚。 |
| `test_downgrade_rejected` | R：降级函数抛 NotImplementedError。 |
| `test_database_constraints` | P：批准的 ORM 约束及冻结 DDL 已生效。 |
| `test_frozen_sql_matches_models` | P：实现升级时冻结的 SQL 与模型一致。 |

`tests/test_audit_accounts.py`

| 测试 | 首次结果及原因 |
|---|---|
| `test_contract_module_removed_before_implementation` | R：过渡模块仍存在。 |
| `test_audit_keyword_required` | R：缺参 TypeError 被包装为 DefectError。 |
| `test_invalid_audit_is_defect` | R：非法上下文被忽略，或先进入业务校验。 |
| `test_http_context_requires_request_id` | R：空请求编号未被拒绝。 |
| `test_ops_context_rejects_http_metadata` | R：运维上下文未校验。 |
| `test_expiry_atomic` | R：删除后没有过期登录日志。 |
| `test_expiry_short_lock` | R：等待普通锁后抛 ConflictError。 |
| `test_expiry_other_errors[write/io/defect]` | R：没有登录日志写入，故障注入未触发。 |
| `test_expiry_other_errors[commit]` | P：已有工作单元已回滚提交失败。 |
| `test_expired_session_never_accessed_has_no_log` | P：现有系统没有后台自动过期记录。 |

`tests/test_audit_api.py`

| 测试 | 首次结果及原因 |
|---|---|
| `test_source_ip` | R：提取函数未实现。 |
| `test_request_id` | R：提取函数未实现。 |
| `test_api_failure_notice` | R：报告函数未实现。 |
| `test_ops_failure_notice` | R：运维报告函数未实现。 |
| `test_expiry_busy_is_unauthorized` | P：领域修复后，原有 AuthenticationError → 401 映射及清 cookie 行为直接满足。 |

已有测试的适配：

| 测试 | 首次结果及原因 |
|---|---|
| `test_accounts.py::test_authenticate_expired_delete_busy` | R：仍抛 ConflictError，与新批准断言不符。 |
| `test_api_database.py::test_configure_version` | R：未来版本样本仍接 0002，造成双 head；已修正样本。 |
| `test_db_migration.py::test_config` | P：当前版本预期更新后通过。 |
| `test_db_migration.py::test_config_none` | P：当前版本预期更新后通过。 |
| `test_db_migration.py::test_migrate_new` | P：由新迁移及既有迁移器满足。 |
| `test_db_migration.py::test_migrate_existing` | P：由新迁移及既有迁移器满足。 |
| `test_db_migration.py::test_backup_contents` | P：原备份行为保持。 |
| `test_db_migration.py::test_backup_filename` | P：原备份命名行为保持，仅版本样本更新。 |
| `test_db_migration.py::test_migrate_upgrade_failure` | P：原事务回滚行为保持。 |
| `test_db_migration.py::test_env_connection` | P：原连接复用行为保持。 |
| `test_db_migration.py::test_installed_package` | P：包内迁移发现机制直接包含 0003。 |

其余第 6 张测试仅适配新签名，作为已有回归测试运行，未冒称本轮新增红测。