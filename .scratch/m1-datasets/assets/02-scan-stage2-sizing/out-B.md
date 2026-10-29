**1. 改动清单**

第二段已完成，改动留在工作区，未提交。

- `_readonly.py`：文件、目录请求 `O_NOATIME`；仅遇 EPERM 静默回退。
- [sizing.py](/home/shawn/桌面/robot-data-platform.wt/m1-02-scan-stage2-sizing/src/rdp/jobs/datasets/sizing.py) 及内部模块：实现 `dataset_sizing`、表观大小、硬链接去重、下载标记计数、索引发布。
- 使用 `ionice -c 3` 设置专属遍历线程；不拿导航写锁。离线、超时、导航变化时保留旧统计。
- 接入每日调度和手动提交；补充测试，删除统计大小跳过项。

仅改 `src/`、`tests/`；未访问 `/mnt`、未联网、未安装。临时检查日志已清理。

**2. 三次 `make check`**

最终版本连续三次退出码均为 `0`，均 **0 skipped**：

```text
================= 2234 passed, 8 warnings in 67.81s (0:01:07) ==================
================= 2234 passed, 8 warnings in 84.98s (0:01:24) ==================
================= 2234 passed, 8 warnings in 70.87s (0:01:10) ==================
```

最后一次末尾：

```text
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  07:48:02
   Duration  7.62s (tests 50%, environment 29%, import 20%)
```

8 条警告均为既有 FastAPI/Starlette 弃用提示。

**3. 契约变更申请、依赖申请**

无待批申请，无新增依赖或数据库迁移。

新增作业定义按本票授权实现；使用本机已有 `/usr/bin/ionice`。调用处有一条带理由的 `S603` 豁免：固定命令参数，线程编号来自内核。

**4. 第 03 张对齐信息与真实验证**

作业类型：`dataset_sizing`。参数：

```json
{"dataset_id": null}
```

表示全量；省略参数字段亦为全量。单数据集：

```json
{"dataset_id": "dataset-14"}
```

拒绝额外字段；编号复用 `RescanParameters` 校验。手动入口为现有 `JobService.submit`；每日本地 **03:00** 由系统提交，按日期持久化去重。恢复方式为 `RESTART`。

统计口径：

- 单链接目标内硬链接去重，内部软链接只计自身大小。
- 入口大小为链接目标之和；数据集大小取规范入口。
- 同次遍历统计 `.aria2`、`.incomplete`，形成 `DOWNLOAD_INCOMPLETE` 提示。
- 保留已确认的扫描发现；历史预期新增未完成文件发现为 2026 的 **1 个**、EgoProDemo 的 **8 个**，待真实统计核对。

运行日志包含目标路径、耗时、字节数及 `native_thread_id`；核验 IO 优先级应查询该线程编号，worker 主线程优先级不变。EPERM 回退后仍可能更新 atime，属于本次明确要求的尽力策略。

**5. 先红后绿**

本轮新增测试：

- `test_storage_opens_request_noatime`：红→绿。
- `test_noatime_eperm_falls_back`：红→绿。
- `test_sizing_bytes_and_incomplete_files`：红→绿，含摘要字节数。
- `test_sizing_hardlinks_match_du`：红→绿，包含硬链接到软链接。
- `test_sizing_idle_priority_and_no_lock`：红→绿。
- `test_sizing_offline_retains_previous`：红→绿。
- `test_sizing_panel_counts_and_clears`：红→绿。
- `test_sizing_navigation_change_preserves_old`：红→绿。
- `test_nightly_sizing_system_submission`：红→绿。
- `test_sizing_priority_failure_is_external`：红→绿。
- `test_sizing_late_stat_stops_before_directory_open`：红→绿。
- `test_manual_sizing_submission_parameters`：首次绿；复用已有参数校验和提交服务。
- `test_sizing_timeout_discards_partial`：首次绿；已有停滞监测及整数据集保留逻辑。
- `test_sizing_progress_allows_long_walk`：首次绿；超时按停滞时间计算。
- `test_sizing_cancel_does_not_publish`：有效夹具首次绿；复用 M0 取消协议，夹具已补齐数据库取消状态。

本轮适配测试：

- `test_production_example_only`：登记扩展断言红→绿。
- `test_no_storage_skips_checks`：登记扩展断言红→绿。
- `test_two_rules`：每日计划扩展断言红→绿。
- `test_assembly_order`：登记数量断言红→绿。
- `test_scheduling_catalog`：计划数量断言红→绿。
- `test_production_types`：类型清单断言红→绿。
- `test_timeout_discards_partial_results`：适配 `os.open` 边界，回归绿。
- `test_timeout_stops_later_reads`：适配 `os.open` 边界，回归绿。
- `test_redirect_timeout_invalidates_root_observations`：适配 `os.open` 边界，回归绿。