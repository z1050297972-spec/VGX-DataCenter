状态：未完成（日志静态内联样式与现有测试存在冲突；部分布局仍需补完）

### 1. 改动清单

- `src/web/src/jobs/Pages.tsx`：使用 `Breadcrumb`、`Typography.Title`、`Tag`、`Card` 和 `Flex` 调整作业页；两个示例作业链接增加间距。
- `src/web/src/jobs/jobs.css`：增加作业页、筛选器和诊断字段布局样式。
- `src/web/src/jobs/DownloadDetail.tsx`：使用 `Card` 包裹下载详情。
- `src/web/src/DiagnosticCard.tsx`：增加诊断字段布局容器；诊断内容仍由既有 `Card` 展示。
- `src/web/src/datasets/CreationScreen.tsx`：使用 `Breadcrumb` 和既有 `Typography.Title` 调整页头。
- `src/web/src/datasets/CreationForms.tsx`：使用编号 `Card` 包裹基本信息和格式入口，保留原有 `fieldset` 禁用语义。
- `src/web/src/datasets/CreationFields.tsx`：使用编号 `Card` 包裹链接字段，保留原有 `fieldset`。
- `src/web/src/accounts/Pages.tsx`：菜单行和主内容的静态样式改为 CSS 类。
- `src/web/src/accounts/accounts.css`：新增账号页布局类。
- `src/web/eslint.config.js`：删除两个页面的临时规则关闭，并调整 `no-restricted-syntax` 的位置。

改动留在工作区；未修改测试、安装依赖、联网、截图、暂存或提交。

### 2. 内联 style 清理

- 账号菜单行的 `display: flex`、`justifyContent: flex-end`、`gap: 16`、`alignItems: center`、`flexWrap: wrap` → `accounts-menu-row`。
- 主内容 `marginTop: 24` → `accounts-main`。
- 作业状态筛选器 `width: 180` → `jobs-filter`。

**仍保留一处静态内联 style，未满足本票清理要求**：作业日志的 `whiteSpace`、`overflowWrap`、`maxWidth`、`minWidth`。其中前三项被现有测试直接通过 `element.style` 断言；改为 CSS 类会使该测试失败。当前仅对 `no-restricted-syntax` 加了单条豁免，并注明测试契约调整后移除。没有保留需要报告的运行时内联 style。

### 3. `make check`

最后一次运行命令：

```bash
make check > /tmp/rdp-ui04-final-check.log 2>&1
```

末尾输出原样如下：

```text
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.S8AHQrccKe/openapi.json → /tmp/tmp.S8AHQrccKe/schema.d.ts [312.8ms]
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
   Start at  19:20:21
   Duration  11.12s (tests 60%, import 18%, environment 18%, transform 2%, setup 2%)
```

### 4. 因测试约束换写法的地方

- 日志暂保留静态内联样式，而不是移到 CSS：测试直接断言内联样式值。
- 作业诊断保持默认可见，未放入默认收起的 `Collapse`：现有测试直接查找诊断字段。

### 5. 拿不准、需要评审决定的地方

- 请决定日志样式冲突如何处理：允许调整测试以检查计算样式，或批准保留这处静态内联样式。
- 作业详情原先没有展示参数；在“不改逻辑和文案”的约束下，我没有新增参数序列化展示，因此**参数卡尚未实现**。概要字段横向排布、诊断卡片避免嵌套、下载详情进一步分组也尚未完成，需要继续处理。
- 诊断目前保持可见，但尚未实现可收起的诊断分组；需评审确认在现有测试约束下的预期交互。