**1. 改动清单**

契约骨架已完成。新增 48 个 Python 函数均仅抛 `NotImplementedError`；已有函数的可执行语句未改。改动留在工作区，未暂存、未提交。

每个文件一行：

```text
src/rdp/infra/actors.py：增加 SYSTEM_ACTOR，补充固定身份契约。
src/rdp/infra/config.py：增加 jobs 配置模型、范围及校验骨架。
src/rdp/infra/state.py：增加示例写锁文件路径属性。
src/rdp/infra/db/migrations/pending/__init__.py：声明隔离迁移目录。
src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py：升级、降级、身份约束及序列保留契约。
src/rdp/audit/_validation.py：补充系统操作人校验契约，保留现有函数体。
src/rdp/audit/records.py：补充操作日志接受系统身份的契约。
src/rdp/jobs/registry.py：增加并发上限、GPU 要求及生产登记契约。
src/rdp/jobs/types.py：增加等待原因、历史卡号和持锁展示字段。
src/rdp/jobs/models.py：调整提交人类型注解，维持活动 0004 元数据。
src/rdp/jobs/policy.py：移除全局并发常量，增加资源预算和容量常量。
src/rdp/jobs/records.py：扩展候选查询、领取、终态清空及恢复领卡契约。
src/rdp/jobs/service.py：增加系统定时提交入口及系统身份查询契约。
src/rdp/jobs/execution.py：扩展依赖、上下文、执行凭据及写锁入口。
src/rdp/jobs/processes.py：增加 GPU 参数和子进程环境隔离契约。
src/rdp/jobs/progress.py：增加资源补写、取消屏蔽及锁内等待契约。
src/rdp/jobs/worker.py：补充多线程调度和共同停止预算契约。
src/rdp/jobs/_loop.py：标明按作业管理监视对象的待实现位置。
src/rdp/jobs/_recovery.py：标明恢复时资源展示复位的待实现位置。
src/rdp/jobs/gpu.py：增加有超时、完整输出和诊断的核卡骨架。
src/rdp/jobs/resources.py：增加资源池、短锁发布和展示持久化骨架。
src/rdp/jobs/navigation.py：增加拿锁、核对、写入、释放的执行骨架。
src/rdp/jobs/resource_examples.py：增加占卡与写锁示例模型和执行契约。
src/rdp/jobs/maintenance.py：增加两个清除作业及现有清除服务适配契约。
src/rdp/jobs/scheduling_types.py：增加调度配置、凭据、每日提交和展示值对象。
src/rdp/jobs/scheduling_config.py：增加配置覆盖与登记表核对骨架。
src/rdp/jobs/scheduling_models.py：隔离声明资源列、身份约束和定时去重表。
src/rdp/jobs/schedule_records.py：增加定时提交记录读写骨架。
src/rdp/jobs/schedules.py：增加显式登记、夏令时、补跑和下次执行时间契约。
src/rdp/jobs/scheduling.py：增加调度装配、领取、扫描预算和定时提交骨架。
src/rdp/jobs/scheduling_service.py：增加数据库只读调度聚合骨架。
src/rdp/ops/worker.py：扩展资源配置注入、启动核卡和停止契约。
src/rdp/api/audit_schemas.py：补充系统身份的空编号和显示契约。
src/rdp/api/job_schemas.py：增加作业资源展示字段。
src/rdp/api/scheduling_schemas.py：增加调度响应模型。
src/rdp/api/jobs.py：扩展配置注入，增加调度查询及两个示例提交接口骨架。
src/web/src/api/openapi.json：通过 make api-types 重新生成。
src/web/src/api/schema.d.ts：通过 make api-types 重新生成。
src/web/src/api/scheduling.ts：增加调度与示例请求骨架。
src/web/src/api/scheduling.test.ts：增加请求、鉴权、取消和超时跳过测试。
src/web/src/scheduling/Pages.tsx：增加调度页、资源示例页骨架。
src/web/src/scheduling/queries.ts：增加账号感知轮询和提交 hook 骨架。
src/web/src/scheduling/search.ts：增加类型化页签参数校验骨架。
src/web/src/scheduling/Pages.test.tsx：增加真实 router、展示和提交跳过测试。
src/web/src/jobs/Pages.tsx：补充等待原因、GPU 和系统提交人的展示契约。
src/web/src/jobs/Resources.test.tsx：增加作业资源展示跳过测试。
src/web/src/jobs/testSupport.ts：补齐新增响应字段的测试数据。
src/web/src/accounts/Pages.tsx：补充所有登录账号可见的调度菜单契约。
src/web/src/router.tsx：补充调度及资源示例路由契约。
tests/test_jobs_migration.py：改为核对 pending 未进入活动迁移链，保留 0004 head 检查。
tests/test_jobs_gpu.py：增加假 nvidia-smi 脚本及 GPU 验收跳过测试。
tests/test_jobs_navigation.py：增加互斥、冲突、取消、停止和文件边界跳过测试。
tests/test_jobs_schedules.py：增加去重、补跑、夏令时和系统提交跳过测试。
tests/test_jobs_maintenance.py：增加保留边界、原子清除及摘要计数跳过测试。
tests/test_jobs_scheduling.py：增加并发、FIFO、恢复、资源释放和预算跳过测试。
tests/test_jobs_scheduling_api.py：增加真实接口鉴权、只读边界和展示跳过测试。
tests/test_jobs_scheduling_config.py：增加配置、声明及生产登记跳过测试。
tests/test_jobs_scheduling_migration.py：增加隔离、身份约束、序列保留和迁移跳过测试。
```

**2. `make check`**

最后一次命令：`make check`，退出码 **0**。

pytest 末尾原样：

```text
=========== 1517 passed, 127 skipped, 1 warning in 112.57s (0:01:52) ===========
```

检查链末尾原样：

```text
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.QrUpjHjPsX/openapi.json → /tmp/tmp.QrUpjHjPsX/schema.d.ts [68.3ms]
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
      Tests  205 passed | 24 skipped (229)
   Start at  22:21:01
   Duration  6.71s (tests 48%, environment 34%, import 16%, transform 1%)
```

`git status --porcelain --untracked-files=all` 原样：

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
 M tests/test_jobs_migration.py
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
?? src/rdp/jobs/scheduling_config.py
?? src/rdp/jobs/scheduling_models.py
?? src/rdp/jobs/scheduling_service.py
?? src/rdp/jobs/scheduling_types.py
?? src/web/src/api/scheduling.test.ts
?? src/web/src/api/scheduling.ts
?? src/web/src/jobs/Resources.test.tsx
?? src/web/src/scheduling/Pages.test.tsx
?? src/web/src/scheduling/Pages.tsx
?? src/web/src/scheduling/queries.ts
?? src/web/src/scheduling/search.ts
?? tests/test_jobs_gpu.py
?? tests/test_jobs_maintenance.py
?? tests/test_jobs_navigation.py
?? tests/test_jobs_schedules.py
?? tests/test_jobs_scheduling.py
?? tests/test_jobs_scheduling_api.py
?? tests/test_jobs_scheduling_config.py
?? tests/test_jobs_scheduling_migration.py
```

未安装依赖、未联网、未调用真实 `nvidia-smi`。没有自行遗留的试验文件，检查链临时目录已清理。

**3. 契约变更申请、依赖申请**

新增待批准的依赖或受保护文件申请：**无**。`pyproject.toml`、依赖表和 import-linter 均未修改。

已批准扩展已写入契约：系统身份、作业配置、示例路径、资源字段、提交人可空及对应接口显示。`0005` 的可空列与约束保持隔离，活动 `0004` 结构未变。

已有公开签名逐项如下；`…` 表示原参数按原顺序保留，返回类型不变：

| 原签名 | 新签名 | 原因 |
|---|---|---|
| `configure_jobs(app, paths, registry)` | `configure_jobs(…, *, scheduling: SchedulingCatalog \| None = None)` | Web 显式接收调度配置。 |
| `run_worker(dependencies, stop, logging_settings)` | `run_worker(…, *, scheduling: WorkerScheduling \| None = None)` | 注入资源、定时登记及核卡路径。 |
| `next_queued_job(session)` | `next_queued_job(session, *, after_job_id=0, excluded_types=frozenset())` | 有界扫描并跳过阻塞类型。 |
| `claim_job(session, job_id, *, now, paths)` | `claim_job(…, gpu_index: int \| None = None)` | 领取事务同时保存卡号。 |
| `run_external_process(command, reporter, log, clock)` | `run_external_process(…, *, gpu_index: int \| None = None)` | 框架统一设置子进程 GPU 环境。 |
| `JobDefinition(type_name, display_name, parameters_model, recovery_mode, execute)` | `JobDefinition(…, concurrency=1, requires_gpu=False)` | 声明每类资源要求。 |
| `ExecutionContext(job_id, parameters, mode, previous_progress, reporter, log, clock)` | `ExecutionContext(…, resources=None, gpu_index=None, maintenance=None)` | 注入共享写锁、卡号与清除能力。 |
| `ExecutionWork(record, mode, previous_progress)` | `ExecutionWork(…, claim: ResourceClaim \| None = None)` | 跟踪本次执行的资源归还责任。 |
| `ExecutorDependencies(engine, registry, paths, clock)` | `ExecutorDependencies(…, resources: WorkerResources \| None = None)` | 同实例共享资源对象。 |
| `ExecutionSignals(cancelled, stopping, monitor)` | `ExecutionSignals(…, publisher: ResourcePublisher \| None = None)` | 上报对象接入短锁资源发布。 |
| `JobRecord(原有字段)` | `JobRecord(…, gpu_index=None, wait_reason=None, holds_navigation_lock=False)` | 传递数据库展示副本。 |
| `JobApiContext(account, service, paths)` | `JobApiContext(…, scheduling: SchedulingService \| None = None)` | 请求接入只读调度服务。 |

模型字段另有两项增量：`PlatformConfig` 增加 `jobs`；`JobResponse` 增加三个资源展示字段。`StatePaths.navigation_example` 是新增属性，构造签名未改。

连带调整：

- 按“空编号当且仅当名字为系统”，账号提交与重新提交须拒绝保留名“系统”；迁移遇此类旧记录前置拒绝，不改历史。
- 原迁移测试从“整个 pending 目录不存在”改为“0005 不在活动迁移链”。
- 四处前端参数增加单条 `no-unused-vars` 豁免：保留公开参数，同时满足函数体只能抛未实现错误的要求。

**4. 拿不准、需要评审决定的地方**

以下选择已写入契约和跳过测试，供骨架评审：

- **夏令时**：不存在的分钟顺延到当天第一个有效分钟；重复分钟取第一次。当天补跑成功后不再按点重复提交。
- **预算与上限**：每类最大并发 32；核卡 5 秒；写锁每 50 毫秒检查、总等待最多 300 秒；占卡示例最多 600 秒、锁内暂停最多 10 秒；调度每轮共享 250 毫秒软预算。
- **示例新值**：追加 JSON 行的 `value` 固定为当前作业编号文本；损坏尾行拒绝继续追加，不自动修复。
- **GPU 演示**：`nvidia-smi` 使用 `-i` 展示所领卡；子进程隔离由假脚本核验实际环境变量，不把硬件列举输出当作 CUDA 可见设备数量的证明。
- **清除数量**：登记两个作业；操作日志与登录日志继续由第 7 张函数原子联合清除。
- **孤儿进程**：沿用第 8 张决定，交第 11 张 systemd `KillMode=control-group`，本票不启动清理。

本轮契约骨架没有剩余项；功能实现、页面接线和迁移激活留待契约获批后逐函数 TDD。