**1. 改动清单**

交检查点：最后检查全绿，尚有部署脚本 22 项未实现。改动留在工作区，未暂存、未提交；本次临时文件已清理。

```text
src/rdp/api/__init__.py：登记版本接口。
src/rdp/api/errors.py：报错写入接入生命周期跟踪。
src/rdp/api/production.py：装配并运行 Web，排空报错后释放引擎。
src/rdp/api/shutdown.py：实现报错任务登记、取消和限时排空。
src/rdp/api/version.py：实现受认证保护的版本快照查询。
src/rdp/cli.py：绑定生产依赖，连接控制台与 Web 入口。
src/rdp/infra/db/migrations/pending/__init__.py：删除。
src/rdp/infra/db/migrations/pending/v0006_platform_version.py：移至活动目录。
src/rdp/infra/db/migrations/versions/v0006_platform_version.py：实现升级、安全降级和序列保留。
src/rdp/infra/logging.py：启动前按活动文件 mtime 补归档。
src/rdp/infra/version.py：实现部署定位、有界构建信息读取和版本校验。
src/rdp/jobs/_loop.py：未启动领取退回时恢复原执行版本。
src/rdp/jobs/_views.py：读取并校验执行版本。
src/rdp/jobs/models.py：把版本列及约束并入 JobRow。
src/rdp/jobs/scheduling.py：领取事务记录版本，保存退回所需旧版本。
src/rdp/jobs/version_models.py：删除独立列声明。
src/rdp/jobs/versioning.py：实现事务内执行版本写入。
src/rdp/ops/cli.py：实现参数解析、命令分派、维护和错误边界。
src/rdp/ops/lifecycle.py：实现 worker 装配、信号恢复及引擎清理。
src/rdp/ops/runtime.py：实现配置、日志、数据库、调度和存储资源装配。
src/rdp/ops/status.py：实现只读作业查询、锁探测和端口检查。
src/rdp/ops/worker.py：传递注入的日志时钟。
src/web/src/VersionFooter.test.tsx：实现版本链路七项测试。
src/web/src/VersionFooter.tsx：显示版本、加载及失败状态。
src/web/src/accounts/Pages.test.tsx：账号测试传输单独响应版本请求。
src/web/src/accounts/Pages.tsx：在完成认证的业务页面挂载页脚。
src/web/src/api/openapi.json：通过 make api-types 重新生成。
src/web/src/api/schema.d.ts：通过 make api-types 重新生成。
src/web/src/api/version.ts：实现有界请求和响应校验。
src/web/src/usePlatformVersion.ts：实现按客户端隔离的缓存及聚焦刷新。
tests/test_api_database.py：模拟后续迁移改为承接 0006。
tests/test_db_migration.py：更新当前版本、后续迁移和备份版本预期。
tests/test_jobs_migration.py：更新活动版本链及当前结构预期。
tests/test_jobs_scheduling_migration.py：保留 0005 历史断言，解除旧 head 假设。
tests/test_logging.py：更新已批准的启动补归档预期。
tests/test_ops_cli.py：实现十九项清单测试，补 Web 适配测试。
tests/test_ops_deploy_scripts.py：实现脚本语法及两个单元模板测试。
tests/test_ops_logging_startup.py：实现九项启动归档测试。
tests/test_ops_runtime.py：实现十四项资源装配测试。
tests/test_ops_version.py：实现十七项版本测试。
tests/test_ops_version_migration.py：实现七项活动迁移测试。
tests/test_ops_web_lifecycle.py：实现十二项清单测试，补报告集成测试。
tests/test_ops_worker_entry.py：实现十二项 worker 入口测试。
tests/ops_support.py：增加全部使用临时路径的运维测试夹具。
```

**2. `make check`**

最后一次命令：

```bash
make check > /tmp/rdp-b-check.tOV4mb/check-final.log 2>&1
```

退出码 **0**。末尾输出原样如下；Vitest 为 **250 passed、0 skipped**：

```text
=========== 1906 passed, 22 skipped, 1 warning in 130.33s (0:02:10) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.wbACTHxbOW/openapi.json → /tmp/tmp.wbACTHxbOW/schema.d.ts [70.8ms]
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
   Start at  10:00:48
   Duration  7.26s (tests 49%, environment 29%, import 21%, transform 1%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
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
?? tests/ops_support.py
```

运行后：

```text
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
?? tests/ops_support.py
```

**3. 契约变更申请、依赖申请**

均为 **无**。已批准的公开函数签名、类型和六项 docstring 未改变，TSDoc 未改变。

文档说明调整：

- `JobRow` 增加属性说明：“`platform_version: 最近实际领取版本，1-128 个码点；历史未知或从未领取为 NULL。`”
- `Scheduler` 增加属性说明：“`previous_version: 最近一次成功领取之前的执行版本；仅供主循环在启动线程前退回领取。`”
- 模块说明更新为当前活动迁移结构。
- 测试说明更新了当前 head、启动补归档、操作人“运维”；锁测试说明改为实际采用的“独立文件描述符”。
- 无新增依赖，无配置豁免调整；脚本语法测试增加一条 `S603` 豁免，注明固定 bash 仅解析固定脚本、HOME 为临时目录。

**4. 剩余工作、评审事项**

这是按时间限制交出的检查点，**不能作为安装部署完成的交付**。安装、升级脚本仍未实现，原有 `exit 78` 尚在；没有执行真实安装或升级。

以下 22 项保留跳过，均在 `tests/test_ops_deploy_scripts.py`：

```text
test_script_help
test_install_order
test_install_defaults
test_install_custom_paths
test_install_existing_directory
test_install_port_busy
test_install_build_failure
test_install_no_systemd
test_units_only_owned
test_upgrade_active
test_upgrade_query_failure
test_upgrade_confirmation
test_upgrade_order
test_upgrade_race
test_upgrade_stop_failure
test_upgrade_no_systemd
test_upgrade_migrate_failure
test_upgrade_restart_failure
test_upgrade_version_changed
test_upgrade_dirty_refused
test_build_file_atomic
test_fake_commands_isolation
```

请重点评审未启动领取的旧版本恢复，以及报错线程超时后保留引擎的生命周期。

执行偏差：`make check` 实际运行了 **3 次**，未满足“最后只跑一次”。第一次暴露 17 项旧迁移版本预期，第二次被一处格式问题阻断，第三次全绿。没有安装、联网或运行真实 systemctl/loginctl/nvidia-smi。

**5. 先红后绿记录**

以下覆盖全部轮次。`红` 表示首次有效运行失败，随后通过；`初绿` 逐项说明已有实现来源。测试自身写错导致的失败单独注明，不计作实现的有效红灯。上列 22 项尚未启用。

`tests/test_ops_version.py`

```text
test_layout_independent_of_cwd：红，deployment_layout 未实现。
test_invalid_layout：红，非法布局未拒绝；同时修正诊断断言位置。
test_version_format：红，版本读取未实现。
test_missing_build_info：红，缺失文件直接抛 FileNotFoundError。
test_metadata_missing：红，PackageNotFoundError 未转换。
test_build_info_invalid：红，坏 JSON 未转换成 InputError。
test_build_info_permission：红，PermissionError 未转换。
test_version_text_bounds：红，超长版本未拒绝。
test_api_version：红，真实应用返回 404。
test_api_authentication：初绿，复用现有统一认证与强制改密边界。
test_api_bad_configuration：红，重复装配未拒绝。
test_openapi_version_schema：初绿，前项登记路由时已声明响应模型和安全要求。
test_job_claim_version：红，领取后版本仍为 None。
test_job_recovery_version：初绿，新领取与恢复领取共用版本事务写入。
test_job_claim_rollback：红，线程未启动退回后仍保留新版本。
test_job_version_errors：红，非 running 作业未拒绝写版本。
test_job_resubmit_version：首次因测试把 HTTP 文本编号直接传领域接口而失败；修正后初绿，现有重新提交不复制执行版本。
```

`tests/test_ops_version_migration.py`

```text
test_active_head：红，活动 head 仍为 0005；替代原 pending 测试。
test_upgrade_empty_and_history：红，迁移 upgrade 未实现。
test_fresh_latest：初绿，前项实现的迁移链已支持空库。
test_constraints：初绿，冻结 DDL 已包含版本长度和原有约束。
test_sequence_preserved：红，downgrade 未实现。
test_downgrade_refuses_data_loss：红，有执行版本时仍允许降级。
test_migration_failure_atomic：初绿，复用既有迁移事务、备份及回滚边界。
```

`tests/test_ops_logging_startup.py`

```text
test_old_mtime：红，未生成旧日期归档。
test_today_mtime：初绿，补归档实现已排除当天文件。
test_future_mtime：初绿，补归档实现已排除未来日期。
test_missing_and_empty：初绿，同一归档路径已处理缺失和空文件。
test_timezone_boundary：初绿，mtime 和启动日期使用同一注入时区。
test_existing_archive：初绿，补归档实现已追加合并同名文件。
test_archive_failure：初绿，I/O 异常传播及原配置原子替换已覆盖。
test_retention_after_archive：初绿，复用既有首条日志过期清理。
test_reconfigure_same_day：初绿，复用既有 handler 替换与日期判断。
```

`src/web/src/VersionFooter.test.tsx`

```text
所有已登录业务页面显示相同平台版本：红，页面没有 footer；之后修正测试环境与响应夹具。
原样显示未知提交号：首次因未安装的 DOM matcher 失败；改用现有断言后初绿，组件原样显示字符串。
区分加载失败和合法未知版本：红，加载时为空文字。
未完成登录或改密时不请求版本：红，强制改密页发出版本请求。
缓存过期聚焦刷新且不同应用隔离：红，缓存有效期内重复请求。
版本请求超时取消与计时器清理：初绿，复用 boundedRequest 和 Query 取消信号。
拒绝不合法版本载荷并沿用统一错误边界：红，缺少 version 的响应被当作成功。
```

`tests/test_ops_runtime.py`

```text
test_assembly_order：红，prepare_service 未实现。
test_configuration_source：初绿，装配复用 load_config 和来源日志。
test_directory_failure：初绿，复用状态目录检查及权限警告。
test_registry_storage_validation：首次夹具 StorageUse 形状错误；修正后红，ValueError 未转为契约要求的 InputError。
test_scheduling_catalog：初绿，装配已使用共享调度目录构造规则。
test_storage_inspector：初绿，装配只绑定挂载读取回调。
test_worker_storage_checker：初绿，此前 worker 入口已传递检查器和版本。
test_version_snapshot：初绿，prepare_service 已保存启动快照。
test_cleanup_partial_failure：初绿，装配失败 finally 已释放引擎。
test_clock_invalid：红，非法时钟未在装配时拒绝。
test_gpu_path_found：红，命令定位未实现。
test_gpu_missing_or_relative：红，None 路径触发 TypeError。
test_gpu_empty：红，空卡列表仍调用 which。
test_gpu_lookup_faults：红，回调异常未转换。
```

`tests/test_ops_worker_entry.py`

```text
test_exit_codes：红，start_worker 未实现。
test_signals_stop：红，stop_signals 未实现。
test_signal_restore：初绿，信号上下文已包含正常与部分安装失败恢复。
test_signal_invalid_thread：初绿，信号上下文已检查主线程。
test_retained_lock：初绿，入口已按 lock_retained 保留引擎。
test_normal_cleanup：初绿，入口 finally 已释放可释放引擎。
test_scheduling_settings：初绿，入口已传共享 catalog、保留期及日志时钟。
test_logging_clock：红，run_worker 二次配置丢失注入时钟。
test_held_lock_refused：红，锁探测未实现。
test_free_and_missing_lock：红，缺失锁文件抛 FileNotFoundError。
test_probe_releases_lock：初绿，前项实现已及时解锁并关闭文件。
test_probe_errors：红，相对路径未拒绝。
```

`tests/test_ops_web_lifecycle.py`

```text
test_engine_passed：红，start_web 未实现。
test_configure_jobs_storage_version：初绿，前项已完成应用装配。
test_uvicorn_logging：初绿，运行器参数和统一日志配置已接通。
test_normal_dispose_order：红，TrackedReport 未实现。
test_late_report：初绿，任务状态机已区分 pending 与 running。
test_queued_report_tracked：初绿，构造时登记已覆盖排队任务。
test_report_submit_failure：初绿，cancel_if_pending 已实现幂等清理。
test_drain_timeout：红，Web 未等待登记任务，错误返回 0。
test_drain_invalid_budget：初绿，排空函数已校验有限非负预算。
test_report_apps_isolated：初绿，登记集合按应用保存。
test_runner_failure：红，运行器异常直接传播，未清理。
test_defect_report_failure_is_complete：初绿，run 的 finally 已解除登记。
test_report_integration：红，真实请求报告尚未接入登记，提交时错误显示已排空。
```

`tests/test_ops_cli.py`

```text
test_help_without_environment：红，参数解析未实现。
test_invalid_arguments：初绿，argparse 声明已禁止缩写并设置必需和互斥参数。
test_main_argument_source：红，main 未实现。
test_console_entry_registration：初绿，契约提交已有 console script 与 sys.exit 包装。
test_version_output：红，run_cli 未实现。
test_service_version_gate：红，服务分派未实现。
test_no_stderr：初绿，复用 prepare_service 的日志配置。
test_foreground_stderr：初绿，复用同一前台日志配置。
test_migrate_dispatch：红，维护命令未实现。
test_accounts_require_current_database：初绿，维护入口已先检查数据库版本。
test_create_admin_dispatch：红，账号分派未实现。
test_reset_password_sessions：首次测试漏传 authenticate.audit；补齐后初绿，复用现有账号重置事务。
test_reset_password_audit：初绿，现有领域事务只追加一条“运维”日志。
test_account_input_failure：初绿，复用既有口令校验和账号约束。
test_account_interrupt：初绿，run_cli 已处理 EOF/Ctrl-C 为 130。
test_status_exit_codes：红，状态命令尚未分派。
test_status_does_not_initialize：初绿，状态分派已采用只读路径。
test_status_port：红，端口检查未实现。
test_boundary_error_once：初绿，CLI 已统一报告一次配置失败。
test_web_adapter：红，包顶层 run_web 未实现。
```

`tests/test_ops_deploy_scripts.py`

```text
test_shell_syntax：初绿，原脚本已具有合法 bash 语法；只运行 bash -n。
test_systemd_web_template：初绿，契约提交的模板已有要求的指令。
test_systemd_worker_template：初绿，契约提交的模板已有 control-group、45 秒及其他指令。
```

已有测试的回归调整：

```text
test_logging.py::test_startup_expiry_cleanup：先失败，旧预期要求继续保留活动文件内容；按已批准的补归档契约更新后通过。
test_jobs_scheduling_migration.py::test_upgrade_preserves：先失败，当前版本仍写死 0005；更新后通过。
test_jobs_scheduling_migration.py::test_downgrade_guard：先失败，回滚后的当前版本仍写死 0005；更新后通过。
test_api_database.py::test_configure_version：完整检查先失败，模拟迁移形成双 head；改为承接 0006 后通过。
test_jobs_migration.py::test_active_declarations：完整检查先失败，版本链预期缺少 0006；更新后通过。
test_jobs_migration.py::test_schema_v4：完整检查先失败，当前版本预期仍为 0005；更新后通过。
accounts/Pages.test.tsx“所有页面卸载清理请求/倒计时…”：先失败，新页脚请求进入账号通配替身；单独响应版本接口后通过。
```

`tests/test_db_migration.py` 首次完整检查中的以下失败均来自旧 head、模拟后续迁移或备份版本预期；更新版本前提后最终全部通过：

```text
test_config：旧 head 预期。
test_config_default：旧 head 预期。
test_version_defect：模拟迁移接在旧 head 后。
test_migrate_new：新库当前版本预期过时。
test_migrate_existing：模拟迁移形成双 head。
test_backup_contents：模拟迁移及备份版本预期过时。
test_backup_before：模拟迁移形成双 head。
test_backup_filename：备份文件名前缀仍为 0005。
test_migrate_upgrade_failure：模拟迁移前提错误。
test_migrate_rollback_failure：模拟迁移前提错误。
test_env_connection：当前版本预期过时。
test_env_propagation：模拟迁移形成双 head。
test_installed_package：模拟迁移形成双 head。
```