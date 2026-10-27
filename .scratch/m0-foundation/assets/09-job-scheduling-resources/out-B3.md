**1. 改动清单**

本轮交检查点。相对 B-cp2，改了以下 10 个文件：

- `src/rdp/jobs/navigation.py`：实现共享写锁、有界等待、超时诊断、取消屏蔽和异常释放。
- `src/rdp/jobs/progress.py`：实现一次性取消屏蔽；保护段等待避免忙等；增加只读身份、时钟属性。
- `src/rdp/jobs/execution.py`：接入导航写入能力和示例路径；停止收尾清资源副本；传递 GPU 编号。
- `src/rdp/jobs/processes.py`：按子进程设置 CUDA 环境，并记录实际传入值。
- `src/rdp/jobs/resource_examples.py`：实现写锁示例、预览冲突、有界尾读和文件错误转换。
- `tests/jobs_progress_support.py`：支持不同作业编号。
- `tests/jobs_navigation_support.py`：新增真实执行、竞争线程及文件故障夹具。
- `tests/test_jobs_navigation.py`：启用原有 21 条测试，新增释放故障测试；另保留一条契约边界测试。
- `tests/test_jobs_gpu.py`：实现并发环境隔离测试；假脚本记录参数、环境和 PID，退出时清理进程组。
- `tests/test_jobs_processes.py`：注释改为“不同类型互不阻塞，所以只核对执行次数”。

未暂存、未提交；本轮临时目录已删除。

**2. `make check`**

最后一次命令：

```bash
make check > /tmp/rdp09-b3-loppwcuq/make-check.log 2>&1
```

退出码 `0`。pytest 末尾原文：

```text
=========== 1595 passed, 70 skipped, 1 warning in 116.99s (0:01:56) ============
```

Vitest 末尾原文：

```text
 Test Files  16 passed | 3 skipped (19)
      Tests  205 passed | 23 skipped (228)
   Start at  04:29:49
   Duration  6.76s (tests 49%, environment 35%, import 16%)
```

运行前 `git status --porcelain --untracked-files=all`：

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
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resource_examples.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/service.py
 M src/rdp/ops/worker.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_progress_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_gpu.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_navigation.py
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
?? tests/jobs_navigation_support.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

运行后：

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
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resource_examples.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/service.py
 M src/rdp/ops/worker.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_progress_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_gpu.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_navigation.py
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
?? tests/jobs_navigation_support.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

**3. 契约变更申请、依赖申请**

**契约申请一项，尚未实施：** `read_example_value` 的读取预算由最多 4096 字节改为最多 **4097 字节**，额外一字节用于确认行界；单行上限仍为 4096 字节。尾部空行计入读取预算，窗口内找不到完整非空记录时拒绝读取。

原因：仅看末尾 4096 字节，无法区分“恰好 4096 字节的完整行”和“超长行的末段”。新增测试已复现当前保守实现误拒绝合法完整行。按 prompt-B 的契约变更停止条件交回。

依赖申请：**无**。

已有生产 docstring 只改一句：

- `execute_gpu_example`：“作业留待下一实例标记中断”→“作业由下一实例标记中断”。

新增只读属性及说明：

- `ProgressReporter.job_id -> int`：“本作业正编号（1至2^63-1），供框架补诊断身份，只读且不访问数据库。”
- `ProgressReporter.clock -> JobClock`：“本作业注入的UTC墙钟和单调秒时钟，只读，框架不另取隐式系统时钟。”

测试说明调整：

- 导航测试模块说明改为“导航写锁、协作取消与状态文件的行为测试；数据库和文件均位于临时目录。”
- GPU 测试模块说明改为“GPU行为测试；唯一外部工具是测试生成的假nvidia-smi，不探测真实硬件。”
- 两条导航测试的“负责人决定：”“评审7：”改为“契约：”。

**4. 需要评审决定及剩余工作**

需要决定第 3 块的读取预算。当前新增边界测试保留跳过，不能据本次全绿认定该边界已经完成。

剩余 Python 测试：

| 文件 | skipped | 剩余范围 |
|---|---:|---|
| `test_jobs_navigation.py` | 1 | `test_full_limit_tail_after_previous_line` |
| `test_jobs_gpu.py` | 22 | 核卡、启动坏卡处理与落库、入口装配、生命周期及示例集成 |
| `test_jobs_schedules.py` | 22 | 定时提交、补跑、时区及夏令时 |
| `test_jobs_maintenance.py` | 11 | 两个清除作业 |
| `test_jobs_scheduling.py` | 2 | `test_shared_stop_budget`、`test_run_loop_checks_schedules_and_finishes_cleanup` |
| `test_jobs_scheduling_api.py` | 12 | 调度查询及示例提交接口 |

前端三个文件仍有 23 条跳过：`jobs/Resources.test.tsx`、`scheduling/Pages.test.tsx`、`api/scheduling.test.ts`；页面接入也仍未完成。

**5. 先红后绿**

除最后注明的边界测试外，以下测试最终均通过。

`tests/test_jobs_navigation.py`：

| 测试 | 首次运行结果 |
|---|---|
| `test_callback_result` | 红：`NavigationWriter.run` 未实现。 |
| `test_execution_context_exposes_only_needed_capabilities` | 红：`write_navigation` 未实现。 |
| `test_cancel_during_write` | 红：写入被取消打断，产物未生成。 |
| `test_deferred_wait_is_bounded_without_spin` | 红：已置位 Event 导致等待忙等。 |
| `test_verify_error` | 首跑诊断构造错误；修正测试后直接绿，已有 finally 已保留原异常并释放锁。 |
| `test_write_error` | 直接绿：已有清理逻辑保留写入异常及部分产物。 |
| `test_stop_during_write` | 红：停止收尾后数据库残留等待原因。 |
| `test_cancel_wait` | 直接绿：已有分段取锁循环检查取消。 |
| `test_stop_wait` | 直接绿：同一循环已检查停止。 |
| `test_wait_timeout` | 直接绿：已有单调截止及持有人诊断。 |
| `test_nested_guard` | 直接绿：已有一次性、线程身份及递归保护。 |
| `test_cancel_after_acquire` | 直接绿：已有拿锁后的最后一次取消检查。 |
| `test_timeout_holder_release_race` | 直接绿：超时身份取自当前内存状态。 |
| `test_matching_value` | 首跑测试访问错误字段；修正后因示例函数未实现而红，再实现通过。 |
| `test_missing_file` | 首跑测试访问错误字段；修正后因诊断出现 `#None` 而红，再修复通过。 |
| `test_conflict` | 直接绿：此前实现的核对逻辑已拒绝过期预览。 |
| `test_serialize` | 直接绿：共享写锁已保证保护段不重叠。 |
| `test_file_corrupt` | 红：损坏 JSON 泄漏原始解码异常。 |
| `test_path_boundary` | 红：相对路径未被拒绝。 |
| `test_file_io` | 红：文件权限错误未转换为 `ExternalError`。 |
| `test_pause_bounds` | 直接绿：已批准的参数模型已有严格类型和范围约束。 |
| `test_release_metadata_failure_keeps_primary` | 红：清理故障导致二次释放，掩盖原异常。 |
| `test_full_limit_tail_after_previous_line` | **红，保留跳过**：合法的完整 4096 字节尾行被误拒绝；对应契约申请。 |

`tests/test_jobs_gpu.py`：

| 测试 | 首次运行结果 |
|---|---|
| `test_child_environment` | 红：两个子进程收到的 CUDA 变量均为空；接入环境传递后通过。 |