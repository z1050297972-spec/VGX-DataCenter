状态：全部完成

## 1. 改动清单

- `src/web/src/mountWeb.tsx`：增加 `ConfigProvider`，使用 antd 明暗算法跟随系统切换；缺少 `matchMedia` 时使用浅色。不改变路由或查询逻辑。
- `src/web/src/shell.css`：增加深色变量；保留原浅色 antd 变量覆盖，深色组件颜色交由暗色算法计算；保留两种主题下的降级开关。

测试文件未修改；改动未暂存、未提交。

## 2. 深色变量表

以下变量名均省略 `--rdp-` 前缀。表中为默认值；降级开关生效时会按原有规则覆盖部分值。

| 变量 | 浅色 | 深色 |
|---|---|---|
| `page` | `#f5f5f7` | `#000` |
| `surface` | `#fff` | `#1c1c1e` |
| `subtle` | `#f5f5f7` | `#2c2c2e` |
| `text` | `#1d1d1f` | `#f5f5f7` |
| `muted` | `#68686d` | `#aaaab0` |
| `on-accent` | `#fff` | `#fff` |
| `accent` | `#0068d1` | `#69b1ff` |
| `accent-fill` | `#0068d1` | `#1668dc` |
| `accent-fill-hover` | `#0059b3` | `#3c89e8` |
| `accent-fill-active` | `#004b99` | `#1554ad` |
| `accent-hover` | `#0059b3` | `#91caff` |
| `accent-active` | `#004b99` | `#4096ff` |
| `accent-soft` | `#e7f2ff` | `#112a45` |
| `accent-soft-hover` | `#d6eaff` | `#15395b` |
| `accent-border` | `#a3cfff` | `#245b8c` |
| `accent-border-hover` | `#70b5ff` | `#337fb8` |
| `border` | `#d2d2d7` | `#48484a` |
| `glass-border` | `rgb(255 255 255 / 70%)` | `rgb(255 255 255 / 16%)` |
| `glass-top` | `#fff` | `rgb(255 255 255 / 24%)` |
| `glass` | `rgb(255 255 255 / 82%)` | `rgb(40 40 42 / 85%)` |
| `glass-opaque` | `#fff` | `#28282a` |
| `hover` | `rgb(0 0 0 / 6%)` | `rgb(255 255 255 / 10%)` |
| `shadow` | `0 4px 20px rgb(0 0 0 / 5%)` | `0 4px 20px rgb(0 0 0 / 35%)` |
| `dock-shadow` | `0 8px 32px rgb(0 0 0 / 16%)` | `0 8px 32px rgb(0 0 0 / 55%)` |

其余变量在两种主题下相同：

| 变量 | 浅色和深色 |
|---|---|
| `blur` | `20px` |
| `saturation` | `160%` |
| `radius-card`、`radius-control`、`radius-small`、`radius-pill` | `18px`、`10px`、`6px`、`999px` |
| `line` | `1px` |
| `space-1` 至 `space-7` | 依次为 `4px`、`8px`、`12px`、`16px`、`24px`、`32px`、`48px` |
| `space-dock`、`space-select-y`、`space-select-x` | `6px`、`7px`、`11px` |
| `width-audit-result`、`width-filter-medium`、`width-audit-kind` | `120px`、`150px`、`160px` |
| `width-filter-wide`、`width-origin-select`、`width-filter-scene` | `180px`、`200px`、`210px` |
| `width-filter-tasks`、`width-origin-table` | `280px`、`640px` |
| `content-width` | `1280px` |
| `scrollbar-track` | `transparent` |
| `dock-clearance` | `calc(100px + env(safe-area-inset-bottom))` |
| `z-header`、`z-dock` | `10`、`20` |
| `font` | `-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif` |
| `mono` | `ui-monospace, "SF Mono", Menlo, Consolas, monospace` |
| `transition` | `160ms ease` |
| `motion-fast`、`motion-mid`、`motion-slow` | `0.1s`、`0.2s`、`0.3s` |

**ConfigProvider token：**`colorPrimary`、`colorBgContainer`、`colorBgElevated`、`colorBgLayout`、`borderRadius`、`fontFamily`、`fontFamilyCode`。浅色使用 `defaultAlgorithm`，深色使用 `darkAlgorithm`。

## 3. `make check`

最后一次运行的命令：

```bash
make check > /tmp/rdp-ui06-check.log 2>&1; result=$?; tail -35 /tmp/rdp-ui06-check.log; exit "$result"
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
================= 2757 passed, 8 warnings in 110.55s (0:01:50) =================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.HDLZcfxR17/openapi.json → /tmp/tmp.HDLZcfxR17/schema.d.ts [483.6ms]
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
   Start at  21:35:08
   Duration  12.65s (tests 58%, import 18%, environment 17%, transform 6%, setup 2%)
```

## 4. 拿不准、需要评审决定的地方

按要求未截图。**浅色一致性及深色各组件的视觉效果仍需执行线通过 headless Chrome 截图验收**；检查链通过不能替代视觉验收。