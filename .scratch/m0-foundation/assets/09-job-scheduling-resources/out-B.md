**1. 改动清单**

本轮交检查点：完成配置基础和 `0005` 迁移，去掉 **20 条**测试跳过。运行期调度和前端尚未完成。改动未暂存、未提交。

```text
src/rdp/infra/config.py：实现 GPU 去重、并发覆盖键校验。
src/rdp/infra/state.py：实现示例写锁文件路径。
src/rdp/jobs/registry.py：校验并发上限和 requires_gpu。
src/rdp/jobs/scheduling.py：实现配置覆盖、未知类型拒绝和不可变快照。
src/rdp/jobs/models.py：激活资源列和可空提交人编号。
src/rdp/jobs/scheduling_models.py：注册定时提交表、核卡表及资源约束。
src/rdp/audit/models.py：允许系统操作人，保留其他约束。
src/rdp/infra/db/migrations/pending/__init__.py：删除。
src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py：移入 versions。
src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py：实现升级、降级保护、原子重建和编号高水位保留。
tests/scheduling_migration_support.py：增加真实 0004 数据库及历史行夹具。
tests/test_jobs_scheduling_config.py：完成 9 条测试，生产类型登记测试仍跳过。
tests/test_jobs_scheduling_migration.py：完成全部 11 条迁移测试。
tests/test_jobs_migration.py：适配当前 head，保留精确针对 0004 的历史约束验证。
tests/test_audit_migration.py：维护历史 0003 元数据视图，恢复旧身份约束。
tests/test_db_migration.py：当前版本更新为 0005，模拟后续版本更新为 0006。
tests/test_api_database.py：同步模拟后续版本的迁移链。
```

**2. `make check`**

本轮完整检查只运行一次，退出码 **0**：

```bash
make check > /tmp/rdp09-b-5s5omelw/check.log 2>&1
```

末尾输出原样：

```text
=========== 1537 passed, 123 skipped, 1 warning in 114.86s (0:01:54) ===========
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.P13LeYYRsB/openapi.json → /tmp/tmp.P13LeYYRsB/schema.d.ts [68.4ms]
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
      Tests  205 passed | 23 skipped (228)
   Start at  02:03:15
   Duration  6.76s (tests 49%, environment 34%, import 17%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? tests/scheduling_migration_support.py
```

运行后：

```text
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? tests/scheduling_migration_support.py
```

临时检查目录和日志已删除。未联网、未安装依赖、未调用真实 `nvidia-smi`。

**3. 契约变更申请、依赖申请**

**无。** 已批准的函数签名、类型和六项 docstring 含义未改。

文档措辞调整：

- `OperationLogRow.actor_id`：“运维 NULL”补为“运维/系统 NULL”；`actor_name` 补明空编号的两个固定名字。
- `JobRow.submitter_id`：将“可空声明隔离”改为由 `JobSchedulingColumns` 共用。
- 模型和迁移模块说明：将隔离状态改为实际注册、活动迁移及冻结 DDL 的说明。
- `test_isolated`、`test_gpu_check_table_isolated_and_roundtrips`：按本次指令改为验证激活后的结构。
- `test_active_declarations`：改为验证 `0005` head；`test_schema_v4` 明确验证当前版本保留的作业字段。
- 没有修改 TSDoc。

新增两处单条 `S608` 豁免：SQL 标识符仅来自冻结的表、列清单，原因写在相邻注释中。未改检查配置。

**4. 拿不准、需要评审决定的地方**

无新增待决事项。本轮未完成全票，剩余清单如下：

| 测试文件 | 剩余跳过 |
|---|---:|
| `tests/test_jobs_scheduling_config.py::test_production_types` | 1 |
| `tests/test_jobs_gpu.py` | 23 |
| `tests/test_jobs_navigation.py` | 21 |
| `tests/test_jobs_schedules.py` | 24 |
| `tests/test_jobs_scheduling.py` | 31 |
| `tests/test_jobs_scheduling_api.py` | 12 |
| `tests/test_jobs_maintenance.py` | 11 |
| `src/web/src/api/scheduling.test.ts` | 4 |
| `src/web/src/jobs/Resources.test.tsx` | 6 |
| `src/web/src/scheduling/Pages.test.tsx` | 13 |

后续需继续实现资源池及副本写入、GPU 核对与进程环境、写锁和取消屏蔽、恢复与并发循环、定时提交与清除作业、接口与页面接线，并增强假工具的参数/环境文件记录。`0005` 已激活，无需再次搬迁。

**5. 先红后绿**

`tests/test_jobs_scheduling_config.py`：

- `test_defaults`：首次绿；默认字段已由契约提交声明。
- `test_empty_gpus`：红；GPU 校验器抛 `NotImplementedError`，实现后绿。
- `test_gpu_validation`：红；重复卡号未拒绝，补校验后绿。
- `test_concurrency_bounds`：红；类型键校验器未实现，实现后绿。
- `test_unknown_type`：红；`resolve_scheduling` 未实现，补未知类型诊断后绿。
- `test_invalid_definition`：红；非法并发声明被接受，补登记校验后绿。
- `test_resolve_sorted`：红；合法配置的合并返回未实现，实现后绿。
- `test_state_path`：红；路径属性未实现，实现后绿。
- `test_required_dependencies_have_no_defaults`：首次绿；必填关键字签名已在契约提交中落实。

`tests/test_jobs_scheduling_migration.py`：

- `test_isolated`：红；head 仍为 `0004`，激活后绿。
- `test_upgrade_preserves`：首次因夹具 SQL 绑定错误失败；修正夹具后确认 `0005.upgrade` 未实现导致红，实现后绿。
- `test_sequence_preserved`：首次绿；重建代码已保存并恢复高水位，本测试补验删除最高编号及空表。
- `test_system_identity`：首次绿；已激活的单向 CHECK 覆盖这些合法、非法组合。
- `test_reserved_name_history`：首次绿；复制保留原编号和名字，单向约束允许同名账号。
- `test_audit_system`：红；旧操作人 CHECK 拒绝系统，更新模型及冻结 DDL 后绿。
- `test_resource_checks`：首次绿；已激活的 CHECK 覆盖各非法组合，测试逐项核对约束名。
- `test_daily_uniqueness`：首次绿；复合主键及作业编号唯一约束已随升级建立。
- `test_upgrade_atomic`：首次绿；受管迁移事务已保证回滚，注入中途 DDL 故障验证结构、序列及旧行均恢复。
- `test_downgrade_guard`：红；降级函数未实现，补拒绝条件及安全重建后绿。
- `test_gpu_check_table_isolated_and_roundtrips`：首次绿；已激活模型与既有 `UTCDateTime` 完成往返。

既有版本回归中，`test_active_declarations` 因旧 head 断言失败后适配；`test_audit_check_extension` 因执行到了 `0005` 失败，改为明确升级到历史 `0004` 后通过。其余版本预期适配后的相关回归全部通过。