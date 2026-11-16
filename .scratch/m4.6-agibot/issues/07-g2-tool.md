# 新工具 agibot2lerobot-g2：AgiBot World 2026 的 LeRobot v2.1 归档 → 合并的 v3.0（不落中间产物）

Status: done（实现及验收完成；负责人已授权合并、升级、推送）

分级：直做（负责人 2026-11-15："同样挂载到工具库中"；按任务合并、保留官方附加信息都同意；"官方是转成了2.1，lerobot提供了2.1-3.0的脚本，可以把他们直接合并到一起吗？我不想要中间产物"）。与第 01–05 张并行：本票只在工具目录里写，不碰平台仓库。

## 数据事实（执行线 2026-11-15 只读核对）

- 数据集 `/mnt/dataset1/agibot_world_2026`（13.2 TB）：`<类别>/<场景>/task_<ID>/<起>_<止>.tar.gz`，一个任务 1–35 个归档，单个 3–36 GB。
- 每个 tar.gz 是一个完整的 LeRobot **v2.1** 小数据集，成员顺序（流式读取已确认）：`data/data/chunk-000/episode_NNNNNN.parquet`（全部）→ `data/meta/{episodes.jsonl,episodes_stats.jsonl,info.json,tasks.jsonl}` → `data/videos/chunk-000/<相机>/episode_NNNNNN.mp4`（按相机分组，组内按集）。
- 一个真实归档的 `meta/` 原样拷在 `tests/fixtures/meta_sample/`（13 集、30681 帧；`robot_type = g2a`、30 fps；7 路视频，含以视频存的 `observation.images.head_depth`；`observation.state` 169 维、`action` 40 维，`features.*.field_descriptions` 给出每段的 `indices`）。`info.json` 另有按集（键是 episode_index 字符串）的非标准字典：`instruction_segments`、`key_frame`、`take_over`、`h5_path`、`camera_parameters`，以及 `data_version`。
- **不要访问 /mnt/dataset1、/mnt/dataset2 或任何 /mnt 下的数据**；测试只用自己造的归档。执行线会在真实归档上验收。

## 要做的

工具目录 `/mnt/datasets/工具/agibot2lerobot-g2/`（你的工作目录）。结构、风格、CLI 形状参照姊妹工具 `/mnt/datasets/工具/agibot2lerobot/`（只读参考，不要改它）：`bin/agibot2lerobot-g2` 启动器（bash，设 `PYTHONDONTWRITEBYTECODE=1`，用 `/home/shawn/miniconda3/envs/lerobot/bin/python`（LeRobot 0.6.2，已有 pyarrow、av、numpy、datasets、pandas），不建 venv）、Python 包 `agibot2lerobot_g2/`、`configs/`、`tests/`、`README.md`（中文）。全局参数 `--events <文件|-|/dev/stderr>` 输出 JSON 事件行（`progress`/`log`/`result`，格式同姊妹工具），人读日志在 stderr；退出码 0/1/2。

### 1. 流式读取（核心约束：不落中间产物）

- 每个归档只顺序读一遍（`tarfile` 的 `r|gz` 流模式，打开文件用 `O_RDONLY | O_NOATIME`，失败退回普通只读），**不解压到盘上**。parquet、meta 读进内存；每个 mp4 成员读进内存（单个几 MB），用 PyAV 从内存打开并**重封装（不重新编码）**写进 v3.0 的视频分片。
- 唯一的磁盘写入是产物目录（及其同级的临时目录 `.<名>.partial`，成功后改名）。内存峰值与单集大小成正比，不随归档大小增长。
- 成员名不安全（绝对路径、`..`、链接、设备文件）→ 整体失败。

### 2. 子命令

- `preview -c <配置> --rules <规则> --result <结果文件> <归档>...`：同一任务的归档；每个归档完整流式扫一遍：读 meta 和全部 parquet，核对视频成员是否齐全（每集每路相机一个、大小 > 0，不解码），对每集做数值检查。结果 JSON 写到 `--result`（不能已存在）。
- `check-archives -c <配置> <归档>...`：快速核对（只读到 meta 为止）：归档能打开、是 v2.1、特征与多数一致。
- `convert-archives -c <配置> -o <产物目录> --format v3.0 [--exclude <JSON 文件>] <归档>...`：按给出的归档顺序、归档内按 episode_index 合并成一个 v3.0 数据集。`--exclude` 是 `[{"archive": 路径, "episode_index": n}, ...]`，被剔除的集在流式读取时跳过（数据、视频、统计都不写）。严格：任何一个未剔除的集不能转就整体失败、不留产物。产物目录不能已存在。

### 3. 预览结果文件（`schema_version = 1`）

`tool_version`、`fps`、`robot_type`、`config_sha256`、`feature_names{observation.state: [...], action: [...]}`（由 `field_descriptions` 展开，如 `state/joint/position[0]`）、`archives[]`：每个归档 `path`、`size_bytes`、`mtime_ns`、`problems`（归档级，非空表示整个归档不能转，例如打不开、不是 v2.1、特征与多数不一致、成员不安全）、`episodes[]`：每集 `episode_index`、`frames`、`task`、`problems`（集级，例如缺视频、parquet 帧数与 episodes.jsonl 不符、缺统计）、`issues[]`（同姊妹工具：`check` ∈ non_finite / joint_limit / action_jump / entire_static / long_static，`feature`、`count`、`first_time_s`、`ranges`（最多 10 段））。

### 4. 数值检查

口径与姊妹工具 `agibot2lerobot/checks.py` 完全相同（读它）。规则文件格式也相同，只是 `[[source]].field` 指 `field_descriptions` 里的段名（如 `state/joint/position`），列号取它的 `indices`。

### 5. 产物（LeRobot v3.0）

- 与 LeRobot 0.6.2 官方转换（`~/桌面/lerobot/src/lerobot/datasets/v30/convert_dataset_v21_to_v30.py`，只读参考）结果一致：`data/chunk-XXX/file-XXX.parquet`、`videos/<相机>/chunk-XXX/file-XXX.mp4`、`meta/episodes/…parquet`（含每集 `stats/*` 列，取自 `episodes_stats.jsonl`，不重新计算）、`meta/tasks.parquet`、`meta/stats.json`（用 LeRobot `aggregate_stats` 汇总）、`meta/info.json`（`codebase_version = v3.0`，特征沿用 v2.1 的定义含 `field_descriptions`）。多归档合并时 `episode_index`、`index`、`task_index` 重新编号（任务按文本去重）；`timestamp` 原样。分片大小照官方默认（数据 100 MB、视频 500 MB），参数可在配置里改。**注意官方 `convert_data` 的分片编号错位缺陷**（姊妹工具 README 的对照表里有说明）：写文件和写元数据要用同一份分组结果。
- 附加文件（LeRobot 会忽略）：`meta/agibot_episodes.jsonl`，每个新 episode 一行：`episode_index`、`source_archive`（文件名）、`source_episode_index`，以及该集在原 `info.json` 里的 `instruction_segments`、`key_frame`、`take_over`、`h5_path`、`camera_parameters`（原样）；`meta/agibot_conversion.json`：工具版本、配置全文与 sha256、输入归档（路径、大小、mtime）、剔除的集、原 `data_version`。
- 组装后自检（结构、每集帧数、视频分片帧数 = 各集之和），不通过不改名。

### 6. 配置 `configs/agibot_g2.toml`

`schema_version`、`robot_type = "g2a"`（与归档不符的归档判为不能转）、`fps = 30`、`[output]`（`data_file_size_in_mb`、`video_file_size_in_mb`、`chunks_size`）。另给 `configs/agibot_g2.cleaning.toml`：照姊妹工具的规则——`[static] feature = "observation.state"`、`long_static_s = 3.0`；`[jump] feature = "action"`；`state/joint/position` 静止阈值 0.001；`state/left_effector/position`、`state/right_effector/position` 静止阈值取一个合理值（先从 fixture 的统计看量纲，在 README 写明依据）；`action` 里与关节位置对应的段跳变阈值 0.5（看 `field_descriptions` 选对段名）。

## 测试（只做关键测试）

测试里自己造 v2.1 归档：用 PyAV 编小视频（如 8×8、几帧）、pyarrow 写 parquet、写 meta，打成 tar.gz，成员顺序同真实归档。

1. **与官方对照**：同一份 v2.1 数据（≥ 2 集），本工具产物 vs 官方 `convert_dataset_v21_to_v30` 产物：`info.json` 特征一致、data 表逐值一致、`meta/episodes` 的索引列和 stats 一致、每路视频解码后逐帧一致。（官方脚本若要联网或依赖 hub，就在测试里调用它的内部函数或做最小替身，写明做法。）
2. 两个归档合并：编号连续、任务去重、`agibot_episodes.jsonl` 对应关系正确；LeRobot 0.6.2 `LeRobotDataset(repo_id, root=产物)` 能加载并取到首尾帧。
3. `--exclude` 剔除一集：产物里没有它的数据、视频时长和统计。
4. 不落中间产物：转换期间监视产物目录以外没有新文件（如用临时 HOME/TMPDIR 检查）；内存不随归档大小增长（可用两份大小相差很大的归档粗测）。
5. 预览：缺一路视频的集 → 集级 problem；特征与多数不同的归档 → 归档级 problem；NaN → non_finite。
6. 不安全成员 → 整体失败。

## 验收

1. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/shawn/miniconda3/envs/lerobot/bin/python -m pytest tests` 全过（lerobot 环境里没有 pytest 时，用 `PYTHONPATH=$HOME/.cache/agibot_check/env/pt`，那里有一份 pytest）。
2. 执行线用一个真实的 5 GB 归档（task_3405）跑 preview 和 convert-archives，与官方转换对照、LeRobot 能加载、两块数据盘写入扇区不变。

## Comments

- 执行线收尾：最终后端3120、前端441全绿；Alpha真实本地样本全链路3 passed、G2合成归档真实bwrap全链路1 passed、G2真实task_3405归档13集30681帧四层检查通过。详见 `../assets/verification-results.md`。没有生产部署或推送。
