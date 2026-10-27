前端已完成，`make check` 全绿。pytest、Vitest 均无 skipped。改动未暂存、未提交，临时文件已清理。

**1. 本轮改动清单**

- `src/web/src/api/scheduling.ts`：实现调度 GET 和两个示例 POST，复用账号客户端、超时及取消机制。
- `src/web/src/api/scheduling.test.ts`：启用并完成 4 条传输测试。
- `src/web/src/scheduling/Pages.tsx`：实现只读调度页、坏卡诊断及两个 Ant Design 提交表单。
- `src/web/src/scheduling/queries.ts`：实现轮询和提交 hooks，调度缓存按账号隔离。
- `src/web/src/scheduling/Pages.test.tsx`：启用并完成 13 条页面测试。
- `src/web/src/scheduling/testSupport.ts`：新增生成类型约束的独立测试样本。
- `src/web/src/scheduling/pageTestSupport.tsx`：新增真实内存路由及浏览器边界夹具。
- `src/web/src/jobs/_actions.ts`：复用作业写请求生命周期，补齐换号取消和迟到导航保护。
- `src/web/src/jobs/queries.ts`：使用共用写请求 hook。
- `src/web/src/jobs/Pages.tsx`：显示等待原因、历史 GPU、系统身份，并增加资源示例入口。
- `src/web/src/jobs/progress.ts`：集中结局和状态名称，供调度页共用。
- `src/web/src/jobs/Resources.test.tsx`：启用并完成 6 条资源显示测试。
- `src/web/src/router.tsx`：登记 `/scheduling`、`/jobs/resources`。
- `src/web/src/accounts/Pages.tsx`：所有登录账号可见“调度”菜单，清理措辞。
- `src/rdp/jobs/maintenance.py`：仅清理模块说明。
- `src/rdp/jobs/navigation.py`：仅清理模块说明。
- `src/rdp/jobs/schedules.py`：仅清理模块说明。
- `src/rdp/jobs/worker.py`：仅清理模块说明。
- `tests/test_jobs_gpu.py`：仅清理测试说明中的过程标签。
- `tests/test_jobs_scheduling.py`：仅清理测试说明中的过程标签。
- `tests/test_jobs_scheduling_api.py`：仅清理测试说明中的过程标签。
- `tests/test_jobs_worker.py`：仅清理测试说明中的过程标签。

要求扫描的措辞为 **0 处**。AST 对比确认本轮 Python 可执行行为未变。

**2. `make check`**

最后一次命令：

```bash
make check > /tmp/rdp09-frontend-uugioxh3/make-check.log 2>&1
```

退出码 `0`。末尾结果原文：

```text
================= 1667 passed, 1 warning in 120.44s (0:02:00) ==================
```

```text
 Test Files  19 passed (19)
      Tests  228 passed (228)
   Start at  10:26:24
   Duration  6.99s (tests 50%, environment 29%, import 20%)
```

OpenAPI 过期检查通过，无需重新生成。

运行前 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/jobs.py
 M src/rdp/audit/_validation.py
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_process_io.py
 M src/rdp/jobs/_storage.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/gpu.py
 M src/rdp/jobs/maintenance.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/navigation.py
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resource_examples.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedule_records.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/scheduling_service.py
 M src/rdp/jobs/scheduling_types.py
 M src/rdp/jobs/service.py
 M src/rdp/jobs/worker.py
 M src/rdp/ops/worker.py
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/scheduling.test.ts
 M src/web/src/api/scheduling.ts
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/Resources.test.tsx
 M src/web/src/jobs/progress.ts
 M src/web/src/jobs/queries.ts
 M src/web/src/router.tsx
 M src/web/src/scheduling/Pages.test.tsx
 M src/web/src/scheduling/Pages.tsx
 M src/web/src/scheduling/queries.ts
 M tests/jobs_api_support.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_progress_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_gpu.py
 M tests/test_jobs_maintenance.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_navigation.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_schedules.py
 M tests/test_jobs_scheduling.py
 M tests/test_jobs_scheduling_api.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? src/rdp/jobs/_parameters.py
?? src/web/src/jobs/_actions.ts
?? src/web/src/scheduling/pageTestSupport.tsx
?? src/web/src/scheduling/testSupport.ts
?? tests/jobs_gpu_support.py
?? tests/jobs_maintenance_support.py
?? tests/jobs_navigation_support.py
?? tests/jobs_schedules_support.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

运行后：

```text
 M src/rdp/api/jobs.py
 M src/rdp/audit/_validation.py
 M src/rdp/audit/models.py
 M src/rdp/infra/config.py
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0005_job_scheduling.py
 M src/rdp/infra/state.py
 M src/rdp/jobs/_loop.py
 M src/rdp/jobs/_process_io.py
 M src/rdp/jobs/_storage.py
 M src/rdp/jobs/_views.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/gpu.py
 M src/rdp/jobs/maintenance.py
 M src/rdp/jobs/models.py
 M src/rdp/jobs/navigation.py
 M src/rdp/jobs/processes.py
 M src/rdp/jobs/progress.py
 M src/rdp/jobs/records.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/resource_examples.py
 M src/rdp/jobs/resources.py
 M src/rdp/jobs/schedule_records.py
 M src/rdp/jobs/schedules.py
 M src/rdp/jobs/scheduling.py
 M src/rdp/jobs/scheduling_models.py
 M src/rdp/jobs/scheduling_service.py
 M src/rdp/jobs/scheduling_types.py
 M src/rdp/jobs/service.py
 M src/rdp/jobs/worker.py
 M src/rdp/ops/worker.py
 M src/web/src/accounts/Pages.tsx
 M src/web/src/api/scheduling.test.ts
 M src/web/src/api/scheduling.ts
 M src/web/src/jobs/Pages.tsx
 M src/web/src/jobs/Resources.test.tsx
 M src/web/src/jobs/progress.ts
 M src/web/src/jobs/queries.ts
 M src/web/src/router.tsx
 M src/web/src/scheduling/Pages.test.tsx
 M src/web/src/scheduling/Pages.tsx
 M src/web/src/scheduling/queries.ts
 M tests/jobs_api_support.py
 M tests/jobs_execution_support.py
 M tests/jobs_loop_support.py
 M tests/jobs_progress_support.py
 M tests/jobs_scheduling_support.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_db_migration.py
 M tests/test_jobs_gpu.py
 M tests/test_jobs_maintenance.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_navigation.py
 M tests/test_jobs_processes.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_schedules.py
 M tests/test_jobs_scheduling.py
 M tests/test_jobs_scheduling_api.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_service.py
 M tests/test_jobs_worker.py
?? src/rdp/infra/db/migrations/versions/v0005_job_scheduling.py
?? src/rdp/jobs/_parameters.py
?? src/web/src/jobs/_actions.ts
?? src/web/src/scheduling/pageTestSupport.tsx
?? src/web/src/scheduling/testSupport.ts
?? tests/jobs_gpu_support.py
?? tests/jobs_maintenance_support.py
?? tests/jobs_navigation_support.py
?? tests/jobs_schedules_support.py
?? tests/jobs_scheduling_execution_support.py
?? tests/scheduling_migration_support.py
```

前后完全一致。

**3. 契约变更、依赖申请及文档调整**

新增契约变更申请：**无**。依赖申请：**无**。已有公开签名未改。

上一轮已落实的批准项：

- `read_example_value` 的 Side Effects 改为：
  > 无（最多读取文件末尾 NAVIGATION_EXAMPLE_LINE_MAX_BYTES + 1 字节）；额外一字节只用于确认行界，单行上限仍为 NAVIGATION_EXAMPLE_LINE_MAX_BYTES 字节；不自动修复或截断坏行。
- `_storage.entry_busy` 职责句改为：
  > 只认可BEGIN语句的SQLite BUSY/LOCKED，事务内和提交阶段的竞争不能静默跳过。
- `OutputReader.tail_text` 职责句改为：
  > 返回共用分行器保留的有界stderr摘要。
- `test_shared_stop_budget` 说明明确为验证共同截止，以及完整返回遗留线程供入口保锁。
- 已完成测试模块的说明改为当前职责，删除“逐项跳过”等过时文字。

本轮：

- `useScheduling` 补充说明：queryKey **以 scheduling 为前缀并包含账号编号**。
- 共用 `_actions.ts` 和新增页面夹具写全 TSDoc。
- 删除模块、测试说明中的过程标签；HTTP 状态码列举的 `/` 改为顿号，含义不变。

**4. 拿不准、缺陷及剩余事项**

没有待决定的契约问题，也没有剩余 skipped。真实 GPU、Web 和 worker 演示仍由执行线完成。

上一轮“系统提交人的两处问题”已这样修复：

- API `_response` 对空账号编号保留 JSON `null`，不再输出字符串 `"None"`。
- `JobService.get/list` 只有**非空账号编号不存在**时才标记已删除；系统身份始终不加删除标记。有编号且名字叫“系统”的账号继续按编号处理。

上一轮还修复了 COMMIT 锁竞争被误当 BEGIN 忙而跳过的问题。

本轮发现的是前端缺陷：原地换号没有取消写请求、调度缓存未按账号隔离。已加入账号变化取消、提交代次检查及账号查询键，测试确认迟到成功不导航、旧调度数据不闪回。**没有因此修改后端行为。**

**5. 先红后绿记录**

以下均已最终通过。

本轮 `api/scheduling.test.ts`：

| 测试 | 首次结果 |
|---|---|
| 调度 GET、类型和 AbortSignal | 红：GET 未实现。 |
| 401、403、409、502及空响应 | 红：`null` 成功响应未拒绝。 |
| GPU/写锁 POST | 红：提交函数未实现。 |
| 超时、取消、默认 fetch 的 this | 直接绿：复用了已有有界请求及默认传输。 |

本轮 `jobs/Resources.test.tsx`：

| 测试 | 首次结果 |
|---|---|
| queued 等待 GPU及轮询转运行 | 红：没有等待原因显示。 |
| 等待导航写锁及获得锁后清除 | 直接绿：此前等待原因映射已覆盖写锁。 |
| GPU 编号、历史卡号、未分配 | 红：详情未显示 GPU。 |
| 系统身份、同名账号、重新提交 | 红：同名账号缺少账号标记。 |
| 真实 router 的 queued、limit=2 | 直接绿：沿用了既有类型化 search。 |
| 取消、中断及六种结局 | 直接绿：既有状态与结果映射已正确处理。 |

本轮 `scheduling/Pages.test.tsx`：

| 测试 | 首次结果 |
|---|---|
| 菜单、路由、成员权限及认证跳转 | 红：路由未登记。 |
| 类型容量、GPU、导航写锁 | 红：页面没有资源内容。 |
| 每日计划、本地时刻及六种结局 | 红：页面没有计划内容。 |
| 离线和查询失败 | 红：缺少“最后已保存状态”提示。 |
| 轮询、离页取消、不重试 | 直接绿：Query 已配置周期、取消和无重试。 |
| 401、换号及迟到响应 | 首跑绿：既有登出清缓存有效；补测原地换号后红，修复账号查询键后绿。 |
| 大整数编号链接 | 直接绿：始终使用编号文本。 |
| 到期等待 worker | 红：缺少到期提示。 |
| GPU 表单边界 | 红：表单未实现。 |
| 写锁表单边界 | 红：写锁表单不存在。 |
| 成功导航、防重复及换号取消 | 红：原地换号没有取消写请求。 |
| 提交失败保留表单、不重试 | 直接绿：复用统一诊断及 Mutation 生命周期。 |
| 移出卡、诊断和核对时间 | 红：缺少移出状态及原因展示。 |

上一轮 B4/B4b 的红灯按文件汇总：

| 文件 | 红灯及实现内容 |
|---|---|
| `test_jobs_navigation.py` | 完整 4KiB 尾行被拒绝；落实批准的额外边界字节。 |
| `test_jobs_gpu.py` | 核卡未实现、非法依赖未拒绝、五类核卡失败仍执行类型、空池误报缺陷、示例未实现、启动未装配资源、核对结果未落库。 |
| `test_jobs_schedules.py` | 日期计算、原子提交、最近提交、定时 tick、本机时区读取、下次时刻及日期窗口未实现；COMMIT 竞争曾被吞掉。 |
| `test_jobs_maintenance.py` | 生产登记、维护服务、日志清除及执行函数未实现。 |
| `test_jobs_scheduling_api.py` | 路由未实现、运行数恒为零、计划缺失、在线恒为假、系统身份转换错误、示例 POST 未实现、坏卡状态恒为 unknown。 |

上一轮直接通过项逐条说明：

| 文件／测试 | 原因 |
|---|---|
| GPU `test_two_cards_three_jobs` | CP2 名额池和队首领取已正确；反转分卡顺序的变异会失败。 |
| GPU `test_release_all_endings[completed]` | 已有 finally 归还；删掉归还的变异会失败。 |
| GPU `test_release_all_endings[failed]` | 失败同样经过归还；漏还变异会失败。 |
| GPU `test_release_all_endings[cancelled]` | 取消收尾已经归还；漏还变异会失败。 |
| GPU `test_release_all_endings[stopped]` | 停止收尾已经归还；漏还变异会失败。 |
| GPU `test_release_all_endings[interrupted]` | 恢复已清卡号并重建池；保留旧卡号的变异会失败。 |
| GPU `test_recheck_after_claim` | 前面的失败测试已接通执行前核卡；跳过核卡的变异会失败。 |
| GPU `test_probe_large_output` | 共用输出组件已有完整流式日志和有界尾部；删除截断标记的变异会失败。 |
| GPU `test_all_startup_cards_excluded` | 启动装配已过滤坏卡；把配置卡全部放回池的变异会失败。 |
| GPU `test_excluded_card_requires_restart` | 池成员固定、重启重新核对；重启后仍不启用卡的变异会失败。 |
| 定时 `test_same_day` | 日期唯一记录和事务内去重已实现。 |
| 定时 `test_first_start` | 启动补跑和当日资格占用已实现。 |
| 定时 `test_catchup_over_day` | 严格超过 24 小时的补跑分支已实现。 |
| 定时 `test_submitted_not_finished` | 补跑依据提交时刻，与执行状态无关。 |
| 定时 `test_clock_backwards` | 负时长按零，数据库按日期去重。 |
| 定时 `test_utc_local_dates` | 已用注入 ZoneInfo 转本地日期。 |
| 定时 `test_spring_gap` | UTC 往返验证已顺延不存在的分钟。 |
| 定时 `test_fall_fold` | 已取第一次出现并按日期去重。 |
| 定时 `test_invalid_clock` | 共用时刻校验已拒绝坏时钟。 |
| 定时 `test_unique_race` | BEGIN IMMEDIATE 和事务内去重已串行保护提交。 |
| 定时 `test_startup_busy` | BEGIN 忙已保留启动检查资格；随后扩展 COMMIT 场景发现红灯。 |
| 定时 `test_schedule_commit_conflict` | 从上述已见红的 COMMIT 子场景拆出；修复后单独通过。 |
| 定时 `test_ordinary_day_after_catchup` | 日常截止独立于补跑时刻。 |
| 定时 `test_skipped_date` | 已有 UTC 往返判断和有界日期搜索。 |
| 定时 `test_resubmit_system` | 既有重提服务使用当前账号。 |
| 清除 `test_audit_atomic` | 委托的原审计服务已保证两表原子删除。 |
| 清除 `test_summary_counts` | 首跑测试自身误用 `model_dump`；修正后直接绿，真实计数上报已实现。 |
| 清除 `test_retention_runtime` | 审计服务执行时读取设置，报错使用注入配置。 |
| 清除 `test_restart_idempotent` | 清除幂等，既有 restart 会重置进度。 |
| 清除 `test_cancel_checkpoint[before]` | 执行前已有取消检查。 |
| 清除 `test_cancel_checkpoint[after]` | 提交后已有取消检查，不撤销删除。 |
| 清除 `test_bad_clock` | 维护服务已在删除前校验时刻。 |
| 清除 `test_no_recursive_audit` | 清除执行没有追加审计，恢复不重新提交作业。 |
| 调度 `test_shared_stop_budget` | CP2 已实现所有线程共用截止。 |
| 调度 `test_run_loop_checks_schedules_and_finishes_cleanup` | 主循环原有每轮 tick，接通定时和维护服务后即可运行完成。 |
| API `test_read_only` | 只读服务只使用数据库和注入配置。 |
| API `test_job_waiting` | 既有记录映射及终态清理已携带资源字段。 |
| API `test_missing_configuration` | 缺配置 502 已接通；扩展坏时区、容量和登记后曾红，再补校验。 |
| API `test_inconsistent_display` | 资源聚合实现已拒绝双持锁、双卡主。 |
| API `test_system_reserved_account` | 正编号账号和固定系统身份已分开校验。 |

上述 GPU 的 10 个直接通过用例已在恢复执行时逐条做行为变异验证，均能失败；变异全部恢复。