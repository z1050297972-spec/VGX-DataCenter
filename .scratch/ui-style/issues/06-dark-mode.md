# 深色模式：跟随系统

Status: done

分级：直做。

## 依据

- 负责人 2026-11-02："把所有的都做完"。followups 第 3、4 条：深色模式要用 antd 的 `theme.darkAlgorithm`，并改用 ConfigProvider 主题。
- 第 01 张的评审记录：只靠 CSS 变量盖不全 antd 的组件 token，所以当时只做了浅色。

## 范围

1. `mountWeb.tsx`（本票允许改）：用 antd `ConfigProvider` 包住应用。
   - 用 `window.matchMedia('(prefers-color-scheme: dark)')` 跟随系统，系统切换时实时生效；
   - 深色用 `theme.darkAlgorithm`，浅色用 `defaultAlgorithm`；
   - 主色、圆角这些 token 和 `shell.css` 的 `--rdp-*` 保持一致。
   - 只加主题包装，不改路由、查询和其他逻辑。
2. `shell.css`：
   - 删掉 `color-scheme: light`，改成 `color-scheme: light dark`；
   - 在 `@media (prefers-color-scheme: dark)` 里重定义 `--rdp-*` 变量：页面底色、卡片、文字、边框、玻璃等，让深色下的玻璃顶栏、底部菜单、卡片和文字都清晰；
   - 原来为了浅色写的 `--ant-*` 覆盖，深色下不能把 antd 算出来的深色值盖回浅色；
   - 变量区开头那句"深色模式另开票"的注释更新掉。
3. 降级开关（`data-rdp-plain`、`prefers-reduced-transparency`、`prefers-contrast`）在深色下照样生效。
4. 页面 CSS 里如果有写死成浅色的地方（不该有，10.7），一并改成变量。

## 验收

1. `git status --porcelain` 只出现 `src/web/src/` 下的 tsx、css，以及 `mountWeb.tsx`（它也在 `src/web/src/` 下）。
2. `make check` 全绿，测试文件没动。
3. 执行线截图验收：浅色、深色各截主要页面。深色下不能有白底表头、白底按钮、看不见的禁用按钮和分页（第 01 张出过的问题）；浅色和合并前一致。

## Comments

### 2026-11-02 开票与派工（执行线）

- 第 05 张已合并（de767d2），解除阻塞。工作目录 `~/桌面/robot-data-platform.wt/ui-style`，分支 `t/ui-06-dark`。
- 派工 A：Codex gpt-6.1-terra high，单元 `rdp-codex-ui-06`，日志 `~/.cache/rdp-dispatch/ui-06/`。

### 2026-11-02 评审 1（执行线）

- Codex 自报全部完成，只改了 `mountWeb.tsx` 和 `shell.css`。`mountWeb.tsx` 只加了 `ConfigProvider` 和跟随系统的明暗切换（`useSyncExternalStore`，没有 `matchMedia` 时用浅色），没动其他逻辑。`make check` 全绿。
- 深色截图在 `~/.cache/rdp-ui-preview/shots/t06d/`，覆盖 18 页：表头、按钮、禁用按钮、分页、Alert、日志框、玻璃效果都清楚，第 01 张出过的问题没有再出现。
- 阻塞：浅色和合并前逐像素对比，下拉框的边框和箭头变淡了，对比图是 `assets/06/light-regression.png`。推测是 ConfigProvider 生成了新的 CSS 变量作用域，`shell.css` 里的 `.css-var-root` 浅色覆盖匹配不上了。
- 顺带：`mountWeb.tsx` 写死了色值，要求集中成常量并写注释，和 `--rdp-*` 同步。
- 修复轮 R1，单元 `rdp-codex-ui-06-r1`。

### 2026-11-02 评审 2 与合并（执行线）

- R1 查实了原因：ConfigProvider 生成了新的 `css-var-*` 作用域；另外，浅色下传入的种子 token 也改变了派生值。修法是把 `cssVar.key` 固定为 `css-var-root`，浅色不再传种子，深色的种子集中成常量并写明要和 `--rdp-*` 同步。
- 逐像素对比浅色和合并前，只剩两处差异：详情页"本次读取"的时间，和作业列表里新增作业的编号，都是数据变化，不是样式。深色截图复查过，没问题。
- 实现提交 `80d030d`；合并提交 `713a5d4`，钩子跑的 `make check` 全绿。工作目录和分支已删除。
