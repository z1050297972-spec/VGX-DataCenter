状态：全部完成

**原因已核实。**加入主题配置后，antd 为 Select 等组件生成了新的 `css-var-*` 作用域，原先的 `.css-var-root.css-var-root` 浅色覆盖因此未匹配。此外，上次实现向浅色主题传入了种子 token，会改变 antd 预计算的组件派生值。

**修法：**

- 将 `ConfigProvider` 的 `cssVar.key` 固定为 `css-var-root`，恢复浅色原有覆盖；深色仍不应用该浅色覆盖。
- 浅色不再传入自定义种子，保留合并前的默认派生 token；深色算法和种子值保持不变。
- 将深色种子集中到带同步说明的常量对象，并在 `shell.css` 中补充对应的弹出层变量。
- 用不落盘的 antd 渲染核对：修复后的 Select DOM 与浅色基线一致；浅色和深色的完整派生 token 分别与对应基线一致。

改动仍只涉及 `mountWeb.tsx` 和 `shell.css`，测试文件未改、未暂存或提交。按原要求未截图；逐像素视觉对比仍交由执行线验收。

## `make check`

最后一次运行的命令：

```bash
make check > /tmp/rdp-ui06-fix-check.log 2>&1; result=$?; tail -35 /tmp/rdp-ui06-fix-check.log; exit "$result"
```

末尾输出：

```text
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /home/shawn/桌面/robot-data-platform.wt/ui-style/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2757 passed, 8 warnings in 91.95s (0:01:31) ==================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.oHD79xJyxS/openapi.json → /tmp/tmp.oHD79xJyxS/schema.d.ts [142.2ms]
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
   Start at  21:44:02
   Duration  13.16s (tests 61%, import 18%, environment 17%, setup 2%, transform 1%)
```