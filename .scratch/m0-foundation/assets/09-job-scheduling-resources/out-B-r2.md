两轮修复已完成。最终检查全绿：pytest **1681 passed**、Vitest **228 passed**，均 **0 skipped**。未暂存、未提交，临时文件已清理。

**1. 改动清单**

以下列出 r1、r2 改动的 23 个文件；后面的 Git 状态还包含此前保留的实现改动。

- `src/rdp/api/jobs.py`：引用统一的示例作业类型常量。
- `src/rdp/audit/_validation.py`：删除已失效的“待实现”注释。
- `src/rdp/audit/job_contracts.py`：引用基础层的类型键正则。
- `src/rdp/infra/config.py`：复用类型键正则常量。
- `src/rdp/infra/ids.py`：统一定义 `JOB_TYPE_KEY_PATTERN`。
- `src/rdp/jobs/_loop.py`：停止或启动失败时退回未启动领取；实际已启动的线程仍走停止收尾；日志耗时改为 `elapsed_s`。
- `src/rdp/jobs/execution.py`：复用类型常量和清除类型集合。
- `src/rdp/jobs/maintenance.py`：复用清除作业类型及显示名常量。
- `src/rdp/jobs/models.py`：补充状态和首次领取时间的字段契约。
- `src/rdp/jobs/navigation.py`：显式捕获本次调用的主异常，正确传播释放故障。
- `src/rdp/jobs/records.py`：新增受限的未启动领取退回事务。
- `src/rdp/jobs/registry.py`：集中定义作业类型、显示名、清除类型集合，复用类型键正则。
- `src/rdp/jobs/resources.py`：补充已提交领取必须先处理数据库退回的契约。
- `src/rdp/jobs/schedules.py`：复用作业类型、显示名和清除类型集合。
- `src/rdp/jobs/scheduling.py`：修复扫描途中释放 GPU 导致的插队；取消恢复作业的日志故障只记 ERROR。
- `src/rdp/jobs/worker.py`：补充未启动领取的停止处理契约，删除失效注释。
- `src/rdp/ops/worker.py`：核卡错误日志使用 `gpu_index=%d`。
- `src/web/src/api/scheduling.ts`：删除模块说明中的“（09）”。
- `src/web/src/scheduling/Pages.tsx`：删除过程标记，校验提示从已有常量插值。
- `src/web/src/scheduling/queries.ts`：删除模块说明中的“（09）”。
- `tests/test_jobs_gpu.py`：调整核卡日志断言，匹配 `key=value` 格式。
- `tests/test_jobs_navigation.py`：覆盖外层正在处理异常时，写锁清理故障仍正确传播。
- `tests/test_jobs_scheduling.py`：增加跨类型抢卡、日志失败、未启动退回及相关异常路径测试。

**2. `make check`**

指定测试组连续运行三次：

```text
.venv/bin/pytest -p no:cacheprovider tests/test_jobs_worker.py tests/test_jobs_scheduling.py tests/test_jobs_gpu.py

============================= 121 passed in 11.01s =============================
============================= 121 passed in 10.87s =============================
============================= 121 passed in 10.95s =============================
```

`test_serial_execution` 的测试内容和断言未修改。

最终命令：

```bash
make check > /tmp/rdp09-r2-njfbl4cq/make-check.log 2>&1
```

末尾原样输出：

```text
================= 1681 passed, 1 warning in 120.82s (0:02:00) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.HxidECIasM/openapi.json → /tmp/tmp.HxidECIasM/schema.d.ts [68ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-09-job-scheduling-resources/src/web


 Test Files  19 passed (19)
      Tests  228 passed (228)
   Start at  15:39:07
   Duration  6.87s (tests 51%, environment 29%, import 19%)

```

唯一 warning 是现有 Starlette TestClient 对 httpx 的弃用提示；未调整依赖。

运行前的 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/jobs.py
 M src/rdp/audit/_validation.py
 M src/rdp/audit/job_contracts.py
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/ids.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_process_io.py
 M src/rdp/jobs/_storage.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/gpu.py
 M src/rdp/jobs/maintenance.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/navigation.py
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resource_examples.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedule_records.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/scheduling_service.py
 M src/rdp/jobs/scheduling_types.py
 M src/rdp/jobs/service.py
 M src/rdp/jobs/worker.py
 M src/rdp/ops/worker.py
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/scheduling.test.ts
 M src/web/src/api/scheduling.ts
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/Resources.test.tsx
 M src/web/src/jobs/progress.ts
 M src/web/src/jobs/queries.ts
 M src/web/src/router.tsx
 M src/web/src/scheduling/Pages.test.tsx
 M src/web/src/scheduling/Pages.tsx
 M src/web/src/scheduling/queries.ts
 M tests/jobs_api_support.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_progress_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_gpu.py
 M tests/test_jobs_maintenance.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_navigation.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_schedules.py
 M tests/test_jobs_scheduling.py
 M tests/test_jobs_scheduling_api.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? src/rdp/jobs/_parameters.py
?? src/web/src/jobs/_actions.ts
?? src/web/src/scheduling/pageTestSupport.tsx
?? src/web/src/scheduling/testSupport.ts
?? tests/jobs_gpu_support.py
?? tests/jobs_maintenance_support.py
?? tests/jobs_navigation_support.py
?? tests/jobs_schedules_support.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

运行后：

```text
 M src/rdp/api/jobs.py
 M src/rdp/audit/_validation.py
 M src/rdp/audit/job_contracts.py
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/ids.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_process_io.py
 M src/rdp/jobs/_storage.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/gpu.py
 M src/rdp/jobs/maintenance.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/navigation.py
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resource_examples.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedule_records.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/scheduling_service.py
 M src/rdp/jobs/scheduling_types.py
 M src/rdp/jobs/service.py
 M src/rdp/jobs/worker.py
 M src/rdp/ops/worker.py
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/scheduling.test.ts
 M src/web/src/api/scheduling.ts
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/Resources.test.tsx
 M src/web/src/jobs/progress.ts
 M src/web/src/jobs/queries.ts
 M src/web/src/router.tsx
 M src/web/src/scheduling/Pages.test.tsx
 M src/web/src/scheduling/Pages.tsx
 M src/web/src/scheduling/queries.ts
 M tests/jobs_api_support.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_progress_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_gpu.py
 M tests/test_jobs_maintenance.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_navigation.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_schedules.py
 M tests/test_jobs_scheduling.py
 M tests/test_jobs_scheduling_api.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? src/rdp/jobs/_parameters.py
?? src/web/src/jobs/_actions.ts
?? src/web/src/scheduling/pageTestSupport.tsx
?? src/web/src/scheduling/testSupport.ts
?? tests/jobs_gpu_support.py
?? tests/jobs_maintenance_support.py
?? tests/jobs_navigation_support.py
?? tests/jobs_schedules_support.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

前后状态完全一致；`git diff --check` 通过。

**3. 契约补充、docstring/TSDoc 改动**

契约变更申请：**无**。依赖申请：**无**。

按本轮批准补充内部状态机，新增：

```python
return_unstarted_job(
    session: Session,
    record: JobRecord,
    *,
    mode: ExecutionMode,
    now: datetime,
) -> JobRecord
```

仅允许本实例仍持有有效领取凭据、执行线程从未启动的领取进入此路径。普通 `StateChange` 仍不允许 `running → queued`，没有新增状态或 HTTP 接口。

文档改动：

- `records.py`：模块说明、`StateChange.target` 和 `transition_job` 将“所有状态写入”明确为“常规状态写入”，注明受限退回入口；`claim_job.Returns` 补充“此快照只证明领取已提交”；新增函数完整六项契约。
- `models.py`：`state` 补充未启动领取的受限退回；`started_at` 明确为首次领取时间，未启动退回时清空，已有执行历史的恢复不变。
- `worker.run_loop.Side Effects`：补充停止、启动失败时短事务退回、取消意图保留、退回失败停止实例，以及真正启动的线程不能退回。
- `ResourcePool.reserve.Side Effects`：补充“已提交但未启动的领取须先由主循环处理数据库退回”。
- `Scheduler.claim_next.Side Effects`：补充同轮较早队首等卡后，后续需卡队首不能领取途中归还的卡；取消终态后的日志故障只记一次 ERROR；未启动领取由主循环退回。
- `NavigationWriter.run.Side Effects`：补充“只保护本次调用显式捕获的主异常”；正常写完后的清理故障传播，不给外层无关异常加备注。
- 私有 `_start`、`_return_unstarted`、`_cancel_recovered`：说明未启动判定、退回失败传播和终态日志故障处理。
- `test_thread_start_failure`：契约说明改为退回排队、清领取字段并归还资源；新增测试 docstring 分别说明所验证行为。
- 前端三个模块说明删除“（09）”；无函数 TSDoc 含义变更。

**4. 拿不准的地方**

无待决定项。

两个边界已明确并测试：新领取后取消已提交时完成取消，不能重新入队；已有历史的续跑/重跑只清本次资源副本，保留历史状态、日志、进度和恢复资格。实际已启动的线程继续按原停止预算收尾。

类型键正则的三处引用均通过 import-linter，无需保留重复定义。

**5. 先红后绿**

r1 的首次运行：

- `test_released_gpu_does_not_bypass_earlier_head_in_same_scan`：**失败**，较晚的 GPU 作业 7 越过作业 5，未继续领取 CPU 作业 9；修复后通过。
- `test_successful_write_cleanup_in_outer_except_propagates[metadata]`：**失败**，持有人清理异常被吞掉；修复后通过。
- `test_successful_write_cleanup_in_outer_except_propagates[display]`：**失败**，展示清理异常被吞掉；修复后通过，外层异常无新增备注。
- `test_cancelled_recovery_log_failure_does_not_stop_claiming[open]`：**失败**，打开日志的 `ExternalError` 冒出 `claim_next`；修复后通过。
- `test_cancelled_recovery_log_failure_does_not_stop_claiming[summary]`：**失败**，写摘要的 `ExternalError` 冒出 `claim_next`；修复后通过。

r2 的首次运行：

- `test_stop_after_committed_claim_returns_fresh_job_to_queue`：**失败**，作业仍为 running、保留 GPU 0；修复后通过，并验证下一实例只执行一次、恢复次数不增加。
- `test_thread_start_failure`：加强断言后**失败**，数据库仍为 running；修复后为 queued，领取字段清空。
- `test_unstarted_return_failure_fails_worker[update]`：首次**通过**；前一修复已实现事务失败传播及 finally 归还资源，新增测试验证 UPDATE 故障。
- `test_unstarted_return_failure_fails_worker[begin]`：首次**通过**；同一失败路径已覆盖入场锁失败，测试用短预算验证不能跳过。
- `test_unstarted_return_preserves_cancel_request`：首次**通过**；退回实现已保留并完成新领取后的取消请求。
- `test_unstarted_recovery_preserves_previous_execution[no-cancel-resume]`：首次**通过**；实现已区分新领取与历史续跑。
- `test_unstarted_recovery_preserves_previous_execution[no-cancel-restart]`：首次**通过**；实现已保留重跑历史和恢复资格。
- `test_unstarted_recovery_preserves_previous_execution[cancel-resume]`：**失败**，错误地提前转为 cancelled；修复后保留 cancelling，交既有恢复流程收尾。
- `test_unstarted_recovery_preserves_previous_execution[cancel-restart]`：**失败**，同样提前转为 cancelled；修复后通过。
- `test_start_error_after_thread_launch_does_not_requeue`：首次**通过**；实现已有实际启动判定，测试验证启动后抛错仍保留运行状态、凭据及线程收尾责任。