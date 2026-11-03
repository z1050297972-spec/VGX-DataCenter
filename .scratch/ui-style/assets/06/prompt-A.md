你在工单「深色模式：跟随系统」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-06-dark）里工作。

先读下面这些。规划文件一律读主仓库 /home/shawn/桌面/robot-data-platform 里的版本：
- AGENTS.md
- docs/standards/CODING_STANDARDS.md：第 4、8、10 节；10.1 节样式，特别是 10.13（深浅色降级只在 shell.css 通过重定义变量实现）
- docs/adr/0010-样式方案用antd加CSS变量不引入Tailwind.md
- 工单 .scratch/ui-style/issues/06-dark-mode.md：本次唯一的需求来源
- .scratch/ui-style/issues/01-apple-style-shell.md 的 Comments：第 01 张当时为什么放弃深色（antd 组件 token 由 JS 预计算，只盖 `--ant-*` 盖不全）
- `src/web/src/shell.css` 全文，`src/web/src/mountWeb.tsx`

分级是直做：一次交付。要点：
1. 本票允许改 `mountWeb.tsx`，但只加 antd `ConfigProvider` 主题包装和跟随系统的明暗切换，不改路由、查询和其他逻辑。
2. jsdom 测试环境可能没有 `window.matchMedia`，要有兜底：没有就按浅色处理。**测试文件一个都不改，现有测试原样通过。**
3. 浅色外观必须和现在一致。可以把现在 `shell.css` 里覆盖 `--ant-*` 的做法换成 ConfigProvider 的 token；换的话，浅色下的颜色、圆角、字体要和现在相同。
4. 深色下检查：
   - 玻璃顶栏、底部菜单；
   - 卡片、表格（表头、行悬停）、按钮（默认、禁用、危险）、分页；
   - 输入框、下拉框和弹出层、`Alert` 各类型、`Tag`、`Segmented`、`Breadcrumb`；
   - 诊断卡片、作业日志框；
   - 数据集详情的等宽文字、筛选卡吸顶时的玻璃效果。
   页面模块 CSS 里如果有写死成浅色的值，改成变量。
5. 降级开关在深色下照样生效：`html[data-rdp-plain]`、`prefers-reduced-transparency`、`prefers-contrast`、`prefers-reduced-motion`。
6. 不写新测试，不做截图，执行线会用 headless Chrome 模拟深色截图验收。

边界：
- 只改 `src/web/src/` 下的 tsx 和 css。`package.json` 和锁文件不动，其他受保护文件也不动。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（评审会查运行日志）。
- 自己建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后分四块：
1. 改动清单：每个文件一行。
2. 深色变量表：每个 `--rdp-*` 变量的浅色值和深色值；ConfigProvider 用了哪些 token。
3. `make check`：最后一次运行的命令和末尾输出，原样贴出。
4. 拿不准、需要评审决定的地方。
