**1. 第 1–15 条处理结果**

本轮仅修订契约、类型和跳过测试。核对的 66 个后端函数均仍为 `raise NotImplementedError`，未进入实现。

1. **进度补写**：增加共用 `flush_due` 和补写截止契约，覆盖 `report`、检查取消、长等待及外部进程轮询。说明了约 1 秒目标、短锁等待及连续跳过造成的延迟；补齐长等待测试和落库握手。
2. **停止超时保锁**：执行及输出线程全部为 daemon。超时一次 ERROR、返回失败；保留原始 fd 到进程退出，GC 不解锁。增加真实进程竞争测试。
3. **终态写库失败**：统一停止领取和心跳，有界收尾后返回 `WORKER_EXIT_FAILURE`，交 systemd 重启。
4. **领取崩溃窗口**：状态、开始时间、唯一日志路径同事务登记。文件缺失时恢复先写开头再写中断段；补了真实 SIGKILL 场景。
5. **SIGTERM 测试竞争**：先等工具 `ready` 完整行进入作业日志，再请求取消。
6. **取消事务**：在 `BEGIN IMMEDIATE` 内读取当前状态；worker 先领取时成功转为正在取消，保留条件更新和审计。
7. **提交顺序**：领取仅按 `job_id ASC`，列表仅按 `job_id DESC`；索引和回拨测试同步调整。
8. **恢复方式**：使用当前登记；历史或当前任一方为标记中断、或类型已删除，均中断。补齐组合测试。
9. **恢复上限与隔离**：增加 `recovery_count`，上限 3 次，第四次中断并说明原因。恢复准备中的单条故障尝试终态，仍失败则 ERROR 并跳过。
10. **取消无响应**：首次观察正在取消后，单调计时超过 60 秒，仅一次 WARNING 和作业日志诊断，不改状态或业务计数。
11. **续跑基线**：首报沿用旧累计值；同阶段进度及累计计数不得倒退。阶段前进可清阶段完成数，累计计数继续累加。
12. **孤儿工具**：明确第 11 张采用 `KillMode=control-group`、`TimeoutStopSec≥30秒`；测试夹具负责清理。
13. **异常清理**：测试改为嵌套 `try/finally`，等待超时也执行孤儿清理。不可回收进程抛 `ExternalError`，存活输出线程作为 daemon 登记遗留。
14. **预算归属**：从 `execute_job.Raises` 删除停止超时，统一由 `run_loop` 判定。
15. **账号公开接口**：确认 jobs 无账号私有模块导入；新增公开 `authorize_job_actor` 契约，支持调用者事务内重验身份。

**2. `make check`**

最后命令，退出码 **0**：

```bash
make check > /tmp/rdp-m0-08-revision-check.log 2>&1
```

末尾输出原文：

```text
=========== 1265 passed, 189 skipped, 1 warning in 75.65s (0:01:15) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.vzGIJgPuaW/openapi.json → /tmp/tmp.vzGIJgPuaW/schema.d.ts [62.9ms]
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
   Start at  05:05:28
   Duration  6.58s (tests 50%, environment 31%, import 19%)
```

```bash
git status --porcelain --untracked-files=all
```

```text
 M pyproject.toml
 M src/rdp/accounts/service.py
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

已运行 `make api-types`，未手改生成文件。临时检查日志已删除；未暂存、未提交。

**3. 申请**

契约变更申请：无。  
依赖申请：无。  
受保护文件申请：无。

**4. 需要评审决定的地方**

无额外待决项。上述行为目前仅形成契约与跳过测试，尚未通过实现验证。