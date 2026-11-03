状态：未完成（详情分节、列表细节和响应式效果尚未全部按工单完成或验证）

## 1. 改动清单

改动均留在工作区，未暂存、未提交；测试文件、依赖文件和受保护文件未修改。

- `src/web/src/shell.css`：调整七档间距、宽度变量命名及全局卡片和表头质感。
- `src/web/src/audit/audit.css`：随全局宽度变量重命名更新引用。
- `src/web/src/navigation/navigation.css`：随间距档位更新引用。
- `src/web/src/datasets/Pages.tsx`：页头使用 antd `Flex`、`Breadcrumb`、`Typography.Title`，筛选区使用 `Affix`、`Card`。
- `src/web/src/datasets/Filters.tsx`：筛选项套用 antd `Row`、`Col`，保留原有筛选控件和处理逻辑。
- `src/web/src/datasets/LayoutA.tsx`：使用 antd `Flex` 排说明行和按钮，使用 `Row`、`Col`、`Card` 排双栏。
- `src/web/src/datasets/BrowserParts.tsx`：表格改用 antd 中等行高；名称按钮增加截断样式和悬停标题。
- `src/web/src/datasets/Details.tsx`：使用 antd `Flex` 排标题与操作，`Row`、`Col` 排摘要，`Divider` 分隔跨视图区。
- `src/web/src/datasets/browser.css`：调整浏览页双栏、筛选、名称和说明文字样式，并换算间距、宽度引用。
- `src/web/src/datasets/creation.css`：随间距档位更新引用。
- `src/web/src/datasets/dataOrigin.css`：随间距和宽度变量更新引用。
- `src/web/src/datasets/fieldEditing.css`：随间距档位更新引用。
- `src/web/src/datasets/fileViewer.css`：随间距档位更新引用。

## 2. 间距换算表

| 旧变量和值 | 新变量和值 | 用途与取舍 |
|---|---|---|
| `--rdp-space-1: 4px` | `--rdp-space-1: 4px` | 微小间隔，保留原值。 |
| `--rdp-space-2: 6px` | `--rdp-space-2: 8px` | 控件内及紧凑元素间距，归入最近的 8px 档。 |
| `--rdp-space-3: 8px` | `--rdp-space-2: 8px` | 保留原值，用于组内间隔。 |
| `--rdp-space-4: 12px` | `--rdp-space-3: 12px` | 保留原值，用于组内边距与间隔。 |
| `--rdp-space-5: 16px` | `--rdp-space-4: 16px` | 保留原值，用于组内较大间距。 |
| `--rdp-space-6: 18px` | `--rdp-space-4: 16px` | 创建页路径缩进归入较近的 16px 档。 |
| `--rdp-space-7: 20px` | `--rdp-space-5: 24px` | 原布局 A 栏间距归入组间 24px 档；现由 antd 栅格间距承担。 |
| `--rdp-space-8: 24px` | `--rdp-space-5: 24px` | 保留原值，用于页面及组间留白。 |

引用逐处换算涉及 `shell.css`、`navigation.css`、`browser.css`、`creation.css`、`dataOrigin.css`、`fieldEditing.css`、`fileViewer.css`。其中 dock 原来使用的 6px 内边距也随变量换算成了 8px；这可能与“dock 不动”的视觉要求冲突，需要评审确认。

宽度变量重命名如下，数值未变：

| 旧变量 | 新变量 |
|---|---|
| `--rdp-width-120` | `--rdp-width-audit-result` |
| `--rdp-width-150` | `--rdp-width-filter-medium` |
| `--rdp-width-160` | `--rdp-width-audit-kind` |
| `--rdp-width-180` | `--rdp-width-filter-wide` |
| `--rdp-width-200` | `--rdp-width-origin-select` |
| `--rdp-width-210` | `--rdp-width-filter-scene` |
| `--rdp-width-280` | `--rdp-width-filter-tasks` |
| `--rdp-width-640` | `--rdp-width-origin-table` |

## 3. `make check`

最后一次运行命令：

```bash
make check > /tmp/rdp-ui-check-final.log 2>&1; code=$?; tail -30 /tmp/rdp-ui-check-final.log; exit "$code"
```

末尾输出原样如下；命令退出码为 0：

```text
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.Ru5420h239/openapi.json → /tmp/tmp.Ru5420h239/schema.d.ts [381.3ms]
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
   Start at  05:36:11
   Duration  13.60s (tests 55%, import 19%, environment 17%, transform 6%, setup 2%)

```

## 4. 因测试约束替换组件

详情摘要使用了 antd `Row`、`Col`，保留原有文本节点，没有使用可能拆开标签和值的 `Descriptions`。**这不是一次经过失败测试确认的替换**，而是按工单提示主动采用的兼容写法。

## 5. 尚未完成及需评审决定

- 详情页尚未把**所有**分节整理为小标题和细分隔线，仍可能存在卡片嵌套；返回按钮也尚未与标题、操作按钮合在同一行。
- 列表分类信息尚未按要求以 `·` 分隔；名称截断使用按钮标题和 CSS，尚未使用工单建议的 antd `ellipsis`。
- 未截图；按要求留给执行线在 1440、1280 宽度验证。尤其需要检查筛选栏吸顶时与玻璃顶栏的关系，以及布局 B、C 的共享部件是否错位。
- `make check` 全绿证明现有自动检查通过，**不证明**上述未完成的视觉验收项已经满足。