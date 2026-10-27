**1. 改动清单**

14 项评审意见已修订，仍只交契约骨架。已有测试断言未改；已有生产函数体仅适配必填构造参数。未暂存、未提交。

本轮文件逐项如下：

```text
src/rdp/jobs/scheduling.py：合并配置解析，改为每类队首调度、恢复按类型优先，删除扫描预算与游标。
src/rdp/jobs/scheduling_config.py：删除，内容并入 scheduling.py。
src/rdp/jobs/scheduling_types.py：迁入 SchedulingCatalog，增加启动核卡结果及展示状态。
src/rdp/jobs/scheduling_service.py：移除调度模块依赖，补充从数据库读取坏卡状态的契约。
src/rdp/jobs/resources.py：删除 ResourcePublisher，增加启动统一清空及核卡结果保存契约。
src/rdp/jobs/scheduling_models.py：改为单向系统身份约束，隔离声明 worker_gpu_checks 表。
src/rdp/jobs/records.py：增加每类队首查询，gpu_index 改必填，撤销排除集合与游标参数。
src/rdp/jobs/types.py：明确 GPU 等待写入者、清除条件及启动清卡语义。
src/rdp/jobs/worker.py：改为全部恢复准备后按类型调度，每轮检查定时作业。
src/rdp/jobs/_loop.py：补充修订说明，适配必填领取参数和执行凭据。
src/rdp/jobs/_recovery.py：明确恢复准备不取资源，返回显式 claim=None。
src/rdp/jobs/execution.py：依赖改必填关键字，上下文收窄为导航入口及最小执行能力。
src/rdp/jobs/progress.py：移除 publisher，改为直接短事务保存资源副本的契约。
src/rdp/jobs/gpu.py：核卡改收 JobLog；启动核对只写 worker.log。
src/rdp/jobs/navigation.py：补充 300 秒超时的实际等待时长和内存持锁者诊断。
src/rdp/jobs/policy.py：删除 SCAN/TICK_BUDGET，新增独立资源池锁预算。
src/rdp/jobs/processes.py：声明记录实际传给子进程的两项 CUDA 环境值。
src/rdp/jobs/resource_examples.py：示例只接收所需命令和文件路径，补充隔离日志契约。
src/rdp/jobs/maintenance.py：增加仅含两个清除回调的 MaintenanceActions。
src/rdp/jobs/service.py：允许有编号且名为“系统”的账号正常提交、重新提交。
src/rdp/jobs/models.py：同步单向身份约束说明，活动元数据仍保持隔离。
src/rdp/ops/worker.py：配置改必填，补充坏卡移出、结果落库及空有效池行为。
src/rdp/api/jobs.py：配置与上下文依赖改必填，示例路径统一到 /example/ 下。
src/rdp/api/scheduling_schemas.py：增加卡的 available/excluded/unknown、诊断和核对时间。
src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py：同步单向身份约束及核卡表迁移契约。
src/web/src/api/openapi.json：重新生成。
src/web/src/api/schema.d.ts：重新生成。
src/web/src/api/scheduling.ts：同步两个示例接口路径。
src/web/src/scheduling/search.ts：删除调度页 URL 参数。
src/web/src/scheduling/Pages.tsx：改为单一只读页，增加坏卡展示契约。
src/web/src/scheduling/queries.ts：删除页签相关约定。
src/web/src/scheduling/Pages.test.tsx：删除两条页签路由测试，增加坏卡展示跳过测试。
src/web/src/router.tsx：删除调度 search 契约。
src/web/src/jobs/Pages.tsx：系统身份按空编号识别，同名账号保留账号语义。
src/web/src/jobs/Resources.test.tsx：同步空编号系统与同名账号的展示测试。
tests/jobs_scheduling_support.py：新增无卡、空定时登记的显式装配夹具。
tests/jobs_execution_support.py：适配必填资源与执行凭据。
tests/jobs_api_support.py：显式提供调度配置。
tests/job_process_support.py：子进程入口显式提供资源与调度配置。
tests/test_jobs_logs.py：领取调用显式传 gpu_index。
tests/test_jobs_records.py：领取调用显式传 gpu_index。
tests/test_jobs_registry.py：执行依赖通过夹具构造。
tests/test_jobs_service.py：执行依赖、凭据及领取参数通过夹具构造。
tests/test_jobs_worker.py：入口与执行依赖通过夹具构造。
tests/test_jobs_scheduling.py：修订恢复测试，补充跨类型抢卡、等待清除及 run_loop 定时集成测试。
tests/test_jobs_gpu.py：补充坏卡移出、全失败、重启恢复、日志出口及命令路径测试。
tests/test_jobs_navigation.py：补充超时持锁者诊断和上下文能力边界测试。
tests/test_jobs_scheduling_api.py：补充坏卡数据库展示和同名系统账号测试。
tests/test_jobs_scheduling_config.py：补充必填依赖测试。
tests/test_jobs_scheduling_migration.py：修订单向身份测试，补充核卡表隔离测试。
```

**2. `make check`**

最后命令：

```bash
make check > /tmp/rdp09-r1-review-baseline/check.log 2>&1
```

退出码 **0**。末尾输出原样：

```text
=========== 1517 passed, 143 skipped, 1 warning in 112.91s (0:01:52) ===========
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.zhmiDq0KYi/openapi.json → /tmp/tmp.zhmiDq0KYi/schema.d.ts [67ms]
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
   Start at  00:50:33
   Duration  6.71s (tests 47%, environment 35%, import 18%)
```

`git status --porcelain --untracked-files=all` 原样（包含上一轮保留的改动）：

```text
 M src/rdp/api/audit_schemas.py
 M src/rdp/api/job_schemas.py
 M src/rdp/api/jobs.py
 M src/rdp/audit/_validation.py
 M src/rdp/audit/records.py
 M src/rdp/infra/actors.py
 M src/rdp/infra/config.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_recovery.py
 M src/rdp/jobs/execution.py
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
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/testSupport.ts
 M src/web/src/router.tsx
 M tests/job_process_support.py
 M tests/jobs_api_support.py
 M tests/jobs_execution_support.py
 M tests/test_jobs_logs.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_records.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/api/scheduling_schemas.py
?? src/rdp/infra/db/migrations/pending/__init__.py
?? src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
?? src/rdp/jobs/gpu.py
?? src/rdp/jobs/maintenance.py
?? src/rdp/jobs/navigation.py
?? src/rdp/jobs/resource_examples.py
?? src/rdp/jobs/resources.py
?? src/rdp/jobs/schedule_records.py
?? src/rdp/jobs/schedules.py
?? src/rdp/jobs/scheduling.py
?? src/rdp/jobs/scheduling_models.py
?? src/rdp/jobs/scheduling_service.py
?? src/rdp/jobs/scheduling_types.py
?? src/web/src/api/scheduling.test.ts
?? src/web/src/api/scheduling.ts
?? src/web/src/jobs/Resources.test.tsx
?? src/web/src/scheduling/Pages.test.tsx
?? src/web/src/scheduling/Pages.tsx
?? src/web/src/scheduling/queries.ts
?? tests/jobs_scheduling_support.py
?? tests/test_jobs_gpu.py
?? tests/test_jobs_maintenance.py
?? tests/test_jobs_navigation.py
?? tests/test_jobs_schedules.py
?? tests/test_jobs_scheduling.py
?? tests/test_jobs_scheduling_api.py
?? tests/test_jobs_scheduling_config.py
?? tests/test_jobs_scheduling_migration.py
```

本轮临时快照、检查日志及 OpenAPI 临时目录已清理。

**3. 契约变更申请、依赖申请**

新增申请：**无**。未改受保护文件、未增加依赖、未联网、未调用真实 `nvidia-smi`。

本轮涉及的已合并公开 API，按原有签名 → 当前签名列出；`…` 表示原参数原序保留：

| 原有签名 | 当前签名 | 原因 |
|---|---|---|
| `run_worker(dependencies, stop, logging_settings)` | `run_worker(…, *, scheduling: WorkerScheduling)` | 调度配置必须显式注入。 |
| `configure_jobs(app, paths, registry)` | `configure_jobs(…, *, scheduling: SchedulingCatalog)` | Web 不隐式找配置或关闭调度。 |
| `claim_job(session, job_id, *, now, paths)` | `claim_job(…, gpu_index: int \| None)` | 无卡也须明确传 `None`。 |
| `ExecutorDependencies(engine, registry, paths, clock)` | `ExecutorDependencies(…, *, resources: WorkerResources \| None)` | 资源依赖必填。 |
| `ExecutionWork(record, mode, previous_progress)` | `ExecutionWork(…, *, claim: ResourceClaim \| None)` | 明确区分恢复准备与已领资源。 |
| `JobApiContext(account, service, paths)` | `JobApiContext(…, *, scheduling: SchedulingService \| None)` | 服务缺失必须显式表达。 |
| `ExecutionContext(原有七项)` | 增加必填关键字 `_navigation`、`gpu_index`、`maintenance`、`gpu_example_command`、`navigation_example_path` | 只提供类型所需能力，不暴露资源池或配置。 |

`next_queued_job(session)` 已恢复原签名；`ExecutionSignals` 删除上一稿新增的 `publisher`，恢复原有三项构造。

未合并骨架的同步调整：

- `verify_gpu(..., *, output_path)` → `verify_gpu(..., *, log: JobLog | None)`。
- `ResourcePool(settings)` → `ResourcePool(settings, *, available_gpus)`。
- `Scheduler` 构造显式接收已经准备完成的 `recovered`。
- `WorkerScheduling.nvidia_smi` 改为 `Path | None`。
- 两个示例路径改为 `/api/jobs/example/gpu`、`/api/jobs/example/navigation`。
- 为坏卡展示增加隔离的 `worker_gpu_checks` 声明；`0005` 仍在 `pending/`。
- 系统身份约束改为单向，不再拒绝有编号的同名账号或其历史记录。

**4. 拿不准、需要评审决定的地方**

无新增待决事项。负责人三项决定及 14 项评审意见均已落实到契约和跳过测试；本轮无剩余修订项。

孤儿外部进程仍交第 11 张 systemd 处理。功能实现和迁移激活继续等待骨架审核通过。