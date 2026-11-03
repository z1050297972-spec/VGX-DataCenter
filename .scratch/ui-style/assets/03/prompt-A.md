你在工单「布局优化一：全局质感、间距档位、数据集浏览页」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-03-layout）里工作。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md：第 4 节注释、第 8 节豁免、第 10 节前端；10.1 节样式（10.7–10.15）是本票的规范，10.14、10.15 是新加的
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/issues/03-layout-texture-datasets.md：本次唯一的需求来源
- 追问记录 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/layout-decisions.md：背景
- 视觉参考图（用图片查看能力打开）：
  - /home/shawn/.cache/rdp-ui-preview/shots/compare/datasets-1440-v3.png
  - /home/shawn/.cache/rdp-ui-preview/shots/compare/dataset-detail-1440-v3.png
  - /home/shawn/.cache/rdp-ui-preview/shots/compare/datasets-1440-v0.png（现状）
  - /home/shawn/.cache/rdp-ui-preview/libs/shadcn-tasks.png
  - /home/shawn/.cache/rdp-ui-preview/libs/shadcn-dashboard2.png
  原型是在预览实例上注入 CSS 拼出来的（/home/shawn/.cache/rdp-ui-preview/variants/），只参考效果，不要照抄写法。工单要求用 antd 组件搭结构（10.14）。

分级是直做：一次交付。要点：
1. 负责人最担心的是改出事故。tsx 只改布局容器，不改逻辑、状态、查询、事件、文案和 aria-label。**测试文件一个都不改，现有测试原样通过**，这是行为没变的证据。某个 antd 组件会让测试失败的，就换不破坏测试的写法，不要改测试。
2. 间距档位换算会改变同名变量的值，`--rdp-space-*` 的每一处用法都要逐个重新对应，别漏。
3. 不写新测试。不做截图，执行线会自己截图验收。
4. 布局 B、C 不专门调整，但共用部件改了以后，它们不能错位或失效。

边界：
- 只改 `src/web/src/` 下的 tsx 和 css。本票允许改的受保护文件：无。`package.json` 和锁文件不动。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（评审会查运行日志，出现安装或联网的命令整轮打回）。
- 自己建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后分五块：
1. 改动清单：每个文件一行，写做了什么。tsx 文件写清楚换上或套上了哪些 antd 组件。
2. 间距换算表：旧变量和值 → 新变量和值，每处用法归到哪一档、为什么；宽度变量的改名表。
3. `make check`：最后一次运行的命令和末尾输出，原样贴出。
4. 因为测试约束没能用上工单建议的组件的地方，换成了什么写法。
5. 拿不准、需要评审决定的地方。
