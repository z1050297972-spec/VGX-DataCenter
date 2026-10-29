**1. 改动清单**

- `scripts/setup.sh`：完成工具引导、配置问答与校验、部署编排、健康检查、前台监管和失败清理；完整帮助仅保留一份。
- `src/rdp/ops/setup_queries.py`：实现六个只读查询入口，复用平台配置、数据库版本和诊断规则。
- `tests/test_ops_setup_queries.py`：启用 19 项测试，补充 2 项回归测试。
- `tests/test_ops_setup_script.py`：启用 46 项测试，补充 4 项回归测试。
- `tests/setup_support.py`：新增临时 HOME、白名单 PATH、假命令、本地归档和有界 PTY/子进程测试设施。

未暂存、未提交；临时辅助脚本和检查日志已删除。

**2. `make check`**

本轮仅运行一次，退出码 0。pytest **2038 passed / 0 skipped**；Vitest **250 passed / 0 skipped**。

命令：

```bash
make check > /tmp/rdp-setup-make-check.log 2>&1
```

末尾输出原样：

```text
================= 2038 passed, 1 warning in 247.10s (0:04:07) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.PpFpkhyQib/openapi.json → /tmp/tmp.PpFpkhyQib/schema.d.ts [70.3ms]
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
   Start at  20:03:14
   Duration  7.66s (tests 49%, environment 30%, import 20%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M scripts/setup.sh
 M src/rdp/ops/setup_queries.py
 M tests/test_ops_setup_queries.py
 M tests/test_ops_setup_script.py
?? tests/setup_support.py
```

运行后：

```text
 M scripts/setup.sh
 M src/rdp/ops/setup_queries.py
 M tests/test_ops_setup_queries.py
 M tests/test_ops_setup_script.py
?? tests/setup_support.py
```

**3. 契约变更申请、依赖申请**

无。

已批准的公开签名、参数和 docstring 含义未改。新增私有助手及测试的行为说明。

帮助原文从注释迁入 `usage`，追加：

> 固定版本：Node 22.23.2；uv 0.13.5；pnpm 11.22.0。

数值引用顶部版本表。

**4. 拿不准的地方**

无待负责人决定事项，无剩余跳过测试。

归档清单复用 2 MiB 元数据上限。真实官方下载、发行包兼容性及真实主机部署，仍由执行线在验收 9 确认；本轮没有联网、安装或调用真实系统管理/硬件命令。

**5. 先红后绿**

以下红项最终均通过；“初绿”逐项注明原因。

`tests/test_ops_setup_queries.py`

- `test_validate_reuses_platform_config`：红，`NotImplementedError`。
- `test_validate_missing_is_not_defaults`：初绿，显式配置路径已复用 `load_config` 的错误处理。
- `test_validate_does_not_initialize`：初绿，配置读取本身无初始化副作用。
- `test_admin_missing_absent_present`：首次收集失败（辅助模块导入路径）；修正后红，`NotImplementedError`。
- `test_admin_database_errors`：首次收集失败（异常模块导入路径）；修正后红，悬空软链接被误判为缺库。
- `test_admin_read_only_no_secrets`：初绿，已有实现使用只读连接和存在性查询。
- `test_admin_snapshot_not_reservation`：初绿，查询无写入，首管理员事务仍执行约束检查。
- `test_mount_metadata_sources`：红，`NotImplementedError`。
- `test_mount_unavailable_reasons`：红，缺 UUID 导致 `TypeError`。
- `test_mount_invalid_snapshot`：红，非法快照产生 `TypeError`，未按契约拒绝。
- `test_mount_no_storage_access`：初绿，挂载转换已经是纯解析。
- `test_urls_listen_scope`：红，`NotImplementedError`。
- `test_urls_invalid_snapshot`：红，缺字段产生 `KeyError`。
- `test_urls_no_network`：初绿，地址映射不执行网络操作。
- `test_query_cli_json_contract`：红，`NotImplementedError`。
- `test_query_cli_exit_codes`：红，帮助抛出 `SystemExit`，没有返回退出码。
- `test_query_cli_bounded_reads`：初次误绿，未实现的模块入口提前退出；修正测试直达查询后红，FIFO 等待超时，再修复通过。
- `test_query_cli_no_business_actions`：初绿，入口仅执行只读查询。
- `test_query_main_argument_source`：红，`NotImplementedError`。
- `test_validate_rejects_nonregular_file`：红，配置 FIFO 导致子进程超时。
- `test_query_failure_preserves_safe_remediation`：红，诊断丢失输入路径。

`tests/test_ops_setup_script.py`

- `test_help_contract`：红，退出 78，没有帮助。
- `test_repository_from_script_location`：红，没有执行仓库定位。
- `test_tool_versions_single_source`：初绿，帮助已引用顶部版本表。
- `test_platform_and_base_tools`：红，不支持的平台没有按契约停止。
- `test_missing_tools_ask_individually`：红，uv/pnpm 尚未逐项询问。
- `test_tool_refusal_stops`：红，没有确认与拒绝处理。
- `test_yes_skips_confirmations`：初绿，已完成的确认分支均支持 `--yes`。
- `test_tools_user_paths_only`：初绿，工具发布已限定用户目录。
- `test_existing_tool_version_policy`：初绿，已有固定版本比较及复用逻辑。
- `test_node_checksum_manifest`：红，Node 尚未下载、校验和发布。
- `test_release_asset_digest`：红，release 资产尚未处理。
- `test_checksum_failure_no_partial_tool`：初绿，SHA256 校验已阻止后续发布。
- `test_archive_path_and_size_limits`：红，去掉顶层目录后的链接越界未被拒绝。
- `test_tool_publish_atomic`：初绿，用户入口保护及原子发布已实现。
- `test_download_proxy_and_budgets`：初绿，下载边界已保留代理并设置预算。
- `test_systemd_missing_or_bus_unavailable`：红，用户总线失败没有规定诊断。
- `test_linger_already_enabled`：红，尚未查询 linger。
- `test_linger_consent`：红，没有说明影响及征求同意。
- `test_linger_enable_failure`：初绿，失败分支已打印管理员命令。
- `test_no_systemd_skips_service_manager`：初绿，前台分支已绕过服务管理器。
- `test_config_source_and_no_overwrite`：红，没有调用配置校验。
- `test_noninteractive_missing_input`：红，缺少管理员交互条件检查。
- `test_validation_environment_matches_commit`：红，没有目标提交归档及隔离环境。
- `test_questionnaire_platform_validation`：红，问答流程退出 78。
- `test_plain_http_listen_prompt`：初绿，问答已包含默认值及明文 HTTP 提示。
- `test_config_validation_failure`：初绿，平台校验失败已阻止发布和安装。
- `test_config_publish_race`：初绿，原子硬链接发布已拒绝覆盖。
- `test_mount_uuid_and_read_only`：红，存储根选择尚未实现。
- `test_unsupported_mounts_not_selectable`：初绿，选择逻辑已拒绝不可选候选。
- `test_storage_write_permission_explicit`：红，明确授权后仍写成只读。
- `test_gpu_missing_and_existing_config`：红，已有配置要求 GPU 时未报告环境冲突。
- `test_gpu_query_failure`：红，新配置没有保存选中的 GPU。
- `test_install_argument_forwarding`：红，没有调用安装脚本。
- `test_install_failure_stops_setup`：初绿，安装失败边界已阻止后续步骤。
- `test_existing_administrator_skipped`：红，没有安装后的管理员检查及跳过提示。
- `test_administrator_interaction_and_audit`：红，没有调用建管理员入口。
- `test_skip_admin_and_no_password_transport`：红，没有输出延后创建命令。
- `test_installed_repeat_reports_only`：红，完整部署被一律拒绝。
- `test_partial_install_not_complete`：红，没有部分部署识别。
- `test_foreground_supervision`：红，前台启动分支退出 78。
- `test_service_start_failure_cleanup`：红，服务确认与清理尚未实现。
- `test_health_timeout_and_log_paths`：红，健康检查尚未实现。
- `test_access_addresses_from_interfaces`：红，地址输出尚未实现。
- `test_setup_concurrency_lock`：红，没有并发锁。
- `test_cleanup_and_retry_boundaries`：初绿，失败清理和已有部署检查已覆盖该场景。
- `test_fake_commands_and_temporary_home`：初绿，测试设施已完整隔离命令和 HOME。
- `test_retry_reuses_verified_tools`：红，重试重复下载后误报版本目录已存在。
- `test_foreground_child_failure_is_not_healthy`：红，worker 提前退出后仍报告部署健康。
- `test_rejects_release_metadata_and_redirect_tampering`：初绿，已有精确资产匹配和逐跳官方域检查。
- `test_foreground_interrupt_preserves_unrelated_process`：初绿，已有 INT 收尾且仅操作本次子进程。