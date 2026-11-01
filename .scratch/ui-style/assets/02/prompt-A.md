你在工单「样式机检与内联 style 清理」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-02-style-lint）里工作。依赖 stylelint 17.16.0、stylelint-config-standard 40.0.0 已经装好并提交（36977d4）。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md：第 4 节注释、第 8 节豁免、第 10 节前端，其中 10.1 节样式（10.7–10.13）是本票的规范
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/issues/02-style-lint-inline-cleanup.md，这是本次唯一的需求来源

分级是直做：没有契约骨架，一次交付。要点：
1. 内联 style 挪到 CSS 类时，只换写法，不换效果，不改 JSX 结构、文案和行为，不改任何测试文件。现有测试原样通过就是行为没变的证据。
2. 不碰 `accounts/Pages.tsx`、`jobs/Pages.tsx`（M2 正在改），也不碰工单范围以外的 tsx。
3. 只按工单「验收」第 3 条验证三个关键行为（ESLint 拦内联 style、stylelint 拦写死颜色、拦没带说明的 !important）。验证用的临时改动做完就撤掉。不另写测试。
4. 不做截图，执行线会自己截图对比。

边界：
- 只改 `src/`，以及本票允许改的受保护文件：`src/web/eslint.config.js`、`Makefile`，并允许新建 `src/web/stylelint.config.js`。`package.json` 和锁文件不动。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（评审会查运行日志，出现安装或联网的命令整轮打回）。
- 自己建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后分五块：
1. 改动清单：每个文件一行，写做了什么。新建的类名逐个列出对应原来的哪段内联 style。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 三个关键行为的验证：每条贴出命令和报错原文。
4. stylelint 配置：关掉了 `stylelint-config-standard` 里的哪些规则，各自的理由；还有所有单条豁免的位置和理由（包括保留下来的运行时内联 style）。
5. 拿不准、需要评审决定的地方。
