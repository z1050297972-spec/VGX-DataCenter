# 深色模式：跟随系统

Status: blocked（等第 05 张合并：两张都会改 `shell.css`）

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
