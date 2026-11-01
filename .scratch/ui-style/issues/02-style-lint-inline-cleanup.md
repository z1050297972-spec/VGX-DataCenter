# 样式机检与内联 style 清理

Status: ready-for-agent

分级：直做。理由：不新增领域对象，不改行为；只把内联 style 挪到 CSS 类，加样式检查。

## 依据

- 负责人 2026-11-01："合并，批准，可以清理"，三项分别对应：合并第 01 张、批准 stylelint 依赖（`followups.md` 第 2 条）、开本票清理内联 style（第 1 条）。
- 规范：`docs/standards/CODING_STANDARDS.md` 10.1 节（10.7–10.13）、ADR 0010。
- 负责人对第 01 张的限制仍然有效："功能代码上不要做任何改动"。本票改 tsx 只做一件事：把 `style={{…}}` 换成 `className`，渲染结果和行为不变。

## 范围

### 1. 清理内联 style（10 个文件）

把下面这些文件里静态的 `style={{…}}` 换成该模块 CSS 文件里的类（10.10：类名用模块前缀，取值用 `--rdp-*` 变量）。模块还没有 CSS 文件的，新建一个，并在该模块的组件里 import：

- `audit/Pages.tsx`（3）、`navigation/Pages.tsx`（3）
- `datasets/Filters.tsx`（6）、`DataOrigin.tsx`（4）、`CreationForms.tsx`（2）、`FileViewer.tsx`、`Repoint.tsx`、`Markdown.tsx`、`CreationFields.tsx`、`FieldSummary.tsx`（各 1）

规则：

- 只换写法，不换效果：间距、宽度、对齐保持原样。原来写死的像素值，有对应变量就用变量，没有就在 `shell.css` 里加变量。
- 运行时才算得出的值（例如由 props 或状态算出的宽度、百分比），保留内联 style，用 `// eslint-disable-next-line no-restricted-syntax -- <原因>` 单条豁免。
- 不改 JSX 结构、文案、属性顺序以外的任何东西，不改测试。现有测试必须原样通过。
- 第 01 张遗留的作业页链接挤在一起的问题，在 `jobs/Pages.tsx` 里，那个文件不在本票范围（见下），留到 M2 合并后处理。

**不碰** `accounts/Pages.tsx`、`jobs/Pages.tsx`：M2 第 03 张正在改它们。它们在 ESLint 配置里按文件临时关掉禁止 style 的规则，注释写"等 M2 合并后清理，见 ui-style followups"。

### 2. ESLint：禁止新增内联 style（10.9 改成机检）

- `eslint.config.js`（本票允许改）：用 `no-restricted-syntax` 禁止 JSX 的 `style` 属性（选择器 `JSXAttribute[name.name='style']`），提示语指向 CODING_STANDARDS 10.9。不需要新依赖。
- 上面两个文件按文件关掉这条规则，其他地方一律生效。

### 3. stylelint（10.7、10.10、10.11、10.13 改成机检）

依赖 `stylelint@17.16.0`、`stylelint-config-standard@40.0.0`（开发依赖）由执行线先装好，单独做依赖提交，Codex 不装。

- 新建 `src/web/stylelint.config.js`（本票允许新建），继承 `stylelint-config-standard`，再加：
  - 10.7：页面 CSS 禁止写死颜色（`color-no-hex`、`color-named: never`，并用 `function-disallowed-list` 禁 `rgb`/`rgba`/`hsl`/`hsla`）。`shell.css` 是定义变量的地方，用 `overrides` 放开。
  - 10.10：`selector-class-pattern` 为 kebab-case；`selector-max-compound-selectors: 3`；`selector-max-id: 0`（`shell.css` 的 `#root` 用单条豁免并写原因）。
  - 10.11：`declaration-no-important: true`，豁免必须带说明（`reportDescriptionlessDisables`、`reportNeedlessDisables` 打开）。`shell.css` 里调试开关那两处 `!important` 用单条豁免。
  - 10.13：页面 CSS 的媒体查询只允许宽度断点（`media-feature-name-allowed-list: ["width", "min-width", "max-width"]`），`shell.css` 放开。
  - `stylelint-config-standard` 里和现有写法冲突、又不在 10.1 节里的规则（例如要求改写法但不影响可读性的），可以关掉，每条在配置里写注释说明为什么关；在最终回复里列出关掉的规则。
- `Makefile`（本票允许改）：在前端检查里加一步 stylelint（放在 Prettier 后面，编号顺延），`make fmt` 不用自动修复。只改这两处。
- 现有 CSS 照规则修到全绿。修 CSS 只改写法，不改视觉效果。

## 验收

1. `git status --porcelain` 只出现：上面 10 个 tsx、对应模块的 CSS（含新建的）、`shell.css`、`eslint.config.js`、`stylelint.config.js`、`Makefile`。
2. `make check` 全绿，包括新加的 stylelint 一步；不改任何测试文件。
3. 关键行为（各验证一次，写进最终回复，验完把试验改动撤掉）：
   - 在任意页面 tsx 里加一个 `style={{ color: "red" }}`，ESLint 报 10.9 的提示。
   - 在页面 CSS 里写 `color: #f00;`，stylelint 报错。
   - 在页面 CSS 里写一个没带说明的 `!important`，stylelint 报错。
4. 执行线截图对比：清理前后 `datasets`、`audit/operations`、`navigation/recovery` 三页像素级一致或肉眼无差别。

## 不做

- `accounts/Pages.tsx`、`jobs/Pages.tsx` 的清理，以及 M2 新加的下载页组件：M2 合并时由执行线处理（`followups.md`）。
- 深色模式（`followups.md` 第 4 条）。

## Comments

### 2026-11-01 开票（执行线）

- 工作目录 `~/桌面/robot-data-platform.wt/ui-style`，分支 `t/ui-02-style-lint`，从 main@58f59c3 开。
- M1/M0 线 datasets-e9 回复：他们现在没在改 Makefile、eslint.config.js 和这 10 个 tsx。M0-13 已合并；他们的下一张是 M0 第 12 张备份，以后端为主，开工前会先 pull main。真实部署由他们统一升级。
- 安装 stylelint 被自动权限检查拦下（判定为外部代码），等负责人亲自执行 `pnpm add`。
- 负责人决定（datasets-e9 转达）：M2 下载线和前端样式线手上的任务都合进 main 后，真实部署统一升级一次。**本票合并后，给 datasets-e9 发消息，写上合并提交号。**升级由他们做。
