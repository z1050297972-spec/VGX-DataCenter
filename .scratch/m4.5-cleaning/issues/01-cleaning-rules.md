# 清洗规则：对齐切段的 Python 重写与数值检查

Status: done（2026-11-09 06:5x 评审通过，合进集成分支 t/m4.5-cleaning）

分级：领域决策票（新的领域规则）。负责人 2026-11-09 设 /goal 预授权本 M 的骨架关卡，由执行线审；合并 main 仍要负责人说。依赖：无。决定见 `../decisions.md`。

## 背景

mcap2lerobot 的清洗只做时间对齐（`../decisions.md`「工具的清洗做法」1–5 条）。平台要在转换前给出清洗预览，所以在平台里用 Python 把这套规则重写一遍，再加上工具没有的数值检查。本票只做**纯逻辑和读文件**：给定一组 MCAP 文件、工具配置和清洗规则，算出报告对象。作业、数据库、接口在第 02 张。

工具源码副本（只读参考，已用 O_NOATIME 拷出）：`~/.cache/rdp-dispatch/m4.5/mcap2lerobot-src/`（`sync.rs`、`verify.rs`、`convert.rs`、`inputs.rs`、`h264.rs`、`cdr.rs`、`config.rs`）。**不要访问 `/mnt` 下任何路径。**

## 要做的

新包 `src/rdp/jobs/cleaning/`（jobs 层，遵守 import-linter；不依赖 api、ops）。模块怎么拆由实现者定，对外入口如下。

### 1. 工具配置解析

按工具 `config.rs` 解析平台登记包里的配置副本（如 `tools/mcap2lerobot/configs/r1lite.toml`）：`robot_type`、`fps`、`task`、`[sync]`（`reference_topic`、`max_dt_ms`、`max_frame_gap`、`min_episode_frames`）、`[video]`（只读不用）、`[[feature]]`（`type = "video"` 带 `topic`、可选 `max_dt_ms`；`type = "vector"` 带 `sources`：`topic`、`field`、`names`、`max_dt_ms`、`optional`、`fill`）。

- 校验与工具一致：fps > 0；至少一个 feature；feature 名不重复；vector 的 sources 非空；`optional` 必须带非空 `fill`、`fill` 必须带 `optional`；`names` 非空时长度等于 `fill`；`reference_topic` 必须被某个 feature 使用且不能是可选话题；`max_frame_gap > 1`；每个话题容差 > 0。未知字段报错（工具是 `deny_unknown_fields`）。
- `topics()`、`is_optional_topic()`（所有引用都是 optional 的 source 才算）、`topic_tolerances()`（按首次出现顺序；同一话题多处引用取最严格；未写用 `sync.max_dt_ms`）语义照搬。

### 2. 清洗规则文件

新文件格式（第 02 张把它挂到工具清单上，本票只做解析和 R1 Lite 这一份）：`tools/mcap2lerobot/cleaning/r1lite.toml`。

```toml
schema_version = 1
[static]                      # 静止判断用哪个 vector feature
feature = "observation.state"
long_static_s = 3.0           # 连续多久算"长时间静止"
[jump]
feature = "action"
[image]
frozen_s = 1.0                # 画面完全相同持续多久算冻结
sample_interval_s = 1.0       # 亮度抽样间隔
dark_below = 10.0             # 平均亮度（0–255）低于它算黑屏
bright_above = 245.0          # 高于它算过曝
[[source]]                    # 按来源话题给阈值；没写的阈值不查
topic = "/hdas/feedback_arm_left"
static_threshold = 0.001
# jump_threshold = 0.5
# limits = [[-3.14, 3.14], ...]  每维 [下限, 上限]，可省略
```

R1 Lite 的初值见 `../decisions.md` 第 5 条：手臂关节（state 和 action 里的 arm 话题）静止阈值 0.001、跳变阈值 0.5；夹爪（gripper 话题，0–100）静止阈值 0.1、不写跳变阈值；不写 `limits`。校验：`feature` 必须是工具配置里的 vector feature；`[[source]]` 的话题必须在工具配置里；数值为正；未知字段报错。

### 3. 输入展开

照 `inputs.rs`：给定若干路径（文件或文件夹），文件原样保留；文件夹递归找扩展名 `mcap`（不分大小写），**每个文件夹内**按路径分量逐个比较排序（与 Rust `PathBuf` 的顺序一致，不是整串字符串比较）；按 `os.path.realpath` 去重，保留第一次出现；文件夹里一个都没有报错。目录遍历用 `os.scandir`，不跟随软链接进目录（与 Rust `path.is_dir()` 的差异写在 docstring 里：Rust 会跟随软链接；平台的数据集目录不该有指向外面的软链接，遇到指向目录的软链接按"跳过并记警告"处理）。

### 4. 读一个 MCAP 文件（一遍线性读）

- 用 `mcap` 的流式读取按文件里的记录顺序线性读（与工具的 `MessageStream` 一致），不按索引或时间重排。文件用 `os.open(..., O_RDONLY | O_NOATIME)` 打开（O_NOATIME 因权限失败时退回普通只读打开并记一条警告）；参照仓库里现有 O_NOATIME 的写法。
- 每条消息只看配置里的话题。按工具规则取 `header.stamp`（schema 第一个字段是 `std_msgs/Header` 且消息编码为 cdr；判断写法参照工具 `ros2msg::has_header`），stamp 为 0 的不参与对齐。
- 图像话题：`sensor_msgs/msg/CompressedImage` 按 `format` 区分 H.264（含 `h264`）、H.265（含 `h265`/`hevc`，不支持）、图片（其余）；`sensor_msgs/msg/Image` 是原始图。H.264 照 `h264.rs` 判断关键帧（IDR）和 B slice，每个文件重新等第一个关键帧，之前的消息 stamp 记 0。
- 向量来源：用 `mcap-ros2-support` 按 schema 解码，按 `field` 路径取数值并展平（照工具 `SourceState.extract`：维度第一次确定后不能变；`optional` 来源的维度必须等于 `fill` 长度）。
- 图片话题（JPEG/PNG/原始图）：每条消息记内容摘要（`hashlib.blake2b`，16 字节）用于冻结判断；按 stamp 每 `sample_interval_s` 秒取第一条，用 Pillow 解码（JPEG 用 `draft` 缩小、转灰度）算平均亮度；原始图直接按字节算。H.264 话题不解码。
- 内存要有界：stamp、数值、摘要用 `array` 等紧凑结构存，不留消息原文。读的过程中定期调用调用方传入的检查点函数（响应取消），并报告已读字节数。
- **会让工具整次转换失败的问题**记为该文件的"致命问题"，不抛异常：非可选话题没有消息、消息没有 Header 或不是 cdr、H.264 含 B 帧、H.265、没有关键帧、基准有效 stamp 不足 2 个、消息解析失败、向量维度变化或与 fill 不符、文件读不了。工具 `verify` 只警告的情况（乱序、重复、平均频率低于 fps × 0.995、关键帧前被排除的消息数、可选话题缺失用 fill）记为文件的警告。

### 5. 对齐与切段

照 `sync.rs` 的 `nearest`、`plan`、`plan_for_config` 逐条重写（排序用稳定排序；距离相同取较早；容差和断点换算成纳秒时与工具一样截断取整：`int(tol_ms * 1e6)`、`int(max_frame_gap * 1e9 / fps)`）。每个文件独立对齐，得到：基准帧数、每个话题的匹配下标、|Δt|、坏帧数、复用次数（相邻两帧取到同一条消息）、坏帧标记、断点数、保留段、过短丢弃段。可选话题缺失时不参与对齐。

### 6. 数值检查（每个保留段上）

按 `../decisions.md` 第 5 条的表，用匹配到的消息取每帧的值（缺失的可选来源用 fill，fill 来源不参与静止和跳变判断）：

- 非有限值（严重）：任一向量特征出现 NaN/±Inf，给出帧数和首次时间。
- 整段静止（严重）：`static.feature` 里有静止阈值的每一维，整段极差都小于阈值。
- 长时间静止（提示）：同上各维逐帧变化都小于阈值、连续 ≥ `long_static_s`，列出每段的起止时间（相对段首的秒数）。
- 动作跳变（提示）：`jump.feature` 里有跳变阈值的维，相邻帧变化大于阈值，给出次数和首次时间。
- 相机冻结（提示）：图片话题连续 ≥ `frozen_s` 秒的帧取到的内容摘要相同。
- 黑屏 / 过曝（提示）：段内的亮度抽样落在阈值外，给出次数和首次时间。
- 关节超限：有 `limits` 才查（R1 Lite 现在没有），超出算提示。
- H.264 话题在报告里标"未检查画面"，不算问题。

### 7. 报告对象

一个 Pydantic 模型（冻结、拒绝未知字段、带 `schema_version = 1`），可序列化成 JSON 存库（第 02 张）。至少包含：

- 规则身份：工具配置 sha256、清洗规则 sha256、fps、基准话题。
- 每个文件（按展开顺序，`file_index` 从 0 起）：数据块编号、绝对路径、大小、`mtime_ns`、致命问题列表、警告列表、基准帧数、保留帧数、坏帧数、断点数、过短丢弃的段数和帧数、每个话题的对齐统计（容差、|Δt| 平均和最大（ms）、复用次数、坏帧数、是否可选缺失）、默认是否剔除（有致命问题或没有保留段时剔除）。
- 每个 episode（按文件顺序、段顺序；身份是 `(file_index, segment_index)`，**不存转换后的全局编号**，因为用户剔除文件会让编号变化）：基准帧起止下标、帧数、时长（秒）、相对文件起点的开始时间、问题列表（检查名、严重或提示、一句中文说明、明细）、默认处理（有严重问题剔除，否则保留）。
- 汇总：文件数、默认剔除的文件数、episode 数、默认剔除的 episode 数、基准帧总数、保留帧总数。

对外入口：`build_cleaning_report(inputs, tool_config_path, rules_path, *, checkpoint, progress) -> CleaningReport`（名字可调整），`inputs` 是按用户顺序的 `(source_id, path)`，内部按第 3 条展开。

## 不做

- 作业类型、数据库、接口、页面（第 02–04 张）。
- 不调用工具程序；不读 `/mnt`；不改工具；不加任何新依赖（`mcap`、`mcap-ros2-support`、`zstandard`、`lz4`、`Pillow` 已由执行线装好）。
- 不做逐帧裁切、H.264 画面检查。

## 允许改的受保护文件

无。

## 测试范围（只做关键测试）

测试用 `mcap` / `mcap-ros2-support` 的写入器在临时目录里造小 MCAP（JPEG 用 Pillow 现场生成），不用真实数据。

1. 工具 Rust 测试逐条搬过来并通过：`sync.rs` 的 picks_closest、tie_picks_earlier、reference_outside_range、empty_stamps、splits_on_bad_frames、splits_on_reference_gap、drops_short_segments、trims_edges；`h264.rs` 的 splits_nal_units、detects_keyframe_and_b_slice、gate_waits_for_keyframe；`inputs.rs` 的 collects_recursively_sorted_and_deduped。
2. 配置解析：R1 Lite 配置副本能读，容差表与手算一致（头部 10、手腕 35、夹爪目标 30）；可选话题做基准、optional 缺 fill 各被拒绝。
3. 端到端（合成文件）：一个文件里中间有一段手腕相机缺帧、基准有一处大间隔、末尾有不足 90 帧的短段，报告里的段起止、保留帧数、坏帧数与手算一致；一个缺非可选话题的文件被标致命、默认剔除，不影响其他文件。
4. 数值检查：整段静止判严重并默认剔除；含 NaN 判严重；一次大跳变给提示；连续相同 JPEG 判冻结；全黑 JPEG 判黑屏。
5. H.264：关键帧前的消息不参与对齐；含 B slice 的文件判致命。

不在名单里的不测，不为罕见情况写防御分支（保留安全底线：只读打开、内存有界、可取消）。

## 验收

1. 上面的测试全部通过。
2. 执行线用真实样本副本（`~/.cache/rdp-m5-offline/sample/r1lite_20261011_52s.mcap`，系统盘）跑一次，报告能生成，耗时记进 Comments（目标：这 855 MB 一分钟内）。与工具 `verify` 的逐项对照在第 05 张做。
3. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-09 05:3x 派工 Codex（gpt-6-astra high，单元 rdp-m45-01，日志 `~/.cache/rdp-dispatch/m4.5-01/`），约 60 分钟交付：`src/rdp/jobs/cleaning/`（`report.py` 入口、`models.py` 报告模型、`_config/_io/_sync/_h264/_media/_records/_scan/_checks/_report`）、`tools/mcap2lerobot/cleaning/r1lite.toml`、5 个测试文件 24 个关键测试。
- 评审打回 1 处（阻塞）：单文件上限 200 万条消息 / 256 MiB 只够约 24 分钟的 R1 Lite 文件，长文件会被误判致命。resume 后改为 1000 万条 / 1 GiB（约 2 小时），超限诊断提示可拆分录制。
- 实现者说明的有意差异（评审接受）：目录软链接跳过并警告（Rust 会跟随）；一遍扫描解码全部向量消息，比工具只解码被用到的消息更严格；资源上限超出明确拒绝；JPEG 亮度只抽样解码。
- 变异抽查 3 处全部被抓：同距取晚（nearest）、整段静止不算严重、关键帧前消息不排除。
- 执行线在真实样本副本（M5 的 52 秒 R1 Lite，系统盘）上重跑：2.45 秒、峰值内存 45 MB；基准 1651、保留 1647、坏帧 4、5 个 episode（0..451、452..849、850..1207、1208..1508、1509..1651）。与执行线在 bwrap 里跑的工具 `verify -v`（`~/.cache/rdp-drill/m4.5-spike/verify.txt`）逐项一致：各话题容差、|Δt| 平均和最大、复用次数、坏帧数，以及每段起止帧。第 05 张的正式对照照此再做一次并存证。
- 检查：`make check` 第一次后端 1 个失败（`tests/test_jobs_schedules.py::test_unique_race`，与本票无关的并发竞争测试，单独重跑 3 次都通过，负载 2.8），重跑全绿：后端 2893、前端 414，0 skipped。

