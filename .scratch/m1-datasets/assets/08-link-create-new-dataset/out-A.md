**1 改动清单**

已交契约骨架，新增函数体仅抛出未实现异常。

- 后端：参数/结果模型、两个 builder、预览作业声明、提交服务及五个 HTTP 接口。见 [create_builders.py](/home/shawn/桌面/robot-data-platform.wt/m1-08-link-create-new-dataset/src/rdp/jobs/navwrite/create_builders.py)、[creation.py](/home/shawn/桌面/robot-data-platform.wt/m1-08-link-create-new-dataset/src/rdp/api/datasets/creation.py)。
- 前端：页面、表单、预览、排队提醒、冲突组件及流程类型。见 [CreationPages.tsx](/home/shawn/桌面/robot-data-platform.wt/m1-08-link-create-new-dataset/src/web/src/datasets/CreationPages.tsx)。
- 新增 65 个 pytest skipped、20 个 Vitest skipped；同步旧 OpenAPI 接口数量断言。
- 已运行 `make api-types`。仅修改 `src/`、`tests/`，未暂存或提交；临时日志已清理。

**2 `make check` 末尾输出**

退出码 **0**。pytest：`2469 passed, 65 skipped, 8 warnings`；全部 skipped 属于本票。

```text
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  32 passed | 1 skipped (33)
      Tests  319 passed | 20 skipped (339)
   Duration  9.27s
```

**3 契约变更申请、依赖申请**

申请新增 `PlanReport.creation: CreationDetails | None = None`，保存创建操作的结构化预览差异；历史预览缺字段时为 `None`。不改变既有操作含义。

依赖申请：无。

**4 骨架关卡审阅点与待确认项**

接口统一位于 `/api/datasets`：

| 方法、路径 | 请求字段 / 返回 |
|---|---|
| `GET /creation-options` | 返回格式登记、版本候选、数据来源 |
| `POST /link-previews` | `dataset_id, link, format_entries` → 201 作业 |
| `POST /creation-previews` | `dataset_name, data_origin, link, format_entries` → 201 作业 |
| `GET /creation-previews/{preview_job_id}` | 返回成功预览 |
| `POST /creation-writes` | `preview_job_id, acknowledged_queue_job_ids` → 确认结果 |

其中 `link` 包含 `name, target_path, fallback_format`；格式选择包含 `format, version`。

预览返回编号、时刻、操作、数据集身份、参数、`report`、`queued_jobs`。`report.creation` 列出文件、目录、链接、所选及重生成的格式入口、新增数据块、`dataset_roots`、格式/版本来源和 `noop`，不返回执行计划正文。

- **建链计划**：规范入口建链接、更新清单，再复用底座生成格式副本；同目标且已登记时零步骤成功。
- **新增计划**：创建规范目录、首链接、三份 JSON 和 `来源.json`，再创建勾选格式入口的目录、链接及三份 JSON。确认后统一交 `nav_write_apply`。
- **名称规则**：拒绝空名、NUL、`/`、`.` 开头及四份 JSON 保留名；数据集名另查重。目标检查登记根、在线状态、realpath 边界及非导航层目标。
- **页面流程**：填参数 → worker 预览 → 审阅差异 → 明确确认及排队提醒 → 作业页；改参数或冲突后重新预览。

需关卡确认：确认写入接口采用 **HTTP 200 双分支**——未确认的新排队提醒返回 `job=null`；确认完成后返回新写入作业。真实副本及浏览器演练留到实现阶段。