**1．改动清单**

后端和前端已完成，改动留在工作区，未暂存、未提交。

新增字段编辑模块、分页表单、逐字段预览、确认、撤回及测试；复用现有 navwrite 流水线。

共用文件逐处改动：

| 文件 | 改动 |
|---|---|
| `src/rdp/api/__init__.py` | 登记编辑路由 |
| `src/rdp/jobs/registry.py` | 登记预览作业 |
| `src/rdp/jobs/navwrite/models.py` | 增加操作码 |
| `src/rdp/audit/types.py` | 增加审计操作和白名单 |
| `pyproject.toml` | 将新 worker 模块加入 import-linter 禁止入口直接依赖的清单 |
| `src/web/src/datasets/Details.tsx` | 接入编辑器 |
| `src/web/src/datasets/Information.tsx` | 展示保存的人工字段 |
| `src/web/src/jobs/Pages.tsx` | 接入撤回 |
| `src/web/src/audit/search.ts` | 增加操作中文名 |
| `src/web/src/api/openapi.json`、`schema.d.ts` | 经 `make api-types` 生成 |
| `tests/test_dataset_api_contract.py` | 扩展路由清单 |
| `tests/test_jobs_registry.py` | 扩展类型数量 |
| `tests/test_jobs_scheduling_config.py` | 扩展生产登记清单 |
| `tests/test_jobs_storage.py` | 保留空存储声明检查 |
| `tests/test_navwrite_audit_migration.py` | 扩展操作码和导入边界清单 |
| `tests/test_ops_runtime.py` | 扩展运行时登记数量 |

**2．检查结果**

`make check` 全绿，**0 skipped**：

```text
2560 passed, 8 warnings
Test Files  36 passed (36)
Tests       354 passed (354)
```

Vite 构建通过，主入口 **55,433 字节，低于 500 kB**；`dist` 已删除。[检查日志](/tmp/m15-field-check.log)

**3．契约变更申请**

仅增加契约，未改变已合并契约含义：

- `数据集信息.json` 顶层增加 `robot_model: string`、`scene: string`、`tasks: string[]`。
- 增加 `nav_fields_preview` 作业和 `edit_dataset_fields` 操作码。
- 增加分页读取、编辑预览及确认接口。
- 无新增依赖、无数据库迁移。请执行线将字段名和位置登记到导航层手册。

**4．演练请求与 aria-label**

先分别读取两份文件，取响应中的 `sha256`：

```text
GET /api/datasets/dataset-14/editable-fields?document=数据集信息.json
GET /api/datasets/dataset-14/editable-fields?document=子任务.json&offset=0&limit=20
```

使用实际编号和返回哈希提交：

```json
POST /api/navigation/fields/preview
{
  "dataset_id": "dataset-14",
  "changes": [
    {"document":"数据集信息.json","expected_sha256":"<信息哈希>","path":["robot_model"],"value":"Franka"},
    {"document":"数据集信息.json","expected_sha256":"<信息哈希>","path":["scene"],"value":"厨房"},
    {"document":"数据集信息.json","expected_sha256":"<信息哈希>","path":["tasks"],"value":["开门","整理"]},
    {"document":"数据集信息.json","expected_sha256":"<信息哈希>","path":["fields",5,"value_markdown"],"value":"人工更新的第六项"},
    {"document":"子任务.json","expected_sha256":"<子任务哈希>","path":["tasks",0,"description"],"value":"人工更新的描述"}
  ]
}
```

预览成功后：

```text
GET  /api/navigation/previews/<预览编号>
POST /api/navigation/fields/previews/<预览编号>/apply
```

浏览器定位：

`编辑导航层字段` → `选择编辑文件` → `机器人型号`／`场景`／`任务` → `预览字段改动` → `字段预览差异` → `确认字段写入`。作业完成后使用 `预览撤回导航改动` → `确认撤回导航改动`。

子任务描述标签为 `1 · <task_key> · 描述`；分页为 `编辑上一页`、`编辑下一页`。

待执行线实测：真实副本完整流程及撤回、14 MB 文件体验、1280×900 页面横向溢出。场景和任务目前允许自由输入，词表由第 03 张接续。未访问 `/mnt` 或真实部署。

**5．先红后绿**

新增 **9 个后端测试、5 个前端测试**，均逐个单跑见红后实现并转绿。覆盖同步、分页、非法输入、身份不一致、填表过期、确认冲突、锁内冲突及撤回。

临时探针中的三处变异全部被检出：跳过副本生成、跳过确认复核、跳过 worker 锁内复核。[变异记录](/tmp/m15-field-mutations.json)