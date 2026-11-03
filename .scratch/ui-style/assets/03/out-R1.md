状态：全部完成

1. **说明行**：仅在一致性面板未打开时显示；“一致性面板 / 返回数据集”按钮始终可见。
2. **筛选卡**：大屏筛选列平均占满可用宽度，窄屏保留换行；机器人型号模式的“更多筛选”按钮按行底部对齐。
3. **页头**：收紧面包屑与标题的间距及标题外边距，右侧操作区与标题区垂直居中。
4. **列表**：三段分类信息之间使用 CSS 伪元素显示 `·`，保留灰色小字。
5. **全局表头**：在 `shell.css` 中覆盖 antd 表头样式，使背景透明、文字为灰色小字。
6. **详情头部**：返回按钮、标题和操作按钮排在同一行；四项摘要收紧为两列、行距 8px，编号和路径使用等宽小字。
7. **详情分节**：统一小标题外观，在分节间加入间距为 24px 的 `Divider`；移除数据集大小的嵌套卡片，将三个操作入口放到标题右侧；字段编辑说明改为灰色小字。原有 h4/h5 语义级别保留，通过 CSS 统一外观。
8. **导航层人工信息**：保留 `dl` 语义，用 CSS grid 对齐标签和值，标签显示为灰色并通过伪元素补充冒号。
9. **Dock**：增加专用的 `--rdp-space-dock: 6px`，恢复原有内边距。

**测试兼容处理：**第一次完整检查时，三套布局的“返回列表后筛选保留”测试超时。随后调整为让返回按钮在详情加载前后保持同一个 DOM 节点；未修改测试，重新运行后全部通过。

未新增依赖，未修改测试文件；改动留在工作区，未暂存、未提交。

## `make check`

最后一次运行命令：

```bash
make check > /tmp/rdp-ui-review-check-final.log 2>&1; code=$?; tail -35 /tmp/rdp-ui-review-check-final.log; exit "$code"
```

末尾输出原文：

```text
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /home/shawn/桌面/robot-data-platform.wt/ui-style/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2757 passed, 8 warnings in 109.20s (0:01:49) =================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.PXsIteySQd/openapi.json → /tmp/tmp.PXsIteySQd/schema.d.ts [149.8ms]
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
   Start at  05:50:01
   Duration  13.47s (tests 60%, import 19%, environment 18%, setup 2%, transform 1%)

```