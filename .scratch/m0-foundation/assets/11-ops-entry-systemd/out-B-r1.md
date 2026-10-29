**1. 改动清单**

仅处理本轮三条要求，改动留在工作区，未暂存、未提交。

- `src/rdp/ops/worker.py`：增加 INFO 开始记录（版本、PID、实例号）；结束记录包含退出码和含义，非零退出为 ERROR。
- `src/rdp/api/production.py`：增加 Web 启停日志；Protocol 方法体改为 `...`。
- `src/rdp/ops/cli.py`：补全六个子命令说明及 status 选项、退出码帮助。
- `tests/test_ops_worker_entry.py`：验证正常、锁冲突、失败及真实主循环停止后的日志。
- `tests/test_ops_web_lifecycle.py`：验证启动日志顺序、结束级别和退出码；区分异常诊断与生命周期摘要。
- `tests/test_ops_cli.py`：验证总帮助、子命令说明和 status 退出码。

**2. `make check`**

本轮运行一次，退出码 **0**；pytest **1953 passed / 0 skipped**，Vitest **250 passed / 0 skipped**。

```bash
make check > /tmp/rdp-r1-check.KbBcGX/check.log 2>&1
```

末尾原样输出：

```text
================= 1953 passed, 1 warning in 141.60s (0:02:21) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.jDKvTrPZIo/openapi.json → /tmp/tmp.jDKvTrPZIo/schema.d.ts [70.4ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  11:33:01
   Duration  7.14s (tests 49%, environment 29%, import 21%)
```

运行前 `git status --porcelain --untracked-files=all`（包含前轮留存改动）：

```text
 M scripts/install.sh
 M scripts/upgrade.sh
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/api/production.py
 M src/rdp/api/shutdown.py
 M src/rdp/api/version.py
 M src/rdp/cli.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0006_platform_version.py
 M src/rdp/infra/logging.py
 M src/rdp/infra/version.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/scheduling.py
 D src/rdp/jobs/version_models.py
 M src/rdp/jobs/versioning.py
 M src/rdp/ops/cli.py
 M src/rdp/ops/lifecycle.py
 M src/rdp/ops/runtime.py
 M src/rdp/ops/status.py
 M src/rdp/ops/worker.py
 M src/web/src/VersionFooter.test.tsx
 M src/web/src/VersionFooter.tsx
 M src/web/src/accounts/Pages.test.tsx
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/api/version.ts
 M src/web/src/usePlatformVersion.ts
 M tests/test_api_database.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_logging.py
 M tests/test_ops_cli.py
 M tests/test_ops_deploy_scripts.py
 M tests/test_ops_logging_startup.py
 M tests/test_ops_runtime.py
 M tests/test_ops_version.py
 M tests/test_ops_version_migration.py
 M tests/test_ops_web_lifecycle.py
 M tests/test_ops_worker_entry.py
?? src/rdp/infra/db/migrations/versions/v0006_platform_version.py
?? tests/deploy_support.py
?? tests/ops_support.py
```

运行后：

```text
 M scripts/install.sh
 M scripts/upgrade.sh
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/api/production.py
 M src/rdp/api/shutdown.py
 M src/rdp/api/version.py
 M src/rdp/cli.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0006_platform_version.py
 M src/rdp/infra/logging.py
 M src/rdp/infra/version.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/scheduling.py
 D src/rdp/jobs/version_models.py
 M src/rdp/jobs/versioning.py
 M src/rdp/ops/cli.py
 M src/rdp/ops/lifecycle.py
 M src/rdp/ops/runtime.py
 M src/rdp/ops/status.py
 M src/rdp/ops/worker.py
 M src/web/src/VersionFooter.test.tsx
 M src/web/src/VersionFooter.tsx
 M src/web/src/accounts/Pages.test.tsx
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/api/version.ts
 M src/web/src/usePlatformVersion.ts
 M tests/test_api_database.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_logging.py
 M tests/test_ops_cli.py
 M tests/test_ops_deploy_scripts.py
 M tests/test_ops_logging_startup.py
 M tests/test_ops_runtime.py
 M tests/test_ops_version.py
 M tests/test_ops_version_migration.py
 M tests/test_ops_web_lifecycle.py
 M tests/test_ops_worker_entry.py
?? src/rdp/infra/db/migrations/versions/v0006_platform_version.py
?? tests/deploy_support.py
?? tests/ops_support.py
```

本轮临时日志和遗留测试临时目录已清理。

**3. 契约补充/docstring 改动**

签名、类型和退出码行为未改，无依赖申请。

- `run_worker.Side Effects`：补充开始记录版本/PID/实例号，结束记录退出码及含义；正常 INFO、非零 ERROR，沿用同一实例号且不重复堆栈。
- `start_web.Side Effects`：补充运行器调用前记录版本，清理后记录退出码及对应级别。
- `test_runner_failure`：说明改为“原异常诊断只报一次，另记生命周期退出码”；断言分别验证两种记录。
- 无 TSDoc 改动。

**4. 拿不准的地方**

无。锁被占用（退出码 2）按非零退出记 ERROR，原锁冲突诊断保留；未改变日志格式或配置。

**5. 先红后绿**

| 测试 | 首次结果与最终结果 |
|---|---|
| `test_worker_lifecycle_logs`（3 场景） | 红：缺少开始、结束记录；实现后全绿。 |
| `test_web_lifecycle_logs`（2 场景） | 红：运行器调用前没有带版本的启动日志；实现后全绿。 |
| `test_command_help_descriptions` | 红：总帮助没有子命令说明；补全后绿。 |
| `test_worker_loop_exit_log` | 初绿：前项实现已覆盖主循环返回分支；确认真实心跳后停止也有结束日志。 |
| `test_runner_failure`（既有回归） | 红：原断言把新增结束摘要也算作重复异常；改为分别断言异常诊断、结束摘要各一条后绿。 |
| `test_drain_timeout`（补充断言） | 绿：超时结束正确记录 ERROR、`exit_code=1`。 |

相关回归共 **127 项通过**，随后完整检查通过。