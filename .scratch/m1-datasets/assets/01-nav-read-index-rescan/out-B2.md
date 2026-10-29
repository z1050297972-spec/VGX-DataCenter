**1. 改动清单**

B2 已完成，改动留在工作区，未暂存、未提交。

- `panel.py`、`_entry_checks.py`、`_view_checks.py`、`_task_checks.py`、`_panel_issue.py`：完成①②组检查，保留未知字段，正确处理合法子集与位置字段。
- `_stage.py`、`_discovery.py`：接入面板发现，补全未知格式目录的诊断位置。
- `panel.py`：完整计数，每组仅保留前 10 条样例。
- `triggers.py`、`service.py`：启动提交、600 秒触发、回拨处理、忙锁重试、错过周期合并，以及系统身份和审计事务。
- `_loop.py`、`ops/lifecycle.py`：接通生产 worker 自动提交。
- 相关测试：启用剩余 28 项，另补 6 项集成/回归测试。

**2. 三次检查结果**

连续三次 `make check`，退出码均为 `0`，均 **0 skipped**：

```text
================= 2190 passed, 8 warnings in 64.69s (0:01:04) ==================
================= 2190 passed, 8 warnings in 76.08s (0:01:16) ==================
================= 2190 passed, 8 warnings in 63.69s (0:01:03) ==================
```

8 条 warning 均为既有 TestClient 弃用提示。最后一次末尾输出：

```text
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m1-01-nav-read-index-rescan/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  05:44:48
   Duration  7.19s (tests 50%, environment 29%, import 20%)
```

`git diff --check` 通过，临时试验文件已清理。

**3. 契约变更申请、依赖申请**

- 契约变更申请：无。
- 依赖申请：无。

**4. 真实数据预计发现**

| 规则 | 级别 | 预计数量 | 对象 |
|---|---|---:|---|
| `TOP_LEVEL_UNREGISTERED` | 需要处理 | 1 | `VGX_video/` |
| `PROVENANCE_MISSING` | 提示 | 35 | 每个数据集的按任务规范入口 |
| 其他①②组规则 | — | 预计 0 | 见下述依据 |

预计共 **36 条发现、2 类问题**。来源提示每个数据集计一次，不按两个视图重复计算。

依据和边界：

- 基线中没有 `来源.json`；35 对 `数据集信息.json` 的哈希全部相同。
- EgoProStandard 的链接位置差异、EgoProDemo 的格式子集应正常通过。
- alpha 三个已删除数据块的存在性、失效引用、未完成文件及未链接内容属于③④组，本轮不检查，不应因此产生①②组错误。
- 缺省 `schema_version`、省略 `version`、合法跨数据集任务引用不应误报。
- 面板发现不直接增加作业失败或警告计数，预计扫描仍为 `succeeded`。

完整真实 JSON 的字段级结果仍需执行线再次扫描核对；本轮没有访问 `/mnt`。

**5. 先红后绿**

原剩余 28 项：**21 项独立红→绿，7 项首次绿**。另增 6 项：3 项红→绿、3 项首次绿。全部最终独立运行通过。

简称对应 `tests/test_datasets_<简称>.py`：

```text
panel::test_json_unreadable                    首次绿：B1读取已覆盖
panel::test_json_invalid                       首次绿：B1解析已覆盖
panel::test_required_field                     首次绿：B1字段校验已覆盖
panel::test_schema_version                     首次绿：B1版本校验已覆盖
panel::test_identity_mismatch                  红→绿
panel::test_name_mismatch                      红→绿
panel::test_duplicate_task_identity            红→绿
panel::test_canonical_missing                  红→绿
panel::test_unregistered_format                红→绿
panel::test_unregistered_top_directory         首次绿：B1目录发现已覆盖
panel::test_unregistered_top_file              首次绿：B1目录发现已覆盖
panel::test_removed_directory                  首次绿：B1登记表和跳过规则已覆盖
panel::test_derived_mismatch                   红→绿
panel::test_information_mismatch               红→绿
panel::test_source_subset                      红→绿
panel::test_source_content                     红→绿
panel::test_dataset_header                     红→绿
panel::test_task_subset                        红→绿
panel::test_task_content                       红→绿
panel::test_egopro_subset                      红→绿
panel::test_provenance_missing                 红→绿
panel::test_aggregation                        红→绿
panel::test_findings_not_failures              红→绿
rescan::test_startup_submission                红→绿
rescan::test_periodic_submission               红→绿
rescan::test_periodic_busy                     红→绿
rescan::test_clock_changes                     红→绿
rescan::test_missed_intervals                  红→绿

triggers::test_production_worker_automatic_scans     红→绿
triggers::test_system_submission_rolls_back_with_audit
                                                   首次绿：提交事务已覆盖回滚
panel::test_fake_navigation_expected_findings       首次绿：完整规则已覆盖
panel::test_cross_dataset_task_reference_is_preserved
                                                   首次绿：子集比较已保留外部引用
panel::test_duplicate_canonical_source_is_reported  红→绿
panel::test_duplicate_task_key_is_reported          红→绿
```