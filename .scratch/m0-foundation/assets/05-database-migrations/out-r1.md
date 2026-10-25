**1. 第 1–13 条处理结果**

13 项已处理，改动留在工作区，未暂存、未提交。本轮只运行了一次完整 `make check`，十一步全绿。

1. **备份文件名**：覆盖 +08:00、−06:00 到 UTC 的转换；两次备份使用同一时刻、同一 revision，验证文件名不同且两份都保留。
2. **备份过滤**：放入 6 份平台备份后触发清理，验证仅删除最旧的平台备份，人工文件、软链接、`.partial` 原样保留。
3. **只读写入断言**：使用必经的 `pytest.raises`，并验证转换后的 `DefectError` 带诊断。
4. **非缺陷报告**：真实应用覆盖 400、404、409、502、422 和无引擎模式；验证无入库记录、无持久化失败日志。删除 `report or ""`，缺陷报告为空时明确失败。
5. **启动版本检查**：通过 `create_app` 覆盖缺失、无版本表、落后、领先或未知版本，均验证 `InputError` 和“先运行 migrate”。
6. **并发写成功**：首个进程持锁，第二个开始 `BEGIN IMMEDIATE` 后确认尚未完成，再释放锁；验证两者成功，第二个确实等待过。
7. **B2**：补齐 N−1、N、N+1；新增真实 HTTP 超长报告测试，验证日志与报错表逐字一致、截断标记和长度上限。
8. **完整建表 SQL**：新增迁移库与模型库的 `sqlite_master.sql` 比较，规范化空白后完全一致，覆盖 CHECK。
9. **常量**：等待文案、报告等待预算、保留期文案均引用对应常量；Python、TS 分别定义 SQLite 有符号 64 位整数上限。
10. **备份连接超时**：两个 `sqlite3.connect` 均显式传入 `BUSY_TIMEOUT_MS / 1000`。
11. **前端写法**：改用 `queryClient.query(options)`，删除弃用豁免，参数去掉 `_` 前缀，Unicode 字符计数改为明确的逐项递增。
12. **去重**：编号规则集中到公开 `validation.py`；只读写入分类集中一处；备份复用 UTC 格式化；迁移测试复用进程回收函数。
13. **补交报告**：本轮及派工 B 的逐项首次测试结果见第 5 块。

未修改受保护文件，未安装依赖、未联网；本轮未使用 `make fmt`，只格式化指定文件。

**2. `make check`**

最后一次命令：

```bash
make check
```

退出码 `0`。pytest **505 passed、0 skipped**；Vitest **77 passed、0 skipped**。唯一 warning 是既有 Starlette 弃用提示。

末尾输出原样：

```text
======================= 505 passed, 1 warning in 25.67s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.qg5u0b7kYe/openapi.json → /tmp/tmp.qg5u0b7kYe/schema.d.ts [19.9ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-05-database-migrations/src/web


 Test Files  9 passed (9)
      Tests  77 passed (77)
   Start at  07:30:45
   Duration  1.49s (environment 40%, tests 31%, import 28%, transform 1%)
```

运行前的 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/__init__.py
 M src/rdp/api/database.py
 M src/rdp/api/error_details.py
 M src/rdp/api/errors.py
 M src/rdp/api/openapi_export.py
 M src/rdp/infra/config.py
 M src/rdp/infra/db/connection.py
 M src/rdp/infra/db/migration.py
 M src/rdp/infra/db/migrations/env.py
 M src/rdp/infra/db/migrations/versions/v0001_error_reports.py
 M src/rdp/infra/db/models.py
 M src/rdp/infra/db/records.py
 M src/rdp/infra/db/utc.py
 M src/rdp/infra/logging.py
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/errorDetails.test.ts
 M src/web/src/api/errorDetails.ts
 M tests/diagnostics_demo.py
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_db_config.py
 M tests/test_db_connection.py
 M tests/test_db_migration.py
 M tests/test_db_records.py
 M tests/test_db_utc.py
 M tests/test_diagnostics_demo.py
 M tests/test_openapi_export.py
 M tests/test_web_app.py
?? src/rdp/infra/db/_constants.py
?? src/rdp/infra/db/_errors.py
?? src/rdp/infra/db/validation.py
?? tests/db_support.py
```

运行后的同一命令输出：

```text
 M src/rdp/api/__init__.py
 M src/rdp/api/database.py
 M src/rdp/api/error_details.py
 M src/rdp/api/errors.py
 M src/rdp/api/openapi_export.py
 M src/rdp/infra/config.py
 M src/rdp/infra/db/connection.py
 M src/rdp/infra/db/migration.py
 M src/rdp/infra/db/migrations/env.py
 M src/rdp/infra/db/migrations/versions/v0001_error_reports.py
 M src/rdp/infra/db/models.py
 M src/rdp/infra/db/records.py
 M src/rdp/infra/db/utc.py
 M src/rdp/infra/logging.py
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/errorDetails.test.ts
 M src/web/src/api/errorDetails.ts
 M tests/diagnostics_demo.py
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_db_config.py
 M tests/test_db_connection.py
 M tests/test_db_migration.py
 M tests/test_db_records.py
 M tests/test_db_utc.py
 M tests/test_diagnostics_demo.py
 M tests/test_openapi_export.py
 M tests/test_web_app.py
?? src/rdp/infra/db/_constants.py
?? src/rdp/infra/db/_errors.py
?? src/rdp/infra/db/validation.py
?? tests/db_support.py
```

**3. 契约变更申请、依赖申请及文档改动**

契约变更申请：**无**。  
依赖申请：**无**。

本轮文档改动：

- `fetchErrorDetails`：`@param _client/_errorId/_signal` 改为 `client/errorId/signal`。
- `createErrorDetailsLoader`：`@param _client/_queryClient` 改为 `client/queryClient`；Returns 中“通过 fetchQuery 调用”改为“通过 queryClient.query(options) 调用”。
- 为公开的 `validation.is_request_id`、`error_source_kind`、`invalid_field` 和共用的 `utc.format_utc_text` 补齐六项文档。
- 新增常量、共享诊断模块和共享校验模块的职责、单位及出处说明。
- 新增三个测试的 docstring：完整建表 SQL 一致性、超长报告端到端一致性、只读仓储错误诊断。
- 对照 B-done 核对，**既有公开 Python 函数的 docstring 未改变**。

**4. 拿不准、需要评审决定的地方**

无。

**5. 先红后绿**

以下“初绿”指第一次单独运行就通过，不计作先红后绿；目前全部通过。B 的结果按执行线记录及原运行输出核对。

**本轮新增或加强的测试**

| 测试 | 首次结果及原因 |
|---|---|
| `test_db_migration.py::test_backup_filename` | 初绿：已有 UTC 转换和 UUID 后缀满足加强后的同版本、同瞬时测试。 |
| `test_db_migration.py::test_backup_foreign` | 初绿：已有命名过滤和保留清理正确；新样例真正触发了删除。 |
| `test_api_database.py::test_read_exception` | 首次因测试漏导入 `SQLAlchemyError` 报 NameError；补齐后业务断言直接通过，原只读机制正确。 |
| `test_api_database.py::test_report_nondefect` | 初绿：原分类分支正确；加强后覆盖更多状态并检查持久化失败日志。 |
| `test_api_database.py::test_configure_version` | 初绿：已有版本闸门正确，新增四种工厂调用场景均被拒绝。 |
| `test_db_connection.py::test_process_success` | 初绿：已有锁等待与提交实现支持真正重叠的事务。 |
| `test_api_database.py::test_report_bound` | 初绿：已有字符上限实现满足 N−1、N、N+1。 |
| `test_api_database.py::test_report_truncated_same_text` | 初绿：已有格式化结果复用保证超长日志与表内容一致。 |
| `test_db_migration.py::test_table_sql_matches_metadata` | 初绿：现有迁移和模型的完整建表 SQL 一致。 |
| `test_db_records.py::test_readonly_write_diagnostic` | 失败：只读仓储抛出的 `DefectError.diagnostics` 为空；集中分类后通过。 |

**派工 B：`tests/test_db_utc.py`（13 项）**

| 测试 | 首次结果及原因 |
|---|---|
| `test_bind_offset` | 失败：`NotImplementedError`。 |
| `test_bind_zero` | 初绿：前一项采用的微秒 ISO 格式已补齐零微秒和四位年份。 |
| `test_bind_null` | 失败：None 被交给 `ensure_utc`，产生 AttributeError。 |
| `test_bind_naive` | 失败：无时区输入仍抛 ValueError，尚未转为 InputError。 |
| `test_bind_type` | 失败：非 datetime 输入产生 AttributeError。 |
| `test_bind_overflow` | 失败：UTC 换算的 OverflowError 尚未转换。 |
| `test_bind_wrapping` | 初绿：已实现的 InputError 加 SQLAlchemy 原生 StatementError 包装满足断言。 |
| `test_result_utc` | 失败：`NotImplementedError`。 |
| `test_result_null` | 失败：None 被交给 `fromisoformat`，产生 TypeError。 |
| `test_result_invalid` | 失败：宽松 ISO 格式被接受，没有拒绝。 |
| `test_result_propagation` | 初绿：前一项已实现坏文本拒绝，查询直接传播 InputError。 |
| `test_roundtrip` | 初绿：此前写入、读出转换已覆盖精度和时区往返。 |
| `test_no_clock` | 初绿：转换实现本身没有时钟、文件或日志副作用。 |

**派工 B：`tests/test_db_connection.py`（32 项）**

| 测试 | 首次结果及原因 |
|---|---|
| `test_engine_lazy` | 失败：`NotImplementedError`。 |
| `test_engine_path` | 失败：非法路径尚未拒绝。 |
| `test_engine_file_failure` | 失败：目录、软链接和缺失父目录尚未拒绝。 |
| `test_engine_defect` | 首次测试替身定位错误产生 AttributeError；修正后事件配置异常未转换，补实现后通过。 |
| `test_pragmas` | 失败：journal_mode 仍为 delete。 |
| `test_pragma_order` | 初绿：前一项已把 PRAGMA 放在连接初始化、BEGIN 之前。 |
| `test_failed_connection` | 初绿：初始化关闭和损坏库分类已经实现。 |
| `test_write_begin` | 失败：进入会话尚未取得写锁。 |
| `test_read_begin` | 失败：只读连接的 query_only 仍为 0。 |
| `test_session_commit` | 失败：`NotImplementedError`。 |
| `test_session_read_commit` | 初绿：会话退出和只读分支已实现。 |
| `test_session_rollback` | 初绿：显式事务配合会话关闭已回滚未提交写入。 |
| `test_session_cancel` | 初绿：已有异常退出路径没有吞掉 BaseException。 |
| `test_session_commit_failure` | 初绿：前面的数据库异常转换和回滚已覆盖提交故障。 |
| `test_session_cleanup_primary` | 失败：回滚失败覆盖了原业务异常。 |
| `test_session_cleanup_only` | 失败：关闭失败仍直接抛 OSError。 |
| `test_session_corrupt` | 初绿：NOTADB/CORRUPT 分类已实现。 |
| `test_session_external` | 初绿：FULL 等外部故障分类已实现。 |
| `test_session_defect` | 失败：非法 SQL 仍泄漏 SQLAlchemy OperationalError。 |
| `test_session_busy` | 初绿：BUSY 扩展码分类和工作单元转换已实现。 |
| `test_session_constraint` | 初绿：约束冲突转换及回滚已实现。 |
| `test_process_success` | 初绿：原测试仅验证两次写成功，已有事务实现即可满足；重叠缺口本轮补齐。 |
| `test_process_timeout` | 初绿：BEGIN IMMEDIATE 和 5000 毫秒等待已实现，实测落在约定范围。 |
| `test_process_cleanup` | 初绿：测试帮助函数已实现 terminate/kill/join 回收。 |
| `test_translate_busy` | 失败：`NotImplementedError`。 |
| `test_translate_constraint` | 失败：约束故障仍被归为 DefectError。 |
| `test_translate_corrupt` | 失败：损坏库仍被归为 DefectError。 |
| `test_translate_external` | 失败：外部 I/O 故障仍被归为 DefectError。 |
| `test_translate_unknown` | 初绿：分类器已有未知故障归 DefectError 的分支。 |
| `test_translate_wrapped` | 失败：没有保留 StatementError.orig 中的原平台异常。 |
| `test_translate_diagnostic` | 初绿：各分类共用的安全诊断构造已实现。 |
| `test_parameters_hidden` | 初绿：引擎已开启 hide_parameters，诊断也不复制绑定值。 |

**派工 B：`tests/test_db_config.py`（5 项）**

| 测试 | 首次结果及原因 |
|---|---|
| `test_default` | 初绿：A 阶段声明式配置已给出默认值和冻结规则。 |
| `test_toml` | 初绿：既有配置加载器会读取新增的嵌套模型。 |
| `test_bounds` | 初绿：Pydantic 字段已声明严格类型及上下界。 |
| `test_unknown` | 初绿：既有 extra=forbid 和隐藏输入机制继续生效。 |
| `test_clock` | 初绿：两种保留期的配置声明及文档已经区分。 |

**派工 B：`tests/test_db_records.py`（31 项）**

| 测试 | 首次结果及原因 |
|---|---|
| `test_metadata` | 初绿：A 阶段表声明已经共享 MetaData 并定义约束名称。 |
| `test_row_constraints` | 初绿：模型声明的 CHECK、非空和主键约束已经生效。 |
| `test_record_request` | 失败：记录校验器仍为 `NotImplementedError`。 |
| `test_record_job` | 初绿：原字段类型已经接受合法作业编号文本。 |
| `test_record_id_invalid` | 失败：非法编号及来源错配未拒绝。 |
| `test_record_fields_invalid` | 首次发生缩进收集错误；修复后空白摘要未拒绝，再补校验通过。 |
| `test_write_success` | 失败：`NotImplementedError`。 |
| `test_write_duplicate` | 失败：仓储未在调用处转换重复键异常。 |
| `test_write_corrupt` | 初绿：仓储已复用损坏库分类。 |
| `test_write_external` | 初绿：仓储已复用外部存储故障分类。 |
| `test_write_defect` | 初绿：仓储已复用 SQL 编程错误分类；只读诊断缺口本轮另补。 |
| `test_write_lock` | 初绿：仓储已复用 BUSY 分类。 |
| `test_find_request` | 失败：`NotImplementedError`。 |
| `test_find_job` | 初绿：已有主键查询和快照转换支持作业编号。 |
| `test_find_missing` | 初绿：查询实现已对缺失行返回 None。 |
| `test_find_invalid` | 失败：非法编号没有在查询前拒绝。 |
| `test_find_corrupt` | 初绿：UTC 结果处理器已拒绝坏时间文本。 |
| `test_find_lock` | 初绿：查询已使用通用锁错误转换。 |
| `test_find_external` | 初绿：查询已使用通用外部错误转换。 |
| `test_find_defect` | 初绿：查询已使用通用程序错误转换。 |
| `test_clear_boundary` | 失败：`NotImplementedError`。 |
| `test_clear_empty` | 初绿：此前 DELETE 实现自然返回 0。 |
| `test_clear_utc` | 初绿：截止时刻已用 ensure_utc 和 timedelta 计算。 |
| `test_clear_days` | 失败：天数类型和范围未校验。 |
| `test_clear_time` | 失败：无时区时刻仍抛 ValueError。 |
| `test_clear_corrupt` | 初绿：清除已复用损坏库转换。 |
| `test_clear_lock` | 初绿：清除已复用锁错误转换。 |
| `test_clear_external` | 初绿：清除已复用外部故障转换。 |
| `test_clear_defect` | 初绿：清除已复用程序错误转换。 |
| `test_clear_commit` | 初绿：清除没有自行提交，已有外层事务可回滚。 |
| `test_report_bound` | 初绿：模型长度限制和此前完成的 B2 截断共同生效。 |

**派工 B：`tests/test_db_migration.py`（49 项）**

| 测试 | 首次结果及原因 |
|---|---|
| `test_config` | 失败：`NotImplementedError`。 |
| `test_config_none` | 初绿：此前配置实现已支持无连接读取脚本图。 |
| `test_config_invalid` | 失败：缺失迁移目录没有被拒绝。 |
| `test_version_current` | 失败：`NotImplementedError`。 |
| `test_version_absent` | 失败：缺失数据库被归为 ExternalError，而非 InputError。 |
| `test_version_unversioned` | 初绿：版本比较已拒绝 None/current 缺失。 |
| `test_version_behind` | 初绿：当前版本与新 head 不等时已有拒绝逻辑。 |
| `test_version_unknown` | 初绿：版本不匹配的拒绝逻辑已覆盖未知版本。 |
| `test_version_multiple` | 初绿：读取版本时已有多行拒绝逻辑。 |
| `test_version_corrupt` | 初绿：只读读取已复用损坏库转换。 |
| `test_version_busy` | 初绿：只读读取已复用锁错误转换。 |
| `test_version_external` | 失败：跟随软链接后抛 InputError，未按约定拒绝软链接。 |
| `test_version_defect` | 初绿：配置构造已检查迁移图和多个 head。 |
| `test_migrate_new` | 失败：`NotImplementedError`。 |
| `test_migrate_empty` | 失败：已有空库没有备份。 |
| `test_migrate_existing` | 初绿：已有升级路径支持从合法祖先升级。 |
| `test_migrate_noop` | 失败：重复迁移仍返回 changed=True；随后也修复了辅助文件变化。 |
| `test_compare_metadata` | 初绿：已实现的冻结迁移与模型结构一致。 |
| `test_backup_contents` | 初绿：此前已采用 SQLite backup，包含已提交 WAL 内容。 |
| `test_backup_before` | 初绿：已有执行顺序是先发布备份、再执行脚本。 |
| `test_backup_filename` | 初绿：原测试只传 UTC 且两次 revision 不同；本轮补齐真正的命名冲突场景。 |
| `test_backup_permissions` | 初绿：目录权限和 tempfile 的 0600 文件权限已生效。 |
| `test_backup_bad_directory` | 失败：已有宽权限目录未拒绝。 |
| `test_backup_failure` | 失败：创建备份失败仍直接抛 OSError。 |
| `test_backup_partial` | 初绿：此前备份清理分支已保留半成品并报告路径。 |
| `test_backup_deadline` | 失败：尚未执行单调时钟预算检查。 |
| `test_backup_rotation` | 失败：成功升级后没有清理到 5 份。 |
| `test_backup_foreign` | 初绿：原样例没有触发保留清理；本轮补齐清理后的保护断言。 |
| `test_rotation_failure` | 初绿：清理异常已明确报告“升级成功，保留清理失败”。 |
| `test_migrate_invalid_time` | 失败：naive 时刻未拒绝。 |
| `test_migrate_invalid_layout` | 失败：越界数据库布局未拒绝。 |
| `test_migrate_unknown` | 首次样例未关闭连接导致锁冲突；修正样例后未知 revision 仍泄漏 Alembic 异常，再补分类通过。 |
| `test_migrate_unversioned_data` | 失败：非空无版本库仍被升级。 |
| `test_migrate_parallel` | 首次测试缺导入；修正为真实双进程后两个迁移都成功，证明缺少排他锁，再补实现。 |
| `test_migrate_busy` | 首次测到约 0.004 秒的 PRAGMA 冲突；调整为 BEGIN 阶段持锁后验证约 5 秒等待，未放宽阈值。 |
| `test_migrate_upgrade_failure` | 失败：脚本 RuntimeError 未转换成 DefectError。 |
| `test_migrate_first_failure` | 初绿：共用显式事务已经回滚首版表和版本表。 |
| `test_migrate_rollback_failure` | 初绿：工作单元已有保留主异常和“结果未知”说明。 |
| `test_migrate_io` | 初绿：升级使用的工作单元已转换驱动 I/O 故障。 |
| `test_migrate_defect` | 初绿：此前脚本异常转换已实现。 |
| `test_env_connection` | 失败：Alembic 加载 env.py 后没有执行迁移，缺少版本表。 |
| `test_env_invalid` | 初绿：环境入口已检查连接和在线模式。 |
| `test_env_propagation` | 初绿：环境入口不吞脚本异常，外层事务负责回滚。 |
| `test_env_logging` | 初绿：环境实现从未改动全局日志配置。 |
| `test_upgrade` | 失败：`NotImplementedError`。 |
| `test_upgrade_failure` | 初绿：冻结建表使用标准 SQLAlchemy 异常及显式事务回滚。 |
| `test_downgrade` | 失败：`NotImplementedError`。 |
| `test_installed_package` | 初绿：脚本位置已按包路径构造，不依赖 cwd 或仓库配置。 |
| `test_bounded_backup_scan` | 初绿：已有保留清理实现能处理更多候选并仅保留 5 份。 |

**派工 B：`tests/test_api_database.py`（43 项）**

| 测试 | 首次结果及原因 |
|---|---|
| `test_database_argument_required` | 失败：省略 database 没有抛 TypeError。 |
| `test_configure_success` | 失败：`NotImplementedError`。 |
| `test_configure_version` | 初绿：已有版本检查拒绝缺失库；本轮扩充其余工厂场景。 |
| `test_configure_busy` | 初绿：底层版本读取已转换锁错误。 |
| `test_configure_io` | 初绿：底层版本读取已转换外部错误。 |
| `test_configure_defect` | 失败：重复装配等非法状态未拒绝。 |
| `test_factory_compat` | 初绿：已有无引擎依赖返回 502，健康和文档接口仍可用。 |
| `test_factory_schema` | 初绿：A 阶段已经登记路由和响应模型。 |
| `test_factory_lifecycle` | 初绿：工厂没有接管外部引擎或日志生命周期。 |
| `test_session_cached` | 失败：依赖仍为 `NotImplementedError`，请求返回 500。 |
| `test_session_commit_before_send` | 初绿：function scope 和工作单元提交已经接通。 |
| `test_session_route_exception` | 初绿：yield 依赖及工作单元已传播异常并回滚。 |
| `test_session_serialization_exception` | 初绿：function scope 的退出同样覆盖序列化失败。 |
| `test_session_no_database` | 初绿：请求引擎获取函数已实现无引擎 ExternalError。 |
| `test_session_database_errors` | 初绿：依赖、仓储、统一错误处理已完成分类串接。 |
| `test_session_cleanup` | 初绿：工作单元已有 BaseException 回滚和传播。 |
| `test_session_thread` | 初绿：FastAPI 同步路由已在线程池执行。 |
| `test_read_session` | 失败：`NotImplementedError`。 |
| `test_read_exception` | 初绿：query_only 已生效；原测试存在分支断言缺口，本轮补齐。 |
| `test_details_request` | 失败：查询端点未实现，请求返回 500。 |
| `test_details_job` | 初绿：已有仓储查询及端点支持规范作业编号。 |
| `test_details_not_found` | 初绿：查询端点实现时已处理 None 并生成 404 诊断。 |
| `test_details_invalid` | 初绿：路由形状校验和端点整数上界校验已实现。 |
| `test_details_corrupt` | 初绿：坏时间文本已由 UTC 类型转换成 InputError。 |
| `test_details_busy` | 初绿：驱动锁错误经现有边界映射成 409。 |
| `test_details_external` | 初绿：驱动外部错误经现有边界映射成 502。 |
| `test_details_defect` | 初绿：驱动程序错误经现有边界映射成 500。 |
| `test_details_auth` | 初绿：本票查询路由按契约没有登录依赖。 |
| `test_report_unknown` | 失败：500 后查询返回 404，持久化尚未接通。 |
| `test_report_explicit` | 初绿：完成未知异常接入时，显式缺陷也已使用共同报告函数。 |
| `test_report_same_text` | 初绿：普通报告已复用一次格式化结果；超长路径本轮另补。 |
| `test_report_nondefect` | 初绿：原测试的 404、422 已提前返回；覆盖不足和日志断言缺口本轮补齐。 |
| `test_report_reentry` | 初绿：共同报告函数已经设置请求级已报告标记。 |
| `test_report_independent` | 初绿：报错已使用独立会话，业务回滚不影响它。 |
| `test_report_failure` | 初绿：持久化异常兜底和一次附加 ERROR 已实现。 |
| `test_report_async` | 初绿：整个独立事务已经通过 to_thread 执行。 |
| `test_report_timeout` | 初绿：wait_for 预算和迟到线程处理已经实现。 |
| `test_report_input` | 初绿：共同报告函数已经校验注入时刻。 |
| `test_report_identity` | 初绿：共同报告函数已经检查请求编号一致性。 |
| `test_report_boundary_failure` | 初绿：日志 handler 异常没有被数据库失败兜底吞掉。 |
| `test_report_stream` | 初绿：既有 ErrorBoundary 保留已开始响应，新增保存路径已接通。 |
| `test_report_bound` | 失败：原格式化结果没有字符上限。 |
| `test_report_sensitive` | 初绿：第 4 张的安全校验诊断仍生效，非缺陷分支不落表。 |

**派工 B：`src/web/src/api/errorDetails.test.ts`（17 项，省略标题统一前缀“验证契约：”）**

| 测试 | 首次结果及原因 |
|---|---|
| fetchErrorDetails 只用生成的 ErrorRecord 类型和相对 GET 路径，返回完整且编号相符的详情 | 失败：抛“未实现”。 |
| 请求 uuid4 hex 和规范整数作业编号均可查询，路径参数由客户端编码 | 初绿：此前编号识别和类型化客户端请求已实现。 |
| 非法编号或已取消信号在发送前拒绝，不产生请求 | 失败：非法编号仍发送请求并成功返回。 |
| HTTP 404 过期或未保存记录拒绝，卡片显示固定完整报错暂不可用提示 | 初绿：共同客户端拒绝错误响应，卡片已有固定失败提示。 |
| HTTP 422、409、500、502 沿用统一客户端的安全 Error cause | 初绿：第 4 张客户端适配和新请求函数的安全转换已接通。 |
| 空体、坏 JSON、缺字段、额外字段、非法来源/时间/类别、编号错配均拒绝 | 失败：成功响应尚未进行运行时结构校验。 |
| 超长摘要/报告拒绝，N 字符和截断标记合法内容逐字保留 | 初绿：前一项实现的字段校验已包含长度限制。 |
| 网络失败和代理 HTML 不显示原文，卡片仅显示固定失败文案 | 初绿：已有客户端安全错误和卡片兜底共同生效。 |
| createErrorDetailsLoader 创建本身无请求，首次展开才经 TanStack fetchQuery 调用一次（现改为 query） | 失败：加载器抛“未实现”。 |
| 详情查询 retry=false，无轮询、无隐式重试，staleTime/gcTime 为 0 | 初绿：加载器已有禁重试和结束后显式移除查询。 |
| 回调合并 Query 和卡片取消信号，不修改 URL、全局 fetch 或浏览器存储 | 初绿：加载器已有 AbortSignal 合并与原生查询取消。 |
| 详情五秒超时沿用 ERROR_DETAILS_TIMEOUT_MS，清理计时器且不显示迟到内容 | 初绿：第 4 张卡片的超时与取消机制已经存在。 |
| 卸载、编号变化、客户端变化取消旧请求，旧结果不污染新卡片 | 初绿：卡片原有清理逻辑与新回调的取消信号已连接。 |
| 不同客户端/编号查询隔离，结束后不长期缓存敏感报告 | 初绿：加载器已有客户端弱引用身份、编号键及显式移除查询。 |
| 返回纯文本包含本地时间和时区、类别、摘要、来源编号，report 段逐字不变 | 初绿：加载器实现时已完成这一纯文本组装。 |
| 包含 HTML 的合法报告按 React 文本显示，不能执行标签 | 初绿：已有卡片使用 React 文本渲染。 |
| 回调请求失败拒绝 Promise，卡片不展示异常原文 | 初绿：已有请求失败传播和安全错误转换。 |

**派工 B：`src/web/src/HealthPage.test.tsx`（5 项，省略标题统一前缀）**

| 测试 | 首次结果及原因 |
|---|---|
| HealthPage 为 DiagnosticCard 传稳定的 createErrorDetailsLoader，普通重渲染不重复请求 | 失败：页面尚未传加载回调，找不到完整报错内容。 |
| 程序缺陷默认折叠不查详情，首次展开显示完整报错，折叠再展开复用本次结果 | 初绿：前一项接入后，已有卡片展开状态和缓存机制即可满足。 |
| 健康成功和非缺陷卡片不发送详情请求，既有健康缓存与五秒超时不变 | 初绿：原有健康成功路径没有详情请求入口。 |
| 详情 404、失败或五秒超时显示固定提示，保持原错误编号和摘要 | 初绿：页面接入后继续沿用卡片既有失败展示。 |
| 客户端变更重建加载器并取消旧查询，不跨账号复用报告 | 初绿：useMemo 已依赖客户端身份，卡片已有切换取消机制。 |