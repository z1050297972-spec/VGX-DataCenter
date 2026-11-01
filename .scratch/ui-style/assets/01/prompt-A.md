你在工单「前端样式：简约外观、底部停靠菜单、玻璃质感」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-01-apple-style）里工作。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md：第 4 节注释、第 10 节前端，**10.1 节样式（10.7–10.13）是本票 CSS 的写法规范，逐条遵守**
- /home/shawn/桌面/robot-data-platform/docs/adr/0010-样式方案用antd加CSS变量不引入Tailwind.md
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/issues/01-apple-style-shell.md，这是本次唯一的需求来源

分级是直做：没有契约骨架，一次交付。这张票**只改样式**：
1. 只改工单「硬性范围」里列出的 6 个已有 `.css` 文件。不改任何 `.ts`/`.tsx`/测试/`index.html`，不新建文件。改了别的文件，整轮打回。
2. 动手前先读要套样式的组件，弄清 DOM 结构和类名，包括 `accounts/Pages.tsx` 的 AccountMenu/AccountLayout/LoginPage、`VersionFooter.tsx`、`DiagnosticCard.tsx`、`jobs/WorkerStatusBanner.tsx`、`navigation/RecoveryBlockBanner.tsx`，以及各页面 CSS 的使用处。只读不改。再读 `node_modules/antd` 源码，确认 CSS 变量的选择器和名字。
3. 不写新测试；样式不在 jsdom 里生效。只要求 `make check` 全绿、`pnpm --dir src/web build` 通过。
4. 不做人工截图，执行线评审时会自己截。

边界：
- 只改上面说的 `.css` 文件。本票允许改的受保护文件：无。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后分六块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check` 和 build：最后一次运行的命令和末尾输出，原样贴出。
3. 覆盖的 `--ant-*` 变量清单，每个对应什么；用了 `!important` 的地方逐处列出和理由。
4. 主要颜色组合的对比度（深浅两套）。
5. 对照 10.7–10.13 逐条自查：每条一行，写怎么满足的；因为不能改 tsx 而做不到的，写明位置和原因。
6. 拿不准、需要评审决定的地方。
