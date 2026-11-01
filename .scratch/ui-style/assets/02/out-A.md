状态：全部完成

## 1. 改动清单

改动均留在工作区，未暂存、未提交；未修改测试文件、`accounts/Pages.tsx` 或 `jobs/Pages.tsx`。

- `Makefile`：在 Prettier 后加入 stylelint，检查步骤由 11 步顺延为 12 步。
- `src/web/eslint.config.js`：禁止 JSX `style` 属性；对 M2 正在修改的两个页面按文件临时关闭该规则。
- `src/web/stylelint.config.js`：新增 stylelint 配置和 `shell.css` 覆盖项。
- `src/web/src/shell.css`：增加保留原布局所需的宽度变量；为既有选择器和调试开关添加单条豁免。
- `src/web/src/audit/Pages.tsx`：引入样式并替换三处内联 style。
- `src/web/src/audit/audit.css`：新增 `audit-page`（`minWidth: 0, maxWidth: "100%"`）、`audit-kind-select`（`minWidth: 160`）、`audit-result-select`（`minWidth: 120`）。
- `src/web/src/navigation/Pages.tsx`：引入样式并替换三处内联 style。
- `src/web/src/navigation/navigation.css`：新增 `navigation-page`（`maxWidth: "100%"`）、`navigation-action`（两处 `marginTop: 16`）。
- `src/web/src/datasets/Filters.tsx`：引入浏览样式并替换六处内联 style。
- `src/web/src/datasets/browser.css`：新增 `browser-filter-wide`（两处 `minWidth: 180`）、`browser-filter-medium`（两处 `minWidth: 150`）、`browser-filter-scene`（`width: 210, maxWidth: "100%"`）、`browser-filter-tasks`（`width: 280, maxWidth: "100%"`）。
- `src/web/src/datasets/DataOrigin.tsx`：引入样式并替换四处内联 style。
- `src/web/src/datasets/dataOrigin.css`：新增 `origin-section`（`position: "relative", minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere"`）、`origin-select`（`width: 200, maxWidth: "100%", margin: "12px 0"`）、`origin-scroll`（`minWidth: 0, maxWidth: "100%", overflowX: "auto"`）、`origin-table`（`minWidth: 640, width: "100%", tableLayout: "fixed", overflowWrap: "anywhere"`）。
- `src/web/src/datasets/CreationForms.tsx`：引入创建样式，两处 `width: "100%"` 改用 `creation-select-full`。
- `src/web/src/datasets/CreationFields.tsx`：引入创建样式，`width: "100%"` 改用 `creation-select-full`。
- `src/web/src/datasets/creation.css`：新增 `creation-select-full`，对应上述三处 `width: "100%"`。
- `src/web/src/datasets/FileViewer.tsx`：`width: "100%"` 改用 `file-viewer-select-full`。
- `src/web/src/datasets/fileViewer.css`：新增 `file-viewer-select-full`，对应文件查看器选择框的 `width: "100%"`。
- `src/web/src/datasets/Repoint.tsx`：引入样式，`width: "100%"` 改用 `repoint-select-full`。
- `src/web/src/datasets/repoint.css`：新增 `repoint-select-full`，对应 `width: "100%"`。
- `src/web/src/datasets/Markdown.tsx`：引入样式，`whiteSpace: "pre-wrap"` 改用 `markdown-paragraph`。
- `src/web/src/datasets/markdown.css`：新增 `markdown-paragraph`，对应 `whiteSpace: "pre-wrap"`。
- `src/web/src/datasets/FieldSummary.tsx`：引入样式，`minWidth: 0, overflowWrap: "anywhere"` 改用 `field-summary`。
- `src/web/src/datasets/fieldSummary.css`：新增 `field-summary`，对应 `minWidth: 0, overflowWrap: "anywhere"`。

## 2. `make check`

最后一次运行的命令：

```bash
make check > /tmp/ui-style-check.log 2>&1; result=$?; tail -n 45 /tmp/ui-style-check.log; exit "$result"
```

退出码为 0。末尾输出原文：

```text
........................................................................ [ 87%]
........................................................................ [ 90%]
........................................................................ [ 92%]
........................................................................ [ 95%]
........................................................................ [ 98%]
............................................                             [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /home/shawn/桌面/robot-data-platform.wt/ui-style/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2636 passed, 8 warnings in 94.94s (0:01:34) ==================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.0wDIPHXnLD/openapi.json → /tmp/tmp.0wDIPHXnLD/schema.d.ts [128ms]
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


 Test Files  39 passed (39)
      Tests  373 passed (373)
   Start at  01:44:46
   Duration  10.80s (tests 57%, import 20%, environment 19%, setup 2%, transform 1%)
```

## 3. 三个关键行为的验证

试验改动均已撤回。

**ESLint 拦截内联 style：**

```text
$ cd src/web && node_modules/.bin/eslint src/audit/Pages.tsx --max-warnings 0

/home/shawn/桌面/robot-data-platform.wt/ui-style/src/web/src/audit/Pages.tsx
  53:37  error  静态样式使用 CSS 类；运行时值须说明原因，见 CODING_STANDARDS 10.9。  no-restricted-syntax

✖ 1 problem (1 error, 0 warnings)
```

**stylelint 拦截页面 CSS 的写死颜色：**

```text
$ cd src/web && node_modules/.bin/stylelint src/audit/audit.css

src/audit/audit.css
  12:28  ✖  Disallowed hex color "#f00"  color-no-hex

✖ 1 problem (1 error, 0 warnings)
```

**stylelint 拦截没有说明的 `!important` 豁免：**

```text
$ cd src/web && node_modules/.bin/stylelint src/audit/audit.css

src/audit/audit.css
  13:3  ✖  Disable for "declaration-no-important" is missing a description  --report-descriptionless-disables

✖ 1 problem (1 error, 0 warnings)
```

## 4. stylelint 配置及豁免

关闭的 `stylelint-config-standard` 规则：

| 规则 | 理由 |
|---|---|
| `comment-empty-line-before`、`rule-empty-line-before`、`at-rule-empty-line-before` | 空行由 Prettier 管理，不强制改写既有排版。 |
| `media-feature-range-notation` | 保留既有 `min-width` / `max-width` 断点写法。 |
| `value-keyword-case` | 保留既有字体名的常见大小写写法。 |
| `property-no-vendor-prefix` | 保留旧版 WebKit 所需的 `-webkit-backdrop-filter`。 |
| `selector-not-notation` | 保留既有合法的 `:not()` 写法。 |
| `no-descending-specificity` | 保留既有层叠顺序，避免为通过形式检查而重排规则。 |

单条豁免：

- `shell.css:174`：豁免 `selector-max-compound-selectors`；既有顶栏结构没有类名，需要限定菜单以外的子项。
- `shell.css:259`：豁免 `selector-max-id`；既有登录卡片通过 `#root` 限定范围。
- `shell.css:325`：豁免 `declaration-no-important`；调试开关必须覆盖 antd 和内联动画时长。
- `shell.css:327`：豁免 `declaration-no-important`；调试开关必须覆盖 antd 和内联过渡时长。

此外，`shell.css` 按配置覆盖放开颜色和媒体特性限制，因为它负责定义设计变量与全局降级；`accounts/Pages.tsx` 和 `jobs/Pages.tsx` 按工单要求暂时按文件关闭 ESLint 的 `no-restricted-syntax`，等待 M2 合并后清理。本票清理范围内没有需要保留的运行时内联 style。

## 5. 需要评审决定的地方

没有额外需要决定的事项。按要求未做截图；视觉对比留给执行线。