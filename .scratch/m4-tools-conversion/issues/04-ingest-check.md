# 入库检查与入库

Status: done

分级：直做（负责人 2026-11-08 授权按顺序完成 M4；骨架和合并由执行线按建议过）。按"只做关键测试"。写导航层，要做副本演练。

Blocked by: 03

## 依据

- `../decisions.md` 决定 5；与 M3 的协调（血缘格式、`collection` 键）。
- ADR 0008：入库检查按产物格式定、分四层；通过自动入库，有警告人确认，不通过留在暂存区；入库是同文件系统改名再建入口；血缘只追加；转换产物是新数据集，数据来源沿用输入。负责人原话："能否给一个检查摁纽，通过后自动入库"。
- M2 第 05 张「下载入库」的做法：改名不覆盖（`RENAME_NOREPLACE`）、复用 M1 的新增数据集流程、写导航层失败时改回暂存位置、14 项自动填（`rdp.jobs.downloads` 的 ingest 系列）。能复用的直接复用，不再写一份。
- `rdp.jobs.navwrite.provenance` 的 `LineageRecord`（不改模型）。
- 真实产物的元数据样本：`tests/fixtures/mcap2lerobot/lerobot-v3/`（没有 videos，见 `meta.json`）。

- M3 已全部合并（main `edd9e5a`，M3 会话 datasets-45 2026-11-08 通知）：
  - `rdp.jobs.navwrite.create_models.DatasetPreviewParameters` 新增 `collection: CollectionInformation | None = None`，`link` 改成 `FirstLink | None = None`。转换产物照旧传 `link`、不传 `collection`（默认 None），写出的 `数据集信息.json` 就不会有 `collection` 键。
  - 血缘上下游投影（迁移 0021、详情响应的 `lineage: {upstream, downstream}`）已按所有记录的 `inputs[].dataset_id` 做，本票写的 worker 记录会自动出现，不用改投影和详情页。
  - 迁移已到 0021；本票如需迁移从 0022 起。

## 契约

### 入库检查（worker 作业，恢复方式 restart）

输入：一个成功的转换作业编号。对象是 `暂存/转换/<作业编号>/out/`。检查按产物格式（`meta/info.json` 的 `codebase_version`）定，不按工具定。v3.0 和 v2.1 的目录布局不同，各按 LeRobot 该版本的布局找文件（v2.1：`meta/episodes.jsonl`、`data/chunk-*/episode_*.parquet`、`videos/chunk-*/<键>/episode_*.mp4`）。

1. **结构**：`meta/info.json` 能读；`codebase_version` 等于转换作业参数里的 `output_format`；必需的目录和文件都在。
2. **计数**：`total_episodes` = episodes 元数据的条数；`total_frames` = 全部 data parquet 行数之和 = 各 episode 长度之和（只读 parquet 元数据，不读全部数据）。
3. **视频**：每个视频特征引用的文件都在；`ffprobe` 读到的编码、宽、高和 `info.json` 的 `video.codec`、shape 一致；每个视频文件时长和它包含的帧数 ÷ fps 相差不超过 1 帧的时长。
4. **内容**：`observation.state`、`action` 的维度和 `info.json` 一致；抽第一个、中间一个、最后一个 episode，这两列没有 NaN/Inf。

- 工具退出码不是 0，或转换作业不是成功状态：直接"不通过"，不往下查。
- 结果三种：`通过`、`有警告`（例如 `info.json` 里有平台不认识的额外字段，或时长差在 1 帧以内但非 0 帧这类不影响使用的情况，由实现时按层定义，写进 docstring）、`不通过`。每层的结论和诊断写进 `暂存/转换/<作业编号>/入库检查.json`，作业结果里也给出。

### 入库

- **自动**：转换作业成功后自动提交一次入库检查；检查"通过"就自动入库，用默认名字和位置；默认名字或位置已被占用时不自动入库，转为等人确认。
- **手动**："检查并入库"按钮（暂存区列表和转换作业详情里都有）：先跑检查，再给预览（数据集名可改、存放位置可改、按格式入口勾选、自动填的 14 项、检查结果），确认后入库。"有警告"必须由人确认。"不通过"不能入库。
- **默认值**：数据集名 `<输入数据集名去掉 _mcap 后缀>_lerobot`，已存在时追加 `_<作业编号>`；存放位置在同一可写存储根下 `转换/<数据集名>`。
- **步骤**：同文件系统改名（不覆盖）→ 用 M1 的新增数据集流程建按任务入口和按格式入口（`lerobot/<版本>`）→ `来源.json` 追加血缘记录 → 失败时把目录改回暂存位置。
- **新数据集的字段**：`data_origin` 沿用输入数据集；**不写** `数据集信息.json` 的 `collection` 键（M3 第 03 张新增；转换产物不是采集任务）；14 项从 `info.json` 自动填（照 M2 第 05 张），"信息来源与核验日期"写"mcap2lerobot 转换自 <输入数据集名>，转换作业 <编号>，入库日期"。
- **血缘记录**（`LineageRecord`，和 M3 商定）：`kind="转换"`、`status="完整"`、`recorded_by.kind="worker"`；`inputs` 每项 `{"dataset_id", "source_id"}`；`outputs` 一项（新数据块的 `source_id`、`format`、`codebase_version`）；`tool` = `{name, version, commit（清单 source_commit）, binary_sha256}`；`config` = `{path（登记包里的相对路径）, sha256, text（全文）}`；`robot_profile=None`；`parameters` = 转换作业参数；`job_id` = 转换作业编号；`started_at`/`finished_at` = 转换作业起止；`ingest_check` = `{result, warning_count}`。

### 暂存区页面

- "转换暂存"列表（放在作业页附近，照 M2 下载暂存列表的样子）：作业编号、输入数据集、工具、格式、大小、检查结果、状态（待检查/待确认/已入库/不通过/失败），操作"检查并入库"和"删除"（删除只对未入库的，走现有的删除暂存写法）。

## 不做

- 逐帧解码等深度质检（ADR 0008："数据质检"）。
- 修改已有数据集（转换产物一律新建）。

## 允许改的受保护文件

- 生成的 `openapi.json`、`schema.d.ts`（只能 `make api-types`）。
- 如需新表，迁移编号用 main 上下一个空号（合并时执行线核对；M3 也在加迁移）。

## 依赖申请

无（pyarrow 已在依赖里；ffprobe 是系统程序，已用于文件查看）。

## 验收（关键测试）

测试用的 LeRobot 产物：以 `tests/fixtures/mcap2lerobot/lerobot-v3/` 为底，复制到 tmp；视频用 ffmpeg 在测试里生成小视频，`info.json` 里的视频 shape 跟着改成小视频的尺寸（测试自己改副本，不改样本文件）。

1. 四层各一个不通过的用例：缺 `meta/info.json`；`total_frames` 和 parquet 行数不一致；视频缺失或分辨率不一致；state 里有 NaN。
2. 通过的用例：自动入库，导航层多出按任务入口和 `lerobot/v3.0` 按格式入口；暂存 `out/` 消失、目标目录出现；`来源.json` 里追加一条 `kind="转换"`、`status="完整"`、`recorded_by.kind="worker"` 的记录，`tool.binary_sha256`、`config.text` 正确；`data_origin` 等于输入数据集的；`数据集信息.json` 没有 `collection` 键。
3. 有警告：不自动入库；人工确认后入库。
4. 默认名字已存在：不自动入库，转为待确认。
5. 写导航层失败（模拟）：目录改回暂存位置。
6. 前端：暂存列表显示检查结果；"检查并入库"打开预览，名字和位置可改，一个 Vitest 用例。
7. `make check` 全绿、0 skipped。
8. **副本演练**（执行线）：在导航层副本上，用第 03 张演练产出的真实转换结果入库一次；两块数据盘写入扇区不变；详情页能看到"由 R1_lite_table_withdrawing_mcap 转换"（M3 第 05 张合并后）。

## Comments

- 2026-11-08 开票（执行线）。
- 2026-11-08 08:2x 派工（直做）：worktree `robot-data-platform.wt/m4-04-ingest-check`，分支 `t/m4-04-ingest-check`；单元 `rdp-m4-04`；`gpt-6-astra` high，90 分钟；会话 `01a1bbbf-7823-7002-b6cc-57d6011259d9`；日志 `~/.cache/rdp-dispatch/m4-04/`。
- 2026-11-08 09:20 第一轮交检查点（约 58 分钟）：四层检查（`check.py`、`check_models.py`、`_check_child.py`、`_check_data.py`、`_check_video.py`）和 7 个用例完成，后端 2844 passed；前端测试因共享 node_modules 只读（Vite 写不了 `.vite-temp`）没跑完。执行线核对：视频按 `(高, 宽) == shape[:2]` 比较，顺序正确；用真实产物量过，ffprobe 时长与帧数 ÷ fps 偏差 0.0 s，"有偏差但不超过一帧算警告"不会在真实数据上误触发。
- parquet 样本：仓库 `.gitignore` 的 `*.parquet` 让 `lerobot-v3/` 的 parquet 没进仓库，按"数据不进仓库"保持；测试在 tmp 里生成，`meta.json` 由本票改成实际情况。
- 2026-11-08 09:2x 执行线把工作目录的 `src/web/node_modules` 换成一层真实目录（子链接指向共享依赖），续接同一会话做完剩余范围（单元 `rdp-m4-04-c1`，90 分钟）。
- 2026-11-08 10:18 续接轮交回（退出码 0）：Codex 自报 `make check` 全绿（2849 / 412），0 skipped。
- 2026-11-08 评审（执行线）：
  1. 重跑：`make check-changed` 全绿（49 s）；另不经 testmon 完整跑转换相关测试 27 passed、入库相关 80 passed、`tests/jobs/`（含 M2 下载入库）98 passed——下载入库被抽成共用代码后行为不变。
  2. 文件归属：只有 `src/`、`tests/`、生成的接口类型，和获准修改的 `tests/fixtures/mcap2lerobot/meta.json`；主仓库目录无非规划改动。
  3. 契约：直做票。
  4. 变异抽查（`~/.cache/rdp-drill/m4-04-probe/mutation_probe.py` → `mutation_probe-c1-done.txt`）：11 处抓住 8 处；**漏网 3 处**："有警告也自动入库"（验收 3，阻塞）、"不比对视频分辨率"、"不比对格式版本"。
  5. 运行日志（两轮）：无旧项目路径、无安装和联网命令、无 /mnt 命令。
  6. 评审：后续作业在前驱终态的同一事务里提交（不漏不重）；改名入库复用 M2 的持久移动记录和回滚；血缘记录字段与 M3 商定一致。遗留：通用执行器认识了转换流水线的类型名（`_followups.py`），以后宜改成作业类型登记上的"完成后"回调。
  7. 违规试验：检查链未改，不做。
- 2026-11-08 修复轮 r1（单元 `rdp-m4-04-r1`）：补上面 3 个漏网变异的测试。
- 2026-11-08 10:3x **副本演练（验收 8，执行线）**：用探针副本里本票的代码，对第 03 张演练产出的真实产物（作业 6，dataset-35 一整天，5.64 GB）"检查并入库"：四层全部"通过"；默认名 `R1_lite_table_withdrawing_lerobot` 已被 dataset-29 占用，按规则用 `R1_lite_table_withdrawing_lerobot_6`；导航层副本只多出按任务入口和 `按格式/lerobot/3.0` 入口；产物从 `暂存/转换/6/out` 改名到测试根的 `转换/R1_lite_table_withdrawing_lerobot_6`；`来源.json` 血缘为 `转换/完整/worker`，输入 dataset-35 的数据块、工具指纹、配置全文都在；`data_origin` 沿用"真机采集"；没有 `collection` 键；详情接口上下游双向显示（M3 第 05 张投影）。两块数据盘写入扇区不变，`/mnt/datasets` 清单逐字节相同，worker 无 ERROR。证据 `../assets/05-drill-docs/`。
- **演练发现（阻塞，修复轮 r2）**：新数据集顶层 `robot_model`、`fps` 为空（第 5 项只填了 info.json 的 `robot_type` = `galaxea_r1lite`），按型号筛选找不到它、转换按钮也匹配不上型号。工单只写了沿用 `data_origin`，是执行线漏写；转换产物与输入是同一次采集，应沿用输入的 `robot_model`、`scene`、`tasks`，`fps` 取产物 info.json。
- 2026-11-08 10:39 r1 交回：三个用例补齐；执行线重跑变异脚本，原先漏网的 3 处都抓住（`mutation_probe-r1-done.txt`）。
- 2026-11-08 10:51 r2 交回：转换产物顶层沿用输入的 `robot_model`、`scene`、`tasks`，`fps` 取产物 info.json；`DatasetInformation` 加可选 `fps`（None 不写键，M1/M2/M3 现有调用方不变，事先批准的只增不改扩展）。复核：两个新变异（型号不沿用、fps 不写）都抓住（`mutation_probe-r2-done.txt`）；新建流程相关测试 236 passed。
- 2026-11-08 实现提交 `8d6a0c6`（钩子全量全绿 2851 / 412）。按负责人授权合并进 main：`d583214`，自动合并无冲突，生成的接口类型按合并结果重新生成；合并钩子全量全绿（2851 / 412）。工作目录和分支已删除（工作目录里那层 node_modules 子链接随之删除，共享依赖不受影响）。
