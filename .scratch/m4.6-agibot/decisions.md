# M4.6：AgiBot 原生数据转换接入（决定记录）

Status: 进行中（2026-11-15 开）

工单 `issues/01`–`06`：01 清单与登记扩展、02 事件进度与工具缓存目录（01、02 并行）；03 清洗预览、04 转换、05 前端（三张并行，依赖 01、02）；06 演练与文档（执行线）。

## 负责人原话

- 2026-11-12："nas已经挂载好了…能否先把这个工具放到工具库中？mcap2lerobot这个工具是放到了/mnt/datasets/工具/下的，这是统一管理工具的位置"；"旧副本我已经删除，可以开始平台登记了"。
- 2026-11-12 三项选择都按推荐：清洗预览做"体检 + 数值检查"；tar 任务"先只支持已解压的"；型号"填 AgiBot G1"。
- 2026-11-12："我觉得可以先把机器人的配置和关节映射文件做好，咱们一步一步来，就像mcap2lerobot中的toml文件一样"。
- 2026-11-15：核对映射后"按你说的做"（action 关节保持原样、阈值照 M4.5）；"没问题，可以使用多个gpt去做"。

## 工具的事实（2026-11-15，执行线写的工具，可以改，但改了要重新登记指纹）

- 目录 `/mnt/datasets/工具/agibot2lerobot`（系统盘），Python 包 `agibot2lerobot/`（16 个 .py），版本 0.2.0。
- 启动器 `bin/agibot2lerobot`（bash，480 字节，sha256 `638728b071c01a34137c50c414223bc3f78f3acf7d3bb9c3aea40725914fe1fb`）：用工具目录里的 `.venv/bin/python`（`--system-site-packages` 基于 conda 环境 lerobot 0.6.2，只多装 h5py），设 `PYTHONDONTWRITEBYTECODE=1`。
- 源码目录指纹（算法同 `envs/lerobot`，见第 2 条）：16 个文件，`dd098862c3b6d6a5d4b9c35245c97725dd0bf34fddf6f49eb3050af3ed8382f1`。
- 三个给平台的入口（全局参数 `--events /dev/stderr` 要写在子命令前）：
  - `preview -c <配置> --rules <规则> --index-cache <缓存目录> --result <结果文件> --task-dir <数据集根>/observations/<任务>`：只读，逐集体检 + 数值检查，结果 JSON 写到 `--result`（文件不能已存在）。
  - `check-episodes -c <配置> --index-cache <缓存目录> <episode 目录>...`：转换前快速核对，不读视频。
  - `convert-episodes -c <配置> -o <产物目录> --format v3.0 --index-cache <缓存目录> <episode 目录>...`：只转给定的集，任何一集不能转就整体失败；产物 episode 按 ID 升序；产物目录不能已存在，暂存放在产物目录的同级 `.agibot2lerobot_work/`，成功后删除。
- episode 目录形如 `<数据集根>/observations/<任务>/<episode>`，工具据此找 `task_info/`、`proprio_stats/`；本体感知没解压时按偏移直接读共用归档 `proprio_stats/*.tar`，索引缓存在 `--index-cache`（要可写；真实 44.8 GB 归档首次扫描约 3 分钟、索引 2.3 MB）。
- 事件：stderr 上每行一个 JSON（行首 `{"event"`）：`{"event":"progress","stage":"preview|probe|stage|data|videos","done":N,"total":M,"task_id":…}`、`{"event":"log","message":…}`、`{"event":"result","ok":bool,…}`；人读的日志行也在 stderr，混在一起。退出码 0 成功、1 失败、2 参数错误。
- 预览结果文件（`schema_version = 1`）：`tool_version`、`task_id`、`task_name`、`dataset_name`、`fps`、`robot_config{path,sha256}`、`feature_names{特征: [维度名]}`、`episodes[]`；每集：`episode_id`（字符串）、`observation_dir`、`observation_mtime_ns`（整数或 null）、`proprio{path,offset,size}` 或 null、`size_bytes`、`frames`、`problems`（字符串列表，非空表示不能转）、`issues[]`（`check` ∈ non_finite / joint_limit / action_jump / entire_static / long_static，`feature`、`count`、`first_time_s`、`ranges`（最多 10 个 `[起, 止]` 秒））、`task`。episodes 按 ID 数值升序。
- 不占 GPU（视频只换封装）；不联网；在 bwrap（`--ro-bind / /`、`--unshare-net`、伪终端 stderr）里实测能跑通（`~/.cache/agibot_check/t10`）。
- 产物能通过平台现有四层入库检查（结构、计数、视频、内容），实测通过。
- 产物/输入体积比实测约 1.15（深度图 TIFF 比原 PNG 大）。

## 决定

### 1. 报告结构复用：一集 = 一个"文件"，一段

- 清洗报告沿用 `CleaningReport`：AgiBot 的每一集是一个 `FileReport`（`file_index` 从 0 起按 episode ID 升序，`path` = 观测目录，`size_bytes` = 工具给的内容字节数，`mtime_ns` = 观测目录 mtime，`fatal_issues` = 体检问题，`reference_frames = kept_frames = frames`，其余计数 0，`topics = ()`），每个没有体检问题的集另有一个 `EpisodeReport`（`segment_index = 0`，`start_frame = 0`，`end_frame = frame_count = frames`，`duration_s = stamp_span_s = frames / fps`，`start_time_s = 0`）。
- 报告加 `source_format`（`"mcap"` 默认 / `"agibot_native"`）；AgiBot 报告的 `reference_topic`、`rules.sync` 和图像类规则字段为 null；`FileReport` 加 `episode_id`（MCAP 为 null）。
- 严重程度照 M4.5：`non_finite`、`entire_static` 严重（默认剔除），其余提示。
- AgiBot 的剔除只用 `excluded_files`：`excluded_episodes` 非空直接拒绝（一集一文件，剔除集就是剔除文件；这样不会走 LeRobot `delete_episodes` 重新编码）。

### 2. Python 工具的指纹：启动器 + 源码目录

- 清单 `[program]` 加可选的 `tree`（相对工具目录的源码目录）和 `tree_sha256`。算法与 `envs/lerobot` 的指纹相同：目录下递归的 `.py`（跳过 `__pycache__`），相对该目录的 POSIX 路径排序，依次把 `路径 + b"\0" + 文件 sha256 十六进制 + b"\n"` 送进 sha256。
- 有 `tree` 时两个指纹都要对上才"可用"；预览记录和转换回执里的工具指纹用 `tree_sha256`（没有 `tree` 的工具仍用程序 sha256）。
- `.venv`（h5py）和 conda 环境不进指纹：LeRobot 环境已有自己的登记（M4.5），h5py 只是读库。

### 3. 进度：解析 stderr 上的 JSON 事件行

- 新解析器名 `agibot2lerobot-events`，仍走伪终端那条通道（不改受管进程）；只取 `progress` 事件，其他行原样当文本。成败只看退出码和产物。

### 4. 清洗预览由工具在沙箱里跑

- 清单 `[command]` 加可选的 `preview` 模板；有它的工具，清洗预览作业改为在 bwrap 里运行工具（数据盘只读，唯一可写的是工具缓存目录），读结果文件生成报告。阈值文件仍在平台登记包的 `cleaning/` 里，经 `{rules}` 传给工具。
- 预览输入：恰好一个 `agibot_native` 数据块，路径是任务的观测目录。

### 5. 工具缓存目录

- `<state_dir>/tool-cache/<工具名>/`，平台建、只给该工具的沙箱可写；放共用归档索引和预览结果文件（读完即删）。模板占位符 `{cache}`、`{result}`。

### 6. 转换

- 仍从预览发起；`{inputs}` = 报告里未剔除集的观测目录，按 `file_index` 顺序。
- 预览后的输入核对：AgiBot 只比观测目录的 `mtime_ns`（目录的 `st_size` 没有意义）；工具转换时还会重新体检，转完平台照旧核对每集帧数。
- 不占 GPU（`needs_gpu = false`）；空间估算的默认百分比由清单给（AgiBot 130，MCAP 仍 25）。
- 沙箱里加 `HF_HUB_OFFLINE=1`、`PYTHONDONTWRITEBYTECODE=1`、`HF_HOME=<暂存>/hf-home`。

### 7. 型号

- 登记两个型号：`AgiBot G1` → 夹爪配置（35 个任务）、`AgiBot G1 灵巧手` → 灵巧手配置（任务 475）。dataset-31/30 的 `robot_model` 由负责人在页面上填"AgiBot G1"。用错配置时预览会把所有集标成维度不符。

### 8. 不在本里程碑做

- tar 观测任务的解压（负责人：先只支持已解压的）；图像类检查；真实数据上的转换演练（负责人后做，见 followups）。
