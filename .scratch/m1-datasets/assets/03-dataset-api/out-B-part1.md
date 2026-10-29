**1. 改动清单**

第一段检查点完成，未暂存、未提交。

- [查询模块](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/queries.py)：实现树、列表、筛选、详情、子任务；复用第 01 张读取器与 L12 指纹。
- [提交模块](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/commands.py)：隔离 M0 作业依赖，提交方法留待第二段实现。
- 禁入契约只检查 queries、schemas，检查间接导入，无 ignore。
- 移除布局审计操作码、明细字段及前端展示。
- 接通生产 Web 的导航根装配；测试使用 ASGI，不监听端口。
- 原 36 项解除 27 项跳过，另补 3 项测试；OpenAPI 经 `make api-types` 生成。
- 0008 保持 pending；临时脚本已清理。未访问 `/mnt`、联网、安装或操作真实部署。

**2. `make check` 汇总及末尾输出**

退出码 0；4 条依赖契约全部通过。

```text
============ 2220 passed, 9 skipped, 8 warnings in 68.22s (0:01:08) ============
```

```text
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  07:29:30
   Duration  7.68s (tests 50%, environment 29%, import 21%, transform 1%)
```

**3. 契约变更申请、依赖申请**

无新增待批准申请，无新增依赖。

落实已批准的拆分，含义保持不变：

| 原服务职责 | 位置 |
|---|---|
| 查询、面板、布局读写 | `queries.DatasetQueries` |
| 重新检查、统计提交 | `commands.DatasetCommands` |
| 子任务返回值、空型号目录适配 | `queries` |

`service.DatasetBrowserService` 保留原构造和方法签名，作为兼容委托入口；事务身份重验通过授权回调传给查询模块，不传入 `JobService`。

生产 `WebRuntime` 增加可选 `nav_root` 装配字段，CLI 显式传入配置值，原调用方式仍兼容。

**4. 拿不准的地方及第二段剩余工作**

无新增阻塞。真实 14 MB 文件响应时间尚未测量；本轮验证了合成大文件逐字节返回、32 MiB 上限及读取中变化的失败行为，真实耗时留给执行线演练。

第二段剩余：

- 面板、重新检查和统计提交。
- 布局读写、激活 0008。
- 9 项跳过测试，以及将不可读假根测试扩展到第二段接口。
- 与第 02 张对齐 `dataset_sizing`，完成最终 OpenAPI 检查。

型号表尚未出现，生产仍用空目录适配；有型号映射的筛选已通过注入目录测试。

**5. 先红后绿记录**

以下名称省略 `test_`，均对应[测试文件](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/tests/test_dataset_api_contract.py)。初绿项没有伪造红灯。

| 测试 | 记录 |
|---|---|
| `storage_import_boundary` | 初绿：拆分后契约已生效；真实检查器验证直接、间接禁入。 |
| `all_endpoints_with_unreadable_storage_roots` | 初绿：五组只读接口均未访问假存储根。 |
| `navigation_symlink_replacement_cannot_reach_storage` | 初绿：复用既有 O_NOFOLLOW 边界。 |
| `robot_type_matches_exact_label` | 红→绿：列表接口原为 NotImplementedError。 |
| `fps_half_up_and_unknown` | 初绿：共用索引筛选已支持整数 FPS 与未知项。 |
| `data_origin_unknown_and_invalid_value` | 初绿：共用筛选及 Pydantic 校验已覆盖。 |
| `unknown_metadata_including_mixed_sources` | 初绿：元信息投影已保留已知、未知并集。 |
| `empty_robot_catalog_falls_back_to_labels` | 红→绿：完成服务装配和候选查询。 |
| `registered_robot_model_maps_multiple_labels` | 初绿：共用元信息投影已按标签映射型号。 |
| `model_catalog_refresh_and_duplicate_rejection` | 初绿：目录逐请求读取，已有重复映射校验。 |
| `filters_intersect_and_paginate_stably` | 初绿：列表共用筛选、排序和分页已实现。 |
| `invalid_query_returns_five_part_problem` | 红→绿：补齐跨字段及穿越路径校验。 |
| `tree_counts_and_size_provenance` | 红→绿：实现树聚合；另纠正了夹具时刻预期。 |
| `list_preserves_damaged_and_format_only_entries` | 初绿：列表投影已保留损坏及无规范入口情况。 |
| `index_only_reads_never_open_navigation` | 初绿：移走导航后索引查询仍成功。 |
| `panel_grouping_bounded_examples_and_offline_banner` | 第二段，保留跳过。 |
| `detail_raw_unknown_fields_and_canonical_information` | 红→绿：实现详情原文与规范副本分离。 |
| `detail_fingerprint_detects_changed_json` | 初绿：复用 L12 内容指纹。 |
| `detail_fingerprint_covers_new_entries_and_unverifiable_state` | 初绿：既有 L12 覆盖新增入口及不可验证状态。 |
| `detail_partial_file_failure_is_visible` | 初绿；补诊断对象断言后红→绿，修复入口身份缺失。 |
| `source_derived_paths_and_validation_labels` | 初绿：详情已复用路径推导及历史标签映射。 |
| `subtasks_not_embedded_and_fourteen_megabytes_exact` | 红→绿：实现独立原字节响应。 |
| `subtasks_headers_and_changed_during_read` | 红→绿：修复拆分遗漏的 dataclass 装饰器，头及竞态断言通过。 |
| `subtasks_missing_oversize_and_io_failure` | 初绿：受限读取及错误分类已覆盖。 |
| `unknown_entry_and_dataset_return_404` | 初绿：已实现索引定位；提交范围部分留第二段。 |
| `rescan_submits_current_actor_and_never_executes` | 第二段，保留跳过。 |
| `sizing_submits_all_or_one_without_worker_import` | 第二段，保留跳过。 |
| `submission_failure_rolls_back_job_and_audit` | 第二段，保留跳过。 |
| `layout_persists_across_sessions_and_isolates_accounts` | 第二段，保留跳过。 |
| `layout_default_idempotence_and_clock_rollback` | 第二段，保留跳过。 |
| `layout_without_audit_and_deleted_account` | 已更新为无审计契约；第二段实现，保留跳过。 |
| `layout_migration_matches_model_and_preserves_existing_data` | 第二段，保留跳过。 |
| `layout_invalid_value_and_database_failure` | 第二段，保留跳过。 |
| `security_precedes_body_and_route_validation` | 初绿：复用 M0 全局安全边界。 |
| `identity_revalidated_inside_business_transaction` | 初绿：查询已在事务内调用 M0 身份重验。 |
| `openapi_and_generated_types_are_current` | 初绿：已生成最新产物；完整检查链另验证类型过期。 |
| `layout_audit_contract_removed` | 新增，红→绿：删除布局审计契约。 |
| `production_entry_configures_dataset_queries` | 新增，红→绿：接通生产入口的数据集服务装配。 |
| `detail_projection_read_failure_marks_stale` | 新增，红→绿：修复二次读取失败仍误报新鲜的问题。 |