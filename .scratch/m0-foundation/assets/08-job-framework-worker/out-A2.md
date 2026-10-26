**1. 改动清单**

契约骨架已留在工作区，未暂存、未提交。新增后端 60 个函数均仅含 `raise NotImplementedError`；新增测试按要求跳过。临时检查日志已删除。

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | 仅调整 jobs → accounts/audit 的 import-linter 方向及理由。 |
| `src/rdp/jobs/policy.py` | 周期、容量、退出码和等待预算。 |
| `src/rdp/jobs/types.py` | 状态、恢复、进度、记录、摘要和心跳类型。 |
| `src/rdp/jobs/errors.py` | 输入、查无记录及协作停止异常。 |
| `src/rdp/jobs/registry.py` | 显式类型登记和生产登记表契约。 |
| `src/rdp/jobs/models.py` | 隔离的抽象作业表、心跳表声明。 |
| `src/rdp/jobs/records.py` | 唯一状态转换、条件领取和快照持久化契约。 |
| `src/rdp/jobs/service.py` | 提交、取消、重提、查询与审计事务契约。 |
| `src/rdp/jobs/progress.py` | 内存最新值、单调节流、诊断及可打断等待。 |
| `src/rdp/jobs/logs.py` | 日志命名、追加、中断段、摘要和有界尾读。 |
| `src/rdp/jobs/processes.py` | 完整输出捕获、进程组 TERM/KILL 和回收契约。 |
| `src/rdp/jobs/execution.py` | 执行上下文、异常收口和三种恢复方式。 |
| `src/rdp/jobs/worker.py` | 单实例锁、心跳、串行主循环和停止契约。 |
| `src/rdp/jobs/example.py` | 数数参数与四种结果触发契约。 |
| `src/rdp/ops/worker.py` | 可注入停止信号的 worker 入口。 |
| `src/rdp/infra/db/migrations/pending/__init__.py` | 隔离迁移目录声明。 |
| `src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py` | 新表、审计 CHECK 重建、序列高水位及拒绝降级契约。 |
| `src/rdp/audit/types.py` | 增加作业操作、`job` 对象和明细白名单。 |
| `src/rdp/audit/job_contracts.py` | 作业审计对象与明细一致性校验契约。 |
| `src/rdp/audit/_validation.py` | 接入作业审计校验入口。 |
| `src/rdp/audit/_query.py` | 扩展历史对象类型。 |
| `src/rdp/api/audit_schemas.py` | 响应对象类型增加 `job`。 |
| `src/rdp/api/job_schemas.py` | 作业、示例、日志和心跳字段声明。 |
| `src/rdp/api/jobs.py` | 登录依赖、依赖装配和全部新接口契约。 |
| `src/rdp/api/__init__.py` | 登记作业及 worker 状态路由。 |
| `src/web/src/api/jobs.ts` | 账号感知作业客户端契约。 |
| `src/web/src/api/jobs.test.ts` | 传输、取消和原生 fetch 绑定回归清单。 |
| `src/web/src/api/openapi.json` | 重新生成 OpenAPI。 |
| `src/web/src/api/schema.d.ts` | 重新生成前端接口类型。 |
| `src/web/src/jobs/Pages.tsx` | 列表、详情、提交表单和离线横幅契约。 |
| `src/web/src/jobs/queries.ts` | 轮询、终态停止及 mutation 契约。 |
| `src/web/src/jobs/progress.ts` | 十秒样本、速度、剩余及已用时间契约。 |
| `src/web/src/jobs/search.ts` | 类型化 URL 筛选校验契约。 |
| `src/web/src/jobs/Pages.test.tsx` | 页面清单及真实内存 Router 测试结构。 |
| `src/web/src/router.tsx` | 增加三个作业页面路由。 |
| `src/web/src/accounts/Pages.tsx` | 所有登录账号菜单增加作业入口。 |
| `src/web/src/audit/Pages.tsx` | 表头改为“对象”，增加作业明细展示字段。 |
| `src/web/src/audit/search.ts` | 增加提交、取消作业中文标签。 |
| `tests/test_audit_migration.py` | 保留 0003 检查，改为明确验证 0004 不进入活动图。 |
| `tests/test_jobs_state.py` | 六条合法边、三十种非法转换和取消优先清单。 |
| `tests/test_jobs_registry.py` | 登记、参数、升级兼容和四种结果清单。 |
| `tests/test_jobs_service.py` | 审计原子性、竞争顺序、重提及历史身份清单。 |
| `tests/test_jobs_progress.py` | 节流、短锁、最终值和时间语义清单。 |
| `tests/test_jobs_logs.py` | 日志一致性、撞名、线程写入和尾读清单。 |
| `tests/test_jobs_worker.py` | 恢复优先、心跳、停止和资源边界清单。 |
| `tests/test_jobs_api.py` | 真实应用鉴权顺序及 HTTP 行为清单。 |
| `tests/test_jobs_migration.py` | 重建保留、序列高水位、空表及回滚清单。 |
| `tests/test_jobs_processes.py` | 真实 Popen、SIGKILL 恢复、锁继承、忽略 SIGTERM 的测试结构。 |
| `tests/job_process_support.py` | 临时数据库、握手和孤儿进程清理夹具契约。 |
| `tests/job_worker_process.py` | 真实 worker 子进程测试入口。 |

**2. `make check`**

最后运行命令，退出码 **0**：

```bash
make check > /tmp/rdp-m0-08-check.log 2>&1
```

末尾输出原文：

```text
=========== 1265 passed, 147 skipped, 1 warning in 75.97s (0:01:15) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.QMKzuzYtd5/openapi.json → /tmp/tmp.QMKzuzYtd5/schema.d.ts [62.2ms]
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
   Start at  04:30:04
   Duration  6.30s (tests 48%, environment 31%, import 20%, transform 1%)
```

```bash
git status --porcelain --untracked-files=all
```

```text
 M pyproject.toml
 M src/rdp/api/__init__.py
 M src/rdp/api/audit_schemas.py
 M src/rdp/audit/_query.py
 M src/rdp/audit/_validation.py
 M src/rdp/audit/types.py
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/audit/Pages.tsx
 M src/web/src/audit/search.ts
 M src/web/src/router.tsx
 M tests/test_audit_migration.py
?? src/rdp/api/job_schemas.py
?? src/rdp/api/jobs.py
?? src/rdp/audit/job_contracts.py
?? src/rdp/infra/db/migrations/pending/__init__.py
?? src/rdp/infra/db/migrations/pending/v0004_jobs_worker.py
?? src/rdp/jobs/errors.py
?? src/rdp/jobs/example.py
?? src/rdp/jobs/execution.py
?? src/rdp/jobs/logs.py
?? src/rdp/jobs/models.py
?? src/rdp/jobs/policy.py
?? src/rdp/jobs/processes.py
?? src/rdp/jobs/progress.py
?? src/rdp/jobs/records.py
?? src/rdp/jobs/registry.py
?? src/rdp/jobs/service.py
?? src/rdp/jobs/types.py
?? src/rdp/jobs/worker.py
?? src/rdp/ops/worker.py
?? src/web/src/api/jobs.test.ts
?? src/web/src/api/jobs.ts
?? src/web/src/jobs/Pages.test.tsx
?? src/web/src/jobs/Pages.tsx
?? src/web/src/jobs/progress.ts
?? src/web/src/jobs/queries.ts
?? src/web/src/jobs/search.ts
?? tests/job_process_support.py
?? tests/job_worker_process.py
?? tests/test_jobs_api.py
?? tests/test_jobs_logs.py
?? tests/test_jobs_migration.py
?? tests/test_jobs_processes.py
?? tests/test_jobs_progress.py
?? tests/test_jobs_registry.py
?? tests/test_jobs_service.py
?? tests/test_jobs_state.py
?? tests/test_jobs_worker.py
```

**3. 契约变更申请、依赖申请**

新增申请：**无**。已按你的批准扩展审计对象。

已合并代码的普通函数显式参数、返回签名没有修改。公开类型构造契约的扩展如下：

- `ObjectRef.kind: Literal["account", "audit_settings"]` → 增加 `"job"`，用于独立作业对象。
- `ObjectResponse.kind` 同上，供接口和前端识别作业对象。
- `AuditValues(原字段…)` → 增加可选 `job_id / job_type / job_state / resubmitted_from`，默认均为 `None`，用于批准的明细白名单。
- `createAppRouter(options)` 参数不变；推断返回的路由类型增加 `/jobs`、`/jobs/new`、`/jobs/$jobId`。

**4. 拿不准、需要评审决定的地方**

- **线程停止限制**：采用每个不可打断步骤至多 1 秒、总停止预算 30 秒的协作契约。Python 无法安全强杀失约线程；这种程序缺陷的进程级处理策略仍需评审。
- **恢复快照**：采用提交时保存的恢复方式，避免升级改变声明后意外自动执行旧作业。累计耗时保留已保存的执行片段、不含停机时间；重跑清零业务计数。
- **日志与数据库**：终态先提交数据库，再写同一冻结摘要。文件写失败时保留终态并报告 ERROR，不声称两者具有原子事务。
- **命名与输出**：日志文件名采用 UTC，撞名加作业编号；显示名上限 40 码点，审计对象名“显示名 #编号”最多 61 码点。超长无换行工具输出分段标记续行，内容不丢弃。
- **展示调整**：操作日志表头已由“对象账号”改为“对象”；对象账号筛选仍只匹配账号。
- **实现阶段接线**：新模型、`0004` 和既有审计 CHECK 尚未激活；`WorkerStatusBanner` 保留完整组件、hook 和集成测试契约，实际挂载到 `AccountLayout` 留待实现。新增测试包括真实进程场景，本轮均未执行。