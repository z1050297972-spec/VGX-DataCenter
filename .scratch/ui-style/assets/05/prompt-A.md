你在工单「布局优化三：其余全部页面，以及诊断组件类名归位」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-05-layout）里工作。

先读下面这些。规划文件一律读主仓库 /home/shawn/桌面/robot-data-platform 里的版本：
- AGENTS.md
- docs/standards/CODING_STANDARDS.md：第 4、8、10 节；10.1 节样式（10.7–10.15）是本票规范
- docs/agents/codex-workflow.md 第 7.1 节
- 工单 .scratch/ui-style/issues/05-layout-remaining-pages.md：本次唯一的需求来源
- .scratch/ui-style/issues/03-layout-texture-datasets.md 和 04-layout-jobs-creation.md 的 Comments：评审打回过的坑和做法，不要再踩
- 截图（用图片查看能力打开）：
  - 现状：/home/shawn/.cache/rdp-ui-preview/shots/b2v0/*-1440.png
  - 已完成页面的效果，本票要和它们保持一致：/home/shawn/.cache/rdp-ui-preview/shots/final03/、final04/ 下的"改后"图
  - 质感参考：/home/shawn/.cache/rdp-ui-preview/libs/shadcn-tasks.png

先看已经完成的 `datasets/Pages.tsx`、`jobs/Pages.tsx`、`jobs/jobs.css`、`datasets/browser.css`，照它们的写法做。每个模块用自己前缀的 CSS 类，写在自己模块的 CSS 文件里；模块还没有 CSS 文件的就新建一个。

分级是直做：一次交付。要点：
1. tsx 只改布局容器，不改逻辑、状态、查询、事件、文案和 aria-label（面包屑是新加的导航文字，允许）。**测试文件一个都不改，现有测试原样通过。**某个 antd 组件会让测试失败的，就换写法，或者那一处保持原样，并在最终回复里写明。
2. 带"展开内容"的组件（按钮点开后原地渲染表单、查看器）不要塞进标题行或按钮行。
3. 分隔线不要因为相邻分节为空而连着出现两条。
4. 不写新测试，不做截图，执行线自己截图验收。
5. 页面多，按工单编号逐页做；每做完几页跑一次 `make check` 的前端部分，及早发现测试问题。

边界：
- 只改 `src/web/src/` 下的 tsx 和 css。受保护文件都不动，`package.json` 和锁文件也不动。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（评审会查运行日志，出现安装或联网的命令整轮打回）。
- 自己建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后分四块：
1. 逐页改动：每页一行，写清楚用了哪些 antd 组件。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 因为测试约束换了写法或保持原样的地方。
4. 拿不准、需要评审决定的地方。
