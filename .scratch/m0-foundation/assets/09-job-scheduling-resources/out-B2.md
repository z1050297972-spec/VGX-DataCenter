**1. 改动清单**

本轮交检查点：去掉 **32 条跳过**，新增 **3 条测试**，共新增 **35 条通过**。公开签名未改，改动未暂存、未提交。

```text
src/rdp/jobs/resources.py：实现资源池、凭据归还、资源副本写入和启动统一清空。
src/rdp/jobs/records.py：实现每类队首查询、领取保存卡号、恢复领卡和终态清空。
src/rdp/jobs/_views.py：把数据库资源字段带入作业快照。
src/rdp/jobs/scheduling.py：实现按类型容量领取、恢复候选优先、等待重判和取消收尾；空定时登记可运行。
src/rdp/jobs/_loop.py：改为每作业独立线程、取消信号和监视对象，共用停止截止。
src/rdp/jobs/execution.py：执行资源回收完成后归还凭据。
src/rdp/ops/worker.py：在恢复前调用资源副本清空事务。
src/rdp/jobs/progress.py：实现资源展示短锁写入、节流及无新进度时补写。
src/rdp/jobs/navigation.py：实现实例锁构造；写入入口仍未完成。
src/rdp/jobs/registry.py：登记五种生产作业类型。
src/rdp/jobs/schedules.py：实现每日登记校验、排序和参数深复制。
src/rdp/jobs/_parameters.py：集中提交与每日登记共用的参数校验。
src/rdp/jobs/service.py：复用共用校验，清理遗留注释。
tests/jobs_scheduling_execution_support.py：新增真实资源池、登记表和迁移数据库夹具。
tests/jobs_scheduling_support.py：替换资源替身，显式领取凭据和模拟重启。
tests/jobs_execution_support.py：直接执行测试使用真实凭据并清理。
tests/jobs_loop_support.py：模拟新实例时重建空资源池。
tests/test_jobs_scheduling.py：完成并发、FIFO、恢复、取消、资源副本及故障测试。
tests/test_jobs_scheduling_config.py：完成五种生产类型登记测试。
tests/test_jobs_schedules.py：完成每日登记校验和深复制测试。
tests/test_jobs_registry.py：同步生产登记数量，保留数数类型及实例隔离断言。
tests/test_jobs_service.py：适配真实执行凭据。
tests/test_jobs_worker.py：适配恢复后的重新领资源和新实例构造。
tests/test_jobs_processes.py：按 K3 修正跨类型顺序假设，保留恢复与执行次数验证。
```

**2. `make check`**

最后命令：

```bash
make check > /tmp/rdp09-b2-_rcdknf1/check.log 2>&1
```

退出码 **0**。末尾原样：

```text
=========== 1572 passed, 91 skipped, 1 warning in 115.59s (0:01:55) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.QyyL7UDMxA/openapi.json → /tmp/tmp.QyyL7UDMxA/schema.d.ts [68.6ms]
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


 Test Files  16 passed | 3 skipped (19)
      Tests  205 passed | 23 skipped (228)
   Start at  03:34:32
   Duration  6.88s (tests 48%, environment 34%, import 17%)
```

本轮曾因两处私有函数跨模块调用停在类型检查；修正并清理过程用语后重跑，最终全绿。

检查前 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/navigation.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/service.py
 M src/rdp/ops/worker.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_schedules.py
 M tests/test_jobs_scheduling.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? src/rdp/jobs/_parameters.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

检查后：

```text
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/navigation.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/service.py
 M src/rdp/ops/worker.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_schedules.py
 M tests/test_jobs_scheduling.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? src/rdp/jobs/_parameters.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

检查前后状态一致。临时快照和检查日志已删除；未联网、未安装依赖、未调用真实 `nvidia-smi`。

**3. 契约变更申请、依赖申请**

**无。** 生产公开签名和已批准契约含义未改。

文档调整：

- `NavigationWriter.run`：“资源副本短锁忙只留待补写”改为“只延后补写”，含义不变。
- `_loop.py` 模块及私有方法说明改为每作业独立监视、全部恢复准备、按类型填充和共同停止截止。
- 测试夹具说明从资源替身改为真实资源对象，并说明重启时重建空池。
- 原生产登记测试由“只有数数类型”改为“五类仍包含数数类型”。
- 清理本轮修改文件中的过程用语；未修改 TSDoc。

旧崩溃恢复测试的全局执行顺序断言与 K3 冲突，已改为核对各作业执行次数；恢复进度、模式、编号、日志路径等断言保留。

**4. 拿不准、需要评审决定的地方**

无新增待决事项。**全票尚未完成**，剩余：

| 文件/测试 | 跳过数 |
|---|---:|
| `test_jobs_scheduling.py::test_shared_stop_budget` | 1 |
| `test_jobs_scheduling.py::test_run_loop_checks_schedules_and_finishes_cleanup` | 1 |
| `tests/test_jobs_gpu.py` | 23 |
| `tests/test_jobs_navigation.py` | 21 |
| `tests/test_jobs_schedules.py` | 22 |
| `tests/test_jobs_maintenance.py` | 11 |
| `tests/test_jobs_scheduling_api.py` | 12 |
| 前端三个测试文件 | 23 |

具体限制：

- 当前循环支持空定时登记；非空定时检查、系统提交和清除执行仍未完成。
- 五种类型已登记，但四个新增类型的执行函数仍需实现。
- GPU 核对、坏卡落库与入口完整装配、子进程环境注入仍需完成。
- 导航写锁只完成构造，写入顺序、等待及取消屏蔽尚未实现。
- 调度接口、页面、路由菜单尚未接通。

**5. 先红后绿**

`tests/test_jobs_scheduling.py`：

```text
test_limit_one：首次绿；上限2实现已按声明容量通用处理。
test_limit_two：红，第二个执行信号超时；改为多线程循环后绿。
test_other_type：红，导航锁及调度构造尚未实现；实现后绿。
test_same_type_fifo：首次绿；每类MIN(job_id)查询及资源判断已覆盖。
test_queue_cancel_race：首次绿；领取重验状态及finally归还已覆盖。
test_claim_busy：首次绿；短事务及凭据归还已覆盖。
test_claim_atomic：首次绿；领取事务和finally已覆盖，注入更新后故障验证回滚。
test_thread_start_failure：首次绿；新循环的start失败清理已覆盖。
test_per_job_signals：首次绿；每作业独立信号、警告计时及上下文已覆盖。
test_recovery_first：红，入口未调用统一清空；接入清空事务后绿。
test_recovery_different_types：红，恢复候选未参与领取；合并同类型恢复队首后绿。
test_recovery_capacity：首次绿；恢复准备与按容量领取已分离。
test_recovery_cancel：红，正在取消仍保留GPU等待导致CHECK冲突；清等待并收尾后绿。
test_unknown_type：首次绿；单一诊断名额及执行器失败收尾已覆盖。
test_terminal_failure：首次绿；实例失败信号、停止和凭据清理已覆盖。
test_resource_release：红，资源池未实现；实现凭据生命周期后绿。
test_display_short_lock：红，资源上报入口未实现；接入节流和补写后绿。
test_display_commit_failure：首次绿；共享事务及已入场错误传播已覆盖。
test_terminal_clear：红，终态保留资源标记导致CHECK冲突；同事务清空后绿。
test_recovery_clear：红，记录转换遗漏资源字段；补齐转换及统一清空后绿。
test_holder_handoff：红，资源副本写入未实现；原子交接标记后绿。
test_two_recoveries_do_not_block_other_type：首次绿；恢复队首合并与类型容量已覆盖。
test_queued_gpu_wait_clears_on_capacity：首次绿；逐轮重判及清空已覆盖。
test_queued_gpu_wait_clears_on_claim_and_cancel：首次绿；领取与终态清空已覆盖。
test_queue_wait_has_one_writer：首次绿；reporter已拒绝写GPU等待。
test_cross_type_gpu_fifo：红，等待原因未落库；补写及领取保存卡号后绿。
test_queued_heads_single_query：红，查询未实现；分组MIN查询后绿。
test_startup_reset_atomic_failure：首次绿；统一清空及受管事务回滚已覆盖。
test_resource_pool_lock_budget：首次绿；资源池短锁守卫已覆盖。
test_pool_inputs_and_admission：红，非法池配置被接受；补严格校验后绿。
test_scheduler_rejects_unprepared_candidates：红，重复恢复候选被接受；补校验后绿。
test_head_query_uses_isolated_short_budget：红，查询仍为5000毫秒；局部派生引擎预算后绿。
```

`tests/test_jobs_scheduling_config.py`：

```text
test_production_types：红，只有一种登记；增加四种登记后绿。
```

`tests/test_jobs_schedules.py`：

```text
test_registry_copy：红，构造未实现；排序及深复制后绿。
test_registry_validation：红，重复名字被接受；补登记校验后绿。
```

回归适配还修正了生产登记数量和跨类型恢复顺序假设；三种真实 SIGKILL 恢复模式最终均通过。