# 派工：「数据集浏览界面」一次性 UI 原型

你在 git worktree `/home/shawn/桌面/robot-data-platform.wt/prototype-dataset-browser`（分支 `prototype/dataset-browser`）里工作。这个分支永远不合入 main。任务：在 `src/web/` 下写一个能运行的 UI 原型，让负责人对着它确认「数据集浏览界面」的布局和交互（决策票 `.scratch/platform-v1/issues/16-dataset-browser.md`）。界面全部用中文。

## 0. 本次的特殊约定（覆盖 AGENTS.md 里的对应条目）

- **一次性原型**：不走"函数契约先行"，不写 docstring 六项，不写测试，不进 `make check`。但必须能运行，`pnpm build` 必须通过。注释用中文，简短，说明"为什么"。
- **只改 `src/web/` 下的文件**，实际上只在 `src/web/src/` 下新建和修改（`src/web/index.html` 必要时可以改）。
  - 下面这些由 Claude 建好，不要改：`src/web/package.json`、`src/web/pnpm-lock.yaml`、`src/web/tsconfig.json`、`src/web/vite.config.ts`、`src/web/.gitignore`。
  - `src/web/public/data/` 是 Claude 导出的数据，只读，不要改、不要删、不要另存副本。
  - `src/web/src/main.tsx` 现在是占位，替换掉。
- **不联网，不装新包**，不运行 `pnpm add/install/update/remove`。需要新包就停下来，在最终回复里写明包名、用途和原因。
- **不碰 `/mnt`**（不读也不写），原型要的数据已经导出到 `src/web/public/data/`。**不读取** `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`。
- 不要 `git add`、`git commit`。不要启动常驻的 dev server。
- 背景资料（可选，都在本 worktree 里）：`docs/manual/导航层手册.md`、`GLOSSARY.md`。下文已经把要用的规则写全了。

## 1. 已装好的依赖（只能用这些）

- 运行：`react` 19.3.1、`react-dom` 19.3.1、`antd` 6.6.7
- 开发：`vite` 8.3.5、`@vitejs/plugin-react` 6.1.2、`typescript` 7.0.2
- `pnpm build` = `tsc --noEmit -p . && vite build`；`pnpm typecheck` 只跑 tsc。
- **没有 `@types/react`**（不在批准清单里）：React 和 antd 的类型在 tsc 里都是 any（tsconfig 已关 `noImplicitAny`）。tsc 仍然检查你自己定义的类型和未定义的名字，所以给 `index.json` 和三份 JSON 写好 TypeScript 类型。
- antd 是 **6.x**，部分属性和 5.x 不同。拿不准的属性，去看 `src/web/node_modules/antd/es/<组件>/index.d.ts` 或同目录下的类型文件，不要凭记忆。
- 不要 import `@ant-design/icons`、`dayjs` 或任何间接依赖：它们不是直接依赖，pnpm 下 import 不到，也没有批准。图标用文字或字符代替（例如 ‹ › ▸ ▾）。
- 用 antd 的 `<App>` 和 `App.useApp()` 拿 `message`、`modal`，不用 `message.info()` 这类静态方法。最外层包 `ConfigProvider locale={zhCN}`（`import zhCN from 'antd/locale/zh_CN'`）。
- 没有路由库：URL 参数用 `URLSearchParams` 和 `history.replaceState` 自己读写。
- 不做持久化（不用 localStorage），状态都在内存里。没有后端，所有"按钮会提交作业"的地方只弹一条提示。

## 2. 数据

页面用 `fetch` 读：

- `/data/index.json`：启动时读一次。
- `/data/entries/<入口键>/原始路径.json`、`/data/entries/<入口键>/数据集信息.json`、`/data/entries/<入口键>/子任务.json`：文件名是中文，拼 URL 时用 `encodeURIComponent`。打开详情时读前两份；`子任务.json` 点了才读。最大的两份约 14 MB（`task__agibot_world_2026`、`format__archives__agibot_world_2026`）。读过的缓存在内存里。

`index.json` 的结构。动手前先用 `jq` 或 `python3 -I` 看一眼实际数据：

- `generated_at`、`generated_by`、`nav_root`（`/mnt/datasets`）
- `scan: {started_at, finished_at}`：上次扫描导航层的时间
- `sizing: {finished_at, command}`：上次统计大小的时间
- `storage_roots[]: {path, mount_source, device, fstype, access, online, mounted_source, checked_at}`：已登记的存储根。现在是 `/mnt/dataset1`、`/mnt/dataset2`，都在线、只读。
- `format_registry[]: {dir, format, has_version, versions_on_disk}`：格式目录登记表。
  - `lerobot` 有版本层，磁盘上有 `2.0`、`2.1`（都是空目录）和 `3.0`。
  - `mcap` 没有版本层。
  - `tar、tar.gz（含分卷）` 没有版本层，它的 `format` 是 `archives`。
- `non_dataset_dirs`：`["索引","文档","工具","解压样本"]`，非数据集目录，平台不扫描。
- `validation_status_labels`：`validation_status` 的值到中文标签的映射。
- `datasets[]`（35 个）：`{dataset_id, dataset_name, title, canonical_entry, entries[], recorded_size_bytes, recorded_size_date, robot_types[], robot_types_raw[], fps[], codebase_versions[], lerobot_sources, lerobot_info_found}`
  - `canonical_entry`：按任务入口的键，它的三份 JSON 是规范副本。`entries`：这个数据集在两个视图里的全部入口键。
  - `robot_types` 已经去掉了 `unknown` 和 `null`，为空表示"未知"。`fps` 是 `meta/info.json` 里的原始值（浮点数），为空表示"未知"。
  - `recorded_size_bytes`：`数据集信息.json` 第 4 项里 10-12 记录的字节数。
- `entries[]`（70 个）：`{key, view, format, format_dir, version, dataset_id, dataset_name, dir_name, path, files, links[], json_links_missing_on_disk[], source_count, dataset_roots[], size}`
  - `view` 是 `task`（按任务）或 `format`（按格式）。`path` 是入口在导航层里的相对路径，例如 `按格式/lerobot/3.0/libero_10`。
  - `files`：三份 JSON 各自的 `{bytes, mtime}`。
  - `links[]`：磁盘上的链接 `{name, target, target_exists, target_type, storage_root, in_json, json_source_path, checked_at}`。`json_links_missing_on_disk`：JSON 的 `links[]` 里登记了、磁盘上却没有的链接名。
  - `size: {bytes, measured_at, per_link[]}`：`bytes` 为 null 表示没统计过。
- `issues[]`（6 类）：`{id, group, group_name, level, rule_no, title, rule, found_by, datasets[], total, storage_roots[], consequence, next_step, samples[]}`
  - `level`：`action` 是"需要处理"，`info` 是"提示"。`group` 取 1–4。
  - `samples[]: {entry, entry_path, object, actual, expected, path, storage_root}`：前几条样例。`total` 是总处数。

三份 JSON 的形状，看 `public/data/entries/task__libero_10/`（小）和 `public/data/entries/task__agibot_world_alpha/`（字段最全）。

## 3. 按 prototype 技能的要求：三个布局变体

### 3.1 结构

- 原型只有一个页面 `/`，用 `?variant=A|B|C` 选变体，默认 A。在原型主文件顶部写一行计划注释：`三个布局变体（A/B/C），用 ?variant= 切换，挂在原型唯一的页面 / 上。`
- 文件放在 `src/web/src/prototype/dataset-browser/` 下，名字里带 prototype，一看就是原型。建议这样分：
  - `data.ts`：类型、加载、派生计算（树、大小回退、筛选、链接状态、问题计数）。
  - `widgets/`：共用的内容部件。
  - `VariantA.tsx`、`VariantB.tsx`、`VariantC.tsx`：各自导出组件和中文名。
  - `PrototypeSwitcher.tsx`、`DemoToggles.tsx`。
- 内容部件可以共用，例如 14 项表、链接表、大小块、数据块表、子任务查看器、一致性面板、筛选栏。**页面布局不共用**：每个变体自己决定布局、信息层次和主要操作方式。
- 三个变体都必须包含第 4 节的全部部件。

### 3.2 浮动切换条

- 屏幕底部居中，固定一个深色药丸形小条：左箭头、标签、右箭头。标签显示变体键和中文名，例如"B（一张大表 + 抽屉详情）"。
- 点箭头循环切换（首尾相接），用 `history.replaceState` 更新 `?variant=`，刷新后保持。
- 键盘 ← → 也能切换。以下情况不拦截：
  - 焦点在 input、textarea、select、contenteditable 里；
  - 焦点在 role 为 tree、treegrid、grid、tablist、menu、listbox、combobox 的元素里。
- 只在开发模式显示：`import.meta.env.DEV` 为 false 时不渲染。
- 一看就不是被评审的设计（高对比、带阴影）。z-index 要高于抽屉和弹窗；不能挡住分页器之类的操作，必要时给页面底部留白。

### 3.3 三个变体

**A（三栏：树 + 列表 + 详情页）**：票里描述的布局。
- 顶栏：标题"数据集浏览（原型）"；两个导航项"数据集""一致性面板"，后者带问题数。
- 左侧栏：两个页签"按格式 / 按任务"，各一棵树（antd Tree）。每个节点显示名字、数据集数量、总大小。
  - 按格式树：格式目录（`lerobot`、`mcap`、`tar、tar.gz（含分卷）`）→ 版本（`lerobot` 下的 `2.0`、`2.1` 是空目录，显示 0 个）→ 入口。
  - 按任务树：一个"按任务"根节点，下面 35 个入口。
- 中间：选中节点下的数据集列表，上面是筛选栏，下面是表格。列：名称、dataset_id、所在入口（例如"按任务""lerobot 3.0"）、机器人型号、FPS、大小、问题数。
- 点列表的行或树上的入口：中间换成该入口的详情页，带面包屑和"返回列表"，左侧树保持并高亮。返回时筛选条件保留。
- 一致性面板：从顶栏切过去，整页显示。

**B（一张大表 + 抽屉详情）**
- 没有左侧栏。顶部一行工具条：分段控件"按格式 | 按任务"、筛选（名称、型号、FPS），以及一致性摘要（"需要处理 1 类 · 提示 5 类"，点了展开面板）。
- 主体是一张树形表格（antd Table 的 children 行），这张表就是"树"：
  - 按格式时，分组行是格式 → 版本，叶子行是入口。分组行上显示数据集数量和总大小。
  - 按任务时，一个分组行下面 35 个入口。
- 点叶子行：右侧弹出宽抽屉（约 60% 宽）。详情分页签：概览（大小、链接、跨视图跳转）、14 项、数据块、子任务、其他字段。
- 一致性面板：放在表格上方一个可折叠的区域，默认收起，只显示摘要。表格每行带问题数徽标。
- 跨视图跳转：在抽屉里点了以后，切换分段控件、展开所在分组、高亮那一行，抽屉换成新入口的内容。

**C（目录式分栏，像文件管理器）**
- 照着导航层本身的目录结构浏览。顶部是路径栏，例如 `/mnt/datasets / 按格式 / lerobot / 3.0 / libero_10`，每一段都能点。
- 主体是横向排开的分栏（Miller columns，像 macOS Finder 的分栏视图）：
  - 第 1 栏是顶层：按任务、按格式，以及灰色的非数据集目录（索引、文档、工具、解压样本），标"不扫描"。
  - 之后每栏是下一级目录。目录项显示数据集数量和总大小；空目录（`lerobot/2.0`、`lerobot/2.1`）显示"空"。
- 选中入口后，下一栏像目录列表一样列出入口里的东西：
  - 每条链接，例如"原始数据 → /mnt/dataset1/…"，带状态；
  - 三份 JSON 文件，带文件大小。
- 点某个 JSON 文件，右侧预览区显示它：
  - `数据集信息.json` → 14 项表；
  - `原始路径.json` → 链接表、数据块表、其他字段；
  - `子任务.json` → 先显示大小和"加载"按钮。
- 入口那一栏的顶部显示大小块和跨视图跳转。
- 筛选：路径栏下面放筛选栏。有筛选条件时，在第 1 栏后面插一栏"筛选结果"，平铺列出匹配的数据集。
- 一致性面板：右上角一个按钮"一致性面板（1 · 5）"，点开右侧可收起的面板。有问题的目录项和入口带小圆点。点样例能跳到对应入口。
- 跨视图跳转：分栏跳到另一个视图里的对应位置。

## 4. 每个变体都要有的部件和显示规则

### 4.1 大小

- 用十进制单位：B、KB、MB、GB、TB（1 TB = 10^12 B），大约 3 位有效数字。鼠标悬停显示精确字节数（带千分位）。
- 入口的大小 = `entry.size.bytes`。数据集的大小 = 它按任务入口（`canonical_entry`）的大小。
- 树节点的大小 = 节点下各入口大小之和；节点的数据集数量 = 节点下不同 `dataset_id` 的个数。
- 列表和树上用统计值。没统计过（`bytes` 为 null）的，用 `recorded_size_bytes` 代替，并标出来，例如一个灰色小标签"记录值"。节点之和里含有记录值时，也要标出来。
- 详情页：统计值加统计时间（`measured_at`），并排显示"10-12 记录"（`recorded_size_bytes`），再给出两者的差（例如 −4.7%）。按格式入口的统计值只含这个格式的那部分，而 10-12 记录是整个数据集的大小，这一点要用一句话说明。
- 时间按 ISO 字符串里的本地时间，显示成 `YYYY-MM-DD HH:mm`，不做时区换算。

### 4.2 筛选

- **名称**：子串匹配，不分大小写，同时匹配 `dataset_id`。
- **机器人型号**：多选。选项是全部数据集 `robot_types` 的并集，再加一个"未知"，即 `robot_types` 为空的数据集（现在 10 个）。
- **FPS**：多选，按四舍五入后的整数匹配（`Math.round`）：数据集任一 FPS 值取整后落在所选集合里，就算匹配。选项是取整后的全部值，再加"未知"，即 `fps` 为空的数据集（现在 3 个）。例如 EgoProDemo 有 25 个原始值，取整后是 25、30、36。列表上显示取整后的值。
- 不同条件之间是"且"，同一条件里的多选是"或"。

### 4.3 详情页（一个入口）

- **读文件**：打开时读这个入口的 `原始路径.json` 和 `数据集信息.json`。
  - 14 项按规范副本显示，即 `canonical_entry` 那份 `数据集信息.json`。两份现在完全相同，但规则是按规范副本。
  - 链接、数据块、子任务用当前入口自己的文件。
  - 读取中显示加载状态，失败显示错误。
- **头部**：数据集名、`dataset_id`、`title`、所在视图和位置（`path`），以及跨视图跳转入口。
- **14 项**：三列表格：编号、名称、内容。
  - `value_markdown` 不用库，简单处理：反引号里的文字显示成代码样式；`[文字](<路径>)` 显示成可复制的路径（antd `Typography.Text` 的 `copyable`）；其余原样显示，包括 `**`。可以用一个正则一次切出两种记号：`` /`([^`]+)`|\[([^\]]*)\]\(<([^>]*)>\)/g ``。
  - 标注"内容是 {snapshot_date} 的快照"。
  - `数据集信息.json` 的其余顶层字段（`summary_path`、`summary_sha256`、`summary_anchor`、`snapshot_date`、`extracted_at`、`information_scope` 等）原样列在表下面。
- **链接表**：列：名字、指向（可复制）、是否存在、在哪个存储根、检查时间、状态（标签）。表头旁边放一个"重新检查"按钮，原型里只弹一条提示："原型：这里会提交一个只扫这个数据集的扫描作业"。状态有以下几种，现在的数据全是"正常"，但每种的代码都要写上：
  - `正常`：目标存在。
  - `断链`：存储根在线，但目标不存在。
  - `存储根离线`：目标所在的存储根离线，不算断链。演示开关 1 打开时，`/mnt/dataset2` 下的链接都是这个状态。
  - `不在已登记的存储根下`：`storage_root` 为 null。
  - `磁盘上没有`：`json_links_missing_on_disk` 里的名字，也要列成一行，指向取 JSON 里登记的值。
  - `JSON 里没有`：`in_json` 为 false。
  - `指向不同`：`json_source_path` 和 `target` 不同。
- **大小**：见 4.1。
- **数据块表**：分页，每页 20 条左右。EgoProStandard 有 734 条，agibot_world_2026 有 407 条。
  - 列：`source_id`、`direct_path`（可复制）、格式和格式版本、`source_role`、`validation_status`、`entry_path`、`entry_type`（有才显示）。
  - `validation_status` 显示中文标签，旁边带原值，标签取 `validation_status_labels`：`metadata_and_references_pass` 绿色，`attention_required` 橙色，其余默认色。
  - 表上方按 `validation_status` 汇总条数。
- **其他字段**：`原始路径.json` 里除 `links`、`sources` 以外的顶层字段原样显示，例如 `dataset_roots`、`notes`、`source_files_modified`；智元的两个数据集还有 `excluded_from_navigation`、`navigation_scope`、`task_metadata`。复杂的值用下面的 JSON 查看器。
- **子任务.json**：
  - 先只显示文件名、大小（`files['子任务.json'].bytes`，例如"14.1 MB"）和一个"加载"按钮，点了才 fetch。
  - 加载后：先是顶层字段的摘要（`task_count`、`data_unit` 等），再是可以折叠的 JSON 查看器。
  - 查看器自己写，不用库：对象和数组默认折叠，只展开第一层，点开才渲染子节点。数组超过 100 项时，按 100 项一组分段（"[0 … 99]"），避免一次渲染上万个节点。14 MB 的文件要能打开，不能卡死页面。
- **跨视图跳转**：列出同一数据集在另一个视图里的入口，即 `datasets[].entries` 里视图不同的那些。点一下就切到另一个视图，定位并选中那个入口（树、表或分栏里能看到选中状态），并打开它的详情。现在每个数据集在按格式视图里恰好有一个入口，但代码要按 0 到多个来写；0 个时写"按格式视图里没有这个数据集的入口"。
- **导航层有改动的提示**：演示开关 2 打开时，详情页顶部出现一条 Alert："导航层在上次扫描（{scan.finished_at}）之后有改动：这个入口的 原始路径.json 比索引新，链接状态和大小可能已经过期。"Alert 带一个"重新扫描"按钮，原型里只弹提示："原型：这里会提交一个只扫这个数据集的重新扫描作业"。

### 4.4 一致性面板

- **顶部**：上次扫描时间；每个存储根一个状态标签（在线或离线）；计数"需要处理 N 类 · 提示 M 类"。
- **四组两级**：
  - 四组是 ① JSON 本身、② 两个视图之间、③ JSON 和磁盘之间、④ 存储状况。四组都要显示，没有问题的组写"没有发现问题"。
  - 每组里分两级，"需要处理"在前，"提示"在后。
  - 按现在的数据：1 类需要处理、5 类提示，其中第 ③ 组 5 类、第 ④ 组 1 类；第 ①② 组没有问题。
- **同类问题合并成一行**（一个 issue 一行）：
  - 行上显示：级别标签、标题、规则（"第 {rule_no} 条：{rule}"）、涉及的数据集（数量和名字）、共 {total} 处、发现于 {found_by}。数据集名可以点，点了打开该数据集的详情。
  - 点开（Collapse）后显示：后果、下一步、样例表（对象、实际、期望、入口）。样例表下面写"显示前 {samples.length} 条，共 {total} 处"。样例的入口可以点，点了打开那个入口的详情。
- **演示开关 1 打开时**：
  - 面板顶部出现一条需要处理的 Alert："存储根 /mnt/dataset2 离线：本次扫描跳过了它下面的磁盘检查。"它属于第 ④ 组第 14 条，也作为一行加进第 ④ 组的"需要处理"。
  - `storage_root` 为 `/mnt/dataset2` 的样例变灰，标"未检查（存储根离线）"。一类问题的样例全部在离线存储根上时，整行标"未检查"。
  - 顶部计数相应调整。

### 4.5 演示开关

- 各变体共用，切换变体时保持状态。放在右下角一个固定的小浮动面板里，样式和底部切换条一致，一看就是原型控件，不属于被评审的设计。
- **开关 1"模拟存储根离线（/mnt/dataset2）"**：
  - 效果见 4.3 的链接表和 4.4。
  - 列表和树上，有链接落在离线存储根上的数据集，标一个"存储根离线"小标签。
  - 大小照常显示上次的统计值，三份 JSON 照常能看。
- **开关 2"模拟导航层在上次扫描后有改动"**：效果见 4.3。

### 4.6 用语

界面用语按 `GLOSSARY.md`：导航层、数据集、入口、视图（按任务视图、按格式视图）、规范副本、格式、格式版本、链接、数据块、存储根、离线、断链、重新扫描、统计大小、一致性面板、诊断。不要用"数据源""死链""失效链接""刷新""体检""健康检查"。

## 5. 交付

- 在 `src/web/` 下跑 `pnpm build`，确认 tsc 和 vite build 都通过。如果 pnpm 本身因为沙箱出错（不是代码问题），改跑 `pnpm exec tsc --noEmit -p .` 和 `pnpm exec vite build`，并在回复里说明。
- 最终回复用中文，包括：
  1. 改动清单：每个文件的路径，加一句话说明。
  2. 三个变体各自怎么放第 4 节的部件。
  3. `pnpm build` 的结果，贴最后十几行输出。
  4. 没做到的、和要求不一致的地方，以及原因。
  5. 需要新包的话，写在这里。
