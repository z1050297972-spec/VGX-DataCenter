你在工单「布局优化二：作业页、新建数据集表单、accounts/jobs 内联 style 清理」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-04-layout）里工作。

先读下面这些。规划文件一律读主仓库 /home/shawn/桌面/robot-data-platform 里的版本：
- AGENTS.md
- docs/standards/CODING_STANDARDS.md：第 4、8、10 节；10.1 节样式（10.7–10.15）是本票规范
- docs/agents/codex-workflow.md 第 7.1 节
- 工单 .scratch/ui-style/issues/04-layout-jobs-creation.md：本次唯一的需求来源
- 上一张 .scratch/ui-style/issues/03-layout-texture-datasets.md：主要看 Comments 里的评审记录，那些坑不要再踩
- 视觉参考图（用图片查看能力打开）：
  - 上一张已经合并的效果，本票要和它保持一致：/home/shawn/.cache/rdp-ui-preview/shots/final03/2-列表-改后.png、4-详情-改后.png
  - 原型：/home/shawn/.cache/rdp-ui-preview/shots/compare/job-detail-1440-v3.png、dataset-new-1440-v3.png；现状 job-detail-1440-v0.png、dataset-new-1440-v0.png
  - 原型是用 CSS 拼出来的，只参考效果；正式实现用 antd 组件搭（10.14）。

第 03 张已经定好的东西直接复用，不要另起一套：
- `shell.css` 里的 `--rdp-space-*` 七档、卡片细边框、表头质感；
- 数据集页的写法：页头 `Breadcrumb` 加 `Typography.Title`，操作放右侧；分节用 `browser-detail-section` 那种"非空分节之间画线"的思路。在作业模块里新建自己前缀的类，不要跨模块引用 `browser-` 类。

分级是直做：一次交付。要点：
1. tsx 只改布局容器，不改逻辑、状态、查询、事件、文案和 aria-label。**测试文件一个都不改，现有测试原样通过。**某个 antd 组件会让测试失败的，就换不破坏测试的写法。
2. 吸取第 03 张的教训：
   - 带"展开内容"的组件（按钮点开后在原地渲染一大块，比如查看器、表单），不要塞进标题行或按钮行；
   - 分隔线不要因为相邻分节为空而连着出现两条。
3. 诊断收起：用 `Collapse` 时要让收起的内容留在 DOM 里（`forceRender`），测试要求默认可见的就不收。
4. 内联 style 清理：静态值挪进 CSS 类；运行时才算得出的值（进度百分比之类）保留，并用单条豁免写明原因（见 10.9）。清理完删掉 `eslint.config.js` 里这两个文件的临时关闭，并把 `no-restricted-syntax` 挪到"后端分支数 ≤ 12…"注释的上方。
5. 不写新测试，不做截图，执行线自己截图验收。

边界：
- 只改 `src/web/src/` 下的 tsx 和 css，以及本票允许改的受保护文件 `src/web/eslint.config.js`。`package.json` 和锁文件不动。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（评审会查运行日志，出现安装或联网的命令整轮打回）。
- 自己建的试验文件，交付前删掉。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后分五块：
1. 改动清单：每个文件一行，写清楚用了哪些 antd 组件。
2. 内联 style 清理：每处原写法 → 新类名；保留下来的运行时内联 style 和豁免理由。
3. `make check`：最后一次运行的命令和末尾输出，原样贴出。
4. 因为测试约束换了写法的地方。
5. 拿不准、需要评审决定的地方。
