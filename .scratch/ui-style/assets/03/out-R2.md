状态：全部完成

1. **原文件查看器**：已从大小分节的 `actions` 中移出，放在大小信息下方独占一行；标题右侧只保留“重新检查”和“统计大小”。未拆改 `FileViewerEntry` 内部结构。
2. **分隔线**：移除了分节内部及详情中的 `Divider`，改由非空分节容器统一绘制上边线，并留出 24px 间距。空分节不画线；人工信息存在时，才与“14 项数据集信息”之间画分隔线。
3. **数据来源控件**：下拉框与“预览改动”按钮使用 antd `Flex gap` 分隔，窄屏可换行。

未修改测试文件或新增依赖；改动留在工作区，未暂存、未提交。

## `make check`

命令：

```bash
make check > /tmp/rdp-ui-r2-check.log 2>&1; code=$?; tail -30 /tmp/rdp-ui-r2-check.log; exit "$code"
```

末尾输出原文：

```text
  /home/shawn/桌面/robot-data-platform.wt/ui-style/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2757 passed, 8 warnings in 133.24s (0:02:13) =================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.2JbyFPdojc/openapi.json → /tmp/tmp.2JbyFPdojc/schema.d.ts [146.7ms]
OpenAPI 与生成类型均未过期
[8/12] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/12] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/12] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/12] stylelint
cd src/web && node_modules/.bin/stylelint "src/**/*.css"
[12/12] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/ui-style/src/web


 Test Files  41 passed (41)
      Tests  380 passed (380)
   Start at  05:59:05
   Duration  12.25s (tests 60%, import 19%, environment 18%, setup 2%, transform 1%)

```