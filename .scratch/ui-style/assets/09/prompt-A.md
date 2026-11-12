你在工单「视觉换肤『暖色有机』」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-09-warm-theme（git worktree，分支 t/ui-09-warm-theme）里实现这张票。这是直做票：没有契约骨架阶段，一次交付实现。

先读下面这些。规划文件一律读主分支工作目录 /home/shawn/桌面/robot-data-platform.wt/m15-19-remove-backfill 里的版本（下称"规划目录"）：
- 规划目录/AGENTS.md
- 规划目录/docs/standards/CODING_STANDARDS.md，重点是第 10 节 10.7–10.15
- 规划目录/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」：这些写法以前被打回过，一开始就避免
- 工单 规划目录/.scratch/ui-style/issues/09-warm-organic-theme.md：「设计取值」是实现的准绳，「范围与边界」是硬约束
- 原型 规划目录/.scratch/ui-style/assets/09/prototype-warm.css 和 assets/09/shots/ 里的两张截图：只作视觉参考。原型用了 `!important`、直接覆盖 `--ant-*` 变量，主按钮用了珊瑚红，右上色块压到了按钮，这些都不能照抄，以工单为准
- 上一张同类票 规划目录/.scratch/ui-style/issues/08-studio-redesign.md：本票沿用它的结构（变量在 shell.css，antd 种子和组件 token 在 mountWeb.tsx，两边同步）

要做的事：
1. 按工单「设计取值」改 `src/web/src/shell.css` 的浅色、深色变量和部件样式，同步改 `src/web/src/mountWeb.tsx` 里浅色、深色的种子和组件 token。主按钮反色只用 antd Button 组件 token，不动全局 `colorPrimary` 的语义，不改 `colorTextLightSolid`。
2. 新增 `--rdp-font-display` 衬线栈，用在页面大标题和登录页标题；栈的末尾接现有无衬线栈，不写通用族 `serif`。不打包新字体。
3. 加背景色块：纯 CSS 背景图，不新增 DOM，不改 tsx。右上色块不能压到页头右侧按钮、告警条和任何正文；小于 1100px 不显示；深色降透明度；`html[data-rdp-plain]` 下不显示。
4. 各模块 CSS 里引用旧取值或和新设计冲突的地方，改成新变量。
5. 自己算对比度（正文、次要文字、链接在各自底色上不低于 4.5:1，包括次级表面上的强调色文字），不达标就按工单说的办法处理。
6. 开发中跑 `make check-changed`；最后跑一次 `make check` 到全绿。在工作目录里跑检查要加 `PYTHONPATH=$PWD/src`，不要用 `uv run`。`pnpm` 在 `~/.npm-global/bin`。

关键约束（违反任何一条整轮打回）：
- 除 `mountWeb.tsx` 外不改任何 `.ts`/`.tsx`；任何测试文件一个字不改；不改 `package.json`、`pnpm-lock.yaml`、`src/web/src/fonts/`、`docs/`。
- 不写 `!important`。新颜色、尺寸先定义 `--rdp-*` 变量再用。
- 危险按钮、成功/失败/警告语义色不改。不用 CSS 隐藏任何已有文字、提示、诊断。
- 不为罕见情况写额外的防御样式；工单没列的部件保持第 08 张的外观，只让颜色随变量变化。本票不新增测试。

边界：
- 只改 `src/`。本票允许改的受保护文件：无。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 对比度：算过的"文字色 / 底色 / 比值"组合，浅色和深色都列。
4. 契约变更申请、依赖申请：没有就写"无"。
5. 拿不准、需要评审决定的地方。
