合并对齐。执行线已经把你的工作提交到分支上（"实现：建链与新增数据集"），然后在工作目录里执行了 `git merge --no-commit main`。main 上新增了第 10 张（数据来源标注）：一个作业类型 `nav_data_origin_preview`、迁移 `0011_data_origin`、`EntrySnapshot.data_origin`、详情里的 `provenance`、前端的 `DataOrigin.tsx`。有 7 个文件冲突：
- src/rdp/jobs/registry.py
- src/web/src/api/openapi.json、src/web/src/api/schema.d.ts（生成文件）
- tests/test_jobs_registry.py、tests/test_jobs_scheduling_config.py、tests/test_jobs_storage.py、tests/test_ops_runtime.py

请这样处理：
1. registry 两边的登记都保留（你加的两种创建预览，第 10 张加的数据来源预览），生产类型数相应变成 12（以实际为准），测试断言同步改。
2. 生成文件冲突不要手工合，先解决其他冲突，再跑 `make api-types` 重新生成。
3. 检查你新增的代码和第 10 张有没有语义上的冲突，例如新增数据集时写的 来源.json、详情响应的字段，两边都要能正常工作。
4. `make check` 全绿、0 skipped；vite build 主入口低于 500 kB，跑完删掉 dist。

可以 `git add` 你解决了冲突的文件，但**不要 git commit**，合并提交由执行线做。其他边界不变。20 分钟内交，报告写怎么解决的和 make check 汇总行。
