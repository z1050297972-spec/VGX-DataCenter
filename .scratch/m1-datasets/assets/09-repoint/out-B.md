后端检查点完成，改动留在工作区，未暂存、未提交。

**1．改动清单**

新增后端文件：

| 文件 | 内容 |
|---|---|
| `navwrite/repoint_models.py` | 前缀输入契约 |
| `navwrite/_repoint_text.py` | L17/L18 替换、计数、逐处差异 |
| `navwrite/_repoint_targets.py` | worker 内 L19 全量核对 |
| [repoint.py](/home/shawn/桌面/robot-data-platform.wt/m1-09-repoint/src/rdp/jobs/navwrite/repoint.py) | 规范副本及全部格式入口的预览构造 |
| `navwrite/repoint_jobs.py` | `nav_repoint_preview` 登记 |
| `navwrite/write_service.py` | 提交、读取、确认及撤回服务 |
| `navwrite/write_views.py` | 安全摘要、反向替换展示 |
| `api/navigation_writes.py` | 三个新增 POST 接口 |

新增测试：

- [test_repoint_builders.py](/home/shawn/桌面/robot-data-platform.wt/m1-09-repoint/tests/test_repoint_builders.py)：构造、边界、存储核对和报告。
- [test_repoint_api.py](/home/shawn/桌面/robot-data-platform.wt/m1-09-repoint/tests/test_repoint_api.py)：真实 HTTP → worker → 写入 → 撤回。
- `src/web/src/datasets/Repoint.test.tsx`：4 项前端验收用例保留跳过。

共用文件单独列出：

- `api/__init__.py`：挂载新路由。
- `api/data_origin.py`：复用已有预览读取接口，追加展示字段。
- `navwrite/_create_query.py`、`create_service.py`：共用原有排队确认规则。
- `navwrite/jobs.py`、`policy.py`：共用撤回类型键，旧导入保持可用。
- `navwrite/models.py`：追加完整正文差异字段。
- `jobs/registry.py`：登记第 13 种作业。
- `src/web/src/api/openapi.json`、`schema.d.ts`：由 `make api-types` 生成。
- `originTestSupport.ts`：补齐新增响应字段的空数组。
- `test_dataset_api_contract.py`、`test_jobs_registry.py`、`test_jobs_scheduling_config.py`、`test_jobs_storage.py`、`test_ops_runtime.py`：更新接口或作业数量断言。

**2．`make check` 汇总**

最后一次命令：`make check`，退出码 **0**。

```text
0 errors, 0 warnings, 0 notes
Contracts: 5 kept, 0 broken.
问题总数: 0
2589 passed, 8 warnings in 111.79s (0:01:51)
Test Files  35 passed | 1 skipped (36)
Tests       349 passed | 4 skipped (353)
```

OpenAPI、TypeScript、ESLint、Prettier 均通过。期间遇到过既有前端首屏等待失败、进程测试读取空临时 JSON；未调整阈值，最终完整检查通过。

**3．契约变更申请**

申请复核以下兼容追加，已按授权实现：

- `PlanReport.repoint_changes`：完整 Markdown／`notes` 差异；上限 **30,000 处**，超限整批拒绝。原 `listed_changes` 保持前 500 条样例的含义。
- 预览响应追加 `reverts_job_id`、`changes`、`queued_jobs`、`reversal`。
- 新增三个 POST：改指向预览、撤回预览、确认写入。

无数据库结构变更，无新增依赖，无已合并函数签名或契约含义变更。

**4．副本演练须知、未验证项与下一段**

以下请求使用已登录 Cookie 和同源 `Origin`：

```http
POST /api/datasets/repoint-previews
Content-Type: application/json

{
  "dataset_id": "dataset-30",
  "old_prefix": "/mnt/dataset1/agibot_world_2026",
  "new_prefix": "/mnt/dataset2/agibot_world_2026"
}
```

流程：

| 操作 | 请求 |
|---|---|
| 轮询预览作业 P | `GET /api/jobs/P` |
| 读取成功预览 | `GET /api/navigation/previews/P` |
| 确认写入 | `POST /api/navigation/writes`，正文 `{"preview_job_id":"P"}` |
| 发起撤回写作业 W | `POST /api/jobs/W/revert-previews` |
| 确认撤回预览 R | 同一写入接口，正文 `{"preview_job_id":"R"}` |

出现排队 **409** 时，查看 `queued_jobs`，再次提交时带明确的 `acknowledged_queue_job_ids`。L19 拒绝发生在 worker 预览作业中，诊断从作业详情读取。

选择成功场景时，仅“新旧同名目录都存在”还不够：三份 JSON、Markdown、`notes[]` 和实际链接引用到的所有新路径都要存在。找不到合适场景时，用临时镜像并登记为在线本地根。旧位置原本缺失只豁免新位置存在性，仍检查新根登记、在线及路径边界。

完整正文差异读取 `report.repoint_changes`；撤回读取 `reversal`。断电演练按 **WriteFileStep 的第 3 个文件**计数，计划中还包含链接步骤。

真实目标是否齐全、实际耗时及 SIGKILL 恢复仍待执行线副本演练；本轮未访问 `/mnt` 或真实部署。下一段剩详情“改指向”入口、预览确认页面，以及作业详情／操作日志的撤回入口。

**5．先红后绿**

新增 **38 个后端用例**：28 项有效行为先红后绿，10 项由已有实现覆盖。18 个 Markdown 参数均单独运行过。

下表测试名省略 `test_`：

| 测试 | 首次结果及处理 |
|---|---|
| `repoint_both_views_and_provenance` | 红：模块不存在；实现后绿 |
| `markdown_boundary_each_occurrence`〔18 参数〕 | 全部红：边界替换或逐处报告缺失；补齐后绿 |
| `existing_old_missing_new_rejects_whole_preview` | 红：未拒绝缺失新路径；补 L19 后绿 |
| `alpha_missing_paths_replaced_and_omissions_listed` | 红：未列遗漏；补齐三块提示后绿 |
| `report_describes_regenerated_replica_not_stale_copy` | 红：报告统计旧格式正文；改用 L8 规范内容后绿 |
| `missing_old_still_rejects_unregistered_new_root` | 红：未拒绝未登记新根；补边界后绿 |
| `json_values_notes_and_original_path_boundaries` | 初绿：前述递归替换已覆盖 |
| `target_failures_are_explicit_and_read_only[offline]` | 初绿：已复用挂载身份与离线检查 |
| `target_failures_are_explicit_and_read_only[escape]` | 初绿：已复用受限 realpath 解析 |
| `target_failures_are_explicit_and_read_only[nas]` | 初绿：L19 实现已明确拒绝 NAS |
| `notes_array_replaces_and_lists_each_occurrence` | 红：数组下标使正文判断失效；修复后绿 |
| `complete_prose_report_survives_500_sample_limit` | 红：缺完整字段；追加后绿 |
| `complete_prose_report_over_budget_rejects` | 初绿：上一条实现已加入完整预算拒绝 |
| `repoint_apply_then_revert_through_http` | 红：接口 404；闭环实现后绿 |
| `queue_requires_explicit_ids_then_confirms` | 初绿：复用创建确认规则及 L12 |
| `revert_conflict_lists_after_image_difference` | 初绿：底座已有后像差异检查 |
| `revert_creation_after_40_days_without_audit` | 首次测试导入错误；纠正后即绿，永久记录已支持 |
| `revert_preview_lists_reverse_replacements` | 红：缺反向差异；补投影后绿 |
| `preview_rejects_plan_dataset_tampering` | 准备阶段先遇覆盖保护；纠正后仍错误返回 200，补关联校验后绿 |
| `http_guards_validation_and_web_no_storage` | 初绿：已有鉴权边界及新输入模型覆盖 |
| `preview_expiry_missing_file_and_clock_rollback` | 初绿：预览加载校验已覆盖 |

另有 5 项既有登记／接口断言，均单独确认红后更新并通过。