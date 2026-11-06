# 视觉重设计「Studio」：编辑式中性风 + 等宽数据层

Status: done

分级：直做（纯样式票，无领域决策）。

## 依据

- 负责人 2026-11-05："希望能将前端优化得更加有美感……至于怎么选择，你来决定。代码可以更改，我放宽这个要求，但是不要影响现有的功能，这是必须遵守的，风格、样式，交给你我是放心的。"
- 参考：Awwwards 作品列表页与 6 个获奖站（Wafer.ai、DeepBook、Turion Space、Grids、Signal-A、Grail）的实测字体、配色、圆角、过渡，抓取结果在 `~/.cache/rdp-ui-preview/awwwards/`。
- 执行线选定方向：Awwwards 本站的编辑式中性风（暖灰底、墨色主按钮、细线卡片）＋ Wafer/Turion 的等宽数据层（小标签、表头、数字用等宽字体）。
- 原型：`assets/08/prototype-r1.css`（丢弃式，选择器写法不规范，只作视觉取值参考），效果截图 `assets/08/shots/`。

## 设计取值（实现以此为准）

字体（原放在 `assets/08/fonts/`，合并后只保留 `src/web/src/fonts/` 一份，OFL 授权，随前端打包，不从外网加载）：
- 正文 `"Inter Tight", "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif`。
- 等宽 `"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace`。
- 两个字体都是可变字重 100–900，各有 latin、latin-ext 两个子集，用 `unicode-range` 分开声明，`font-display: swap`。

浅色：

| 用途 | 值 |
|---|---|
| 页面底色 | `#f5f5f3` |
| 卡片表面、弹层 | `#fff` |
| 次级表面（筛选托盘、日志框、分段控件底） | `#ededea` |
| 正文 | `#161616` |
| 次要文字 | `#6e6e6a` |
| 边线 / 加深边线（悬停、描边按钮） | `#e2e2de` / `#cfcfca` |
| 强调色（链接、选中、复选框、开关、焦点环、页签） | `#2a45c9`，悬停 `#1f37a8`，按下 `#182b85`，浅底 `#eceffb`/`#dfe4f8`，边框 `#b9c3ef`/`#8f9fe4` |
| 主按钮（solid primary）| 墨色 `#161616`，悬停 `#2e2e2e`，按下 `#000`，白字 |

深色：

| 用途 | 值 |
|---|---|
| 页面 / 表面 / 弹层 / 次级表面 | `#0b0b0c` / `#131314` / `#1a1a1c` / `#1c1c1e` |
| 正文 / 次要 | `#ededec` / `#98989d` |
| 边线 / 加深边线 | `#262628` / `#3a3a3d` |
| 强调色 | `#93a6ff`（文字用），填充类（复选框、开关）用 antd 深色算法由种子 `#5b74f0` 推导 |
| 主按钮 | 近白 `#ededec`，悬停 `#fff`，按下 `#d4d4d2`，**深色字 `#0b0b0c`** |

注意：主按钮反色只能用 antd 的 Button 组件 token（`ConfigProvider` 的 `components.Button`，或对应的 `--ant-button-*` 变量），不能把全局 `colorPrimary` 设成墨色/近白，也不能改全局 `colorTextLightSolid`：复选框、单选、开关、Tooltip 都用这两个值，改了会出现白底白勾、黑底黑字。

形状与动效：
- 圆角：卡片 14px，控件 8px，小标签 4px，胶囊 999px。卡片不用阴影，只用 1px 细线，悬停时边线加深。
- 缓动 `cubic-bezier(0.22, 1, 0.36, 1)`，交互过渡 220ms；antd 的 `motionEaseOut` 等缓动 token 同步换成这条曲线。
- 进场：页面内容（`main` 下页面根元素的直接子块）依次上浮淡入，位移 10px，时长 520ms，每块间隔 50ms，最多到第 5 块（200ms）。路由切换时页面重新挂载，所以这同时就是转场动画。只在挂载时触发，轮询刷新不能让内容重复闪动。
- `prefers-reduced-motion` 和 `html[data-rdp-plain]` 下，进场动画和所有过渡都关闭（沿用 shell.css 的变量降级方式）。

各部件：
1. **顶栏**：从浮起的玻璃卡片改成贴顶、通栏的扁平毛玻璃条，只有底部 1px 细线，没有圆角、没有阴影；左侧放等宽字标 `VGX / DATA`（13px、600、字距 0.08em）。字标是装饰，屏幕阅读器不读也不影响任何功能。
2. **停靠菜单**：保留位置和滚动行为。底色改成墨色半透明胶囊（浅色 `rgb(22 22 22 / 88%)`，深色 `rgb(30 30 32 / 82%)`），链接 13px、500、白色 72% 透明度；当前页用白色胶囊底、墨色字、600 字重。当前页要靠形状（胶囊底）加字重区分，不能只靠颜色（10.12）。10 个入口在 1280px 宽度下要完整显示，不出现横向滚动。
3. **页头**：面包屑改成等宽、11.5px、字距 0.06em、次要色；页面大标题 36px、600、字距 -0.025em、行高 1.15。
4. **卡片标题**（antd `Card` 的标题和 `.app-card-heading`）：等宽 12px、500、字距 0.06em，正文色，左侧加一个 6px 的实心小方块。
5. **筛选卡**：改成次级表面色的托盘，没有边线；里面的下拉框保持白底（深色下用表面色）；字段标签用等宽小字、次要色。
6. **表格**：表头等宽 11px、500、字距 0.06em、次要色，去掉列间竖线；单元格数字用 `tabular-nums`；行高收紧（单元格上下内边距 13px，用 antd Table 组件 token）；悬停行用 `--rdp-hover`。
7. **按钮**：字重 500，无阴影；solid 按钮按下时缩放到 0.98；描边按钮用加深边线。
8. **标签**（antd `Tag`）：等宽 11px、透明底、4px 圆角的描边小徽章。**语义色（成功、失败、警告）保持原来的颜色**，只改形状和字体。
9. **分段控件**：胶囊形，次级表面底；**页签**：墨条 1.5px，选中项正文色加粗。
10. **树**：选中项用强调色浅底，圆角 6px。
11. **告警**：圆角 8px。worker 状态这类全局告警用柔和的黄底细边（浅色 `#fbf5e4`/`#ecdcae`，深色 `#221c0c`/`#4a3d16`），醒目程度不能低于现在（10.12）。错误告警不改颜色。
12. **进度条**：轨道用次级表面色，进度变化过渡 600ms；成功/失败色不改。
13. **日志、JSON、文件预览**：等宽 12.5px，行高 1.7，8px 圆角。
14. **登录页**：卡片 18px 圆角，卡片顶部加同样的 `VGX / DATA` 字标。

## 范围与边界

允许改：
- `src/web/src/shell.css`：变量、全局部件样式、`@font-face`、降级。
- 各模块 CSS（`src/web/src/**/*.css`）：只在需要时改成新变量，或删掉和新设计冲突的旧写法。
- `src/web/src/mountWeb.tsx`：只改主题配置（浅色和深色的 token、组件 token），不动挂载、查询、路由。
- 新增 `src/web/src/fonts/`：从 `assets/08/fonts/` 复制 4 个 woff2 和 2 个许可证文件，原样复制。

不许改：
- 除 `mountWeb.tsx` 以外的任何 `.ts`/`.tsx`。尤其是 `datasets/` 下的 tsx：M1.5 第 12 张正在改这些文件，会冲突。
- 任何测试文件（`*.test.ts(x)`、`testSetup.ts`、`testSupport.ts`）。**测试一个不改、全部通过，是"不影响现有功能"的硬性证明。**
- `package.json`、`pnpm-lock.yaml`：不加依赖。

规范：
- 遵守 CODING_STANDARDS 10.7–10.15。新颜色、尺寸、时长先在 `shell.css` 定义 `--rdp-*` 变量再使用；`mountWeb.tsx` 的种子色和 `shell.css` 同步，两边都写注释互相指向。
- 选中 antd 内部结构（例如面包屑后面的标题）只能靠结构选择器时，写注释说明原因（10.10 的例外）。
- 不用 CSS 隐藏 DOM 里已有的任何文字、提示和诊断（10.12）。
- 本票会推翻 10.15 里"强调色只给主按钮"那一句：现在主按钮是墨色，强调色给链接和选中状态。规范文字由执行线在合并时更新，Codex 不改 `docs/`。

## 验收

1. `git status --porcelain` 只有：`src/web/src/` 下的 `.css`、`mountWeb.tsx`、新增的 `src/web/src/fonts/`。
2. `make check` 全绿，测试文件零改动（`git diff --stat -- '*.test.*' '**/testSetup.ts' '**/testSupport.ts'` 为空）。
3. 执行线截图验收（`~/.cache/rdp-ui-preview`）：
   - 浅色、深色 × 1440/1280/390 宽度，覆盖 18 页；`overflow.mjs` 在 1280、1440 下没有横向溢出。
   - 点开下拉、弹窗、抽屉、日期选择这类会展开的组件看一遍。
   - 深色下没有白底白字的主按钮、看不见的复选框勾、白底表头、看不见的禁用按钮和分页。
   - 中文、数字、等宽字体都正确加载（不回退成衬线体），打包产物里有 woff2，页面没有外网请求。
   - 开 `prefers-reduced-motion` 和 `data-rdp-plain` 时没有动画。

## Comments

### 2026-11-05 开票（执行线）

- 负责人 2026-11-05 点名做前端美化，方向由执行线定（见依据）。原型在预览实例上验证过浅色和深色两套取值。
- 工作目录 `~/桌面/robot-data-platform.wt/ui-08-redesign`，分支 `t/ui-08-redesign`（从 main 523db5c 开）。预览实例 `rdp-ui-preview` 目前从这个工作目录起，端口 8611。
- 避开 M1.5 第 12 张（in-progress，改 `datasets/*.tsx`、`api/*`）。
- 派工 A：Codex gpt-6-astra high，单元 `rdp-codex-ui-08`，会话 `01a1af2f-3c3f-7563-a530-cfab664b3030`，日志 `~/.cache/rdp-dispatch/ui-08/`，提示 `assets/08/prompt-A.md`。

### 2026-11-05 评审 1（执行线）

- 自己重跑 `make check`：全绿（后端 2763 passed，前端 40 文件 385 passed）。文件归属正确：只有 5 个 css/mountWeb.tsx 和新增 fonts/；测试零改动；运行日志里只有 `pnpm build`，没有安装和联网命令。
- 截图 18 页 × 浅/深 × 1440/1280（`shots/t08l`、`shots/t08d`），390 抽查数据集和作业详情。深色主按钮反色正确，表头、分页、复选框正常。`/jobs/new` 在预览实例里是 404，基线也是这样，与本票无关。
- 打回 2 条（阻塞）：① 字标被顶栏玻璃层盖住，看不见；② 顶栏通栏用了 100vw，1440 下 11 页横向溢出 8px（overflow.mjs）。修复轮提示 `assets/08/prompt-R1.md`，单元 `rdp-codex-ui-08-r1`。

### 2026-11-05 评审 2（执行线）：通过

- 修复轮只改了 `shell.css`：玻璃层放到顶栏层叠上下文底层，字标清晰；通栏不再用 100vw。
- 自己重跑 `make check`：全绿（后端 2763 passed，前端 385 passed）。测试零改动。`overflow.mjs` 在 1280、1440 下 0 页溢出。
- 复截 9 页浅/深（`shots/t08l2`、`shots/t08d2`）：危险按钮仍是红色，禁用按钮可见，深色表单清晰。
- Codex 提到首次检查时遇到一次后端测试读空 JSON 的竞争失败，重跑通过；我两次重跑都没复现，记入 followups 观察。
- 等负责人说"合并"。合并时执行线同步更新 CODING_STANDARDS 10.15（主按钮墨色，强调色给链接和选中）。

### 2026-11-06 合并（执行线）

- 负责人："it's ok, just merge updata and push"。
- 实现提交 `766be0a`。第一次提交被钩子拦下，38 个迁移、OpenAPI 和分类测试失败。原因是工作目录的 .venv 软链到主仓库，钩子没有设 PYTHONPATH，测到的是已合并 M1.5-12/13 的 main 代码；加 `PYTHONPATH=$PWD/src` 重提后全绿。
- `--no-ff` 合并为 `b5b6ca6`，没有冲突。钩子在合并后的代码上全绿：后端 2765 passed，前端 385 passed。
- CODING_STANDARDS 10.15 已改：主按钮用墨色，强调蓝只给链接、选中和焦点环，标签和数字用等宽字体，字体随包打包。
- 字体副本已从 assets 删掉，只保留 `src/web/src/fonts/` 一份。
