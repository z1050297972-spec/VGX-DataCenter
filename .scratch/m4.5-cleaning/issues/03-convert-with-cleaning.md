# 转换接入清洗结果，接上 LeRobot 环境

Status: not-started

分级：领域决策票（转换契约变化：必须先预览；新增外部环境）。负责人 2026-11-09 设 /goal 预授权本 M 的骨架关卡，由执行线审。依赖：第 01、02 张。决定见 `../decisions.md` 第 3、4、6、8 条。

## 背景

负责人："如果用户点击，产出一份清洗后的lerobot格式数据即可，这些操作发生在我们转换格式前，所以不会有未清洗的lerobot格式数据。"本票让转换只能从清洗预览发起：只把没剔除的文件交给工具，转完核对与预览一致，再用 LeRobot 的 `delete_episodes` 删掉剔除的 episode。

## 要做的

### 1. "进行转换"接口

`POST /api/cleaning-previews/{job_id}/convert`（`operation_id = convert_from_cleaning_preview`），只有管理员：

- 请求体：`output_format`（可省略，取清单首项）、`space_ratio_percent`、`space_reserve_gib`（含义和默认值同现有转换参数）、`excluded_files`（预览里的 `file_index` 列表）、`excluded_episodes`（`{file_index, segment_index}` 列表）。这两项是用户的**最终**选择（前端以报告的默认处理为初值），服务端原样保存，不再套默认。
- 校验（不通过 422）：预览存在；`file_index`、`(file_index, segment_index)` 都在报告里；有致命问题的文件必须在 `excluded_files` 里；剔除后至少剩一个文件、至少剩一个 episode；`excluded_episodes` 里不能有已被剔除文件的段（冗余输入直接拒绝，免得含义不清）。
- 通过后提交该工具的转换作业，参数见下一条；返回新作业（201）。
- 取消直接提交转换的 `POST /api/jobs/convert/{tool_name}`；通用 `POST /api/jobs` 提交转换类型时，参数里没有预览编号也会被执行时拒绝（见第 2 条）。前端改动在第 04 张。

### 2. 转换参数与执行

- `ConversionParameters` 加 `cleaning_preview_job_id`、`excluded_files`、`excluded_episodes`。为了旧作业记录还能读出来，模型上可以是可选的；但新提交（第 1 条接口）一定带上，执行时没有预览编号直接以输入问题失败："转换必须从清洗预览发起"。
- 执行第 2 阶段「核对输入」在现有检查之前加预览核对，任一不符都以输入问题失败、提示"请重新清洗预览"，不建暂存目录：
  - 预览存在、数据集和型号与本次一致；
  - 工具程序 sha256、工具配置 sha256、清洗规则 sha256 与预览记录一致；
  - 报告里每个未剔除文件的大小和 `mtime_ns` 与当前一致（`os.stat`，不打开文件）。
- 交给工具的输入改成**报告里未剔除的文件路径，按 `file_index` 顺序逐个传**（不再传数据块目录）；命令仍经 bwrap，只读根照旧。
- 空间预检：输入字节按未剔除文件的大小合计；有 episode 要剔除时，估算产物按两倍算（工具产物加清洗后副本），诊断里写明。
- 阶段改成六个：「核对工具」「核对输入」「扫描」「转换」「剔除」「收尾」（工具进度解析的阶段编号随之对齐；没有要剔除的 episode 时「剔除」直接跳过）。
- 「转换」结束后先核对产物与预览一致：产物的 episode 数，以及每个 episode 的帧数，与报告里未剔除文件的段按顺序逐一相等（v3.0 读 `meta/episodes/`，v2.1 读 `meta/episodes.jsonl`；复用入库检查里现有的读取代码）。不一致以外部问题失败，规则 `cleaning.output_mismatch`，诊断写出第一处不一致，暂存保留，不做剔除、不入库。
- 「剔除」：把 `excluded_episodes` 按未剔除文件的顺序换算成产物里的 episode 编号，在沙箱里用登记的 LeRobot 环境运行平台自带的脚本，从 `暂存/转换/<作业>/out` 产出 `暂存/转换/<作业>/cleaned`；之后核对 `cleaned` 的 episode 数等于保留数。成功结果（`ConversionResult`）的产物位置指向 `cleaned`；入库检查和入库照旧按结果里的位置走（确认它们读的是结果里的位置，不是写死的 `out`）。
- `转换回执.json` 加 `cleaning` 段：预览作业编号、规则和配置的 sha256、剔除的文件（路径和原因）、剔除的 episode（预览身份、产物编号、原因）、LeRobot 版本和指纹、剔除命令。入库写血缘时，`来源.json` 转换记录的 `parameters` 加标量：`cleaning_preview_job_id`、`cleaning_rules_sha256`、`cleaning_excluded_files`（个数）、`cleaning_excluded_episodes`（产物编号，逗号分隔，没有为空字符串）、`lerobot_version`、`lerobot_fingerprint`；不改 `LineageRecord` 模型。

### 3. LeRobot 环境登记与指纹

- 新目录 `envs/lerobot/`（仓库根，不放在 `tools/` 下，免得被当成工具登记包）：
  - `env.toml`：`schema_version`、期望的 LeRobot 版本（`0.6.2`）、指纹（sha256）、指纹范围（包目录下 `datasets/`、`configs/`、`utils/` 里的全部 `.py`）。
  - `delete_episodes.py`：在 LeRobot 环境里运行的小脚本：参数是源目录、目标目录、要删的 episode 编号；用 `LeRobotDataset`（本地根目录、离线）加载后调用 `lerobot.datasets.dataset_tools.delete_episodes`，结束时在 stdout 打一行 JSON（保留的 episode 数、帧数）。脚本只做这些。
- 平台配置 `[tools]` 加可选的 `lerobot_python`（LeRobot 环境解释器的绝对路径）。没配置时，有 episode 要剔除的转换在「核对输入」以输入问题失败（"未配置 LeRobot 环境"）；没有要剔除的转换不受影响。本机部署要配成 `/home/shawn/miniconda3/envs/lerobot/bin/python`（运维手册写在第 05 张；本票不改真实配置）。
- 指纹核对：每次「剔除」前，在同一个沙箱设置下用该解释器运行一段探测（`-I`，`PYTHONDONTWRITEBYTECODE=1`），取实际导入的 `lerobot` 版本和包目录；平台在自己这边按指纹范围读包目录里的文件算 sha256（相对路径排序，路径和内容摘要依次进哈希），与 `env.toml` 比对。版本或指纹不符以输入问题失败："LeRobot 环境已变化，需要重新登记"。
- 运行 LeRobot：沙箱照现有 bwrap 写法（根目录只读，只有本作业暂存目录可写），另外断网（`--unshare-net`），环境变量 `HF_HUB_OFFLINE=1`、`PYTHONDONTWRITEBYTECODE=1`，`HF_HOME` 指向暂存目录下的私有目录；不额外要 GPU（试跑实测重新编码走 CPU 的 libx265，见 Comments），作业本身因工具需要仍占着一张卡。超时与取消复用受管进程（上限 12 小时）。
- `GET /api/tools`（或详情）带上 LeRobot 环境状态：未配置 / 可用 / 版本或指纹不符（附实际值）。状态在请求时探测，超时和失败都如实显示，不让工具列表失败。
- 指纹算法（平台和登记要一致）：包目录下 `configs/`、`datasets/`、`utils/` 递归找 `.py`（跳过 `__pycache__`），取相对包目录的 POSIX 路径，按路径排序；依次把 `路径 + b"\0" + 文件内容的 sha256 十六进制 + b"\n"` 送进一个 sha256，取十六进制。执行线 2026-11-09 用此算法在本机算得：63 个文件，`9e5c3242e11ad6be6bbd594bb4fa6bbe09f8eb8f2392081af2c2279449495831`（包目录 `/home/shawn/桌面/lerobot/src/lerobot`，版本 0.6.2），写进 `env.toml`。

## 不做

- 页面（第 04 张）；改 LeRobot 环境本身；逐帧裁切；已经是 LeRobot 的数据。

## 允许改的受保护文件

无。`pyproject.toml` 若要把 `envs/**/*.py` 加进 ruff 范围，由执行线改。

## 测试范围（只做关键测试）

工具和 LeRobot 都用假程序（测试里的可执行脚本，按参数写出最小的 LeRobot 目录结构），不依赖真实环境。

1. 从预览转换：只把未剔除文件按顺序交给工具（断言假工具收到的参数）；产物与预览一致时成功，结果位置正确。
2. 有剔除的 episode：编号按未剔除文件顺序换算正确（剔除一个文件后，后面文件的段编号前移）；假 LeRobot 脚本收到正确编号；结果位置指向 `cleaned`；回执和血缘参数里有清洗信息。
3. 预览后输入文件变了（改 mtime）→ 作业以输入问题失败，没有暂存目录，工具没被调用。
4. 产物 episode 帧数和预览不一致 → `cleaning.output_mismatch`，不调用 LeRobot。
5. LeRobot 指纹不符 → 失败，不调用删除脚本；未配置 LeRobot 且有剔除 → 失败；未配置但没有剔除 → 照常成功。
6. 接口校验：致命文件没剔除 → 422；全部剔除 → 422；成员调用 → 403。
7. 原有转换测试改成从预览发起后照常通过（只改它们的构造方式和期望阶段数，不改断言的含义）。

## 验收

1. 测试通过；`make check` 全绿、0 skipped。
2. 执行线用真实 LeRobot 环境在副本上跑一次删除脚本：先用工具把 M5 真实样本副本转成 v3.0 到测试目录（系统盘，GPU），再删掉一个 episode，`cleaned` 能用 `LeRobotDataset` 读出、episode 数对、视频能解码；记下耗时和重新编码用的编码器。两块数据盘写入扇区不变。

## Comments

- 2026-11-09 05:4x 执行线预先试跑（`~/.cache/rdp-drill/m4.5-spike/`，系统盘，两块数据盘写入扇区前后 5304 / 33280 不变）：
  - 工具在 bwrap 里（`--ro-bind / /`，只绑定试跑目录可写）把 M5 样本副本转成 v3.0：25 秒，5 个 episode、1647 帧、105 MB，三路视频 `hevc`（hevc_nvenc）。
  - `lerobot` 环境在 bwrap 里（另加 `--unshare-net`、`HF_HUB_OFFLINE=1`、私有 `HF_HOME`、`PYTHONDONTWRITEBYTECODE=1`）用 `LeRobotDataset("local/x", root=out)` 加载后 `delete_episodes(ds, episode_indices=[2], output_dir=cleaned, repo_id=...)`：82 秒，剩 4 个 episode、1290 帧，长度 [451, 397, 300, 142]；`cleaned` 能重新加载，三路视频各取一帧都能解码。
  - 重新编码：LeRobot 按 `info.json` 的 `video.codec = hevc` 选了 **libx265（CPU）**、CRF 30、g=2，每路约 55 帧/秒；三路视频文件都整份重编，体积 105 MB → 32 MB。GPU 没用上，所以「剔除」可以不占 GPU；画质与工具的 hevc_nvenc 不同，记进 followups 待负责人。
