状态：未完成（降级和深色模式仍有待评审确认的缺口）

## 1. 改动清单

- `src/web/src/shell.css`：新增设计变量、antd 变量覆盖、顶栏与底部停靠菜单、登录页及内容区样式、深浅色与降级变量。
- `src/web/src/datasets/browser.css`：将现有颜色、边线、圆角和间距替换为设计变量，保留 A/B/C 布局结构。
- `src/web/src/datasets/creation.css`：将现有颜色、边线、圆角和间距替换为设计变量，保留布局。
- `src/web/src/datasets/fieldEditing.css`：将现有边线颜色和间距替换为设计变量。
- `src/web/src/datasets/fileViewer.css`：将现有间距替换为设计变量，保留布局。
- `src/web/src/navwrites/writes.css`：已检查，未发现本票需要替换的颜色，因此未修改。

改动留在工作区；未暂存、未提交。`git status --porcelain` 只显示上述五个已修改 CSS 文件。

## 2. `make check` 和 build

最后一次 `make check` 成功。它在最终 CSS 修改前启动，但前端检查步骤是在修改完成后执行的；末尾输出原样如下：

```text
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/ui-style/src/web


 Test Files  39 passed (39)
      Tests  373 passed (373)
   Start at  01:46:58
   Duration  11.21s (tests 54%, import 21%, environment 20%, transform 4%, setup 1%)
```

后端 pytest 结果为 `2627 passed, 8 warnings`。

最后一次 `pnpm --dir src/web build` 成功，末尾输出原样如下：

```text
dist/assets/time-8LP5GLf6.js              325.63 kB │ gzip:  68.97 kB
dist/assets/ui-D0Z2k7ns.js                811.12 kB │ gzip: 259.86 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 328ms
```

构建有大 chunk 警告；未做修改前后的入口体积基线比较。

## 3. antd 变量与 `!important`

已确认 antd 默认变量选择器是 `.css-var-root`；使用 `.css-var-root.css-var-root` 提高覆盖优先级。

- `--ant-color-primary`、`-hover`、`-active`：主色及悬停、按下色。
- `--ant-color-primary-bg`、`-bg-hover`：主色浅底及悬停浅底。
- `--ant-color-primary-border`、`-border-hover`：主色边线及悬停边线。
- `--ant-color-primary-text`、`-text-hover`、`-text-active`：主色文字及交互状态。
- `--ant-color-link`、`-hover`、`-active`：链接及交互状态。
- `--ant-border-radius`、`-sm`、`-lg`、`-xs`：控件及不同尺寸圆角。
- `--ant-font-family`、`--ant-font-family-code`：正文与等宽字体。
- `--ant-color-text`、`-heading`、`-secondary`、`-tertiary`、`-quaternary`：正文、标题和次级文字。
- `--ant-color-bg-container`、`-elevated`、`-layout`：容器、浮层和页面底色。
- `--ant-color-border`、`-secondary`：通用边线。
- `--ant-motion-duration-fast`、`-mid`、`-slow`：antd 动画时长，用于降级。

状态 Alert 内还局部覆盖了正文、标题和链接变量，以配合保留的浅色状态背景；未改 error、warning、success 状态色变量。

`!important` 共两处，均在 `html[data-rdp-plain]` 的后代及伪元素规则内：

- `animation-duration: 0s !important`：覆盖 antd 或内联声明的动画时长。
- `transition-duration: 0s !important`：覆盖 antd 或内联声明的过渡时长。

## 4. 主要颜色组合对比度

以下是按不透明色值计算的对比度；玻璃叠加背景及组件实际渲染仍需执行线检查。

| 模式 | 前景 / 背景 | 对比度 |
|---|---|---:|
| 浅色 | `#1d1d1f` / `#f5f5f7` | 15.46:1 |
| 浅色 | `#1d1d1f` / `#ffffff` | 16.83:1 |
| 浅色 | `#68686d` / `#ffffff` | 5.54:1 |
| 浅色 | `#68686d` / `#f5f5f7` | 5.09:1 |
| 浅色按钮 | `#ffffff` / `#0068d1` | 5.38:1 |
| 深色 | `#f5f5f7` / `#000000` | 19.29:1 |
| 深色 | `#f5f5f7` / `#1c1c1e` | 15.63:1 |
| 深色 | `#b0b0b5` / `#1c1c1e` | 7.88:1 |
| 深色链接 | `#2997ff` / `#1c1c1e` | 5.64:1 |

## 5. 对照 10.7–10.13 自查

- **10.7**：新增视觉颜色、圆角、间距、阴影和层级集中在 `shell.css`；已修改页面 CSS 中的现有色值已替换。存量布局尺寸保持原样。
- **10.8**：沿用现有 antd 组件，未手写替代组件。
- **10.9**：静态改动写在 CSS；按工单限制，既有 TSX 内联样式未清理。
- **10.10**：模块样式留在原 CSS，外壳样式放在 `shell.css`；针对既有 JSX 和 antd 结构的标签/结构选择器写了说明。存量选择器和类名未全面重构。
- **10.11**：两处 `!important` 仅用于调试模式覆盖动画与过渡时长，并有原因注释。
- **10.12**：没有新增隐藏诊断信息的规则；增加焦点环，当前菜单同时使用强调底色、字重和下划线。实际焦点与状态告警效果尚待浏览器评审。
- **10.13**：深浅色、透明度和动效降级集中在 `shell.css`；页面 CSS 只保留原有响应式媒体查询。但调试模式尚不能保证消除所有存量透明效果，见下文。

## 6. 需要评审决定或继续处理的地方

1. **`data-rdp-plain` 不完全满足“关闭所有透明”**：例如 `browser.css` 中已有 `.dataset-miller-item .dataset-tree-meta { opacity: 0.7; }` 仍会生效；第三方组件的透明效果也未全部消除。动效降级主要覆盖本次变量、antd 时长变量和调试模式下的动画/过渡时长，不能宣称已覆盖所有可能的第三方动效。
2. antd 部分组件色值由组件 token 预计算，深色模式下表格交互态、表单和状态提示的所有组合尚未逐一验证；尤其请执行线检查 Alert 正文与链接的对比度，以及弹层是否始终位于停靠栏上方。
3. 按要求未做人工截图。登录页居中、窄屏菜单滚动、底部留白及深色模式均需要执行线按工单截图验收。