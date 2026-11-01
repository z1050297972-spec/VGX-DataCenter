# 前端样式：简约外观、底部停靠菜单、玻璃质感

Status: done

分级：直做。理由：只改样式，不新增领域对象，不改任何接口和行为。这个目录只有这一张票，不另写 spec。

## 依据

- 负责人 2026-11-01 的要求："对前端样式做优化，风格参考 apple 官网的简约美学设计风格，可以使用停靠在下边栏的菜单目录等等，也可以加一些 liquid glasses 的设计。同时还要兼顾用户使用体验、开发者调试便利。"
- 负责人追加了两条限制："还有其他窗口在编写代码，不要冲突。""我希望本次前端优化只针对样式，功能代码上不要做任何改动，我担心会造成事故。"
- 现状：antd 6.6.7，没有配主题（没有 ConfigProvider）。外壳样式在 `src/web/src/shell.css`，它由 `accounts/Pages.tsx` 引入，登录页和所有登录后页面都会加载。主菜单是 `AccountMenu` 里的 `<nav aria-label="主菜单" className="app-menu">`，目前和用户名、角色、登出按钮挤在同一行。

- 负责人随后又要求："前端的代码编写方式，也请工程规范化。"样式的写法规范已写进 `docs/standards/CODING_STANDARDS.md` 10.1 节（10.7–10.13），本票的 CSS 必须照它写。tsx 里存量的内联 style 不在本票处理（见「不做」）。

## 硬性范围（越界直接打回）

- **只改 `src/web/src/` 下已有的 `.css` 文件**：`shell.css`、`datasets/browser.css`、`datasets/creation.css`、`datasets/fileViewer.css`、`datasets/fieldEditing.css`、`navwrites/writes.css`。
- **不改任何 `.ts`、`.tsx`、测试文件和 `index.html`**。不新建 CSS 文件，因为新文件需要在 tsx 里加 import。全局样式都写进 `shell.css`。
- 不加依赖，不改受保护文件，不用图标库，也不用网络字体。
- 其他线正在改 `accounts/Pages.tsx`、`jobs/Pages.tsx`、`audit/Pages.tsx`、`datasets/Creation*.tsx`。本票不碰这些文件，合并时就不会冲突。

## 设计要求

### 1. 设计变量（写在 `shell.css` 开头）

- 所有颜色、圆角、间距、阴影、模糊程度都定义成 `:root` 上的 `--rdp-*` 变量，后面的规则只引用变量。每个变量写中文注释，说明用在哪里。
- 字体：`-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif`；等宽字体：`ui-monospace, "SF Mono", Menlo, Consolas, monospace`。
- 浅色参考：页面底色 `#f5f5f7`，正文 `#1d1d1f`，次要文字 `#6e6e73`，强调色 `#0071e3`，卡片白底，大圆角（卡片 18px，控件 10–12px），阴影很淡，不用粗边框。
- 深色：用 `@media (prefers-color-scheme: dark)` 整套重定义变量（底色 `#000`/`#1c1c1e`，正文 `#f5f5f7`，强调色 `#2997ff`）。

### 2. 让 antd 用上这套变量

- antd 6 一直开着 CSS 变量模式（前缀 `ant`，key `css-var-root`，见 `node_modules/antd/es/theme/useToken.js`）。先读 antd 源码，确认变量声明在哪个选择器上、优先级是多少。然后在 `shell.css` 里用优先级足够的选择器覆盖 `--ant-*` 变量：主色及其 hover/active/浅底色、链接色、圆角、字体、正文色、容器底色、边框色。
- 只覆盖主色、不覆盖派生色，会出现半蓝半新色。所以要列出你覆盖的全部 `--ant-*` 变量，在最终回复里说明每个对应什么。
- 某个组件走不通变量覆盖时，再用组件类名（`.ant-card` 等）写规则，并在注释里写明原因。
- **状态色不动**：error、warning、success 的颜色和醒目程度保持原样或更醒目。`WorkerStatusBanner`、`RecoveryBlockBanner`、权限提示和 `DiagnosticCard` 是安全提示，不能为了好看把它们调淡。

### 3. 顶栏与底部停靠菜单（只用 CSS 实现）

- **顶栏**：`AccountMenu` 的外层 div（用 `.app-shell > div:has(> nav.app-menu)` 选中，不改 JSX）做成吸顶的玻璃栏，放用户名、角色、登出。外层 div 有内联 style（flex、右对齐），需要的话可以用 `!important` 覆盖内联样式，每处都写注释说明理由。
- **底部停靠菜单**：`nav.app-menu` 用 `position: fixed` 停在视口底部居中，距底 `calc(16px + env(safe-area-inset-bottom))`，做成胶囊形的玻璃底座：
  - 玻璃：半透明底色、`backdrop-filter: blur() saturate()`（加 `-webkit-` 前缀）、1px 的半透明高光描边（上沿亮一点）、柔和的投影。
  - 每个链接是一个药丸按钮。当前页（`a[aria-current="page"]`）用实心强调底色加白字，**不能只靠颜色区分**，再加字重或下划线之类的第二个提示。hover 有轻微的底色变化。
  - 键盘可用：`:focus-visible` 有清楚的焦点环，不要 `outline: none`。
  - 窄屏（≤ 640px）：底座占满宽度减去两侧 12px，菜单项过多时**在底座内部横向滚动**，整个页面不出现横向滚动条。
  - 正文不能被底座挡住：`.app-shell > main` 和版本 footer 留够底部空白（变量 `--rdp-dock-clearance`），保证最后一行表格和分页能滚出来，能点到。
  - 版本 footer（`.app-shell > footer`）用小号次要文字，放在内容末尾、底座上方，必须看得见。
- 登录页没有 `.app-shell`，单独处理：内容居中，放在一张白色大圆角卡片里。

### 4. 内容区

- `main` 设最大宽度（约 1280px），水平居中，留白宽松。宽表格仍然只在自己的容器里横向滚动（保留现有的 `min-width: 0`）。
- 标题层级清楚：页面标题大一些，`letter-spacing` 稍微收紧；次要信息用次要色。
- 卡片、表格、表单统一圆角和淡阴影，表格行高宽松一些，表头用次要色。
- 各页面 CSS 文件里写死的颜色换成 `--rdp-*` 变量。**布局不动**：grid、flex 的结构、列宽、显示和隐藏都保持原样，只调颜色、圆角、间距、字体。数据集浏览器的布局 A/B/C 尤其不要动。

### 5. 降级与无障碍

- `@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)))`：玻璃退回不透明底色。
- `@media (prefers-reduced-transparency: reduce)` 和 `(prefers-contrast: more)`：不透明底色、实线边框。
- `@media (prefers-reduced-motion: reduce)`：关掉过渡动画。
- 正文与底色的对比度至少 4.5:1，深浅两套都要满足。最终回复里列出主要几组颜色的对比度。

### 6. 方便开发者调试

- 在 `<html>` 上加属性 `data-rdp-plain`（在浏览器开发者工具里手动加，不写代码）就关掉所有模糊、透明和动画，方便截图和排查遮挡。这个开关只写在 CSS 里。
- `shell.css` 按"变量 → antd 覆盖 → 外壳 → 停靠菜单 → 内容 → 降级 → 调试开关"分节，每节开头写中文注释。不写嵌套很深的选择器。
- 不用 `display: none`、`visibility: hidden`、`opacity: 0` 或 `pointer-events: none` 隐藏任何已有元素。诊断卡片里的错误码、请求编号之类的细节照常显示，并用等宽字体。
- 不用 `z-index` 军备竞赛：只给顶栏和底座定 z-index（定成变量），而且要低于 antd 弹层（Modal、Dropdown、Message 的默认 z-index 是 1000 起），不能挡住弹窗。

## 验收

1. `git status --porcelain` 只出现上面列出的 `.css` 文件。
2. `make check` 全绿。测试不应受影响，因为 jsdom 不算样式；有测试失败，说明改到了不该改的东西。
3. `pnpm --dir src/web build` 通过，主入口大小没有明显变化。
4. 人工看效果（执行线用 headless Chrome 截图，负责人在浏览器里看）：
   - 宽屏（1440×900）和窄屏（390×844）各看：登录页、首页、数据集、作业列表、作业详情、账号管理、操作日志，共 7 页。
   - 底座不挡内容；当前页高亮清楚；弹窗和下拉菜单在底座上面。
   - 深色模式和 `data-rdp-plain` 各看一遍首页。

## 不做

- 图标、动效编排、页面结构调整、新组件、换路由、菜单分组。这些都要改 tsx，不在本票范围。
- 清理 tsx 里存量的 24 处 `style={{…}}`（分布在 10 个文件里），改成 CSS 类，并加 ESLint 规则禁止新增。这要改 tsx，也会撞上其他线正在改的文件。等 m2-03、m0-13 合并后另开第 02 张，见 `../followups.md`。
- 加 stylelint 做机检。这是新依赖，要改 `package.json` 和 `Makefile`，需要负责人批准，见 `../followups.md`。
- 用 ConfigProvider 接 antd 主题。效果更彻底，但要改 `mountWeb.tsx`；负责人要求这次不改代码。要做的话以后另开票。

## Comments

### 2026-11-01 开票与派工（执行线 m2）

- 工作目录 `~/桌面/robot-data-platform.wt/ui-style`，分支 `t/ui-01-apple-style`，从 main@87b21fc 开。只改 CSS，和 m2-03（accounts/jobs 的 tsx）、m0-13（audit/creation 的 tsx）没有共同的文件。
- 第一次派工开跑约两分钟时，负责人追加了"前端代码工程规范化"和"Tailwind 由 Claude 把控"两条要求，于是停掉，工作区没有改动。补写 CODING_STANDARDS 10.1 节（10.7–10.13）和 ADR 0010（不引入 Tailwind）后重新派工。
- 派工 A：Codex gpt-6.1-terra high，systemd 单元 `rdp-codex-ui-01`，会话 `01a1960f-c068-7ec2-bae9-6b279eb047c7`，日志 `~/.cache/rdp-dispatch/ui-01/`，提示 `assets/01/prompt-A.md`。

### 2026-11-01 评审 1（执行线）

- Codex 自报"未完成"，列出的都是待评审确认的点。文件归属：只改了 5 个允许的 CSS 文件（`writes.css` 没有要改的）。运行日志里没有安装和联网命令。
- `make check` 第一次因为 `test_file_preview_api.py::test_video_concurrency_is_two_and_recovers` 失败（和其他线同时跑检查，抢资源；CSS 影响不到后端）。单独重跑通过，整体重跑全绿（373 个前端测试、后端全过）。build 通过，入口 55.85 kB。
- 截图：隔离预览实例（scratchpad，假导航层，端口 8611，systemd 单元 `rdp-ui-preview`），7 页 × 1440/390，加深色和 `data-rdp-plain`。浅色达到预期。
- 打回 4 条：①深色模式下 antd 组件 token 盖不全（白表头、白按钮、禁用按钮不可见）。决定本票只做浅色，深色改用 antd 暗色算法，另开票（改 tsx）。②顶栏和横幅与内容区宽度不一致。③普通链接是浏览器默认蓝。④窄屏底座露出滚动条。
- 工单「设计要求」1 里的深色要求由本次评审撤销；`data-rdp-plain` 只要求关闭玻璃、模糊和动画，`browser.css` 里表示"次要"的 `opacity: 0.7` 是语义样式，保留。
- 修复轮 R1：同一会话续接，单元 `rdp-codex-ui-01-r1`。

### 2026-11-01 评审 2（执行线）：通过，等负责人说"合并"

- R1 只改了 `shell.css`，4 条都修好了：浅色固定（系统深色时也一致）、顶栏和横幅与内容区同宽、链接用主题色、窄屏底座只剩细滚动条。运行日志里没有安装和联网命令。
- 自己重跑 `make check` 全绿（后端 2627 passed，前端 373 passed）；build 通过，入口 55.85 kB，和改动前一样。
- 截图在 scratchpad 的 `preview/r1/`、`preview/r1-dark/`。
- 实现提交 `dbbfa42`（分支 `t/ui-01-apple-style`，钩子跑了全量 `make check`）。合并时后合并的一方要 rebase；本票只改 CSS，和 m2-03、m0-13 没有共同的文件。
- 不阻塞的问题：作业页两个相邻链接挤在一起（"提交示例作业提交资源示例"），要改 tsx 才能加间距，并入第 02 张。

### 2026-11-01 合并（执行线）

- 负责人："合并，批准，可以清理"。main 上先合了 M0 第 13 张（5cf3bc9），它没碰这 5 个 CSS 文件，`--no-ff` 合并没有冲突，合并提交 `fff6236`。钩子在合并结果上跑 `make check` 全绿（后端 2636 passed，前端 373 passed）。
- 工作目录和分支已删除，预览实例已停。真实部署没有升级，什么时候升由负责部署的 M1/M0 线决定。
