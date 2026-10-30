合并对齐。执行线已经把你的工作提交到分支上（"实现：页面编辑导航层内容"），然后在工作目录里执行了 `git merge --no-commit main`。main 上新增了 M1.5 第 01 张（原文件只读查看器：两个 GET 接口、FileViewer、import-linter 例外）。现在有 3 个文件冲突：
- src/web/src/api/openapi.json、src/web/src/api/schema.d.ts（生成文件）
- tests/test_dataset_api_contract.py

请这样处理：
1. 测试文件里两边新增的路由和断言都保留。
2. 先解决测试文件，再跑 `make api-types` 重新生成那两个生成文件，不要手工合并。
3. 检查语义上有没有冲突：两边都改过 Details.tsx 和 import-linter，要确认查看器和编辑器都能用。
4. `make check` 全绿、0 skipped；vite build 主入口低于 500 kB，跑完删掉 dist。

你在沙箱里做不了 `git add`，改好文件就行，暂存和提交由执行线来做。15 分钟内交，报告写怎么解决的和 make check 的汇总行。
