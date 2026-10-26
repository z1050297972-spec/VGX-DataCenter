10 条已处理。最终 `make check` 一次通过：**pytest 1517 passed、Vitest 205 passed，两套均 0 skipped**。临时探针已清理，未暂存、未提交。

**1. 改动清单**

本轮仅修改以下文件，工作区其余改动沿用前轮。

| 文件 | 改动 |
|---|---|
| `src/rdp/jobs/_process_io.py` | 空白 stderr 尾部使用固定说明，原始输出仍保留在日志中。 |
| `src/rdp/jobs/execution.py` | 恢复边界日志中的编号改为 `job_id=%s`。 |
| `src/rdp/jobs/_loop.py` | 取消警告及诊断写入失败日志改用 `job_id=%s`。 |
| `src/rdp/infra/exception_report.py` | 清理过程说法，补充第 8 张共享模块来历。 |
| `src/rdp/api/errors.py` | 删除转调函数和重复文档，显式重导出基础层函数，兼容原导入名。 |
| `src/web/src/jobs/Pages.tsx` | 百分比四舍五入为整数；日志框内换行；范围提示插值已有常量。 |
| `src/web/src/jobs/Pages.test.tsx` | 增加百分比文字、日志样式、作业页及账号管理页横幅测试。 |
| `tests/test_jobs_worker.py` | 覆盖两条空白 stderr 故障路径，并加强日志上下文断言。 |
| `tests/test_jobs_logs.py` | 增加恢复期间另一事务提交取消的测试。 |
| `tests/test_jobs_service.py` | 改为另一账号取消运行中作业，核对审计取消人。 |

**2. `make check`**

最后命令：

```text
make check
```

末尾输出原文：

```text
================= 1517 passed, 1 warning in 111.84s (0:01:51) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.0uETNGJeF5/openapi.json → /tmp/tmp.0uETNGJeF5/schema.d.ts [63ms]
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
      Tests  205 passed (205)
   Start at  10:23:41
   Duration  6.65s (tests 53%, environment 29%, import 17%)
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

**3. 契约变更／依赖申请及文档修改**

无新申请。

- `JobDetailPage` TSDoc 补充：“已知总数进度条（百分比四舍五入为整数）”。
- `OutputReader.tail_text()` docstring 改为：“返回有界诊断尾部；纯空白用固定说明，完整原始输出仍保留在日志文件。”
- `infra.exception_report` 模块补充：“第8张约定jobs与api共用此格式化入口，基础层不依赖Web入口。”
- 格式化函数删除“D2 不再替换…”、“B2：…”措辞，直接描述保留异常消息、源码行及增量截断行为。
- `api.errors` 删除重复转调函数；原导出名显式重导出基础函数，并注明“契约以 `rdp.infra.exception_report.format_exception_report` 为准”。原导出名称及签名兼容。
- `test_cancel_running` docstring 补充另一账号取消及审计操作人要求。

**4. 拿不准的地方**

无。百分比采用整数四舍五入；日志采用框内折行。第 4–6 条通过隔离副本上的变异验证，工作目录中的正确业务实现未被变异污染。

**5. 先红后绿**

| 测试 | 首次结果 |
|---|---|
| `test_whitespace_stderr_nonzero_stays_external` | 红：真实工具空白 stderr 导致 `DiagnosticObject` 校验失败，未得到 `ExternalError`。 |
| `test_whitespace_stderr_unreaped_stays_external` | 红：回收超时路径同样被诊断校验改成程序缺陷。 |
| 评审2：8/30进度显示整数27% | 红：页面没有 `27%`，仍显示长小数。 |
| 评审3：日志长行在框内换行 | 红：`whiteSpace` 样式为空。 |
| `test_recovery_cancel_committed_before_resume` | 隔离变异红：只有 `resume` 段，缺少 `cancel` 段；正常实现通过。 |
| `test_cancel_running` | 隔离变异红：审计操作人错误地为提交人 1，而非取消人 2；正常实现通过。 |
| 评审6：作业页横幅 | 隔离移除横幅后红：页面缺少离线提示；正常实现通过。 |
| 评审6：账号管理页横幅 | 首跑选择器误把卡片标题当 heading；修正后，隔离移除横幅确实导致缺少离线提示，正常实现通过。 |
| `test_recovery_record_corrupt` | 红：日志缺少 `job_id=71`。 |
| `test_recovery_log_failure` | 红：隔离终态日志缺少 `job_id=71`。 |
| `test_cancel_stall_warning` | 红：取消警告仍是“作业 71”，缺少规范化上下文。 |

以上最终均通过。第 7–9 条的文档、转调及常量整理由既有异常报告测试、表单测试和静态检查回归验证。