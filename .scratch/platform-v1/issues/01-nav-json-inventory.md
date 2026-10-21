# 盘点导航层的 70 份 JSON

Type: task
Status: resolved

## Question

对 `/mnt/datasets` 导航层做一次全量只读盘点，产出「数据集板块的数据契约」所依赖的事实。这张票由 agent 独立完成（AFK），全程不修改 `/mnt` 下的任何东西。

0002 的 F2–F6 只抽查了 `libero_10` 等少数样本。这张票要把每一项都扩展到全部 35 个数据集和两个视图：

- **schema**：三种 JSON（`原始路径.json`、`数据集信息.json`、`子任务.json`）各自的字段集合、`schema_version`、字段类型是否全部一致，列出所有偏离项。
- **两个视图的副本**：每个 `dataset_id` 在 `按任务` 和 `按格式` 里能否一一配对；`数据集信息.json` 是否全部相同；`原始路径.json` 是否只在 `view`/`format`/`version`/`entry_path` 上不同（F4）。
- **链接形态**：单链、跨盘 `__datasetN`、按子目录逐个链接，每种各有多少、分别是哪些；磁盘上的链接和 `links[]` 是否一一对应。
- **失效引用与断链**：`summary_path`、`文档/` 里的引用、断链。
- **取值集合**：`validation_status`、`source_role`、`source_type`、`format`/`version` 的全部取值。
- **数据集大小**：`数据集信息.json` 里"数据大小"一项的写法（单位、格式），能否解析成数字。
- **体积分布**：`子任务.json` 的大小分布。
- **非数据集目录**：`索引/`、`解压样本/`、`文档/`、`工具/` 等目录里有什么。
- **假导航层样本**：每种链接形态和目录深度各挑一个代表，作为 M0 测试用假导航层的样本清单。

**完成标准**：上面每一项都有数量和清单，并附上可以复跑的命令。结论写进本票的 `## Answer`；明细较长时存为 `docs/research/导航层盘点.md`，在 Answer 里链接过去。

## Answer

2026-10-21 全量只读盘点，全程没有写 `/mnt`。下面每一项的数量和清单见明细文档，复跑脚本在它的附录 A。

- **总体**：与 0002 F2 一致。35 个数据集 × 2 个视图 = 70 个目录；每个目录正好 3 份 JSON（共 210 份），没有其他文件；每个视图 42 条软链接（共 84 条），没有断链。
- **schema**：
  - 三种 JSON 的核心字段在 70 份里全部出现，类型一致。`原始路径.json` 和 `子任务.json` 的 `schema_version` 都是 1；`数据集信息.json` 没有 `schema_version`，并且多一个 F5 没记的字段 `information_scope`。
  - 偏离项：额外字段只出现在两个智元数据集，以及 12 个按 episode 选取子任务的数据集里。`子任务.json` 里非 LeRobot 的 source 省略 `version` 键，而 `原始路径.json` 写的是 `null`。robotwin_unified 有一个中文键 `说明`。
  - 一个 `task_key` 可以同时属于两个数据集（libero 系列有 2 例）。
- **两个视图**：
  - `数据集信息.json` 35/35 逐字节相同。
  - `原始路径.json` 33/35 只在 `view`/`format`/`version`/`entry_path` 上不同。
  - **例外是 EgoProStandard 和 EgoProDemo**：它们在 `按格式` 里的链接指向数据集内部的格式子目录；EgoProDemo 的 `按格式` 视图还少 1 条 mcap source 和 1 个子任务。所以 `按格式` 是"该格式的那一部分"，不一定是副本。
  - `tar、tar.gz（含分卷）` 目录下的 `format` 值是 `archives`。
- **链接形态**：单链 32 个；跨盘 1 个（EgoProStandard）；按子目录 2 个（agibot_world_2026、agibot_world_alpha）。84/84 与 `links[]` 一一对应（名字、`readlink` 目标、`entry_path`、`source_type`）。
- **失效引用**：
  - `summary_path` 70/70 失效；`文档/` 里有 8 处引用不存在的 `预览/`。
  - **两个智元数据集下的 3 个目录在 10-17 被删除，但 10-16 写的 JSON 还在引用它们**：涉及 `excluded_from_navigation` 3 条、source 3 条、子任务 root 3 个、evidence 6 条、`数据集信息.json` 链接 1 个。数据盘已经有过平台之外的改动，导航 JSON 没有同步。
  - agibot_world_2026 还留着一个 `.aria2` 控制文件，对应的 53.5 GB 归档可能没下完。
- **取值集合**：
  - `validation_status`：5 种。
  - `source_role`：4 种。
  - `source_type`：只有 `directory`。
  - source 的 `format`/`version`：8 种组合。
  - `label_status`：3 种。
  - `scope`：6 种。
- **数据大小**：35 条都能解析出精确字节数，取第一个 `（N B；`。其中 34 条写法统一，EgoProStandard 多了"合计 + 分盘"。这些都是 10-12 的快照：alpha 的数字里还包含已经删除的转换副本，35 条合计 35.77 TB，与 F7 的 35.11 TB 对不上。
- **`子任务.json` 体积**：中位数 3.7 KB；18 份 < 4 KB；最大的 agibot_world_2026 有 14.1 MB，其次是 EgoProStandard 1.0 MB。
- **非数据集目录**：
  - `索引/` 是空的。
  - `文档/` 有 3 份 md。
  - **`解压样本/` 里是 224 GB 真实数据，放在系统盘上**（推翻 F1 "只有软链接和 JSON"）。
  - `工具/mcap2lerobot` 有 2.1 GB，主要是构建产物。
  - `预览/`、`日志/` 不存在。
- **假导航层样本**：
  - 必选 5 个：libero_10、R1_lite_table_withdrawing_mcap、EgoProStandard、EgoProDemo、agibot_world_alpha。
  - 可选：agibot_world_2026，用于大文件测试；libero_90，用于测跨数据集子任务。
  - 另外要有空的 `lerobot/2.0`、`lerobot/2.1` 目录，以及非数据集目录的骨架。
  - 假导航层具体做成什么形态，由「数据集板块的数据契约」决定。
- 明细和复跑脚本：[docs/research/导航层盘点.md](../../../docs/research/导航层盘点.md)
- 对 0002 的更正：[docs/brief/0005-环境事实更新-导航层盘点.md](../../../docs/brief/0005-环境事实更新-导航层盘点.md)
