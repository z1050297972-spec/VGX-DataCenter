状态：全部完成

根据现有 CSS 和复测结果，最可能的原因是三个页面的单列 Grid 使用了默认的自动最小轨道宽度：宽表格的内容宽度反向撑大了页面列，页头也随之变宽。

本次修改：

- 将账号、调度、作业页面及相关内层 Grid 的列设为 `minmax(0, 1fr)`，并给需要收缩的容器设置 `min-width: 0`。
- 保留表格已有的横向滚动配置，让宽表格在卡片内部滚动，而不是撑宽页面。
- 在 640px 及以下，将账号和作业页的标题与操作项分行排列；作业操作链接仍可继续换行。

未改测试或业务逻辑。**没有自行进行 390px 浏览器复测**，需由执行线按现有脚本确认页面宽度和表格滚动效果。

### `make check`

最后一次运行的命令：

```bash
make check > /tmp/rdp-t05-mobile-final.log 2>&1; result=$?; tail -n 35 /tmp/rdp-t05-mobile-final.log; exit "$result"
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
================= 2757 passed, 8 warnings in 97.79s (0:01:37) ==================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.mttxd2oGIs/openapi.json → /tmp/tmp.mttxd2oGIs/schema.d.ts [239ms]
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
   Start at  21:20:12
   Duration  12.09s (tests 61%, import 18%, environment 17%, setup 2%, transform 2%)
```