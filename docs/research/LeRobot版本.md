# LeRobot 版本：数据集格式 v2.1 vs v3.0，配套 lerobot 库版本

- 对应决策票：`.scratch/platform-v1/issues/07-lerobot-version.md`
- 调研日期：2026-10-21
- 一手来源：huggingface/lerobot 官方仓库（源码、文档、发布说明）、PyPI，以及各训练框架的官方仓库。lerobot 源码引用固定在 tag `v0.6.1`，第三方仓库固定在调研当天的 commit。
- 本机核对：只读查看 `/mnt` 下 4 个样本的 `meta/`；查询 conda `lerobot` 环境；在 scratchpad 里对**拷贝出来的**小样本做了转换实验（见附录 A）。全程没有写 `/mnt`，没有安装或升级任何包。

## 结论速览

1. **v3.0 不是 v2.1 的增量，而是存储模型换了**。v2.1 是"一个 episode 一个文件"；v3.0 是"多个 episode 拼进一个分片文件，再用 `meta/episodes/*.parquet` 里的偏移量定位"。`meta/` 从 JSONL 换成了 Parquet（详见 §1）。
2. **lerobot ≥ 0.4.0 只读写 v3.0**。v2.1 数据在加载元数据时直接抛 `BackwardCompatibilityError`，本机 0.6.2 已实测。官方只提供单向的 v2.1 → v3.0 转换脚本，lerobot 里没有反向工具（详见 §2）。
3. **最新稳定版是 lerobot 0.6.1**（2026-08-03）。`main` 上的 0.6.2 还没发布。本机 `lerobot` 环境装的是 `main` 的开发快照（0.6.2，editable 安装，另有 3 个本地改动文件），不是发布版（详见 §3）。
4. **训练侧分成两派**。lerobot 自带的训练（ACT、Diffusion、pi0/pi0.5、SmolVLA、GR00T N1.7、X-VLA 等）只吃 v3.0。openpi、Isaac-GR00T 官方仓库、Galaxea 的 G0.5（GalaxeaVLA）、AgiBot-World GO-1 仍然只吃 v2.1（详见 §4）。
5. **推荐组合**：平台以 **v3.0** 为唯一规范格式，配套 **lerobot 0.6.1**（`lerobot[dataset]`，Python 3.12）。需要给只认 v2.1 的训练框架用时，导出一份 v2.1 派生副本（详见 §5）。

---

## 1. v2.1 和 v3.0 在目录结构、`meta/` 文件、视频与分块上的差别

### 1.1 目录结构

```
v2.1（一个 episode 一个文件）                    v3.0（多个 episode 一个文件）
dataset/                                         dataset/
├── data/chunk-000/episode_000000.parquet        ├── data/chunk-000/file-000.parquet
├── videos/chunk-000/<video_key>/episode_000000.mp4  ├── videos/<video_key>/chunk-000/file-000.mp4
└── meta/                                        └── meta/
    ├── info.json                                    ├── info.json
    ├── episodes.jsonl                               ├── episodes/chunk-000/file-000.parquet
    ├── episodes_stats.jsonl                         ├── stats.json
    └── tasks.jsonl                                  └── tasks.parquet
```

出处：官方 porting 文档里的 v2.1/v3.0 对比 [S2]，转换脚本头部的 OLD/NEW 对照 [S6 L104 起]，路径常量 `DEFAULT_DATA_PATH` / `DEFAULT_VIDEO_PATH` / `DEFAULT_TASKS_PATH` / `LEGACY_*_PATH` [S4 L90–L111]。本机的 4 个样本与此完全一致（附录 B）。

注意视频路径里 **`chunk` 和 `video_key` 的顺序反过来了**：v2.1 是 `videos/chunk-*/<key>/…`，v3.0 是 `videos/<key>/chunk-*/…`。

### 1.2 `meta/` 文件

| 内容 | v2.1 | v3.0 |
|---|---|---|
| 模式与路径模板 | `info.json` | `info.json`（字段有变化，见 1.3） |
| 每个 episode 的长度、任务 | `episodes.jsonl`：`{episode_index, tasks, length}` | `episodes/chunk-*/file-*.parquet`，一行一个 episode，列见下 |
| 每个 episode 的统计量 | `episodes_stats.jsonl` | 并进上面的 episodes parquet，列名形如 `stats/<feature>/<min\|max\|mean\|std\|count>` |
| 全局统计量 | 没有文件，加载时由 `episodes_stats` 聚合（v2.1 起 `stats.json` 被移除 [S9-711]） | `stats.json`（重新出现） |
| 任务表 | `tasks.jsonl`：`{task_index, task}` | `tasks.parquet`：以 `task` 字符串为索引，列 `task_index` |

v3.0 episodes parquet 的定位列（以本机 libero_10 为例，用 lerobot 0.6.2 读出）：
`episode_index, tasks, length, data/chunk_index, data/file_index, dataset_from_index, dataset_to_index, videos/<key>/chunk_index, videos/<key>/file_index, videos/<key>/from_timestamp, videos/<key>/to_timestamp, …, meta/episodes/chunk_index, meta/episodes/file_index`。
出处：转换脚本生成这些列的代码 [S6 `convert_data` / `convert_videos_of_camera` / `generate_episode_metadata_dict`]；本机实测（附录 A）。

**官方文档有一处与代码不符**：`lerobot-dataset-v3` 文档 [S1 L82] 和 v3 博客 [S3] 把 v3.0 的任务表写成 `meta/tasks.jsonl`。但代码常量是 `DEFAULT_TASKS_PATH = "meta/tasks.parquet"` [S4 L102]，本机 3 个 v3.0 样本也都是 `tasks.parquet`。**以代码为准**。

### 1.3 `info.json` 字段变化

| 字段 | v2.1 | v3.0 |
|---|---|---|
| `codebase_version` | `"v2.1"` | `"v3.0"` |
| `total_chunks`、`total_videos` | 有 | **删除** |
| `data_files_size_in_mb`、`video_files_size_in_mb` | 无 | **新增**：单个分片的大小上限 |
| `chunks_size` | 每个 chunk 目录放多少个 **episode** | 每个 chunk 目录放多少个 **文件**（默认 1000） |
| `data_path` | `data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet` | `data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet` |
| `video_path` | `videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4` | `videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4` |
| 非视频 feature | — | 转换时补上 `fps` |
| `fps` | 可能是 float | 转换时强制转成 int |

出处：转换脚本的 `convert_info` [S6 L442]，`DatasetInfo` 的字段定义 [S4 L115 起]。

`DatasetInfo.from_dict` **会静默丢弃未知的顶层字段**，只打一条 warning [S4 L181]。这对 §2.3 的转换有直接影响。

### 1.4 视频与分块方式

- **v2.1**：每个 (episode, camera) 对应一个 MP4，按 episode 编号分进 `chunk-XXX` 目录。
- **v3.0**：每个 camera 单独成一串 MP4 分片，多个 episode 首尾相接拼在同一个文件里。分片大到 `video_files_size_in_mb` 时，再开下一个 `file-XXX`。parquet 分片同理，上限是 `data_files_size_in_mb`（默认 100）。同一个 episode 在 data 分片和各个 camera 视频分片里的 `file_index` **可以各不相同**，必须查 episodes 元数据才能定位。
- **时间语义**：parquet 里的 `timestamp` 是 episode 内的相对时间。解码视频时，要加上该 episode 在分片里的起点 `videos/<key>/from_timestamp`：`shifted_query_ts = from_timestamp + ts` [S8 L279]。平台的数据浏览器（票 16）如果自己解码视频，必须遵守这条规则。
- **拼接不重编码**：转换和聚合时用 ffmpeg concat demuxer 做 stream copy。要求所有输入的分辨率、fps、codec、pix_fmt 一致，否则报错 [S7 L648]。
- **视频分片默认上限变过**：0.4.0–0.4.1 是 500 MB，从 0.4.2 起是 200 MB（PR #2514）[S9-2514]。本机 `aloha_mobile_cabinet` 的值是 500，libero_10 和 R1_lite 是 200，与生成时的库版本吻合。这个值是数据集自带的参数，读取时以 `info.json` 为准，不影响兼容性。
- **v3.0 也允许一个 episode 一个文件**：CB_Autolife 的"事务模式"每条 episode 都写新文件，README 明说 `VIDEO_FILES_SIZE_IN_MB` "不能用它合并 episode" [S16-README]。这仍然是合法的 v3.0，平台不能假设一个分片里一定有多个 episode。

### 1.5 对平台的直接影响

- v3.0 里 **episode 不再对应文件**。删除或挑出某条 episode 要重写分片，不能删文件了事。官方为此提供 `lerobot-edit-dataset`，支持 `delete_episodes / split / merge / remove_feature / modify_tasks / recompute_stats / reencode_videos / info` 等操作 [S10-edit L280 起]。
- 统计"有多少 episode、每条多长"只需要读 `meta/episodes/*.parquet`，不用扫 `data/`。

---

## 2. 官方工具对两个版本的读写支持；v2.1 → v3.0 转换

### 2.1 新库（≥ 0.4.0）读写

- **写**：`LeRobotDataset.create` 固定写入 `CODEBASE_VERSION = "v3.0"`，没有写 v2.1 的选项 [S5 L60, L840]。
- **读**：`LeRobotDatasetMetadata._load_metadata` 先执行 `check_version_compatibility`。数据集的主版本号小于库的主版本号时，抛 `BackwardCompatibilityError`，提示运行转换脚本 [S5 L214, S4 L32/L68/L304]。即使指定了本地 `root` 也一样。
- **本机实测**：用 lerobot 0.6.2 加载智元 v2.1 样本（拷贝）→ `BackwardCompatibilityError`；加载 libero_10 v3.0 的 `meta/`（拷贝）→ 正常，379 个 episode、101469 帧（附录 A）。

### 2.2 旧库（v2.1 时代）读 v3.0

- v2.1 时代的代码写死读 `meta/tasks.jsonl`、`meta/episodes.jsonl`。读 v3.0 时会 `FileNotFoundError`，然后转去 Hub 查询版本、在 `root/meta` 下建目录并下载 `meta/`（读 openpi 锁定的 commit `0cf86487` 的源码得出 [S12-pin]）。**结论：读不了**。本地数据会在 Hub 查询或建目录这一步失败，不会给出"格式不支持"的提示。
- openpi 的社区 PR #972（未合并）就是为了把这种情况报成清晰的错误："datasets produced by recent lerobot releases cannot be read by the pinned lerobot at all" [S12-972]。

### 2.3 v2.1 → v3.0 转换脚本

- **位置变过**：0.4.0–0.5.0 在 `lerobot/datasets/v30/convert_dataset_v21_to_v30.py`，0.5.1 起移到 `lerobot/scripts/convert_dataset_v21_to_v30.py`（本地 git 各 tag 的文件树核对）。v3 博客 [S3] 里的命令还是旧路径；0.6.x 的错误提示用新路径 `python -m lerobot.scripts.convert_dataset_v21_to_v30` [S4 L32]。
- **用法**：`--repo-id=<任意名> --root=<本地数据集目录> --push-to-hub=false` 转换本地数据 [S6 头部 docstring]。
- **行为与代价**（源码 [S6 L464 起] + 本机实验，附录 A）：
  1. **原地替换**：先写到 `<root>_v30`，再把原目录改名为 `<root>_old`，新目录改名为 `<root>` [S6 L495 起]。所以 **`root` 的父目录必须可写**。`/mnt` 上的数据不能直接转，要先拷到可写位置，或者把输出放到别处。实验里确实生成了 `agibot_sub_old/`。
  2. **丢弃非标准元数据**：智元 `info.json` 的 10 个自定义顶层字段（`aid_info, camera_parameters, data_version, episode_ids, h5_path, high_level_instruction, instruction_segments, intervention_info, key_frame, take_over`）转换后**全部消失**，只有 warning。原因是 `DatasetInfo.from_dict` 丢弃未知字段 [S4 L181]。`meta/` 下的非标准文件（例如智元的 `annotations.json`）不会被拷到新目录，只会留在 `<root>_old` 里（新目录只由 `convert_info/tasks/data/videos/episodes_metadata` 写入 [S6]）。
  3. **视频不重编码**：智元的 HEVC 视频直接 stream copy 拼接成功，转换后用 lerobot 0.6.2 能正常解码首帧和末帧。`video_info`（v2.0 遗留的键名）原样保留，新代码能识别。
  4. **统计量照搬**：全局 `stats.json` 由原有的 `episodes_stats` 聚合而来，不会重算。智元样本里图像的 `episodes_stats` 是占位值（`count: [0]`，全 0），转换后这 3 路图像在 `stats.json` 里是 **NaN**。这是样本本身的问题，不是脚本的 bug；需要时可以用 `lerobot-edit-dataset` 的 `recompute_stats` 处理。
  5. 脚本的 docstring 已经过时：仍写着生成 `episodes_stats.jsonl`、删除 `stats.json` 等，那是 v2.0 → v2.1 时代的说明。以代码为准。

### 2.4 反向（v3.0 → v2.1）

- **lerobot 本身没有**（v0.6.1 的文件树里没有 v30→v21 或 downgrade 之类的脚本）。
- **NVIDIA Isaac-GR00T 官方仓库提供** `scripts/lerobot_conversion/convert_v3_to_v2.py` [S13-conv]。它写出 `codebase_version = "v2.1"`（L158），用 `ffmpeg -ss … -t … -c copy` 按 episode 切视频（L336 起），并重建 `episodes.jsonl` 和 `episodes_stats.jsonl`。该脚本自带独立环境（Python < 3.12，锁定 lerobot commit `c75455a6`）。
- 另一条路：直接用 mcap2lerobot 的 `--format v2.1` 从原始 MCAP 重新导出（F8）。

---

## 3. lerobot 库版本与数据集格式版本的对应；最新稳定版

### 3.1 对应表

| lerobot 版本 | 发布日期 | `CODEBASE_VERSION` | 转换脚本 |
|---|---|---|---|
| （格式 v2.0 引入，PR #461） | 2024-11-29 合入 | v2.0 | v1→v2 |
| （格式 v2.1 引入，PR #711） | 2025-02-25 合入 | v2.1 | v2.0→v2.1 |
| 0.3.2 / 0.3.3 | 2025-08-01 / 08-06 | **v2.1** | `datasets/v2/…`、`datasets/v21/…` |
| （格式 v3.0 引入，PR #1412） | 2025-09-15 合入 | v3.0 | — |
| 0.4.0 | 2025-10-23 | **v3.0** | `datasets/v30/convert_dataset_v21_to_v30.py` |
| 0.4.1 – 0.5.0 | 2025-11-10 – 2026-03-09 | v3.0 | 同上 |
| 0.5.1 | 2026-04-07 | v3.0 | 移到 `scripts/convert_dataset_v21_to_v30.py` |
| 0.6.0 | 2026-07-06 | v3.0 | 同上 |
| **0.6.1（最新稳定版）** | **2026-08-03** | v3.0 | 同上 |
| 0.6.2（`main`，未发布） | — | v3.0 | 同上 |

出处：各 tag 的 `CODEBASE_VERSION` 和文件树，用本机 lerobot 克隆的 git 历史逐个核对（`git grep` / `git ls-tree`，命令见附录 C）；发布日期取自 PyPI JSON [S11-pypi] 和 GitHub Releases [S11-gh]，两者一致；格式引入的 PR 见 [S9]。v0.4.0 的发布说明列出了 "Dataset v3 (#1412)" [S11-040]；v3 博客写明 "`LeRobotDataset:v3.0` will be released with `lerobot-v0.4.0`" [S3]。

**最新稳定版**：PyPI 上 `lerobot` 的最新版是 **0.6.1**（2026-08-03 上传）。GitHub Releases 的最新一条也是 v0.6.1。`main` 的 `pyproject.toml` 是 `0.6.2`，`CODEBASE_VERSION` 仍是 `v3.0`（2026-10-21 查询）[S11]。

### 3.2 "v3.0" 不是冻结的规格：读端版本不能低于写端

`codebase_version` 从 0.4.0 起一直是 v3.0，但这期间不断加入**可选**的新内容：

| 新增内容 | 首次进入的版本 | 出处 |
|---|---|---|
| 深度视频（`DepthEncoderConfig` / `RGBEncoderConfig`，`--dataset.vcodec` 改名为 `--dataset.rgb_encoder.vcodec`） | 0.6.0 | PR #3644 [S9-3644]，0.6.0 breaking changes [S11-060] |
| 语言列 `language_persistent` / `language_events`（feature dtype 为 `"language"`） | 0.6.0 | PR #3467 [S9-3467]，`language.py` [S10-lang] |
| `info.json` 的 `tools` 字段 | 0.6.0 | `DatasetInfo.tools` [S4 L147] |

0.4.x 的 `get_hf_features_from_features` 会把未知的 dtype 直接交给 `datasets.Value(dtype=…)`，而 `datasets.Value("language")` 会抛 `ValueError`（本机实测）。所以 **0.6 写出的、带语言列的 v3.0 数据，0.4.x 读不了**。这是读源码得出的推论，没有用 0.4.x 实际跑过。不带这些可选内容的 v3.0 数据，跨 0.4–0.6 理论上可以互读。

**结论：平台不能只锁定"格式 v3.0"，还要锁定库版本，并校验 feature 的 dtype 集合。**

CB_Autolife 用到了 `RGBEncoderConfig` / `DepthEncoderConfig` [S16-rec]，这两个类是 0.6.0 才有的。这和 F8 里"依赖 lerobot ≥ 0.6"的说法吻合。

### 3.3 0.6.x 的安装注意事项

- 从 0.6.0 起，`pip install lerobot` **不再带**数据集依赖，需要 `lerobot[dataset]`。这个 extra 包含 `datasets>=4.8,<5`、`pandas`、`pyarrow>=21,<30`、`av`，以及按平台选择的 `torchcodec` [S11-060, S10-pyproject L97]。
- `requires-python >= 3.12`（0.5.0 起，PR #3023）；最低 PyTorch 2.7（0.6.0）[S11-060]。

### 3.4 本机 `lerobot` 环境的实际情况

- `pip show lerobot` 报 `0.6.2`，是 **editable 安装**，源码在 `/home/shawn/桌面/lerobot`。
- 这个克隆来自 `gitee.com/mirrors/lerobot`，HEAD 是 `6adf5151`（2026-08-13），即 `v0.6.1-24-g6adf5151`，**不是发布版**。工作区另有 3 个本地改动：`motors/feetech/feetech.py`、`scripts/lerobot_record.py`、`utils/keyboard_input.py`，都和数据集代码无关。
- 和 v0.6.1 相比，`datasets/` 下有 7 个提交（语言 recipe、分位数统计聚合的修复、视频时间戳容差 `<` 改为 `<=`、深度标记统一等），没有改格式版本。
- 配套依赖：Python 3.12.13、torch 2.10.0+cu126、datasets 4.8.5、pyarrow 25.0.1、av 15.1.0、torchcodec 0.10.0、pandas 2.3.3。

---

## 4. 训练侧主流 policy 代码读哪个版本

| 训练代码 | 读取的格式 | 证据 |
|---|---|---|
| **lerobot 自带训练**（`lerobot-train`，≥ 0.4.0）：ACT、Diffusion、pi0、pi0.5、pi0-FAST、SmolVLA、GR00T N1.7、X-VLA、VQ-BeT、TDMPC 等 | **只读 v3.0** | 同一套 `LeRobotDataset`（§2.1）；v0.6.1 的 `policies/` 目录 [S10-pol]；pi0/pi0.5 在 0.4.0 加入 [S11-040] |
| **openpi**（Physical Intelligence 官方，pi0/pi0.5 原版） | **只读 v2.1** | `pyproject.toml` 把 lerobot 锁在 commit `0cf86487`（2025-05-28，`CODEBASE_VERSION = "v2.1"`）[S12-pin]；升级到 v3.0 的诉求 #756、#818 至今 open，相关 PR #972 也未合并 [S12] |
| **Isaac-GR00T**（NVIDIA 官方仓库） | **只读 "GR00T LeRobot" = v2（v2.1）+ `meta/modality.json`** | 官方文档："GR00T currently uses the LeRobot v2 data format … We plan to support both v2 and v3 formats natively in a future release. For now, please convert v3 datasets to v2" [S13-doc L5–L15]；提供 `convert_v3_to_v2.py` [S13-conv] |
| **GalaxeaVLA / G0.5**（Galaxea 官方 VLA，R1 Lite 的厂商） | **只读 v2.1** | 仓库内嵌的 lerobot 是 `CODEBASE_VERSION = "v2.1"`，路径常量是 `episodes.jsonl` / `tasks.jsonl` [S14-vla]；配套的 GalaxeaDP、GalaxeaLeRobotToolkit 依赖的 GalaxeaLeRobot fork 基于 commit `a5e0aae`（2025-07-08，v2.1）[S14-fork]。Galaxea 另有一个 GalaxeaLerobot3.0 fork，但没有查到哪个训练仓库依赖它 |
| **AgiBot-World GO-1**（智元） | **只读 v2.1** | README："built on LeRobot (dataset `v2.1`, commit `2b71789`)" [S15] |

**小结**：截至 2026-10，HF 官方栈已经全面转到 v3.0；但几个重要的第三方 VLA 训练仓库（openpi、GR00T 官方、Galaxea G0.5、智元 GO-1）都还停在 v2.1，而且都没有给出切换日期。和本平台直接相关的两家机器人厂商（Galaxea、智元），自家训练代码也都读 v2.1。

---

## 5. 推荐的版本组合

### 推荐

> **规范格式：LeRobot v3.0。配套库：lerobot 0.6.1（PyPI 发布版，安装 `lerobot[dataset]`，Python 3.12）。**
> v2.1 只作为**派生的导出格式**，按需生成给只认 v2.1 的训练框架用，不作为平台的存储与校验基准。

### 依据

1. **现有数据和产线已经是 v3.0**：4 个样本里 3 个是 v3.0（附录 B）；mcap2lerobot 的 `--format` 默认就是 `v3.0`（`/mnt/datasets/工具/mcap2lerobot/src/convert.rs:59`）；CB_Autolife 的录制器写的是 "official LeRobotDataset v3"，它自带的 `convert_dataset.py` 遇到非 v3.0 直接报错 "Only LeRobot v3.0 datasets are supported" [S16]。
2. **上游只维护 v3.0**：lerobot 从 0.4.0 起读写都只支持 v3.0，v2.1 被硬拒（§2.1）；格式转换只有单向工具（§2.3）。以 v2.1 为基准，等于锁死在 2025-08 的 0.3.x，并且和 CB_Autolife（要求 ≥ 0.6）冲突。
3. **选 0.6.1 而不是 0.4.x / 0.5.x**：CB_Autolife 用到了 0.6.0 才有的深度编码配置（§3.2），读端版本不能低于写端；0.6.1 是最新的稳定发布。
4. **选 0.6.1 而不是本机的 0.6.2 开发快照**：发布版可复现、可锁定；本机克隆来自镜像，而且带本地改动（§3.4）。两者在数据集格式上没有差别，所以本机现有环境可以继续用来做核对，但平台的依赖声明应写 `lerobot[dataset]==0.6.1`。

### 代价与缓解

| 代价 | 缓解 |
|---|---|
| openpi、GR00T 官方、Galaxea G0.5、智元 GO-1 只读 v2.1（§4） | 平台提供"导出 v2.1"作为派生产物：可以用 Isaac-GR00T 的 `convert_v3_to_v2.py`（NVIDIA 官方仓库，依赖独立环境），或者用 mcap2lerobot `--format v2.1` 从原始 MCAP 重新导出。导出副本标为派生物，不进入规范存储 |
| 智元等 v2.1 存量数据要转换；官方转换脚本是原地转换、丢弃非标准元数据、照搬统计量（§2.3） | 先拷到可写位置再转，输出到新目录；转换前把 `info.json` 的非标准字段和 `meta/` 下的非标准文件另存为旁注（sidecar）；转换后校验 `stats.json` 里有没有 NaN，必要时 `recompute_stats`。具体规则留给数据契约票（11） |
| "v3.0" 在 0.4 → 0.6 之间不断加入可选内容（深度视频、语言列、`tools`），旧读端会失败（§3.2） | 平台锁定 lerobot 版本；校验时检查 feature dtype 是否在允许集合内；升级 lerobot 要当作一次显式决策 |
| v3.0 里 episode 不对应文件，删除或挑选 episode 要重写分片（§1.5） | 用 `lerobot-edit-dataset`（`delete_episodes` / `split` / `merge`），或者用平台自己的等价实现；"删掉坏 episode"这个功能的语义要在数据集板块里说清楚 |
| 0.6.x 要求 Python ≥ 3.12、torch ≥ 2.7，基础安装不带数据集依赖（§3.3） | 依赖声明写 `lerobot[dataset]==0.6.1`；按 AGENTS.md 硬性规则 5，引入这个依赖要先经负责人批准 |
| 官方文档有错（v3.0 写成 `tasks.jsonl`）（§1.2） | 平台的格式契约以 v0.6.1 源码常量和真实样本为准，不以文档为准 |

### 留给负责人拍板的点

- 平台运行时是直接依赖 lerobot 库，还是只把它当作测试里的"判定基准"（v3.0 的 `meta/` 是普通的 JSON/Parquet，用 pyarrow 就能读）？这属于技术栈票（03）的范围，本票不定。
- 要不要把"导出 v2.1"做成平台功能；如果要，用 GR00T 的脚本还是 mcap2lerobot。

---

## 6. 没能查实 / 需要后续核对的点

1. **CB_Autolife 的实际产出**：只核对了源码（`LeRobotDataset.create` 和 v3.0 校验），还没有拿到它的样本输出；机器人上实际装的 lerobot 版本（`LEROBOT_PY` 指向 `/home/ubuntu/miniconda3/envs/lerobot/bin/python`）也不知道。按代码推断，它必然产出 v3.0，可能带深度视频。
2. **0.4.x 读 0.6 写的 v3.0**："带语言列会失败"是读源码加 `datasets.Value("language")` 报错推出来的，没有安装 0.4.x 实际跑过（约束是不安装包）。深度视频在 0.4.x 下的表现也没有验证。
3. **GR00T `convert_v3_to_v2.py` 的帧边界精度**：它用 `-ss` 加 `-c copy` 切分，只能切在关键帧上。lerobot 写 v3.0 时每个 episode 是单独编码后再拼接的，所以 episode 起点应该就是关键帧，切分应该准确。但这一点没有实测。
4. **openpi / GR00T 官方什么时候支持 v3.0**：只有 open issue 和"future release"的表态，没有时间表。
5. **其他训练框架**（RDT、starVLA、Dexbotic、X-VLA 官方仓库等）没有逐个核对，只覆盖了上面 5 家。
6. 智元样本里 `annotations.json` 这类非标准 `meta/` 文件在转换后的处理，是按源码推断的；实验时的拷贝没有包含这个文件。

---

## 附录 A：本机实验（只在 scratchpad 的拷贝上进行）

- 环境：conda `lerobot`，lerobot 0.6.2（editable，main@6adf5151），`HF_HUB_OFFLINE=1`，`HF_HOME` 指向 scratchpad。
- 智元 v2.1 子集：从 `/mnt/datasets/解压样本/agibot_world_2026_simulation_scoop_popcorn_lite` 拷出前 3 个 episode，只保留 3 路 RGB 相机（`top_head`、`hand_left`、`hand_right`），去掉深度相机以控制体积（约 86 MB）。相应修改了拷贝里 `info.json` 的 `total_*` 和 `features`。
- 结果：
  - `LeRobotDatasetMetadata(root=<v2.1 拷贝>)` → `BackwardCompatibilityError`，提示运行 `python -m lerobot.scripts.convert_dataset_v21_to_v30 --repo-id=…`。
  - `LeRobotDatasetMetadata(root=<libero_10 meta 拷贝>)` → 正常，v3.0，379 个 episode，101469 帧，列名见 §1.2。
  - `convert_dataset(root=<v2.1 拷贝>, push_to_hub=False)` → 生成 `data/chunk-000/file-000.parquet`、`meta/{info.json,stats.json,tasks.parquet,episodes/chunk-000/file-000.parquet}`，以及每路相机一个 `videos/<key>/chunk-000/file-000.mp4`；原目录被改名为 `agibot_sub_old`。`info.json` 只剩 13 个标准字段，10 个智元自定义字段被丢弃（有 warning）。
  - `LeRobotDataset(root=<转换后>)` → 1883 帧、3 个 episode、fps 30。第 0 帧和第 1882 帧的 3 路 HEVC 图像都解码正常；ffprobe 显示 `top_head` 分片为 `hevc, 30/1, 1883 帧`。
  - 转换后的 `stats.json` 里，3 路图像的统计量是 NaN，原因是源数据的图像 `episodes_stats` 为占位值 `count: [0]`。

## 附录 B：本机样本核对（只读）

| 样本 | `codebase_version` | `meta/` 文件 | `video_files_size_in_mb` | 视频路径模板 |
|---|---|---|---|---|
| `/mnt/dataset1/libero_v3/libero_10` | v3.0 | `info.json, stats.json, tasks.parquet, episodes/` | 200 | `videos/{video_key}/chunk-…/file-….mp4` |
| `/mnt/dataset2/R1_lite_table_withdrawing_lerobot` | v3.0 | 同上 | 200 | 同上 |
| `/mnt/dataset1/aloha/aloha_mobile_cabinet` | v3.0 | 同上 | 500 | 同上 |
| `/mnt/datasets/解压样本/agibot_world_2026_simulation_scoop_popcorn_lite` | v2.1 | `info.json, episodes.jsonl, episodes_stats.jsonl, tasks.jsonl, annotations.json`（没有 `stats.json`） | — | `videos/chunk-{episode_chunk}/{video_key}/episode_….mp4` |

智元样本的额外特征：视频 feature 用的是 `video_info` 键（不是 `info`），codec 为 `hevc`；有 6 路相机（含 3 路深度）；`info.json` 有约 0.96 MB，主要是自定义字段。

## 附录 C：复现命令

```bash
# 本机样本（只读）
python3 -I -c "import json;d=json.load(open('/mnt/dataset1/libero_v3/libero_10/meta/info.json'));print({k:v for k,v in d.items() if k!='features'})"
# 本机 lerobot 版本
conda run -n lerobot pip show lerobot
git -C /home/shawn/桌面/lerobot describe --tags --always
# 各 tag 的格式版本
cd /home/shawn/桌面/lerobot && for t in $(git tag --sort=creatordate); do echo "$t $(git grep -h '^CODEBASE_VERSION = ' $t -- src/lerobot lerobot | head -1)"; done
# 最新发布
curl -s https://pypi.org/pypi/lerobot/json | python3 -c "import json,sys;print(json.load(sys.stdin)['info']['version'])"
```

---

## 出处

lerobot 源码均固定在 tag `v0.6.1`：`https://github.com/huggingface/lerobot/blob/v0.6.1/<path>`。

- [S1] LeRobotDataset v3.0 文档：https://huggingface.co/docs/lerobot/lerobot-dataset-v3 ；源文件 https://github.com/huggingface/lerobot/blob/v0.6.1/docs/source/lerobot-dataset-v3.mdx#L82 （v3 目录说明，`tasks.jsonl` 的错误在此），#L285（迁移一节）
- [S2] Porting Large Datasets to v3.0：https://huggingface.co/docs/lerobot/porting_datasets_v3 ；https://github.com/huggingface/lerobot/blob/v0.6.1/docs/source/porting_datasets_v3.mdx#L5
- [S3] HF 博客《LeRobotDataset:v3.0》（2025-09-16）：https://huggingface.co/blog/lerobot-datasets-v3
- [S4] `src/lerobot/datasets/utils.py`：https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/utils.py — `V30_MESSAGE` #L32、`BackwardCompatibilityError` #L68、路径与大小常量 #L88-L111、`DatasetInfo` #L115、`tools` #L147、`from_dict` #L181、`check_version_compatibility` #L304
- [S5] `src/lerobot/datasets/dataset_metadata.py`：https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/dataset_metadata.py — `CODEBASE_VERSION` #L60、`_load_metadata` #L214、`create` 写入 v3.0 #L840
- [S6] `src/lerobot/scripts/convert_dataset_v21_to_v30.py`：https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/convert_dataset_v21_to_v30.py — OLD/NEW 对照 #L104、`convert_info` #L442、`convert_dataset` #L464、原地替换 #L495
- [S7] `src/lerobot/datasets/video_utils.py` `concatenate_video_files`：https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/video_utils.py#L648
- [S8] `src/lerobot/datasets/dataset_reader.py`：https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/dataset_reader.py#L279
- [S9] 格式相关 PR：v2.0 https://github.com/huggingface/lerobot/pull/461 ；v2.1 https://github.com/huggingface/lerobot/pull/711 ；v3.0 https://github.com/huggingface/lerobot/pull/1412 ；视频分片默认值改为 200 MB https://github.com/huggingface/lerobot/pull/2514 ；深度视频 https://github.com/huggingface/lerobot/pull/3644 ；语言列 https://github.com/huggingface/lerobot/pull/3467
- [S10] v0.6.1 的其他文件：`pyproject.toml` https://github.com/huggingface/lerobot/blob/v0.6.1/pyproject.toml#L97 ；`lerobot_edit_dataset.py` https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/lerobot_edit_dataset.py#L280 ；`language.py` https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/language.py#L24 ；`policies/` https://github.com/huggingface/lerobot/tree/v0.6.1/src/lerobot/policies
- [S11] 发布信息：PyPI https://pypi.org/project/lerobot/ （JSON：https://pypi.org/pypi/lerobot/json）；GitHub Releases https://github.com/huggingface/lerobot/releases ；v0.4.0 https://github.com/huggingface/lerobot/releases/tag/v0.4.0 、https://huggingface.co/blog/lerobot-release-v040 ；v0.6.0 https://github.com/huggingface/lerobot/releases/tag/v0.6.0 、https://huggingface.co/blog/lerobot-release-v060 ；v0.6.1 https://github.com/huggingface/lerobot/releases/tag/v0.6.1
- [S12] openpi：锁定版本 https://github.com/Physical-Intelligence/openpi/blob/215abfb217dbac7d5f1273282331b9b1866c0479/pyproject.toml#L70 ；锁定的 lerobot commit https://github.com/huggingface/lerobot/tree/0cf864870cf29f4738d3ade893e6fd13fbd7cdb5 ；issue https://github.com/Physical-Intelligence/openpi/issues/756 、https://github.com/Physical-Intelligence/openpi/issues/818 、https://github.com/Physical-Intelligence/openpi/issues/706 ；PR https://github.com/Physical-Intelligence/openpi/pull/972
- [S13] Isaac-GR00T：数据准备文档 https://github.com/NVIDIA/Isaac-GR00T/blob/dac54b313160c201c450f97df0fd74ebd379c892/getting_started/data_preparation.md#L5-L15 ；转换脚本 https://github.com/NVIDIA/Isaac-GR00T/blob/dac54b313160c201c450f97df0fd74ebd379c892/scripts/lerobot_conversion/convert_v3_to_v2.py#L158 （写 v2.1）、#L336（ffmpeg `-c copy`）
- [S14] Galaxea：GalaxeaVLA 内嵌的 lerobot https://github.com/OpenGalaxea/GalaxeaVLA/blob/89f2322b4ad016e192437adc1a2c253b05bab246/src/g05/data/lerobot/lerobot_dataset.py#L84 、https://github.com/OpenGalaxea/GalaxeaVLA/blob/89f2322b4ad016e192437adc1a2c253b05bab246/src/g05/data/lerobot/datasets/utils.py#L54-L70 ；GalaxeaLeRobot fork https://github.com/OpenGalaxea/GalaxeaLeRobot/blob/7b0902adc7abecae90516f87a6e25d741a09c36c/README.md
- [S15] AgiBot-World README：https://github.com/OpenDriveLab/AgiBot-World/blob/98f136ea6b345db1a08451a2f543d67c1789a809/README.md#L121
- [S16] CB_Autolife_Data_Collector：`record_lerobot_official.py` https://github.com/lee1354774070-ai/CB_Autolife_Data_Collector/blob/0bbaa841e19eaebf9ea9a6f22865aadd68e0def7/record_lerobot_official.py#L2 （"official LeRobotDataset v3"）、#L57-L61（`RGBEncoderConfig` / `DepthEncoderConfig`）；`convert_dataset.py` https://github.com/lee1354774070-ai/CB_Autolife_Data_Collector/blob/0bbaa841e19eaebf9ea9a6f22865aadd68e0def7/convert_dataset.py#L220-L221 ；README（事务模式与分片说明）https://github.com/lee1354774070-ai/CB_Autolife_Data_Collector/blob/0bbaa841e19eaebf9ea9a6f22865aadd68e0def7/README.md#L192-L193
- [S17] mcap2lerobot 默认格式：`/mnt/datasets/工具/mcap2lerobot/src/convert.rs:59`（`default_value = "v3.0"`），本机只读
- [S18] 本机样本：上表 4 个路径下的 `meta/info.json`，只读
