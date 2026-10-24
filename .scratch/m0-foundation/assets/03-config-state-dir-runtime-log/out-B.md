**1. 改动清单**

实现完成，改动留在工作区，未暂存、未提交。

- [config.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/config.py)：实现配置读取、路径展开、严格校验和安全错误转换。
- [state.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/state.py)：实现路径布局、0700目录创建及 P4 不可变宽权限清单。
- [logging.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/logging.py)：实现格式化、P2 容错、上下文、切分清理、uvicorn 接管及启动提示。
- [api/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/api/__init__.py)：接入请求编号中间件，覆盖框架500响应；删除骨架注释和未使用类豁免。
- [test_config.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_config.py)：实现24项配置测试。
- [test_state.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_state.py)：实现原17项测试，补1项 P4 范围及顺序测试。
- [test_logging.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_logging.py)：实现原58项测试，补5项时钟、P4及故障恢复测试。
- [test_web_app.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_web_app.py)：实现15项中间件测试，保留既有20项测试。
- [conftest.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/conftest.py)：恢复测试修改的全局 logging 状态，关闭新增 handler。

未修改依赖或检查配置，未安装、未联网；临时 TDD 辅助文件及缓存已删除。

**2. `make check`**

最后一次命令：

```text
make check
```

十一项全部通过：**221 passed，0 skipped**。唯一 warning 是基线已有的 TestClient/httpx 弃用提示。

末尾输出原文：

```text
======================== 221 passed, 1 warning in 4.91s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.pHXS0ZrAK7/openapi.json → /tmp/tmp.pHXS0ZrAK7/schema.d.ts [11.8ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/web


 Test Files  6 passed (6)
      Tests  19 passed (19)
   Start at  19:46:23
   Duration  1.04s (environment 42%, tests 29%, import 28%, transform 1%)
```

运行前，`git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/__init__.py
 M src/rdp/infra/config.py
 M src/rdp/infra/logging.py
 M src/rdp/infra/state.py
 M tests/test_config.py
 M tests/test_logging.py
 M tests/test_state.py
 M tests/test_web_app.py
?? tests/conftest.py
```

运行后，同一命令输出：

```text
 M src/rdp/api/__init__.py
 M src/rdp/infra/config.py
 M src/rdp/infra/logging.py
 M src/rdp/infra/state.py
 M tests/test_config.py
 M tests/test_logging.py
 M tests/test_state.py
 M tests/test_web_app.py
?? tests/conftest.py
```

**3. 契约变更申请、依赖申请**

无。对照 `cb86a80` 检查，既有函数契约仅修改了获批的 `RuntimeFormatter.format` 和 `initialize_state`。

P2 的文档修改：

- `RuntimeFormatter.format.Args`：把“值仅为……”改为“值推荐为……，不规范字段按 Returns 容错”；保留敏感内容禁止项。
- `Returns`：非标量先 `str()`；失败用 `<无法字符串化>`。非有限浮点用带引号的字符串。
- `Returns`：非法键加 JSON 引号；用户提供的保留键丢弃；非映射输出为 `fields=<字符串化的值>`；映射遍历失败输出 `fields="<无法读取字段>"`。
- `Raises`：删除字段内容导致的 `ValueError`，仅保留无效时钟/时区的 `ValueError`，说明配置函数预检、独立格式化时仍检查。

P4 的文档修改：

- `initialize_state` 返回类型改为 `tuple[DirectoryPermissionWarning, ...]`。
- `Returns`：改为按 root、logs、作业目录顺序返回既有宽权限目录快照；排除祖先、新建目录，空清单合法。
- `Side Effects`：补充“第二次调用不写任何东西，仍返回当前宽权限清单”；明确不直接报警，由配置日志后的 `log_state_warnings` 报告。
- 新增 `DirectoryPermissionWarning.Attributes`，说明路径和权限位。
- 新增 `log_state_warnings` 六项契约，明确启动顺序、WARNING 内容、空清单行为及不重新读取或修改目录。

**4. 取舍与评审关注点**

- P2 保留无效时钟/时区的异常：这是注入配置错误；字段容错不会掩盖它。
- P4 采用建议的“先收集、后报告”。权限警告即使配置为 ERROR 也会落盘，通过发送单条 WARNING 实现，不修改全局阈值。
- 本地时区读取 `/etc/localtime`，未修改系统时区，也不采用不一致的 `/etc/timezone`。
- 切分子类复用标准库的写入、锁及文件流；为避免父构造函数读取真实时钟/mtime，直接初始化文件基类，再设置注入时钟的日界。代码有说明，测试验证初始化不读取系统时钟。
- 已补故障恢复：归档后清理失败，下一条可继续完成清理并恢复写入；旧 handler 关闭失败不破坏新配置。
- `logging.raiseExceptions=False` 的代价仍存在：运行期日志写失败可能丢记录且没有 stderr 提示，已按评审要求注明。
- 两条 `reportUnusedClass` 豁免已删除；保留源码 S104，并在默认地址测试中使用同一条有理由的局部豁免。

**5. 先红后绿**

本次120项测试均有单独首次运行记录：**48项首次失败，72项首次即通过**。以下“红→绿”均已修复；“首绿”后说明已有覆盖来源。

`tests/test_config.py`：

| 测试 | 首次结果及原因 |
|---|---|
| `test_state_dir_validator_valid` | 红→绿：路径校验器尚未实现。 |
| `test_state_dir_validator_invalid` | 红→绿：未拒绝非法路径。 |
| `test_missing_default_file` | 红→绿：配置读取尚未实现。 |
| `test_explicit_config` | 红→绿：未使用指定文件。 |
| `test_empty_environment_value` | 首绿：读取实现已将空值作为缺省位置。 |
| `test_only_one_environment_variable` | 首绿：实现仅读取 RDP_CONFIG。 |
| `test_missing_explicit_file` | 首绿：读取实现已保留显式文件缺失异常。 |
| `test_empty_and_partial_file` | 首绿：读取与模型默认值已覆盖。 |
| `test_strict_types` | 红→绿：原校验异常缺少配置文件来源。 |
| `test_unknown_fields` | 首绿：模型拒绝未知字段，错误转换已隐藏其值。 |
| `test_port_boundaries` | 首绿：获批模型已有端口范围约束。 |
| `test_host_constraints` | 首绿：获批模型已有字符串约束。 |
| `test_log_level_options` | 首绿：获批模型已有 Literal 约束。 |
| `test_retention_boundaries` | 首绿：获批模型已有严格类型和范围约束。 |
| `test_immutable_nested_models` | 首绿：模型和返回数据类已冻结。 |
| `test_expand_home_paths` | 红→绿：尚未展开注入的 home。 |
| `test_reject_invalid_paths` | 红→绿：home 错误缺少来源，配置位置未预检。 |
| `test_toml_syntax_error` | 红→绿：解析异常缺少文件及文档项信息。 |
| `test_invalid_utf8` | 红→绿：编码异常未转换。 |
| `test_configuration_read_errors` | 首绿：读取实现已保留文件系统异常。 |
| `test_validation_error_translation` | 首绿：严格类型测试已驱动逐项转换。 |
| `test_sensitive_error_values` | 首绿：白名单回显及模型隐藏输入已覆盖。 |
| `test_load_read_only` | 首绿：读取实现没有写入副作用。 |
| `test_snapshot_requires_reload` | 首绿：每次调用创建独立配置对象。 |

`tests/test_state.py`：

| 测试 | 首次结果及原因 |
|---|---|
| `test_complete_layout` | 红→绿：路径计算尚未实现。 |
| `test_empty_job_types` | 首绿：元组构造自然支持空清单。 |
| `test_immutable_layout` | 首绿：冻结对象与元组快照已覆盖。 |
| `test_invalid_job_names` | 红→绿：尚未校验名称。 |
| `test_duplicate_job_names` | 红→绿：尚未拒绝重复名称。 |
| `test_layout_has_no_io` | 首绿：路径计算仅操作显式输入。 |
| `test_initialize_all_directories` | 红→绿：初始化尚未实现。 |
| `test_restrictive_umask` | 首绿：新建目录显式 chmod 已覆盖。 |
| `test_existing_permissions_unchanged` | 红→绿：尚未返回宽权限清单。 |
| `test_partial_existing_layout` | 首绿：逐层补建逻辑已覆盖。 |
| `test_file_blocks_directory` | 红→绿：普通文件被误认为已存在目录。 |
| `test_symlink_directory_rejected` | 红→绿：尚未拒绝软链接。 |
| `test_unwritable_directory` | 红→绿：尚未检查可写、可搜索权限。 |
| `test_create_permission_failure` | 首绿：创建和 chmod 异常已直接保留。 |
| `test_other_filesystem_failure` | 首绿：检查和创建异常已直接保留。 |
| `test_failure_retains_created_directories` | 首绿：逐层创建无删除或回滚操作。 |
| `test_existing_layout_checked_without_writes` | 首绿：已有目录分支仅检查。 |
| `test_permission_warning_scope_and_order` | 首绿：P4 收集逻辑已按目标目录顺序工作。 |

`tests/test_logging.py`：

| 测试 | 首次结果及原因 |
|---|---|
| `test_formatter_construction` | 红→绿：构造函数尚未实现。 |
| `test_exact_line_format` | 红→绿：格式化尚未实现。 |
| `test_milliseconds_truncated` | 首绿：毫秒 ISO 格式化已覆盖截断和换日。 |
| `test_no_extra_fields` | 首绿：空字段和尾部空格处理已覆盖。 |
| `test_field_order_and_context` | 红→绿：尚未追加上下文编号。 |
| `test_quoted_field_values` | 首绿：JSON 转义已覆盖。 |
| `test_scalar_field_values` | 红→绿：安全字符串被多加引号。 |
| `test_multiline_diagnostics` | 红→绿：未规范换行和缩进。 |
| `test_exception_and_stack_details` | 红→绿：未输出异常链和调用栈。 |
| `test_invalid_fields` | 红→绿：非标量导致 JSON 格式化异常。 |
| `test_invalid_time_source` | 红→绿：naive 时刻被隐式解释成本地时间。 |
| `test_format_message_type_error` | 首绿：标准 getMessage 已保留类型错误。 |
| `test_format_time_overflow` | 首绿：标准时间换算已保留溢出错误。 |
| `test_record_snapshot` | 红→绿：重复格式化重新取了时间和上下文。 |
| `test_format_no_output` | 首绿：纯格式化及成功后发布快照已覆盖。 |
| `test_bind_job_context` | 红→绿：上下文管理器尚未实现。 |
| `test_bind_request_context` | 首绿：成对绑定与恢复已覆盖请求编号。 |
| `test_nested_context` | 首绿：token 恢复机制已支持嵌套。 |
| `test_invalid_context_identifiers` | 红→绿：未校验编号。 |
| `test_context_validation_atomic` | 首绿：两项校验均在绑定前完成。 |
| `test_context_exception_restore` | 首绿：finally 已覆盖异常恢复。 |
| `test_context_cancel_restore` | 首绿：finally 已覆盖取消恢复。 |
| `test_concurrent_context_isolation` | 首绿：contextvars 提供任务隔离。 |
| `test_child_context_inheritance` | 首绿：沿用标准 contextvars 继承语义。 |
| `test_web_file_only` | 红→绿：日志配置尚未实现。 |
| `test_worker_file_only` | 首绿：文件名已由 process 决定。 |
| `test_stderr_disabled` | 红→绿：日志自身失败仍向 stderr 输出。 |
| `test_stderr_enabled` | 红→绿：尚未安装 stderr handler。 |
| `test_level_filtering` | 首绿：配置日志阈值已覆盖。 |
| `test_uvicorn_loggers` | 红→绿：尚未接管 uvicorn logger。 |
| `test_uvicorn_access_disabled` | 红→绿：访问日志仍传播到文件。 |
| `test_repeat_configuration` | 红→绿：旧文件 handler 未关闭。 |
| `test_reconfigure_destination` | 首绿：替换输出和阈值已覆盖。 |
| `test_unrelated_loggers_unchanged` | 首绿：实现只修改指定 logger。 |
| `test_invalid_logging_settings` | 红→绿：未校验进程名和绝对路径。 |
| `test_missing_log_directory` | 首绿：文件打开已保留目录缺失异常。 |
| `test_log_directory_is_file` | 首绿：文件打开已保留非目录异常。 |
| `test_logging_setup_io_failure` | 首绿：新文件在发布配置前打开。 |
| `test_failed_setup_leaves_empty_file` | 首绿：原用例覆盖早期初始化失败；随后加强为文件打开后的失败，发现新 handler 未关闭，修复后通过。 |
| `test_midnight_rollover` | 红→绿：尚未实现切分。 |
| `test_retention_calendar_boundary` | 红→绿：尚未清理过期归档。 |
| `test_retention_ignores_foreign_files` | 红→绿：清理误选目录，导致后续写入中断。 |
| `test_idle_days_no_empty_archives` | 首绿：按记录触发切分及日历清理已覆盖。 |
| `test_startup_expiry_cleanup` | 红→绿：启动首条日志未清理旧归档。 |
| `test_dst_calendar_midnight` | 首绿：下一当地零点的计算已支持夏令时。 |
| `test_clock_rollback` | 首绿：固定未来切分边界已避免重复归档。 |
| `test_timezone_change` | 红→绿：更换时区仍触发旧边界。 |
| `test_archive_collision` | 首绿：保留期边界测试已驱动同名归档追加。 |
| `test_runtime_write_failure` | 首绿：标准 handleError 和后续切分重试已覆盖。 |
| `test_handler_reuses_standard_library` | 首绿：已复用标准 handler，初始化使用注入时钟。 |
| `test_handler_rollover_decision` | 首绿：切分判断已独立于 record.created。 |
| `test_handler_deletion_candidates` | 首绿：日期筛选和排序已实现。 |
| `test_default_configuration_notice` | 红→绿：启动提示尚未实现。 |
| `test_explicit_configuration_no_notice` | 首绿：used_defaults 条件已覆盖。 |
| `test_default_notice_threshold` | 首绿：INFO 提示遵循日志阈值。 |
| `test_default_notice_no_global_deduplication` | 首绿：提示函数无全局去重或重读配置。 |
| `test_default_timezone_read_failure` | 红→绿：默认时区适配器尚未实现。 |
| `test_configure_time_overflow` | 首绿：时间预检及打开文件前计算日界已覆盖。 |
| `test_default_clock_is_utc` | 红→绿：默认时钟适配器尚未实现。 |
| `test_state_permission_warning_after_logging` | 红→绿：P4 启动警告函数尚未实现。 |
| `test_private_state_directories_have_no_warning` | 首绿：空清单不记录，报告函数不重读目录。 |
| `test_rollover_cleanup_failure_recovers` | 红→绿：归档后清理失败导致后续反复读取缺失活动文件。 |
| `test_old_handler_close_failure_keeps_new_output` | 红→绿：旧 handler 关闭异常中断新配置发布。 |

`tests/test_web_app.py` 本票15项：

| 测试 | 首次结果及原因 |
|---|---|
| `test_request_middleware_construction` | 红→绿：中间件构造尚未实现。 |
| `test_response_request_id` | 红→绿：应用未接入中间件，响应缺少编号。 |
| `test_client_request_id_ignored` | 首绿：每次服务端新生成编号已覆盖。 |
| `test_response_and_log_id_match` | 首绿：请求绑定和日志上下文组合已覆盖。 |
| `test_concurrent_request_ids` | 首绿：请求局部变量与 contextvars 已提供隔离。 |
| `test_request_ids_on_all_response_statuses` | 首绿：包装完整框架栈已覆盖框架500等响应。 |
| `test_response_id_header_replaced` | 首绿：复制起始消息并替换同名头已覆盖。 |
| `test_health_has_no_access_log` | 首绿：中间件不记录访问日志，uvicorn.access 已禁用。 |
| `test_request_context_restored_after_failure` | 首绿：上下文管理器已覆盖下游及回调异常。 |
| `test_request_context_restored_after_cancel` | 首绿：上下文管理器已覆盖取消恢复。 |
| `test_streaming_and_background_context` | 首绿：绑定覆盖完整下游 ASGI 调用。 |
| `test_non_http_scope_passthrough` | 首绿：非 HTTP 分支直接透传。 |
| `test_failure_before_response_start` | 首绿：中间件不制造响应或吞异常。 |
| `test_request_wrapper_outside_error_stack` | 首绿：应用子类已包装父类完整中间件栈。 |
| `test_app_does_not_configure_logging` | 首绿：工厂只创建应用与中间件，不配置全局日志。 |