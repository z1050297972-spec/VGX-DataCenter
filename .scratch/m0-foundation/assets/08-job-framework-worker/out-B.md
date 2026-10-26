**1. 改动清单**

本轮交付**数据库与领域规则检查点**，整票尚未完成。未暂存、未提交；自行创建的临时日志目录已删除。

| 文件 | 改动 |
|---|---|
| `src/rdp/accounts/service.py` | 实现公开的事务内身份重验接口。 |
| `src/rdp/audit/models.py` | 激活审计对象 `job` 的 CHECK。 |
| `src/rdp/infra/db/migrations/pending/__init__.py` | 删除隔离目录声明。 |
| `src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py` | 移出 `pending/`。 |
| `src/rdp/infra/db/migrations/versions/v0004_jobs_worker.py` | 实现建表、审计表重建、序列保留和拒绝降级。 |
| `src/rdp/jobs/models.py` | 激活 ORM；可空 JSON 使用真正的 SQL NULL。 |
| `src/rdp/jobs/registry.py` | 实现独立登记表、字段检查和生产登记。 |
| `src/rdp/jobs/example.py` | 实现示例参数交叉校验。 |
| `src/rdp/jobs/types.py` | 实现进度字段关系校验。 |
| `src/rdp/jobs/records.py` | 实现记录存取、六态转换、领取、快照及心跳写入的当前切片。 |
| `src/rdp/jobs/_storage.py` | 增加受管事务检查、异常分类和输入校验。 |
| `src/rdp/jobs/_views.py` | 增加快照转换、跨字段一致性和容量校验。 |
| `src/rdp/jobs/policy.py` | 定义诊断溢出组的保留键。 |
| `src/rdp/jobs/worker.py` | 实现心跳在线判定。 |
| `tests/jobs_storage_support.py` | 增加独立行样本和临时状态目录夹具。 |
| `tests/test_jobs_records.py` | 新增存取、事务、领取和故障边界测试。 |
| `tests/test_jobs_registry.py` | 启用登记表和参数测试。 |
| `tests/test_jobs_progress.py` | 启用进度模型校验测试。 |
| `tests/test_jobs_worker.py` | 启用在线阈值测试，增加非法快照测试。 |
| `tests/test_jobs_service.py` | 启用公开账号接口测试。 |
| `tests/test_jobs_state.py` | 启用合法/非法转换、结果、时间和摘要测试。 |
| `tests/test_jobs_migration.py` | 启用迁移、DDL 一致性、高水位和回滚测试。 |
| `tests/test_audit_migration.py` | 固定历史 0003 包及元数据视图，保留旧版断言。 |
| `tests/test_db_migration.py` | 更新当前 head、下一版夹具和独立模型注册。 |
| `tests/test_api_database.py` | 更新下一版迁移夹具。 |

**2. `make check`**

首次在类型检查阶段中断，修正测试类型表达后复跑；全量 pytest、Vitest 各完成一次。

最后命令，退出码 **0**：

```bash
make check > /tmp/rdp-m0-08-implementation/check.log 2>&1
```

末尾输出原文：

```text
=========== 1367 passed, 133 skipped, 1 warning in 77.57s (0:01:17) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.SW0V7LBW5C/openapi.json → /tmp/tmp.SW0V7LBW5C/schema.d.ts [64.3ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-08-job-framework-worker/src/web


 Test Files  14 passed | 2 skipped (16)
      Tests  179 passed | 22 skipped (201)
   Start at  06:23:58
   Duration  6.38s (tests 49%, environment 31%, import 19%)
```

运行前的 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/accounts/service.py
 M src/rdp/audit/models.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py
 M src/rdp/jobs/example.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/policy.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/types.py
 M src/rdp/jobs/worker.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_progress.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_service.py
 M tests/test_jobs_state.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0004_jobs_worker.py
?? src/rdp/jobs/_storage.py
?? src/rdp/jobs/_views.py
?? tests/jobs_storage_support.py
?? tests/test_jobs_records.py
```

运行后：

```text
 M src/rdp/accounts/service.py
 M src/rdp/audit/models.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py
 M src/rdp/jobs/example.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/policy.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/types.py
 M src/rdp/jobs/worker.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_progress.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_service.py
 M tests/test_jobs_state.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0004_jobs_worker.py
?? src/rdp/jobs/_storage.py
?? src/rdp/jobs/_views.py
?? tests/jobs_storage_support.py
?? tests/test_jobs_records.py
```

**3. 契约变更申请、依赖申请**

均为 **无**。公开签名和六项函数契约未改含义；TSDoc 未修改。

说明性文档调整：

- `jobs/models.py` 模块说明：“抽象声明不进入当前 0003 的 metadata”改为“导入时注册共用 metadata”。
- `audit/models.py` 的 `OperationLogRow.object_kind`：“account/audit_settings”改为“account/audit_settings/job，job不是账号”。
- `v0004_jobs_worker.upgrade`：“与 0004 的抽象模型一致”改为“与 0004 的表声明一致”。
- 已修改测试文件的模块说明删除“执行行为尚不可用”；测试 docstring 改为实际断言说明。主要包括活动迁移检查、完整 DDL 对比、嵌套秘密字段、事务内身份重验和独立计数结果核对。

**4. 检查点剩余工作**

仍有 **133 项后端、22 项前端测试跳过**：

| 文件 | 剩余 skipped |
|---|---:|
| `tests/test_jobs_api.py` | 12 |
| `tests/test_jobs_logs.py` | 16 |
| `tests/test_jobs_migration.py` | 3 |
| `tests/test_jobs_processes.py` | 8 |
| `tests/test_jobs_progress.py` | 19 |
| `tests/test_jobs_registry.py` | 7 |
| `tests/test_jobs_service.py` | 22 |
| `tests/test_jobs_state.py` | 4 |
| `tests/test_jobs_worker.py` | 42 |
| `src/web/src/jobs/Pages.test.tsx` | 17 |
| `src/web/src/api/jobs.test.ts` | 5 |

主要未完成：

- 作业服务与审计作业明细校验、HTTP 接口。
- 执行器、恢复、上报对象、日志、外部进程、单实例锁和 worker 主循环。
- 示例执行函数及真实子进程测试。
- 全部作业前端功能及 `WorkerStatusBanner` 挂载。
- 剩余迁移行为测试：删除账号不影响记录、恢复次数约束、领取路径约束。
- 存取层仍需补齐尚未覆盖的边界，尤其是**编号耗尽应归 `ConflictError`，目前仍沿用通用数据库错误分类**，不能把这一边界算作已验收。

诊断溢出组采用保留键 `("平台", "诊断规则种类超过上限")`；续接上报对象时应复用此常量，保留样例原始来源。

**5. 先红后绿记录**

以下按测试函数列出；参数化用例结果相同的合并说明。

| 测试 | 首次运行结果 |
|---|---|
| `test_jobs_registry::test_explicit_registry` | 失败：登记表未实现。 |
| `test_directory_names` | 失败：非法目录名未拒绝。 |
| `test_stable_keys` | 失败：重复键和非法键未拒绝。 |
| `test_secret_models` | 失败：秘密模型未拒绝。 |
| `test_production_example_only` | 失败：生产登记工厂未实现。 |
| `test_count_parameter_bounds` | 失败：交叉字段校验未实现。 |
| `test_jobs_progress::test_invalid_progress` | 失败：进度关系校验未实现。 |
| `test_jobs_worker::test_heartbeat_threshold` | 失败：在线判定未实现。 |
| `test_heartbeat_online_rejects_invalid_snapshots` | 失败：非法时刻泄漏为 `ValueError`。 |
| `test_jobs_migration::test_active_declarations` | 失败：模型仍为 abstract。 |
| `test_schema_v4` | 失败：0004 未实现，升级归为 `DefectError`。 |
| `test_audit_sequence_highwater` | 失败：序列从 100 降为 1。 |
| `test_audit_sequence_empty` | **首次通过**：前一测试的序列保留逻辑已覆盖空表。 |
| `test_audit_check_extension` | **首次通过**：建表测试所需的冻结重建 SQL 已保留旧结构与数据。 |
| `test_downgrade_refused`（2组） | 失败：降级函数未实现。 |
| `test_migration_rollback`（6组） | **首次通过**：复用已有迁移事务，故障均整体回滚。 |
| `test_corrupt_audit_sequence_is_rejected`（4组） | 失败：损坏序列未按 `InputError` 拒绝。 |
| `test_jobs_service::test_public_actor_authorization`（9组） | 失败：公开身份重验函数未实现。 |
| `test_public_account_boundary` | **首次通过**：前一实现复用调用者 Session，已满足事务可见性与回滚。 |
| `test_jobs_records::test_find_job_detached_snapshot` | 失败：ORM 把 `None` 写成 JSON `null`，触发终态 CHECK。 |
| `test_find_rejects_invalid_missing_and_unmanaged` | 失败：输入、查无记录和会话边界未正确分类。 |
| `test_jobs_state::test_legal_edges`（6组） | 失败：状态转换未实现。 |
| `test_illegal_edges`（30组） | **首次通过**：合法边实现使用白名单，已拒绝全部其他边。 |
| `test_completed_outcome_only`（8组） | **首次通过**：复用已合并的唯一结果计算函数。 |
| `test_transition_rejects_invalid_change_and_detects_stale_state` | 失败：非规范日志路径未拒绝。 |
| `test_clock_rollback` | **首次通过**：转换保留 UTC 时刻，耗时使用存储片段。 |
| `test_queued_cancel_summary` | **首次通过**：终态分支已正确处理未开始记录。 |
| `test_jobs_records::test_find_rejects_corrupt_record[json]` | **首次通过**：已有存取边界已处理 JSON 解码错误。 |
| 同上其余 7 组 | 失败：状态、计数、摘要或参数形状损坏未正确拒绝。 |
| `test_insert_is_owned_by_callers_transaction` | 失败：插入未实现，未到达预期回滚断言。 |
| `test_next_job_uses_id_and_does_not_claim` | 失败：候选查询未实现。 |
| `test_claim_registers_unique_log_path_in_transaction` | 失败：领取未实现。 |
| `test_insert_rejects_invalid_commands_before_writing` | 失败：非法命令落到数据库约束，得到错误类别。 |
| `test_save_progress_atomic_latest_snapshot` | 失败：快照写入未实现。 |
| `test_save_progress_rejects_invalid_snapshot_and_terminal` | 失败：非法快照落到 SQL CHECK，得到 `ConflictError`。 |
| `test_save_progress_diagnostic_group_invariants` | 失败：无效聚合样例未拒绝。 |
| `test_save_progress_preserves_overflow_diagnostic_sources` | 失败：溢出组原始来源被错误拒绝。 |
| `test_heartbeat_singleton_transaction_and_validation` | 失败：心跳写入未实现。 |

既有迁移回归首次出现的失败也已修复：审计迁移 2 项、数据库迁移 15 项、API 数据库版本测试 1 项，原因是当前 head 更新、下一版夹具产生分叉或独立运行时模型注册不完整。它们原本已启用，不属于解除跳过的新测试。