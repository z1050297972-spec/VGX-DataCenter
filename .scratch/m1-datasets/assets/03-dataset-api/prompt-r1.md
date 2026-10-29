评审第 1 轮，任务是合并对齐。执行线已经把 main（含第 02 张）合进了你的工作目录，没有提交，也没有文本冲突。全量检查只失败 1 项：
```
FAILED tests/test_dataset_api_contract.py::test_all_endpoints_with_unreadable_storage_roots
rdp.infra.diagnostics.DefectError（registry.py:138，dataset_sizing 重复登记）
```
原因：测试自己登记了一个 `dataset_sizing` 替身，现在第 02 张的正式登记已经有这个键了，于是重名。

修法：
- `commands.py` 删掉 `DATASET_SIZING_JOB_TYPE`，改用 `rdp.jobs.datasets.catalog.SIZING_TYPE`。参数模型复用第 02 张定义的那个（在 `rdp.jobs.datasets.sizing` 或 `catalog` 里，你去找），不要自己再定义一份，形状同样是 `{"dataset_id": str | null}`。注意 import-linter：commands 不在禁入契约里，可以 import；queries 和 schemas 仍然不能经任何路径碰到存储根访问。
- 测试里的替身登记都删掉，改用 `production_registry()`；断言"只插作业行，Web 不执行"的意思不变。
- 顺带检查：OpenAPI 里统计提交的请求模型要和第 02 张的参数一致，有变化就用 `make api-types` 重新生成。

不要提交，合并状态原样保留（MERGE_HEAD 在）；你只能改工作区里的文件，提交由执行线来做。最后跑一次 `make check`，0 skipped。边界不变。20 分钟内交付。最终回复五块，第 1、5 块只写本轮。
