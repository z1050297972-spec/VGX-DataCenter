你在工单「ui-style 08 视觉重设计 Studio」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-08-redesign（git worktree，分支 t/ui-08-redesign）里直接实现。这是纯样式票，没有骨架关卡。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md，重点第 10 节和 10.1 样式（10.7–10.15）
- /home/shawn/桌面/robot-data-platform/docs/adr/0010-样式方案用antd加CSS变量不引入Tailwind.md
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/issues/08-studio-redesign.md：设计取值、各部件要求、范围和验收都以它为准
- 视觉参考 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/assets/08/prototype-r1.css（丢弃式原型，取值可参考，选择器写法不规范，不要照抄）和 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/assets/08/shots/ 下的截图
- 现有样式入口 src/web/src/shell.css 和 src/web/src/mountWeb.tsx

要求：
1. 把 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/assets/08/fonts/ 下 6 个文件原样复制到 src/web/src/fonts/，在 shell.css 里用 @font-face 引用（相对路径，交给 Vite 打包），按工单写 unicode-range。
2. 按工单「设计取值」和「各部件」逐条实现，浅色、深色都做。主按钮反色只用 antd Button 组件 token；全局 colorPrimary 是强调色（浅色 #2a45c9，深色种子 #5b74f0）。不要改全局 colorTextLightSolid。
3. 不影响现有功能是硬性要求：除 mountWeb.tsx 外不改任何 .ts/.tsx，不改任何测试文件，不加依赖。如果某条设计必须改 tsx 或测试才能做到，跳过这一条，在最终回复里说明。
4. 保留并沿用 shell.css 现有的降级机制（prefers-reduced-motion、prefers-reduced-transparency、prefers-contrast、html[data-rdp-plain]），新加的动画和过渡都要被它们关掉。
5. 最后在 src/web 下跑 pnpm build 确认能打包，再在仓库根目录跑 make check 到全绿。跑后端测试时加 PYTHONPATH=$PWD/src（.venv 是软链到主仓库的 editable 安装）。

边界：
- 只改 `src/`。本票允许改的受保护文件：无。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 依赖申请、跳过的设计条目：没有就写"无"。
4. 拿不准、需要评审决定的地方。
