# 五个筛选统一以数据集信息.json 为准；数据来源挪出来源.json；与原文件比对

Status: done

分级：骨架关卡。理由：改两份导航文件的格式（`数据集信息.json` 加 `fps`、`data_origin`；`来源.json` 去掉数据来源，升到第 2 版），改筛选接口契约（去掉 `robot_type`、`robot_model_id`），还有一次批量写导航层的迁移（3.0 第 1 条"数据契约""改已有契约的含义"）。按"只做关键测试"；安全底线照旧。

Blocked by: 14（基于 t/m15-14-manual-check 分支开工，合并时先合 14）

## 依据

负责人（2026-11-06）：

> 我们不对原文件做任何更改，更改的是导航层的 数据集信息.json，那么条件匹配也根据 数据集信息.json 来筛选……五个筛选条件全部按照数据集信息.json为准，我们再额外做一个比对的功能，将14项信息和原数据文件做一个比较，这也算是提醒使用者 在正式使用该数据集前，哪些参数要更改……我们在前端对这点也作出说明。这样筛选中就不会出现很多"未知"。

> M3中的机器人型号直接使用型号标签这个字段

> 因为问题一中，筛选是以 数据集信息.json为准了，所以我觉得 型号标签这个字段无所谓

> 保留来源.json，只存血缘

当面定下的（执行线提出，负责人同意）：
- 筛选读 `数据集信息.json` 的**顶层结构化字段**，不解析 14 项 Markdown（ADR 0006 已放弃解析：35 份里 6 份是自由文字）。14 项只做展示和并排对照。
- 型号只留一个概念：顶层 `robot_model`。"型号标签"不再作为筛选；M3 不建平台型号表。
- 上线时做一次回填，否则切换后型号和 FPS 会变成"未标注"。
- `来源.json` 保留，只存血缘和采集任务编号。

## 导航层现状（2026-11-06，执行线只读核对，不跟随链接）

- 35 个数据集。`robot_model`：25 个已人工填写，10 个没有这个键：EgoProStandard、R1_lite_table_withdrawing_mcap、agibot_world_2026、agibot_world_alpha、aloha_mobile_elevator、aloha_mobile_rigid_multi_pick、aloha_mobile_shrimp、aloha_mobile_wash_pan、aloha_mobile_wipe_wine、nyu_door_opening。
- 顶层 `fps`：35 个都没有。
- `来源.json`：35 个都有，`data_origin` 都已填，`lineage` 全空，`collection_task_id` 全空。
- 已有人工值里有前导空格（如 `" Kinova Gen3 机械臂"`、`" PR2（Personal Robot 2）"`）。

## 契约（先定死，骨架照此提交）

### 导航文件

- `数据集信息.json` 顶层（新键追加在末尾，ADR 0009 L11）：
  - `robot_model`：已有，非空文本。读取时去首尾空白；缺失、空串、非文本 → 未标注。
  - `fps`：**新增**，正整数。缺失或不合法 → 未标注。
  - `data_origin`：**新增**，取值为 `DATA_ORIGINS` 的中文值之一（真机采集、UMI 采集、ego 采集、仿真生成、开源下载、未知）。缺失 → 未知。不再记 `data_origin_set_by`，谁改的靠操作日志和变更记录追溯。
  - 按格式入口的副本照旧由规范副本整份复制（ADR 0009 L8、L9）。
- `来源.json` 第 2 版：`schema_version: 2`，去掉 `data_origin` 和 `data_origin_set_by`，保留 `dataset_id`、`dataset_name`、`collection_task_id`、`lineage`。
  - 读：第 1 版照旧能读，其中两个数据来源字段读到后忽略（不再参与任何显示和筛选）。
  - 写：平台写出的一律是第 2 版。

### 筛选接口

- 五个筛选：`robot_model`、`fps`、`data_origin`、`scene`、`tasks`，全部取自规范副本的 `数据集信息.json` 顶层（经扫描进索引）。
  - `robot_model`：按去空白后的文本精确匹配；`unlabeled` 表示未填写。
  - `fps`：整数精确匹配；`unknown` 表示未填写（沿用现有写法）。
  - `data_origin`、`scene`、`tasks`：规则不变，只是数据来源换了。
- 删除：查询参数 `robot_type`、`robot_model_id`；筛选候选里的 `robot_types`、`robot_model_options`、`robot_models`、`robot_models_registered`、`default_robot_filter`；M3 型号表的回调 `read_robot_models`（含 `read_unregistered_robot_models`）。
- 新增候选：`robot_models`（值、计数，含"未标注"）。列表行里显示型号的字段改为 `robot_model`（文本或 null），去掉 `robot_types`、`robot_model_ids`。
- `meta/info.json` 的 `robot_type`、`fps` 仍由扫描读进索引，**只用于比对和回填**，不出现在任何筛选里。

## 范围

1. **读取与索引**（`reading.py`、`_index_write.py`、`models.py`、迁移）：扫描读顶层 `fps`、`data_origin`；索引存这两个值和去空白的 `robot_model`；`来源.json` 按上面的读规则。加数据库迁移；如果升级后需要重新扫描才有值，在最终回复里说明。
2. **筛选**（`dataset_browser/_listing.py`、`queries.py`、`schemas.py`、`api/datasets`）：按契约改匹配和候选；删除型号表相关代码。
3. **编辑**（`navwrite/_field_rules.py` 等）：
   - `INFO_LABELS` 加 `fps`（FPS）和 `data_origin`（数据来源）。`data_origin` 只能选取值表里的值；`fps` 只收正整数。
   - 删除只改 `来源.json` 的数据来源作业（`navwrite/origin.py`）及其接口，数据来源改为普通字段编辑。
   - 新建数据集：`data_origin` 仍然必填，写进 `数据集信息.json`；同时建第 2 版 `来源.json`（血缘为空）。
   - 下载入库（M2）：`开源下载` 写进 `数据集信息.json`；血缘照旧写进 `来源.json`（第 2 版）。
4. **回填迁移**：一个管理员才能提交的写导航层作业，走现有的预览 → 确认 → 写入 → 可撤回流水线，一次覆盖全部数据集。

   **硬约束（负责人 2026-11-06："14项数据集信息我都已经改好了，我不希望回填对他产生影响"）**：回填对 `数据集信息.json` 只**新增**两个顶层键，别的一个字节都不改：`fields`（14 项）、`title`、`robot_model`、`scene`、`tasks`、`subtask_notes` 及其余键保持原值、原顺序。测试要逐键断言除新增两键外前后相等。

   - `data_origin`：顶层没有时，从 `来源.json` 第 1 版复制。
   - `fps`（负责人 2026-11-06："用第 8 项的数字回填 FPS，可以回退同info.json中的FPS做回填……但是这个方法只是一次性的"）：顶层没有时，按顺序取：
     1. 第 8 项（number=8、name=FPS）的 `value_markdown` 去首尾空白后是**一个正整数，后面可以跟一个括号说明**（全角或半角括号，例如 `50（meta/info.json 声明的数据帧率）`），就用这个整数。只认这两种写法，不从自由文字里抠数字。
     2. 否则取索引里规范入口的 info.json `fps`（只限 LeRobot 且读到了），**而且只有一个取值**时才用（EgoProDemo 有 30/36/25 三种，不写）。
     3. 都没有就不写。
     预计（2026-11-06 核对）：30 个走第 1 条（23 个纯数字，7 个"数字+括号说明"），1 个走第 2 条（agibot_world_2026，第 8 项是自由文字），EgoProDemo、agibot_world_alpha、R1_lite_table_withdrawing_mcap、EgoProStandard 不写。
     **只在这次回填用**：之后扫描、筛选、比对都不再读第 8 项文字；顶层 `fps` 只能通过字段编辑改。
   - `robot_model`：**不回填、不清空格**。空的保持空（目前 aloha_mobile 的 6 个和 nyu_door_opening 等），由负责人在页面上填。
   - `来源.json` 改写成第 2 版（血缘原样）。
   - 跑第二次时预览应为空（幂等）。入口放在哪里由实现选，管理员可见即可。
   - 前导空格：读取和筛选时 `robot_model` 去首尾空白；字段编辑保存 `robot_model` 时写入去空白后的值。回填不做这件事。
5. **比对**（worker 扫描，结果进一致性面板，提示级，只报告不修复）：只比规范入口、LeRobot、info.json 读到了的数据集。
   - `INFO_ROBOT_MODEL_DIFFERS`：`robot_model` 与 info.json `robot_type` 不同（去空白、不区分大小写后比较）。
   - `INFO_FPS_DIFFERS`：顶层 `fps` 与 info.json `fps`（取整）不同。
   - 场景、任务、来源在原数据里没有对应项，不比。14 项正文不自动比，详情页把平台读到的值和 14 项并排显示。
   - 编辑页的 FPS 输入旁，照现有"原文件 robot_type（索引参考）"的写法显示"原文件 fps"。
6. **前端**：
   - 筛选栏：型号一个下拉（候选来自索引里已用过的值，带计数），删掉"型号标签"和"更多筛选"；FPS、来源、场景、任务不变。
   - 筛选栏加一行说明（文字可调，意思不改）："筛选以导航层的数据集信息为准，不读原数据文件。与原文件不一致的地方见一致性面板，正式使用数据集前请核对。"
   - 型号输入改为可选已有值、也可新建（`AutoComplete` 或 `mode="tags"` 单值），减少同一型号多种写法。
   - 新字段在 14 项编辑器里的位置照第 09 张的写法：`fps` 输入放第 8 项（FPS）那一行，`data_origin` 选择放第 3 项（类型与组成）那一行，原来的文字框保留在下面。按 number+name 找不到对应项时退回单独位置。
   - 数据来源部件（`DataOrigin.tsx`）并入字段编辑。
   - 第 14 张的说明卡片"检查什么"补一条："与原文件比对：型号、FPS 和 LeRobot 的 meta/info.json 是否一致（只提示）"。
7. **文档**：使用手册、导航层手册（两份 JSON 的新字段、来源.json 第 2 版）。ADR 0006、0008 的修订由执行线写（已写，见「修订（2026-11-06）」）。

## 验收

1. **关键测试**：
   - 读取：顶层 `fps: 30`、`data_origin: "仿真生成"` 进索引；`来源.json` 第 1 版里的 `data_origin` 不再影响筛选。
   - 筛选：按 `robot_model`、`fps`、`data_origin` 各能命中；`robot_model=unlabeled` 命中没填型号的；接口不再接受 `robot_type`（422）。
   - 编辑：提交 `fps`、`data_origin` 后规范副本和格式副本都改了；`data_origin` 传取值表外的值返回 422。
   - 回填 FPS 来源：第 8 项 `"20"` → `fps: 20`；第 8 项 `"50（meta/info.json 声明的数据帧率）"` → `fps: 50`（取自第 8 项，不读 info.json）；第 8 项是自由文字、info.json 只有 30 → `fps: 30`；第 8 项是自由文字、info.json 有两种帧率 → 不写。
   - 回填：`数据集信息.json` 除新增的 `fps`、`data_origin` 外逐键不变（含 `fields`、`robot_model`，空 `robot_model` 仍为空）；`来源.json` 变成第 2 版且血缘原样；第二次预览为空；能撤回。
   - 空白：`robot_model: " PR2"` 筛选按 `PR2` 命中；编辑保存后写成 `PR2`。
   - 比对：型号或 FPS 和 info.json 不同时出现对应提示，相同时不出现。
   - 前端：筛选栏只有一个型号下拉，有说明文字。
2. **真实演练**（执行线）：升级后先预览回填、核对差异（应只有 31 份 `fps` 新增、35 份 `data_origin` 新增、35 份来源.json 升版；14 项和型号零差异），确认写入，看筛选和面板，再撤回一次确认能回去，最后重新写入。两块数据盘写入扇区数不变。
3. **检查链**：`make check` 全绿、0 skipped。

## 负责人已定（2026-11-06）

1. 型号比对的提示可以接受（现有人工型号多是品牌名，与 info.json 的 `robot_type` 写法不同，首轮提示会较多）。
2. 前导空格要清，但不通过回填改文件：读取时去空白，保存时写去空白后的值。
3. 回填不得影响 14 项信息页上已改好的内容（见范围第 4 条硬约束）。
4. FPS 回填先用第 8 项的纯数字，再回退 info.json；只用这一次。

## Comments

- 2026-11-06 开票（执行线；负责人点名"按照你说的来吧"）。ADR 0006、0008 已追加修订节。等第 14 张合并后派工。
- 2026-11-06 负责人定了三点（见「负责人已定」）。回填改成只新增 `fps`、`data_origin`，不碰 `robot_model` 和 14 项。
- 2026-11-06 负责人："现在就开始做吧"。契约已逐条当面定，按工单契约直接实现，不另交骨架。基于 t/m15-14-manual-check 开分支 t/m15-15-filters-info；前后端两个并行会话（gpt-6-astra medium）。真实演练（回填写真实导航层）另等负责人。
- 2026-11-06 05:34 派工：前后端两个会话（systemd 单元 rdp-m15-15-be / rdp-m15-15-fe，日志 ~/.cache/rdp-dispatch/m15-15/），超时 60 分钟。
- 2026-11-06 05:38 负责人要求多开并行：停掉后端单会话（未改文件），拆成核心/回填/比对三个会话（rdp-m15-15-core/backfill/compare），前端会话照旧。make api-types 由执行线最后统一跑。
- 2026-11-06 06:04 负责人要求暂停。比对（05:49）、前端（06:02）、回填（06:02）三个会话已交回；后端核心会话被手动停掉，改动做了一半留在工作目录（未提交），Codex 会话 "thread_id":"01a1b0dd-b314-76b2-a5de-6ead1d195dea"，可用 codex exec resume 续做。已知待办：核心会话删 api/data_origin.py 时要保留通用接口 GET /api/navigation/previews/{job_id}，并清理注册表里的 build_data_origin_definition；之后执行线统一 make api-types、删前端临时类型 api/informationTypes.ts、跑 make check。待办（不阻塞）：比对按数据块逐个出提示，EgoProDemo 会刷很多条，以后改为每个数据集一条。
- 2026-11-06 09:37 负责人说继续：续接核心会话（rdp-m15-15-core2），附上回填会话报的两处集成问题。
- 2026-11-06 10:13 核心交回（迁移 0018_information_filters，升级后需重扫；通用预览接口迁到 api/navigation_writes.py）。执行线跑 make api-types；前端续接删掉临时类型（10:16）。make check 全绿：后端 2753 passed、Vitest 376 passed、0 skipped。变异抽查：回填清 robot_model 空格、FPS 规则不认括号说明，均被 tests/test_information_backfill.py 抓到。评审无阻塞问题。待办（不阻塞）：比对按数据块出提示，EgoProDemo 会多条。剩：真实演练（回填真实导航层）和合并，等负责人；合并顺序先 14 后 15。
- 2026-11-06 18:55 负责人说合并：先合 14（e49530d）再合 15。接着做真实演练。
