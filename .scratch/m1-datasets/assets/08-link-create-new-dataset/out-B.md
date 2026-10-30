**1 改动清单**

后端检查点已完成：两种预览构造、校验、HTTP 接口和作业执行已实现，写入复用 `nav_write_apply`。新增 65 项后端测试全部启用；前端仅同步 409/201 契约，20 项测试继续跳过。

共用文件改动：

- `registry.py`：登记两个创建预览类型。
- `navwrite/policy.py`、`jobs.py`：归并 `NAV_APPLY_TYPE` 常量，保留旧导入路径。
- `test_jobs_registry.py`、`test_jobs_scheduling_config.py`、`test_jobs_storage.py`、`test_ops_runtime.py`：同步十一种生产类型的断言。

未暂存、未提交；临时脚本和日志已清理。

**2 `make check` 汇总和末尾输出**

退出码 **0**，Python 零跳过，前端跳过仅为本票保留项。

```text
2534 passed, 8 warnings in 82.93s
OpenAPI 与生成类型均未过期
All matched files use Prettier code style!

Test Files  32 passed | 1 skipped (33)
     Tests  319 passed | 20 skipped (339)
  Duration  9.00s
```

**3 契约变更申请**

无新增申请、无新依赖。

已落实获批变更：未确认的新排队写作业返回 **409**；诊断规则为 `NAV_CREATE_QUEUE_CONFIRMATION`，对象键 `queued_job_id_N` 列出编号。确认成功返回 **201 + JobResponse**。

**4 副本演练交接**

使用第 07 张副本配置运行本分支 Web 和 worker，导航根必须指向副本。

- 建链用 **libero_10**，编号从数据集接口读取。
- 目标由执行线只读挑选：登记本地根内已有、非软链接的真实目录。要展示三类追加变化，应选尚未被该数据集链接、数据块及 `dataset_roots` 覆盖的目录。
- 不为演练在真实数据盘上新建目录；写入只改副本导航，目标数据不修改。

新增数据集参数例子，`target_path` 是须替换的占位路径；此例适用于缺少元信息的 mcap 目标：

```json
{
  "dataset_name": "M1_08_演练",
  "data_origin": "开源下载",
  "link": {
    "name": "原始数据",
    "target_path": "/REGISTERED_LOCAL_ROOT/EXISTING_DIRECTORY",
    "fallback_format": "mcap"
  },
  "format_entries": [{"format": "mcap"}]
}
```

流程：提交 `/api/datasets/creation-previews` → 等预览作业完成 → 读取对应预览 → 向 `/api/datasets/creation-writes` 提交文本 `preview_job_id`。遇队列 409，确认诊断中的编号后带 `acknowledged_queue_job_ids` 重提。

真实目标和副本当前最大编号尚未现场核验；只有最大编号为 35 时才预计分配 `dataset-36`。下一段剩余前端实现、20 项 Vitest，以及依据副本演练反馈调整。

**5 先红后绿**

8 项完成业务红→绿；其余 57 项首次即绿，逐项原因已记录在 [TDD 记录](/home/shawn/桌面/robot-data-platform.wt/m1-08-link-create-new-dataset/tests/creation_tdd_evidence.json)。

所有单项验证均经 `make check` 选择测试并限制一个 pytest worker，最后执行了全量检查。