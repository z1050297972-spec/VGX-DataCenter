**1. 改动清单**

契约骨架已完成，未暂存、未提交。

- [路由](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/api/datasets/__init__.py)：10 个操作已挂载，共用 M0 认证、Origin、强制改密及诊断边界。
- [请求与响应模型](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/schemas.py)、[服务契约](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/service.py)：新增函数均为六项 docstring 加 `raise NotImplementedError`。
- [布局表模型](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/preference_models.py)、[pending 迁移](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/infra/db/migrations/pending/v0008_dataset_layout.py)：活动 head 保持 0007。
- [依赖契约](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/pyproject.toml:153)：新增存储访问禁入规则。
- [测试清单](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/tests/test_dataset_api_contract.py)：36 个跳过测试，覆盖验收 2–7；旧迁移测试调整为检查 pending 不进入活动迁移图。
- 审计新增 `SET_DATASET_LAYOUT`、`dataset_layout` 字段及前端展示。
- OpenAPI、TypeScript 类型均由 `make api-types` 生成。

未访问 `/mnt`、联网、安装依赖或启动部署；临时日志已清理。

**2. `make check` 末尾输出原样**

退出码 0。后端结果为 `2190 passed, 36 skipped, 8 warnings`；36 个跳过均属本票骨架清单。

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
   Start at  06:36:16
   Duration  7.53s (tests 48%, environment 29%, import 21%, transform 1%)
```

**3. 契约变更申请、依赖申请**

- 已合并契约含义变更申请：无。
- 依赖申请：无。
- 本次新增契约包括布局表、接口及布局审计字段，提交本轮骨架关卡审核；已有操作码、索引表和迁移未改写。

**4. 骨架关卡要看的东西，以及拿不准的地方**

接口前缀均为 `/api/datasets`。共享筛选 **F**：

`robot_model_id、robot_type、fps、data_origin、view、format、version、entry_path`。

通用错误 **E**：400 数据问题、401 未认证、403 Origin/强制改密、409 冲突、422 参数错误、500 缺陷、502 外部失败。错误响应复用 `application/problem+json`；OpenAPI 保留 M0 的统一错误声明。

| 方法、路径 | 请求字段 | 成功响应字段 | 错误 |
|---|---|---|---|
| GET 空路径 | F、`offset、limit` | `items、total、offset、limit、indexed_at` | E |
| GET `/trees` | F | `nodes、indexed_at` | E |
| GET `/filters` | 无 | `robot_models_registered、default_robot_filter、robot_models、robot_model_options、robot_types、fps、data_origins` | E |
| GET `/panel` | 可选 `dataset_id` | `findings、storage_roots、indexed_at` | E、404 |
| GET `/detail` | `entry_path` | `entry、entries、canonical_entry_path、original_paths、information、canonical_information、sources、links、dataset_size、subtasks_entry_path、index_stale、indexed_at、observed_at、diagnostics` | E、404 |
| GET `/subtasks` | `entry_path` | 原始文本及下述响应头 | E、404 |
| POST `/{dataset_id}/rescan` | 路径编号，无请求体 | 201，既有 `JobResponse` | E、404 |
| POST `/sizing` | `dataset_id`，显式 null 为全量 | 201，既有 `JobResponse` | E、404 |
| GET `/layout` | 无 | `layout、updated_at` | E |
| PUT `/layout` | `layout: A/B/C` | `layout、updated_at` | E |

嵌套字段、类型及空值语义完整列在上述模型文件与生成的 [schema.d.ts](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/web/src/api/schema.d.ts)。其中大小明确区分统计值、记录值和未知；树区分数据集数与入口数，未知大小不充当零。

布局表 `dataset_layout_preferences`：

| 字段 | 约束 |
|---|---|
| `account_id` | INTEGER 主键、正整数，外键 accounts，删除级联 |
| `layout` | VARCHAR(1)，非空，CHECK A/B/C |
| `updated_at` | UTCDateTime，底层 TEXT，非空 |

无行读取返回 A/null；GET 不建行；同值保存不重复写入或记日志；重建索引不清偏好。

import-linter 的核心写法：

```toml
type = "forbidden"
source_modules = ["rdp.api.datasets", "rdp.jobs.dataset_browser"]
forbidden_modules = [
    "rdp.jobs.datasets",
    "rdp.jobs.storage",
    "rdp.infra.storage",
    "rdp.jobs.execution",
    "rdp.jobs.worker",
    "rdp.jobs.registry",
    "rdp.api.storage",
]
allow_indirect_imports = false
ignore_imports = [
    "rdp.jobs.dataset_browser.service -> rdp.jobs.service",
    "rdp.jobs.dataset_browser.schemas -> rdp.jobs.datasets.catalog",
    "rdp.jobs.dataset_browser.schemas -> rdp.jobs.datasets.types",
]
```

三条豁免分别用于既有 M0 提交服务、纯常量、纯类型；实际文件访问仍需实现阶段的假根及换链测试验证。

14 MB 子任务的返回契约：

- 独立返回 `text/plain; charset=utf-8` 原字节，不包装成 JSON 字符串。
- 沿用既有 32 MiB 上限，在工作线程受限读取完毕后发送，避免重新按路径打开。
- 返回 `Content-Length、X-Index-Stale、X-Document-SHA256、X-Observed-At、Cache-Control: no-store、X-Content-Type-Options: nosniff`。
- 前端按文本接收，交工作线程解析。

需关卡留意的选择：

- **统计作业键**固定在 `DATASET_SIZING_JOB_TYPE = "dataset_sizing"`；合并第 02 张时对齐登记键和参数形状。
- 型号表尚不存在：采用显式型号读取器，M1 空目录适配，M3 接真实表；未提前建型号表。
- 完整 L12 复核仍会读取子任务字节；独立接口隔离的是正文传输。真实响应耗时尚未测量，留给 Claude 的验收 1。
- 树只展示索引已有入口及父节点；空版本目录没有索引记录，不额外读取导航补齐。