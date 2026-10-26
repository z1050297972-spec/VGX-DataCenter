剩余实现和测试已完成。最终 `make check` 一次通过：**pytest 1514 passed、Vitest 201 passed，两套均 0 skipped**。改动未暂存、未提交。

**1. 本轮改动清单**

| 文件 | 改动 |
|---|---|
| `src/rdp/jobs/_audit.py` | 非法请求上下文明确抛 `DefectError`。 |
| `src/web/src/DiagnosticCard.tsx` | 抽出共用诊断渲染，增加作业诊断卡片，不拼造 HTTP 错误编号。 |
| `src/web/src/jobs/Pages.tsx` | 完成详情、取消、重提、日志和示例提交表单。 |
| `src/web/src/jobs/queries.ts` | 完成详情／日志轮询和写操作；离页取消请求，忽略迟到成功。 |
| `src/web/src/jobs/progress.ts` | 完成单调计时、有界采样和终态冻结；修复旧快照导致计时冻结。 |
| `src/web/src/jobs/Pages.test.tsx` | 完成剩余 11 条页面测试。 |
| `src/web/src/jobs/testSupport.ts` | 增加已完成作业样本。 |
| `tests/test_jobs_state.py` | 完成真实写锁耗尽后的失败退出测试。 |
| `tests/test_jobs_registry.py` | 完成旧类型／旧参数失效后继续处理队列的测试。 |
| `tests/test_jobs_logs.py` | 完成日志状态、恢复写入顺序和真实崩溃窗口测试。 |
| `tests/test_jobs_service.py` | 完成取消、身份快照、永久记录、故障分类及审计边界测试。 |
| `tests/test_jobs_worker.py` | 完成心跳故障、进程组、保锁、孤儿及不可回收资源测试。 |
| `tests/test_jobs_api.py` | 完成 OpenAPI 和 Web 不执行作业的测试。 |
| `tests/test_jobs_processes.py` | 测试期间接管孤儿进程，清理后恢复 subreaper 状态。 |
| `tests/job_process_support.py` | 增加 GC 后保活和读线程遗留场景。 |
| `tests/jobs_api_support.py` | 支持注入测试登记表。 |
| `tests/jobs_process_resources.py` | 新增有界孤儿回收及真实管道阻塞夹具。 |

**2. `make check`**

在指定 worktree 中执行，最后命令：

```text
make check
```

末尾输出原文：

```text
================= 1514 passed, 1 warning in 111.68s (0:01:51) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.lC1N0mAr6y/openapi.json → /tmp/tmp.lC1N0mAr6y/schema.d.ts [63.1ms]
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


 Test Files  16 passed (16)
      Tests  201 passed (201)
   Start at  09:06:46
   Duration  6.42s (tests 52%, environment 29%, import 18%)
```

运行前，`git status --porcelain --untracked-files=all`：

```text
 M src/rdp/accounts/service.py
 M src/rdp/api/errors.py
 M src/rdp/api/jobs.py
 M src/rdp/audit/job_contracts.py
 M src/rdp/audit/models.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py
 M src/rdp/jobs/example.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/logs.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/policy.py
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/service.py
 M src/rdp/jobs/types.py
 M src/rdp/jobs/worker.py
 M src/rdp/ops/worker.py
 M src/web/src/DiagnosticCard.tsx
 M src/web/src/accounts/Pages.test.tsx
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/jobs.test.ts
 M src/web/src/api/jobs.ts
 M src/web/src/jobs/Pages.test.tsx
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/progress.ts
 M src/web/src/jobs/queries.ts
 M src/web/src/jobs/search.ts
 M src/web/src/router.tsx
 M tests/job_process_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_api.py
 M tests/test_jobs_logs.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_progress.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_service.py
 M tests/test_jobs_state.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0004_jobs_worker.py
?? src/rdp/infra/exception_report.py
?? src/rdp/jobs/_audit.py
?? src/rdp/jobs/_clock.py
?? src/rdp/jobs/_diagnostics.py
?? src/rdp/jobs/_loop.py
?? src/rdp/jobs/_pagination.py
?? src/rdp/jobs/_process_io.py
?? src/rdp/jobs/_recovery.py
?? src/rdp/jobs/_storage.py
?? src/rdp/jobs/_views.py
?? src/web/src/jobs/testSupport.ts
?? tests/jobs_api_support.py
?? tests/jobs_execution_support.py
?? tests/jobs_loop_support.py
?? tests/jobs_process_resources.py
?? tests/jobs_progress_support.py
?? tests/jobs_storage_support.py
?? tests/test_jobs_records.py
```

运行后，同一命令输出：

```text
 M src/rdp/accounts/service.py
 M src/rdp/api/errors.py
 M src/rdp/api/jobs.py
 M src/rdp/audit/job_contracts.py
 M src/rdp/audit/models.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py
 M src/rdp/jobs/example.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/logs.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/policy.py
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/service.py
 M src/rdp/jobs/types.py
 M src/rdp/jobs/worker.py
 M src/rdp/ops/worker.py
 M src/web/src/DiagnosticCard.tsx
 M src/web/src/accounts/Pages.test.tsx
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/jobs.test.ts
 M src/web/src/api/jobs.ts
 M src/web/src/jobs/Pages.test.tsx
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/progress.ts
 M src/web/src/jobs/queries.ts
 M src/web/src/jobs/search.ts
 M src/web/src/router.tsx
 M tests/job_process_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_api.py
 M tests/test_jobs_logs.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_progress.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_service.py
 M tests/test_jobs_state.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0004_jobs_worker.py
?? src/rdp/infra/exception_report.py
?? src/rdp/jobs/_audit.py
?? src/rdp/jobs/_clock.py
?? src/rdp/jobs/_diagnostics.py
?? src/rdp/jobs/_loop.py
?? src/rdp/jobs/_pagination.py
?? src/rdp/jobs/_process_io.py
?? src/rdp/jobs/_recovery.py
?? src/rdp/jobs/_storage.py
?? src/rdp/jobs/_views.py
?? src/web/src/jobs/testSupport.ts
?? tests/jobs_api_support.py
?? tests/jobs_execution_support.py
?? tests/jobs_loop_support.py
?? tests/jobs_process_resources.py
?? tests/jobs_progress_support.py
?? tests/jobs_storage_support.py
?? tests/test_jobs_records.py
```

**3. 契约变更申请、依赖申请**

无。既有生产公开签名、HTTP 路径、字段和状态码未改。

文档变动：

- `worker_main` 补充：`shutdown_timeout` 和 `reader_timeout` 在入口返回后丢弃结果引用、执行 GC，再有界保活。
- `test_jobs_processes.py` 模块说明改为：“08验收2/3/4真实进程场景；隔离进程组，finally清理工具后代并恢复subreaper状态。”
- 新增 `DiagnosticEntries`、`JobDiagnosticCard` 的六项 TSDoc，明确共用五段渲染、隐藏程序缺陷细节、不伪造 HTTP 错误编号。
- 新增资源夹具的职责说明。
- 测试夹具 `job_api_case` 增加可选登记表注入；生产接口不受影响。

**4. 拿不准、需要评审决定的地方**

无未决申请，无剩余跳过测试。

默认 fetch 回归测试保持前轮校正，本轮未改，留待评审核对。搜索到的“尚未”均为“尚未上报”“尚未提交”等业务生命周期描述，保留了获批契约的原意；过程说法已清理。

`/tmp/rdp-m0-08-*` 已清空。沙箱外演示按原分工由执行线进行。

**5. 本轮先红后绿**

以下仅列本轮新增启用的测试；全部最终通过。

```text
tests/test_jobs_state.py
test_final_commit_failure — 首跑夹具短锁预算大于调小后的普通预算；修正夹具后通过，既有失败收尾逻辑有效。

tests/test_jobs_registry.py
test_unknown_queued_type — 初次通过：既有执行器会失败结束该条并继续队列。
test_obsolete_parameters — 初次通过：既有当前模型校验及安全诊断符合契约。

tests/test_jobs_logs.py
test_missing_log — 初次通过：既有尾读和 HTTP 已区分未开始、已清除、权限故障。
test_recovery_log_first — 初次通过：观察数据库写入前，文件中已有完整中断段。
test_claim_crash_before_header — 初次通过：既有恢复沿登记路径先写头，再写中断段。

tests/test_jobs_service.py
test_cancel_running — 初次通过：主循环传播取消，可打断示例长等待。
test_deleted_submitter — 初次通过：已有编号快照和删除标记，不按同名账号关联。
test_no_delete_api — 初次通过：没有删除入口，旧记录仍可查询且编号递增。
test_service_failures — 红：None 上下文漏出 AttributeError；修为 DefectError。
test_audit_name_limit — 初次通过：40码点显示名加19位编号得到61码点对象名。
test_cancel_vs_completion_orders — 初次通过：最终事务重读状态，完成后的取消拒绝且无新审计。

tests/test_jobs_worker.py
test_heartbeat_invalid — 初次通过：已有字段校验和数据库错误分类。
test_external_group_and_failure_diagnostics — 初次通过：真实工具及后代随组终止，失败诊断完整。
test_external_readers_and_deadlines — 初次通过：父进程结束后，持管道后代被清理，读线程有界回收。
test_lock_retention_no_gc_close — 红：夹具缺少显式GC握手；补齐场景后通过。
test_reader_timeout_retains_lock — 红：夹具缺少读线程遗留模式，未达到返回握手；补齐后通过。
test_cancel_stall_not_repeated — 初次通过：已有一次性标记，终态后不再警告。
test_systemd_orphan_boundary — 初次通过：SIGKILL后工具仍存活，由夹具清理并回收。
test_unreapable_external_process[True] — 初次通过：wait超时保留未知退出码、遗留线程并失败退出。
test_unreapable_external_process[False] — 初次通过：读线程超时保留真实退出码，主循环失败收尾。

tests/test_jobs_api.py
test_openapi_job_schema — 初次通过：既有路由、字段与生成 OpenAPI 一致。
test_no_web_execution — 初次通过：全部 Web 路径均未调用注入的执行函数。

src/web/src/jobs/Pages.test.tsx
未知总数详情显示 — 红：详情页面未实现。
已用时间与终态冻结 — 红：计时hook未实现；进一步发现旧快照会冻结计时，已修复。
取消按钮、409刷新与继续轮询 — 红：控制按钮和写操作hook未实现。
终态重提及大编号导航 — 红：重提按钮和hook未实现。
日志状态和HTML文本展示 — 红：详情日志未实现。
统一诊断展示 — 红：作业诊断展示未实现。
轮询停止边界 — 初次通过：前述查询实现已按终态切换日志查询并停止轮询。
账号隔离与迟到响应 — 初次通过：已有账号边界及本轮请求归属管理有效。
示例表单 — 红：提交页面未实现。
真实Router筛选、返回和刷新 — 初次通过：已有类型化search与导航实现有效。
审计作业对象展示 — 初次通过：已有对象列、操作标签及明细白名单支持job。
```