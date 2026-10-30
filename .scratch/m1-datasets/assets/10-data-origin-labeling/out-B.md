**1．改动清单**

后端检查点已完成，改动留在工作区，未暂存、未提交。

- 新增来源预览作业、参数模型和 [HTTP 接口](/home/shawn/桌面/robot-data-platform.wt/m1-10-data-origin-labeling/src/rdp/api/data_origin.py)。
- 新增 [0011 来源枚举迁移](/home/shawn/桌面/robot-data-platform.wt/m1-10-data-origin-labeling/src/rdp/infra/db/migrations/versions/v0011_data_origin.py)，保留已有索引行和外键。
- 写入、索引更新、审计、变更记录和撤回全部复用第 07 张流水线。
- 共用文件改动：`api/__init__.py` 接路由；`jobs/registry.py` 登记作业；`datasets/{reading,types,_index_write,models}.py` 增加来源投影和枚举；`dataset_browser/{queries,schemas}.py` 更新来源计数及说明。
- **现有 `navwrite` 文件零修改**，仅新增本票模块。
- 已运行 `make api-types`；新增 12 项后端测试，前端 3 项明确跳过。全部改动限于 `src/`、`tests/`，临时试验文件已清理。

**2．`make check`**

退出码 **0**。pytest 汇总与末尾输出：

```text
================= 2481 passed, 8 warnings in 80.78s (0:01:20) ==================

 Test Files  32 passed | 1 skipped (33)
      Tests  319 passed | 3 skipped (322)
   Start at  00:45:27
   Duration  8.88s (tests 47%, environment 30%, import 21%, transform 2%, setup 1%)
```

**3．契约变更申请、依赖申请**

无既有契约含义变更；以下增量按授权先实现，提交审核：

- 新作业 `nav_data_origin_preview`，参数为 `dataset_id`、中文 `data_origin`。
- 新增两条接口，见下一块。
- `EntrySnapshot.data_origin` 新字段，默认 `unknown`。
- 数据库 CHECK 新增五个来源编码，保留 `unknown`，迁移至 `0011_data_origin`。

`来源.json` 仍为第 1 版，血缘字节保留。无新增依赖，无受保护文件改动。

**4．副本演练交接**

使用隔离配置、导航层副本和独立状态目录，先迁移副本库至 `0011_data_origin`。POST 请求带登录 cookie 和同源 `Origin`。先查询 libero_10 的实际 `dataset_id`。

| 顺序 | 请求及参数 |
|---|---|
| 预览 | `POST /api/navigation/data-origin/preview`，`{"dataset_id":"实际编号","data_origin":"开源下载"}` |
| 查看 | 等预览作业成功后，`GET /api/navigation/previews/{预览编号}` |
| 确认 | `POST /api/jobs`，`{"type_name":"nav_write_apply","parameters":{"preview_job_id":预览整数编号}}` |
| 筛选 | 写入成功后，`GET /api/datasets?data_origin=open_source` |
| 撤回预览 | `POST /api/jobs`，`{"type_name":"nav_revert_preview","parameters":{"target_job_id":写入整数编号}}` |
| 撤回确认 | 等撤回预览成功，再提交 `nav_write_apply` 引用它 |

应检查：仅按任务入口新增文件、缺来源提示消失、来源筛选及计数更新；撤回后文件删除、提示恢复。

需审核的时间语义：来源印记固定为**预览提交人及生成预览的 UTC 秒时刻**；确认写入人另记于变更记录和操作日志。真实副本演练尚未执行。

下一段剩详情页选择、预览确认、作业状态与缓存刷新，以及真实浏览器演练和截图。

**5．先红后绿**

新增测试均已单独运行：

- `test_preview_new_provenance_is_read_only`：红，类型未登记 → 绿。
- `test_modify_preserves_lineage_bytes`：红，把已有文件误作新建导致冲突 → 绿。
- `test_preview_refuses_wrong_provenance_identity`：红，错误身份被接受 → 绿。
- `test_preview_refuses_ambiguous_canonical`：红，重复规范入口被接受 → 绿。
- `test_preview_refuses_disagreeing_identity_documents`：红，基础文件身份不一致被接受 → 绿。
- `test_changed_provenance_conflicts_without_writing`：首绿，复用第 07 张 L12 冲突检查。
- `test_invalid_provenance_is_never_overwritten`：首绿，复用既有来源三态读取及拒绝逻辑。
- `test_http_preview_submission_and_report`：红，接口返回 404 → 绿。
- `test_apply_reindexes_audits_and_reverts`：红，新来源筛选为空 → 绿。
- `test_member_can_preview_and_invalid_requests_are_safe`：修正夹具后首绿；复用鉴权、参数校验及前一切片的报告检查。
- `test_origin_filter_counts_follow_index`：红，计数仍为未知 5、开源 0 → 绿。
- `test_migration_preserves_populated_index_and_expands_origins`：红，没有 0011 迁移 → 绿。

两项变异抽查均触发预期失败：重序列化血缘、索引来源固定为 `unknown`。前端三项按本次分段要求跳过，未计为通过。