本轮交检查点：`make check` 全绿，整票尚未完成。pytest 剩 **22 项跳过**，Vitest 剩 **11 项跳过**。改动未暂存、未提交，临时文件已清理。

**1. 改动清单**

以下列本轮改动；上一检查点的其他改动保留。

| 文件 | 本轮改动 |
|---|---|
| `src/rdp/api/errors.py` | 保留原接口，委托共用异常报告函数。 |
| `src/rdp/api/jobs.py` | 实现装配、提交、取消、重提、查询、日志和心跳接口。 |
| `src/rdp/audit/job_contracts.py` | 实现作业审计对象与明细校验。 |
| `src/rdp/infra/exception_report.py` | 下移既有异常报告实现，供 Web、worker 共用。 |
| `src/rdp/jobs/_audit.py` | 作业审计白名单、原子追加与失败补记。 |
| `src/rdp/jobs/_clock.py` | 单调时钟及 UTC 时钟校验。 |
| `src/rdp/jobs/_diagnostics.py` | 有界增量诊断聚合，保留完整总数。 |
| `src/rdp/jobs/_loop.py` | 串行调度、恢复扫描、心跳、取消观察和停止收尾。 |
| `src/rdp/jobs/_pagination.py` | 按编号分页及绑定筛选的游标。 |
| `src/rdp/jobs/_process_io.py` | 流式输出、续行标记、有界 stderr 尾部。 |
| `src/rdp/jobs/_recovery.py` | 当前登记恢复方式、恢复次数和重跑清零事务。 |
| `src/rdp/jobs/_storage.py` | 增加入场 BUSY/LOCKED 的异常链识别。 |
| `src/rdp/jobs/example.py` | 实现数数、警告、条目失败和整体中止。 |
| `src/rdp/jobs/execution.py` | 执行、取消收尾、最终快照、异常报告和恢复隔离。 |
| `src/rdp/jobs/logs.py` | 实现完整日志段、并发写锁、有限尾读和资源关闭。 |
| `src/rdp/jobs/processes.py` | 实现外部进程、输出捕获和 TERM/KILL 收尾。 |
| `src/rdp/jobs/progress.py` | 实现节流补写、协作取消、等待、累计基线及资源登记。 |
| `src/rdp/jobs/records.py` | 编号耗尽归 `ConflictError`，保留真正磁盘满的原分类。 |
| `src/rdp/jobs/service.py` | 实现提交、取消、重提、详情、分页和心跳服务。 |
| `src/rdp/jobs/worker.py` | 实现单实例锁及主循环入口。 |
| `src/rdp/ops/worker.py` | 实现 worker 装配、退出码和遗留线程保锁。 |
| `src/web/src/accounts/Pages.tsx` | 挂载所有登录账号可见的 worker 横幅。 |
| `src/web/src/accounts/Pages.test.tsx` | 为新增心跳请求提供独立响应，保留账号测试语义。 |
| `src/web/src/api/jobs.ts` | 实现全部作业传输函数。 |
| `src/web/src/api/jobs.test.ts` | 启用并实现五条传输测试。 |
| `src/web/src/jobs/Pages.tsx` | 实现列表、筛选和 worker 横幅；详情、提交页仍待续接。 |
| `src/web/src/jobs/Pages.test.tsx` | 实现真实路由、速率、状态标签和横幅测试。 |
| `src/web/src/jobs/progress.ts` | 实现速率计算、终态判断和状态标签。 |
| `src/web/src/jobs/queries.ts` | 实现列表与 worker 状态查询。 |
| `src/web/src/jobs/search.ts` | 实现类型化 URL 筛选校验。 |
| `src/web/src/jobs/testSupport.ts` | 增加生成类型约束的独立测试样本。 |
| `src/web/src/router.tsx` | 接通作业 search 校验及错误提示分支。 |
| `tests/job_process_support.py` | 实现真实 worker、工具进程、握手和清理夹具。 |
| `tests/jobs_api_support.py` | 临时迁移库和真实 ASGI 作业装配夹具。 |
| `tests/jobs_execution_support.py` | 执行器公共边界夹具。 |
| `tests/jobs_loop_support.py` | 有界主循环线程及状态握手。 |
| `tests/jobs_progress_support.py` | 真实数据库、日志和可注入时钟夹具。 |
| `tests/test_jobs_api.py` | 启用十条真实 HTTP 测试。 |
| `tests/test_jobs_logs.py` | 日志内容、边界、故障和资源测试。 |
| `tests/test_jobs_migration.py` | 完成剩余三个迁移测试。 |
| `tests/test_jobs_processes.py` | 八个真实子进程用例全部启用。 |
| `tests/test_jobs_progress.py` | 全部进度测试启用，补线程归属等边界测试。 |
| `tests/test_jobs_records.py` | 增加编号耗尽分类测试。 |
| `tests/test_jobs_registry.py` | 启用五条示例执行结果测试。 |
| `tests/test_jobs_service.py` | 提交、取消、重提、分页及作业审计测试。 |
| `tests/test_jobs_state.py` | 启用取消优先和执行异常测试。 |
| `tests/test_jobs_worker.py` | 恢复、主循环、心跳、停止及故障回归测试。 |

**2. `make check`**

最后命令，在指定 worktree 中执行：

```text
make check
```

本轮完整检查运行了两次：首次在契约检查发现五个内部构造器缺职责说明；补齐后，最后一次全部通过。末尾输出原文：

```text
=========== 1491 passed, 22 skipped, 1 warning in 104.59s (0:01:44) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.s9bFiJp32X/openapi.json → /tmp/tmp.s9bFiJp32X/schema.d.ts [62.7ms]
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
      Tests  190 passed | 11 skipped (201)
   Start at  07:47:05
   Duration  6.61s (tests 50%, environment 30%, import 19%, transform 1%)
```

最后一次运行前，`git status --porcelain --untracked-files=all`：

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
?? tests/jobs_progress_support.py
?? tests/jobs_storage_support.py
?? tests/test_jobs_records.py
```

**3. 契约变更申请、依赖申请**

无。没有修改受保护文件，也没有修改既有公开签名。

`rdp.api.errors.format_exception_report(error: BaseException) -> str` 的签名和 docstring 原样保留，仅将实现下移到基础层共用。

本轮文档补充：

- `AccountLayout`：将“不使用定时轮询……”改为“身份查询不使用定时轮询；worker 状态通过顶部横幅每秒查询，任意接口401均触发既有身份清理。根布局统一保护页面内容。”
- `ProcessCase.wait_running`：补 `Returns: 已持久化第3条进度的作业快照。`
- `prepare_process_case`：补 `Returns: 含两个作业编号和临时根目录的夹具句柄。`
- `worker_main`：补 `Raises: SystemExit: 完成worker退出后把具名退出码交操作系统。`
- `_clock`、`_loop`、`_process_io`、`_ExecutionRun`、`_ProcessRun` 的内部构造器补职责说明。
- `test_jobs_logs.py`、`test_jobs_api.py` 的模块说明改为当前测试行为，去掉“执行行为尚不可用”。

**4. 拿不准、需要评审决定的地方及剩余工作**

没有新的负责人决策申请。有一处测试校正请评审核对：默认 fetch 回归测试沿用已合并的 client/audit 测试，接受 `undefined/globalThis` 接收者，仍拒绝配置对象作为 `this`；没有修改 `defaultFetch`。

本轮未完成整票。下一轮须继续以下 **22 个 Python 测试**：

```text
tests/test_jobs_api.py
  test_openapi_job_schema
  test_no_web_execution

tests/test_jobs_logs.py
  test_missing_log
  test_recovery_log_first
  test_claim_crash_before_header

tests/test_jobs_registry.py
  test_unknown_queued_type
  test_obsolete_parameters

tests/test_jobs_service.py
  test_cancel_running
  test_deleted_submitter
  test_no_delete_api
  test_service_failures
  test_audit_name_limit
  test_cancel_vs_completion_orders

tests/test_jobs_state.py
  test_final_commit_failure

tests/test_jobs_worker.py
  test_heartbeat_invalid
  test_external_group_and_failure_diagnostics
  test_external_readers_and_deadlines
  test_lock_retention_no_gc_close
  test_reader_timeout_retains_lock
  test_cancel_stall_not_repeated
  test_systemd_orphan_boundary
  test_unreapable_external_process
```

前端剩 **11 个页面测试**及对应实现：

- 未知总数的详情显示。
- 已用时间和 `useJobTiming`。
- 取消按钮、409 刷新。
- 重新提交与导航。
- 日志状态及 HTML 安全文本展示。
- 详情诊断卡片。
- 终态停止详情／日志轮询。
- 账号切换、401 和迟到响应隔离。
- 示例提交表单。
- URL 筛选切换、返回及刷新。
- 操作日志作业对象展示。

`JobDetailPage`、`SubmitCountJobPage`、对应详情／写操作 hooks 和 `useJobTiming` 仍保留未实现函数体。外部进程不可回收、后代持有管道等故障路径尚未完成测试，不能视为已验收。

**5. 先红后绿——仅本轮**

下列参数化测试注明例数；各例首次结果一致。“未实现”指首次运行触达 `NotImplementedError` 或前端“未实现”异常。所有本轮启用测试最终均通过。

```text
tests/test_jobs_records.py
test_insert_exhausted_id_is_conflict — 首跑漏导入；修正后红：误抛 ExternalError。

tests/test_jobs_logs.py
test_header_metadata — 红：日志打开未实现。
test_utc_filename — 红：日志打开未实现。
test_millisecond_collision — 红：日志打开未实现。
test_summary_matches_record — 红：摘要写入未实现。
test_thread_lines — 初次通过：前一组实现已包含写锁和逐行刷新。
test_output_prefixes — 红：外部进程入口未实现。
test_large_output — 红：外部进程入口未实现，未保存真实退出码。
test_bounded_tail — 红：尾读未实现。
test_path_escape — 红：尾读未实现。
test_recovery_log_deleted — 初次通过：恢复实现已重建原路径并先写头。
test_summary_io_failure — 初次通过：执行器已分离终态提交和日志结尾失败。
test_close_resources — 红：关闭故障覆盖首次 flush 故障。
test_claim_atomic_path — 初次通过：前轮领取事务已保证整体回滚。
test_tail_local_missing_and_io — 红：尾读未实现。
test_diagnostic_and_interruption_segments — 红：诊断／中断段未实现。
test_header_rejects_byte_oversize_and_nonobject — 红：未按 UTF-8 字节拒绝超限配置。
test_stderr_tail_byte_boundary_marks_truncation — 首跑工具字符串转义错误；修正后红：缺截断标记。
test_large_summary_preserves_all_artifacts — 红：合法大摘要被 64KiB 过程消息限制拒绝。

tests/test_jobs_progress.py
test_throttle_latest — 红：上报对象未实现。
test_throttle_clock_rollback — 红：上报对象未实现。
test_short_lock_skip — 红：入场忙未跳过。
test_entered_failure_not_skipped — 初次通过：已有事务边界会传播约束失败。
test_final_forced_snapshot — 首跑测试导入笔误；修正后通过：执行器已有最终普通事务。
test_unknown_total — 首跑测试导入笔误；修正后通过：存储和 HTTP 已保留 null。
test_progress_monotonic_counts — 红：上报对象未实现。
test_cancel_interruptible_wait — 红：等待未实现。
test_stop_distinct_cancel — 红：停止检查未实现。
test_bounded_diagnostics — 红：诊断上报未实现。
test_artifact_bounds — 红：产物上报未实现。
test_persist_elapsed_fragments — 红：上报对象未实现。
test_long_wait_flushes_latest — 红：长等待未补写最新值。
test_checkpoint_flushes_latest — 红：检查点未实现。
test_process_poll_flushes_latest — 首跑测试导入笔误；修正后通过：进程轮询已复用上报等待。
test_flush_busy_delay — 红：忙锁异常直接传播。
test_flush_stop_priority — 红：取消检查未实现。
test_resume_cumulative_baseline — 红：上报对象未实现。
test_resume_stage_advance — 红：上报对象未实现。
test_tool_exit_and_thread_ownership — 红：退出码／线程登记未实现。
test_invalid_wait_and_diagnostic_identity — 红：诊断上报未实现。

tests/test_jobs_registry.py
test_count_success — 红：执行器未实现。
test_count_warnings — 红：执行器未实现。
test_count_partial — 红：执行器未实现。
test_count_all_failed — 红：执行器未实现。
test_count_aborted — 红：执行器未实现。

tests/test_jobs_state.py
test_cancel_wins_return — 初次通过：执行器最终事务已重读取消态。
test_cancel_wins_exception — 初次通过：同一取消优先收尾已覆盖异常返回。
test_execution_exception — 红：完整报错未写入报错表。

tests/test_jobs_worker.py
test_serial_execution — 红：主循环未实现。
test_recovery_priority — 红：主循环未实现。
test_resume_context — 红：恢复未实现。
test_restart_context — 红：恢复未实现。
test_recover_cancelling — 红：恢复未实现。
test_heartbeat_interval — 首跑漏导入 select；修正后通过：主循环已实现周期心跳。
test_heartbeat_busy — 初次通过：主循环已区分入场忙并警告。
test_stop_in_process — 红：主循环未实现，未到执行握手。
test_lock_error_codes — 红：运维入口未实现。
test_context_logging — 初次通过：线程已 copy_context，执行器已绑定／恢复编号。
test_final_failure_halts_claiming — 初次通过：执行线程失败通知已停止主循环。
test_recovery_mode_snapshot（12例）— 红：恢复未实现。
test_recovery_heartbeat_not_blocked — 初次通过：恢复执行已放入独立线程。
test_shutdown_timeout_result — 初次通过：主循环已有共同停止预算和遗留线程结果。
test_recovery_limit（4例）— 红：恢复未实现。
test_recovery_attempt_before_execution — 红：资格提交失败未隔离。
test_recovery_record_corrupt — 红：坏记录异常逃出恢复边界。
test_recovery_log_failure — 红：日志错误逃出恢复边界。
test_recovery_scan_advances — 初次通过：恢复游标已按编号推进。
test_cancel_stall_warning — 红：未产生取消超时警告。
test_lock_public_lifecycle — 红：实例锁未实现。
test_external_timeout_diagnostic_after_reap — 红：诊断提前冻结为未知退出码。
test_runtime_clock_failure_still_returns_failure — 红：收尾再次读取坏时钟，异常逃逸。
test_execution_log_open_failure_preserves_history — 红：新故障覆盖历史诊断总数。
test_external_failure_has_job_identity — 红：工具诊断缺作业编号。

tests/test_jobs_processes.py
test_sigkill_recovery（3例）— 红：真实进程夹具未实现。
test_second_worker_lock — 红：真实进程夹具未实现。
test_lock_not_inherited — 红：真实进程夹具未实现。
test_external_process_ignores_sigterm — 红：取消服务夹具入口未实现；随后修正测试账号改密状态。
test_shutdown_timeout_keeps_lock_until_process_exit — 红：真实进程夹具未实现。
test_crash_after_claim_before_log_header — 红：真实进程夹具未实现。

tests/test_jobs_migration.py
test_job_foreign_key_absent — 初次通过：前轮 0004 已无账号外键。
test_recovery_counter_schema — 初次通过：前轮模型／迁移已有 0–3 约束。
test_claimed_log_path_constraint — 初次通过：前轮已激活非空和唯一约束。

tests/test_jobs_service.py
test_submit_member_other_jobs — 红：详情查询未实现。
test_submit_atomic_audit — 红：服务未实现。
test_submit_rollback — 初次通过：提交实现已有同事务审计及失败补记。
test_reject_no_audit — 初次通过：校验／鉴权在执行事件建立之前。
test_cancel_queued — 红：服务未实现。
test_cancel_terminal_conflict — 红：服务未实现。
test_cancel_commits_first — 初次通过：前轮条件状态更新和本轮取消已接通。
test_claim_commits_first — 初次通过：取消已在写事务内读当前状态。
test_cancel_atomic_failure — 初次通过：取消实现已有回滚及失败补记标记。
test_resubmit_terminal — 红：重新提交未实现。
test_resubmit_nonterminal — 红：重新提交未实现。
test_resubmit_incompatible — 初次通过：重新提交已按当前模型验证。
test_cursor_pagination — 红：列表未实现。
test_cursor_invalid — 红：列表未实现。
test_audit_job_shape — 红：失败取消事件未核对 before 对象编号。
test_audit_account_filter — 首跑测试构造／字段名错误；修正后通过：既有审计筛选已限定 account。

tests/test_jobs_api.py
test_real_app_order — 红：列表入口未实现。
test_real_app_invalid_payload — 红：通用提交入口未实现。
test_real_app_submit_cancel — 红：作业装配未实现。
test_real_app_cancel_conflict — 初次通过：取消接口及服务已有冲突拒绝。
test_real_app_resubmit — 红：重提接口未实现。
test_real_app_detail_notfound — 红：作业装配未实现。
test_real_app_log_status — 红：作业装配未实现。
test_real_app_cursor — 红：通用提交／列表入口未实现。
test_real_app_worker_status — 红：作业装配未实现。
test_claim_before_cancel_returns_cancelling — 初次通过：接口已委托事务内取消服务。

src/web/src/api/jobs.test.ts
默认 fetch 接收者 — 红：listJobs 未实现。
提交／取消／重提传输 — 红：传输函数未实现。
401／409／422 错误传播 — 红：传输函数未实现。
筛选与大编号传输 — 红：传输函数未实现。
AbortSignal 与迟到响应 — 红：传输函数未实现。

src/web/src/jobs/Pages.test.tsx
真实 Router 合法筛选 — 红：路由／列表未实现。
真实 Router 非法筛选 — 红：路由／页面未实现。
最近十秒速率样本 — 红：calculateJobRate 未实现。
九种状态标签 — 红：jobStatusLabel 未实现。
成员页面 worker 离线横幅 — 红：横幅未挂载。
加载／故障不伪装离线 — 红：横幅未挂载。
```