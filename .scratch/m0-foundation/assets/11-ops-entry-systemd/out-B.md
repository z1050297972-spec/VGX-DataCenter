**1. 本轮改动清单**

已完成剩余脚本，移除 `exit 78`，此前完成的文件未改动。

- [scripts/install.sh](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/scripts/install.sh)：实现安装、帮助、原子发布、单元转义和失败清理。
- [scripts/upgrade.sh](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/scripts/upgrade.sh)：实现双重作业检查、停机确认、配置继承、升级及失败处理。
- [tests/test_ops_deploy_scripts.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/tests/test_ops_deploy_scripts.py)：启用全部 22 项，增加参数化故障场景及两项补充测试。
- [tests/deploy_support.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/tests/deploy_support.py)：新增临时 HOME、假命令及调用记录夹具。

未暂存、未提交；本轮临时文件已清理。

**2. `make check`**

本轮只运行一次，退出码 **0**：

```bash
make check > /tmp/rdp-deploy-check.vl1aqV/check.log 2>&1
```

结果：**pytest 1946 passed / 0 skipped；Vitest 250 passed / 0 skipped**。

末尾输出原样：

```text
================= 1946 passed, 1 warning in 141.20s (0:02:21) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.3WOvceCu2k/openapi.json → /tmp/tmp.3WOvceCu2k/schema.d.ts [70.1ms]
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
   Start at  11:00:56
   Duration  7.26s (tests 49%, environment 29%, import 21%)
```

运行前 `git status --porcelain --untracked-files=all`，包含前轮留存改动：

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

**3. 契约变更申请、依赖申请**

均为 **无**。

原有 docstring/TSDoc 未改。脚本注释补充了共享逻辑、转义、错误传播及清理理由；帮助输出补充失败后的人工处理步骤。

**4. 需要评审决定的地方**

无待决申请。采用保守处理：只解析本脚本生成的单条 `Environment="RDP_CONFIG=..."`；遇到 `EnvironmentFile`、配置冲突或无法解析的转义时拒绝升级。

本轮只在临时目录配假命令运行脚本，未执行真实安装、升级或 systemd 操作。

**5. 本轮先红后绿**

以下均最终通过；参数化场景合并在同一测试行。

| 测试 | 首次运行结果 |
|---|---|
| `test_script_help` | 红：返回 78，没有帮助输出。 |
| `test_install_order` | 红：没有执行安装步骤，调用记录为空。 |
| `test_install_defaults` | 红：uv 仍继承开发环境的 `VIRTUAL_ENV`。 |
| `test_install_custom_paths` | 红：单元中的百分号、引号和反斜线未转义。 |
| `test_install_existing_directory` | 红：已有目录仍被当作安装成功。 |
| `test_install_port_busy` | 红：虽已停止，但诊断缺少配置路径和 `web.port`。 |
| `test_install_build_failure` | 初绿：前项实现的 `set -e`、阶段报告和临时文件清理已覆盖三种构建失败。 |
| `test_install_no_systemd` | 红：仍调用 systemctl。 |
| `test_units_only_owned` | 初绿：单元写入已经限定两个明确文件名。 |
| `test_upgrade_active` | 红：升级未检查作业，直接返回成功。 |
| `test_upgrade_query_failure` | 初绿：前项已拒绝所有非零查询结果。 |
| `test_upgrade_confirmation` | 红：拒绝或 EOF 仍返回成功，没有确认流程。 |
| `test_upgrade_order` | 红：缺少停机、更新、迁移和启动步骤。 |
| `test_upgrade_race` | 初绿：顺序测试推动的实现已包含停机后二次检查。 |
| `test_upgrade_stop_failure` | 初绿：已有停止错误传播和 inactive 核验。 |
| `test_upgrade_no_systemd` | 红：忽略前台停止检查，仍调用 systemctl。 |
| `test_upgrade_migrate_failure` | 初绿：复用构建失败边界，迁移失败也不会进入启动步骤。 |
| `test_upgrade_restart_failure` | 红：Web 启动失败后，先启动的 worker 仍为 active。 |
| `test_upgrade_version_changed` | 红：未调用新入口输出升级后的版本。 |
| `test_upgrade_dirty_refused` | 红：未拒绝源码改动、配置冲突和单元配置差异，也未继承配置；补充非法转义场景再次红，发现嵌套命令替换吞掉失败。 |
| `test_build_file_atomic` | 初绿：安装实现已使用临时文件、原子替换和失败清理；注入发布失败后旧文件完整保留。 |
| `test_fake_commands_isolation` | 初绿：夹具已把全部目标命令和 HOME 隔离到临时目录。 |
| `test_literal_dollar_in_exec_start`（补充） | 红：ExecStart 中的美元符号未转义。 |
| `test_install_partial_start_cleanup`（补充） | 初绿：升级失败测试推动的共享清理逻辑已覆盖安装部分启动失败。 |
| `test_shell_syntax`（回归） | 通过：两份脚本语法有效。 |
| `test_systemd_web_template`（回归） | 通过：沿用已验证模板。 |
| `test_systemd_worker_template`（回归） | 通过：沿用已验证模板。 |