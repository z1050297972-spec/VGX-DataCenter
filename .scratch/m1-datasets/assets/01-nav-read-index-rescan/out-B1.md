**1. 改动清单**

B1 功能已实现，三次检查通过；TDD 执行有偏差，见第 5 块。未暂存、未提交。

- `reading.py`、`_io.py`、`_json.py`、`_discovery.py`、`_issues.py`：宽松读取、受控目录访问、字段校验、记录大小与诊断。
- `fingerprint.py`、`_fingerprints.py`：L12 指纹、入口增删发现、不可验证状态。
- `index.py`、`_index_read.py`、`_index_write.py`、`_plan.py`：原子替换、冲突跳过、损坏占位、旧统计保留及失效处理。
- `rescan.py`、`_stage.py`、`scan_types.py`：持锁第一段、`NOT_RUN` 第二段、提交复核和作业摘要。
- `registry.py`、`ops/runtime.py`：登记扫描类型，分别装配 Web 提交能力和 worker 执行能力。
- `panel.py`：实现扫描所需的诊断聚合；①②组检查保留给 B2。
- `v0007_dataset_index.py`：激活冻结迁移，删除 `pending/`。
- 数据集测试及两份测试辅助文件：启用 53 项 B1 测试，保留 28 项 B2 跳过。
- M0 相关回归测试：同步活动版本、登记数量；历史降级测试固定在原版本验证。
- `Makefile`：仅修改 pytest 行为 `-n auto --maxprocesses=8`，降低子进程测试的 CPU 争用，保留原断言和超时预算。

**2. `make check`**

最终连续三次执行 `make check`，退出码均为 `0`：

```text
=========== 2156 passed, 28 skipped, 8 warnings in 65.09s (0:01:05) ============
=========== 2156 passed, 28 skipped, 8 warnings in 73.25s (0:01:13) ============
=========== 2156 passed, 28 skipped, 8 warnings in 73.09s (0:01:13) ============
```

8 条 warning 为既有 TestClient 弃用提示。最后一次末尾输出：

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
   Start at  04:32:38
   Duration  7.37s (tests 49%, environment 30%, import 20%)
```

任务开始时工作区为空。最终三连跑前、跑后均执行了：

```bash
git status --porcelain --untracked-files=all
```

两次输出逐字相同，`cmp` 返回 `0`，共同输出如下：

```text
 M Makefile
 D src/rdp/infra/db/migrations/pending/__init__.py
 D src/rdp/infra/db/migrations/pending/v0007_dataset_index.py
 M src/rdp/jobs/datasets/fingerprint.py
 M src/rdp/jobs/datasets/index.py
 M src/rdp/jobs/datasets/panel.py
 M src/rdp/jobs/datasets/reading.py
 M src/rdp/jobs/datasets/rescan.py
 M src/rdp/jobs/datasets/scan_types.py
 M src/rdp/jobs/registry.py
 M src/rdp/ops/runtime.py
 M tests/test_api_database.py
 M tests/test_audit_migration.py
 M tests/test_datasets_fingerprint.py
 M tests/test_datasets_index.py
 M tests/test_datasets_panel.py
 M tests/test_datasets_reading.py
 M tests/test_datasets_rescan.py
 M tests/test_db_migration.py
 M tests/test_jobs_migration.py
 M tests/test_jobs_registry.py
 M tests/test_jobs_scheduling_config.py
 M tests/test_jobs_scheduling_migration.py
 M tests/test_jobs_storage.py
 M tests/test_ops_cli.py
 M tests/test_ops_runtime.py
 M tests/test_ops_version_migration.py
?? src/rdp/infra/db/migrations/versions/v0007_dataset_index.py
?? src/rdp/jobs/datasets/_discovery.py
?? src/rdp/jobs/datasets/_fingerprints.py
?? src/rdp/jobs/datasets/_index_read.py
?? src/rdp/jobs/datasets/_index_write.py
?? src/rdp/jobs/datasets/_io.py
?? src/rdp/jobs/datasets/_issues.py
?? src/rdp/jobs/datasets/_json.py
?? src/rdp/jobs/datasets/_plan.py
?? src/rdp/jobs/datasets/_stage.py
?? tests/datasets_execution_support.py
?? tests/datasets_support.py
```

`git diff --check` 通过，临时试验文件已清理。

**3. 契约变更申请、依赖申请**

新增三处只增不改的契约扩展：

- `production_registry(rescan_dependencies=None)`：注入 worker 的扫描依赖。
- `read_index_baseline(..., nav_root=None)`：恢复无编号入口的指纹范围时使用明确导航根。
- `NavigationScan.job_id=None`：将来源作业编号写入已有扫描元数据列。

数据库表结构未改变。依赖申请：**无**。

**4. 拿不准的地方及 B2 剩余范围**

- 无新增阻塞问题。真实导航层扫描和真实规模持锁耗时仍由执行线验证。
- 单数据集更新只修改指定范围；入口发现仍遍历登记视图，以发现新增或改名入口。
- B2 剩余：①②组完整检查、启动触发、600 秒定时触发，以及 `submit_system`、`poll_submissions` 的实现与接入。
- 存储根检查及 `meta/info.json` 读取仍属于第 02 张。

**5. 先红后绿记录**

53 项均已独立运行通过。**18 项有独立红→绿记录；35 项补充用例首次独立运行即绿，因此没有完全满足“每项先独立红”的过程要求。**

下面文件简称均对应 `tests/test_datasets_<简称>.py`。`R`＝独立红→绿；`G`＝共享实现已覆盖，首次独立运行即绿。

```text
reading::test_missing_schema                         R
reading::test_omitted_version                        R
reading::test_unknown_fields                         G
reading::test_invalid_json                           R
reading::test_missing_required_field                 R
reading::test_invalid_required_type                  R
reading::test_unreadable_file                         G
reading::test_all_documents_unavailable               G
reading::test_derived_fields                          G
reading::test_source_path_boundary                    G
reading::test_no_target_access                        G
reading::test_recorded_sizes                          R
reading::test_missing_recorded_size                   G
reading::test_recorded_size_first_match               R
reading::test_read_budgets                            G
reading::test_empty_version_directories               R

fingerprint::test_stable                              R
fingerprint::test_json_bytes_change                   G
fingerprint::test_member_add_remove                   G
fingerprint::test_readlink_change                     G
fingerprint::test_provenance_presence_hash            G
fingerprint::test_all_format_entries                  G
fingerprint::test_additional_json                     G
fingerprint::test_roundtrip_immutable                 G
fingerprint::test_unverifiable                        R
fingerprint::test_no_storage_read                     G

index::test_atomic_rollback                          G
index::test_atomic_visibility                        G
index::test_full_removal                             G
index::test_single_scope                             G
index::test_broken_entry_identity                    G
index::test_unverifiable_placeholder                 G
index::test_preserve_sizes                           G
index::test_storage_metadata_fields                  G
index::test_utc_roundtrip                            R
index::test_schema_constraints                       G
index::test_migration_upgrade                        R
index::test_migration_downgrade                      G
index::test_obsolete_scan_cleanup                    G
index::test_projection_fingerprint_race              G
index::test_first_unreadable_identified_entry        R
index::test_actual_link_change_clears_size           R

rescan::test_all_five_datasets                       R
rescan::test_single_dataset                          G
rescan::test_manual_submission                       R
rescan::test_first_stage_lock                        R
rescan::test_second_stage_unlocked                   G
rescan::test_changed_dataset_skip                    G
rescan::test_recheck_commit_lock                     G
rescan::test_cancel_and_restart                      G
rescan::test_job_definition                          R
rescan::test_summary_counts                          G
rescan::test_parallel_isolation                      G
```