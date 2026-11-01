评审（含 headless Chrome 实际截图）发现下面的问题，逐条修复，别处不动。仍然只改工单列出的 `.css` 文件，规范照 CODING_STANDARDS 10.1 节。

1. 问题：深色模式不可用。antd 的组件级 token（表头底色、默认按钮底色、禁用按钮、分页等）由 JS 按浅色算法预计算，只覆盖 `--ant-*` 全局变量盖不全，截图里表头是白条、默认按钮白底、禁用分页按钮几乎不可见。位置：`shell.css` 的 `@media (prefers-color-scheme: dark)` 整块。期望：**本票只做浅色**。删掉深色媒体查询，在 `:root` 加 `color-scheme: light`，这样操作系统是深色时，浏览器自带的控件和滚动条也保持浅色。删掉只为深色存在的变量（如 `--rdp-status-text`，以及 `.ant-alert.css-var-root.css-var-root` 那段为深色写的覆盖；Alert 回到 antd 默认）。在变量区开头写一句注释：深色模式要用 antd 的暗色算法，会改 tsx，另开票。
2. 问题：顶栏和状态横幅通栏（距视口两侧 24px），内容区却是居中的 1280px，1440 宽时左右边缘对不齐。位置：`.app-shell > div:has(> nav.app-menu)` 和 `.app-shell` 下 main、footer 以外的直接子元素（WorkerStatusBanner、RecoveryBlockBanner、权限 Alert）。期望：它们和 main 使用同一个最大宽度变量（新增 `--rdp-content-width: 1280px`，main 和 footer 也改用它），水平居中，横幅与顶栏之间、横幅与正文之间有统一间距。不要改变横幅的颜色和醒目程度。
3. 问题：非 antd 的普通链接（例如作业页 TanStack `Link` 渲染的"提交示例作业""提交资源示例"）仍是浏览器默认的 `#0000ee`。期望：全局 `a` 用 `--rdp-accent`，hover 用 `--rdp-accent-hover`；停靠菜单里的链接维持现有样式。
4. 问题：390 宽时停靠菜单底部露出一条灰色横向滚动条。期望：`.app-menu` 用 `scrollbar-width: thin` 加透明轨道（WebKit 用 `::-webkit-scrollbar` 设高度 0–4px），保留横向滚动能力，不要禁止滚动。

修完后 `make check` 全绿，`pnpm --dir src/web build` 通过。

边界：
- 只改工单列出的 `.css` 文件。本票允许改的受保护文件：无。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络。
- 自己建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"；然后逐条写处理结果；`make check` 和 build 最后一次运行的命令和末尾输出，原样贴出。
