**1. 改动清单**

第一段已完成，停在检查点。

- 新增 `_storage_scan.py`、`_storage_paths.py`、`_references.py`：第二段扫描、③④组诊断、元信息读取、超时与离线处理。
- 修改 `rescan.py`、`ops/runtime.py`：接入 worker，记录扫描耗时。
- 修改 `_index_write.py`、`_plan.py`：发布扫描结果，保护指纹变化的数据集，保留旧大小。
- 新增 [测试及验收用例](/home/shawn/桌面/robot-data-platform.wt/m1-02-scan-stage2-sizing/tests/test_datasets_storage.py) 和 `datasets_storage_support.py`。

仅修改 `src/`、`tests/`；未访问 `/mnt`、未联网、未提交。临时检查日志已删除。

**2. 最后一次 `make check`**

退出码 `0`，全绿。pytest 汇总原文：

```text
============ 2219 passed, 1 skipped, 8 warnings in 82.39s (0:01:22) ============
```

末尾输出：

```text
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  06:53:52
   Duration  7.46s (tests 49%, environment 30%, import 21%)
```

唯一跳过项是统计大小；8 条警告来自现有 FastAPI TestClient 弃用提示。

**3. 契约变更申请、依赖申请**

无额外契约变更申请，无依赖申请。沿用已预留的第二段结果和索引字段，没有新增公开参数、字段，也未修改 `pyproject.toml`。

**4. 真实数据预计发现**

以下以手册、盘点票及第 01 张扫描记录为基线，尚未经本次真实存储扫描验证。

| 组别 | 预计发现 |
|---|---|
| ③需要处理 | alpha 三个已删除转换副本：`SOURCE_MISSING`，两个视图共 **6 条**。 |
| ③提示 | 35 个数据集的汇总文档失效：`SUMMARY_PATH_MISSING`，共 **70 处引用**。 |
| ③提示 | alpha 的 `lerobot_v2_output`，以及 2026 的 `extracted`、`scripts` 排除目录失效：两个视图共 **6 条**。 |
| ③提示 | alpha 子任务中的转换副本及元信息引用失效；2026 正文中的 `scripts/README_extraction_and_v30_conversion.md` 链接失效。 |
| ③提示 | alpha 未链接、未排除的 `.venv_lerobot_v2`、`.venv_lerobot_v2_v21_v3`、`README.md`、`scripts/`：规范入口预计 **4 条**。 |
| ④需要处理 | 两盘正常在线时预计 **0 条**；没挂载、挂错盘、超时均按根报告，并跳过相应检查。 |

另外保留 **35 条缺少 `来源.json` 提示**。未完成下载计数留到下一段：历史预期为 2026 有 1 个、EgoProDemo 有 8 个。

待核对之处：盘点后的真实数据变化、挂载状态、元信息版本，以及子任务重复引用的计数；实现按引用出现次数统计，可能与盘点的去重数量不同。没有变化时，预计不新增断链、链接清单差异、目标越界、数据集根失效或版本冲突。

**5. 先红后绿**

每项均单独运行；首次即绿的已注明原因。

- `test_meta_is_indexed`：红→绿；样本 FPS 期望按原件纠正为 20。
- `test_meta_unknown`：首次绿；首个元信息实现已覆盖未知值和读取失败。
- `test_meta_invalid_numbers`：红→绿。
- `test_meta_version_mismatch`：红→绿。
- `test_missing_sources_grouped`：红→绿。
- `test_link_declarations`：红→绿。
- `test_broken_link`：红→绿。
- `test_actual_target_checked`：红→绿。
- `test_mismatched_and_extra_broken_links`：红→绿。
- `test_unregistered_target`：红→绿。
- `test_unregistered_source`：红→绿。
- `test_target_outside_dataset_roots`：红→绿。
- `test_missing_dataset_root`：红→绿。
- `test_stale_references`：红→绿，包括顶层共享数据块引用。
- `test_unlinked_root_content`：红→绿。
- `test_same_rule_across_roots_aggregates`：红→绿。
- `test_offline_roots`：红→绿。
- `test_wrong_disk_skips_access`：首次绿；复用 M0 身份检查和已实现的离线处理。
- `test_timeout_discards_partial_results`：首次绿；已有整根超时预算及私有结果隔离。
- `test_timeout_stops_later_reads`：红→绿。
- `test_redirect_timeout_invalidates_root_observations`：红→绿。
- `test_offline_retains_size_and_storage_is_unlocked`：首次绿；第 01 张已有大小保留和阶段解锁，本次验证真实存储回调。
- `test_cross_root_symlink`：红→绿。
- `test_cross_root_source_meta`：红→绿。
- `test_realpath_preserves_symlink_parent_semantics`：红→绿。
- `test_disk_results_published_and_cleared`：红→绿，同时核对缺来源提示。
- `test_worker_assembly_runs_storage`：红→绿。
- `test_publication_rejects_unknown_storage_entry`：红→绿。
- `test_unverified_placeholder_discards_storage_findings`：红→绿。
- `test_sizing_bytes_and_incomplete_files`：按要求保留跳过。